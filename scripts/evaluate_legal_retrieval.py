"""Reproducible TASK-0018 legal retrieval ranking and applicability benchmark."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion, RetrievalQuery
from bidding_compliance.legal.corpus import index_hash, ingest
from bidding_compliance.legal.retrieval import (
    CharacterEmbedding,
    LegalRetriever,
    clause_exclusions,
    confirmation_reason,
    scope_exclusions,
)

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "evals/legal_retrieval"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def process_memory() -> dict[str, int | None]:
    if os.name == "nt":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return {"working_set_bytes": None, "peak_working_set_bytes": None}
        return {
            "working_set_bytes": int(counters.WorkingSetSize),
            "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        }
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # ru_maxrss uses bytes on macOS and KiB on Linux.
        if platform.system() != "Darwin":
            peak *= 1024
        current = None
        statm = Path("/proc/self/statm")
        if statm.exists():
            pages = int(statm.read_text(encoding="ascii").split()[1])
            current = pages * os.sysconf("SC_PAGE_SIZE")
        return {"working_set_bytes": current, "peak_working_set_bytes": peak}
    except (ImportError, OSError, ValueError, IndexError):
        return {"working_set_bytes": None, "peak_working_set_bytes": None}


def host_memory() -> dict[str, int | None]:
    if os.name != "nt":
        return {"total_bytes": None, "available_bytes": None}

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"total_bytes": None, "available_bytes": None}
    return {
        "total_bytes": int(status.ullTotalPhys),
        "available_bytes": int(status.ullAvailPhys),
    }


def make_query(item: dict[str, Any], query_set: dict[str, Any]) -> RetrievalQuery:
    return RetrievalQuery.model_validate(
        {
            **query_set["context"],
            "text": item["text"],
            "review_date": query_set["review_date"],
            "limit": query_set["top_k"],
        }
    )


def evaluate_filters(
    version: LegalVersion,
    article: str,
    cases: dict[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for category in ("scope", "validity"):
        counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
        details = []
        for item in cases["cases"]:
            if item["category"] != category:
                continue
            query = RetrievalQuery.model_validate(
                {
                    **item["context"],
                    "text": "Applicability control case",
                    "review_date": item["review_date"],
                    "include_references": False,
                    "limit": 10,
                }
            )
            reasons = list(scope_exclusions(version, query))
            reasons.extend(
                reason
                for reason in clause_exclusions(version, article, query)
                if reason not in reasons
            )
            confirmation = confirmation_reason(version, article, query)
            if confirmation != "valid" and confirmation not in reasons:
                reasons.append(confirmation)
            actual = not reasons
            expected = bool(item["expected_eligible"])
            bucket = "tp" if expected and actual else "fn" if expected else "fp" if actual else "tn"
            counts[bucket] += 1
            detail = {
                "id": item["id"],
                "expected_eligible": expected,
                "actual_eligible": actual,
                "actual_reasons": reasons,
            }
            expected_reason = item.get("expected_reason")
            if expected_reason is not None:
                detail["expected_reason"] = expected_reason
                detail["expected_reason_present"] = expected_reason in reasons
            if actual != expected or (
                expected_reason is not None and expected_reason not in reasons
            ):
                detail["error"] = True
            details.append(detail)
        output[category] = {
            **counts,
            "false_inclusions": counts["fp"],
            "false_exclusions": counts["fn"],
            "errors": counts["fp"] + counts["fn"],
            "cases": details,
        }
    return output


def evaluate() -> dict[str, Any]:
    lock_path = EVAL_ROOT / "snapshot.lock.json"
    query_path = EVAL_ROOT / "queries.json"
    filter_path = EVAL_ROOT / "applicability_cases.json"
    unconfirmed_path = EVAL_ROOT / "unconfirmed_candidates.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    query_set = json.loads(query_path.read_text(encoding="utf-8"))
    filter_cases = json.loads(filter_path.read_text(encoding="utf-8"))
    unconfirmed = json.loads(unconfirmed_path.read_text(encoding="utf-8"))

    manifest_path = ROOT / lock["manifest_path"]
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != lock["manifest_sha256"]:
        raise ValueError("legal manifest hash differs from the evaluation lock")
    manifest = LegalManifest.model_validate_json(manifest_bytes)
    build_started = time.perf_counter()
    index = ingest(ROOT, manifest)
    index_build_ms = (time.perf_counter() - build_started) * 1000
    snapshot_sha = index_hash(index)
    if snapshot_sha != lock["index_sha256"]:
        raise ValueError("rebuilt legal index hash differs from the evaluation lock")
    if len(index.manifest.versions) != lock["legal_version_count"]:
        raise ValueError("rebuilt legal version count differs from the evaluation lock")
    if len(index.clauses) != lock["fragment_count"]:
        raise ValueError("rebuilt legal fragment count differs from the evaluation lock")

    confirmed = lock["confirmed_label_source"]
    versions = {(item.law_id, item.version): item for item in index.manifest.versions}
    version = versions[(confirmed["law_id"], confirmed["version"])]
    if (
        version.verification != "verified"
        or version.verified_through.isoformat() != confirmed["verified_through"]
        or version.source_hash != confirmed["source_sha256"]
        or version.text_hash != confirmed["text_sha256"]
    ):
        raise ValueError("confirmed label source differs from its frozen provenance")

    clauses = {(item.law_id, item.version, item.article): item for item in index.clauses}
    query_file_hash = file_sha256(query_path)
    start_memory = process_memory()
    retriever = LegalRetriever(index, CharacterEmbedding())
    latencies: list[float] = []
    query_results = []
    target_filter_errors = []
    verified_target_queries = 0
    retrieved_verified_targets = 0
    reciprocal_ranks = []
    dcg_scores = []
    recall5 = 0
    recall10 = 0
    unverified_candidates = 0
    hit_count = 0

    filters = evaluate_filters(
        version,
        "第二十一条",
        filter_cases,
    )

    # Each query is timed repeatedly after a single warm-up; model load is absent for
    # CharacterEmbedding and is reported separately for neural adapters.
    queries = [make_query(item, query_set) for item in query_set["queries"]]
    if queries:
        retriever.search(queries[0])
    for item, query in zip(query_set["queries"], queries, strict=True):
        target_clause = clauses[(confirmed["law_id"], confirmed["version"], item["target_article"])]
        filter_reasons = list(scope_exclusions(version, query))
        filter_reasons.extend(
            reason
            for reason in clause_exclusions(version, item["target_article"], query)
            if reason not in filter_reasons
        )
        target_reason = confirmation_reason(version, item["target_article"], query)
        if target_reason != "valid" and target_reason not in filter_reasons:
            filter_reasons.append(target_reason)
        target_eligible = not filter_reasons
        if not target_eligible:
            target_filter_errors.append({"query_id": item["id"], "reasons": filter_reasons})
        else:
            verified_target_queries += 1

        per_query_ms = []
        result = None
        for _ in range(3):
            started = time.perf_counter()
            result = retriever.search(query)
            per_query_ms.append((time.perf_counter() - started) * 1000)
        assert result is not None
        latencies.extend(per_query_ms)
        ranks = [
            rank
            for rank, hit in enumerate(result.hits, start=1)
            if hit.evidence_id == target_clause.clause_id
        ]
        rank = ranks[0] if ranks else None
        found = target_eligible and rank is not None
        if found:
            retrieved_verified_targets += 1
            if rank <= 5:
                recall5 += 1
            if rank <= 10:
                recall10 += 1
            reciprocal_ranks.append(1 / rank)
            dcg_scores.append(1 / math.log2(rank + 1))
        else:
            reciprocal_ranks.append(0.0)
            dcg_scores.append(0.0)
        unverified_candidates += sum(hit.reason != "valid" for hit in result.hits)
        hit_count += len(result.hits)
        query_results.append(
            {
                "query_id": item["id"],
                "target_article": item["target_article"],
                "target_eligible": target_eligible,
                "target_filter_reasons": filter_reasons,
                "target_rank": rank,
                "top_articles": [
                    {
                        "article": hit.article,
                        "version_status": hit.version_status,
                        "reason": hit.reason,
                        "evidence_id": hit.evidence_id,
                    }
                    for hit in result.hits
                ],
                "latency_ms": per_query_ms,
            }
        )

    denominator = verified_target_queries
    memory = process_memory()
    sorted_latency = sorted(latencies)
    p95_index = min(len(sorted_latency) - 1, math.ceil(0.95 * len(sorted_latency)) - 1)
    metrics = {
        "labeled_query_count": len(query_results),
        "eligible_label_denominator": denominator,
        "Recall@5": recall5 / denominator if denominator else None,
        "Recall@10": recall10 / denominator if denominator else None,
        "MRR@10": statistics.mean(reciprocal_ranks) if reciprocal_ranks else None,
        "nDCG@10": statistics.mean(dcg_scores) if dcg_scores else None,
        "average_query_latency_ms": statistics.mean(latencies) if latencies else None,
        "p95_query_latency_ms": sorted_latency[p95_index] if sorted_latency else None,
        "average_hit_count": hit_count / len(query_results) if query_results else None,
        "unverified_reference_hit_count": unverified_candidates,
        "expert_unconfirmed_risk_candidate_count": len(unconfirmed["candidates"]),
        "confirmed_accuracy_includes_unconfirmed_risks": False,
    }
    return {
        "schema_version": "task0018.legal-retrieval-report.v1",
        "run": {
            "embedding": "character-bigram-1",
            "retrieval_algorithm": "bm25-char-cosine-rrf-5",
            "top_k": query_set["top_k"],
            "rrf_k": 60,
            "bm25_weight": 1.0,
            "vector_weight": 1.0,
            "reranker_enabled": False,
            "reranker_version": None,
            "external_calls": False,
        },
        "snapshot": {
            "index_sha256": snapshot_sha,
            "index_json_bytes": len(index.model_dump_json().encode()),
            "manifest_sha256": manifest_sha,
            "query_set_sha256": query_file_hash,
            "applicability_cases_sha256": file_sha256(filter_path),
            "versions": len(index.manifest.versions),
            "fragments": len(index.clauses),
            "verified_versions": sum(v.verification == "verified" for v in index.manifest.versions),
            "unverified_versions": sum(
                v.verification == "unverified" for v in index.manifest.versions
            ),
            "confirmed_label_law_id": confirmed["law_id"],
            "confirmed_label_version": confirmed["version"],
            "confirmed_label_source_sha256": confirmed["source_sha256"],
            "confirmed_label_text_sha256": confirmed["text_sha256"],
        },
        "performance": {
            "index_build_ms": index_build_ms,
            "working_set_before_retrieval_bytes": start_memory["working_set_bytes"],
            "peak_working_set_bytes": memory["peak_working_set_bytes"],
            "host_memory_at_start": host_memory(),
        },
        "metrics": metrics,
        "filtering": {
            "scope_and_applicability": filters["scope"],
            "legal_validity_and_horizon": filters["validity"],
            "labeled_target_filter_errors": target_filter_errors,
        },
        "queries": query_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".verification/task0018-legal-baseline/character.json",
    )
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps({"report": str(args.output), "metrics": result["metrics"]}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
