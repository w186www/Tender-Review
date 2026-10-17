"""Evaluate the checked-in synthetic rule cases without a model or network call."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bidding_compliance.domain.rules.engine import SKILLS, discover, ruleset_sha256
from bidding_compliance.domain.rules.models import (
    DiscoveryInputSnapshot,
    DocumentVersionRef,
    LocatedFragment,
)
from bidding_compliance.ingestion.schemas import Fragment

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "evals/golden_cases"
CASE_SKILL = {
    "GC-0001": "qualification_review",
}
TENANT_ID = "task0019-synthetic-tenant"
PROJECT_ID = "task0019-synthetic-project"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: object) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _load_fixture(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("synthetic") is not True:
        raise ValueError(f"non-synthetic case is outside this offline evaluator: {path.name}")
    return payload, raw


def _legal_retrieval_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "not_run_with_this_command", "risk_metrics": None}
    raw = path.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    metrics = report["metrics"]
    snapshot = report["snapshot"]
    filters = report["filtering"]
    scope = filters["scope_and_applicability"]
    validity = filters["legal_validity_and_horizon"]
    return {
        "status": "measured_on_fixed_legal_retrieval_dataset",
        "report_path": path.resolve().relative_to(ROOT).as_posix()
        if path.resolve().is_relative_to(ROOT)
        else "external_local_verification_report",
        "report_sha256": _sha_bytes(raw),
        "legal_index_sha256": snapshot["index_sha256"],
        "manifest_sha256": snapshot["manifest_sha256"],
        "query_set_sha256": snapshot["query_set_sha256"],
        "applicability_cases_sha256": snapshot["applicability_cases_sha256"],
        "versions": snapshot["versions"],
        "fragments": snapshot["fragments"],
        "verified_versions": snapshot["verified_versions"],
        "unverified_versions": snapshot["unverified_versions"],
        "retrieval_metrics": {
            key: metrics[key]
            for key in (
                "labeled_query_count",
                "eligible_label_denominator",
                "Recall@5",
                "Recall@10",
                "MRR@10",
                "nDCG@10",
                "average_query_latency_ms",
                "p95_query_latency_ms",
                "unverified_reference_hit_count",
            )
        },
        "scope_applicability_filter": {
            "case_count": len(scope["cases"]),
            "tp": scope["tp"],
            "tn": scope["tn"],
            "fp": scope["fp"],
            "fn": scope["fn"],
            "errors": scope["errors"],
        },
        "validity_horizon_filter": {
            "case_count": len(validity["cases"]),
            "tp": validity["tp"],
            "tn": validity["tn"],
            "fp": validity["fp"],
            "fn": validity["fn"],
            "errors": validity["errors"],
        },
        "candidate_specific_legal_recall": None,
        "interpretation": (
            "fixed legal retrieval benchmark, not candidate-specific legal citation accuracy"
        ),
    }


def _ocr_baseline_summary() -> dict[str, Any]:
    path = ROOT / "evals/ocr/results/tesseract-baseline-final-reviewed-20261015.json"
    raw = path.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    main_scan = report["cases"][0]
    blank = report["cases"][1]
    malformed = report["cases"][2]
    return {
        "status": "reused_existing_real_isolated_parser_measurement_on_synthetic_files",
        "report_path": path.relative_to(ROOT).as_posix(),
        "report_sha256": _sha_bytes(raw),
        "parser_image_sha256": report["run"]["parser_image_sha256"],
        "fixture_type": main_scan["fixture_type"],
        "page_count": main_scan["page_count"],
        "character_error_rate": main_scan["character_error_rate"],
        "critical_tokens": main_scan["critical_tokens"],
        "table_cell_completeness": main_scan["table_cell_completeness"],
        "page_marker_hits": main_scan["page_marker_hits"],
        "page_marker_expected_locations": main_scan["page_marker_total"],
        "valid_page_locator_ratio": main_scan["valid_page_locator_ratio"],
        "repeated_text_occurrences_located": main_scan["repeated_text_occurrences_located"],
        "repeated_text_occurrences_expected": main_scan["repeated_text_occurrences_expected"],
        "main_scan_quality": main_scan["quality"],
        "main_scan_quality_alert": main_scan["synthetic_benchmark_alert"],
        "blank_quality": blank["quality"],
        "blank_issues": blank["issues"],
        "malformed_error": malformed["error"],
        "timeouts": report["observed_timeouts"],
        "limitations": report["limitations"],
        "interpretation": (
            "synthetic parser/OCR measurement only; not representative of real tender files"
        ),
    }


def _case_fragments(case: dict[str, Any]) -> tuple[Fragment, ...]:
    excerpts = case.get("input_fragments")
    if excerpts is None:
        excerpt = case.get("document_excerpt")
        if not isinstance(excerpt, dict) or not isinstance(excerpt.get("text"), str):
            raise ValueError(f"case has no supported excerpt: {case.get('case_id')}")
        excerpts = [excerpt]
    if not isinstance(excerpts, list) or not excerpts:
        raise ValueError(f"case has no input fragments: {case.get('case_id')}")

    fragments: list[Fragment] = []
    for index, item in enumerate(excerpts):
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError(f"case fragment has no text: {case.get('case_id')}[{index}]")
        case_id = case["case_id"]
        table = item.get("table")
        row = item.get("row")
        column = item.get("column")
        if table is not None:
            locator = str(
                item.get("locator", f"cell:{row if row is not None else index}:{column or 0}")
            )
            kind = "table_cell"
        else:
            locator = str(item.get("locator", f"fixture/{case_id}/fragment/{index}"))
            kind = "paragraph"
        fragments.append(
            Fragment(
                locator=locator,
                page=None,
                bbox=None,
                coordinate_system="ooxml",
                kind=kind,
                section=str(item.get("section", "合成黄金案例")),
                text=text,
                text_sha256=_sha_bytes(text.encode("utf-8")),
                source="native",
                confidence=None,
                table=table,
                row=row,
                column=column,
            )
        )
    return tuple(fragments)


def _freeze_case(
    case_id: str, raw_sha256: str, fragments: tuple[Fragment, ...]
) -> tuple[DiscoveryInputSnapshot, dict[str, tuple[LocatedFragment, ...]]]:
    document_id = f"synthetic-{case_id.lower()}"
    section_id = f"section-{case_id.lower()}"
    fragment_payload = [
        {
            "section_id": section_id,
            "section_revision": 1,
            "fragment": item.model_dump(mode="json"),
        }
        for item in sorted(fragments, key=lambda fragment: fragment.locator)
    ]
    fragments_sha256 = _sha_json(fragment_payload)
    version_payload = {
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "document_id": document_id,
        "raw_source_sha256": raw_sha256,
        "parse_version": 1,
        "context_version": 1,
        "fragments_sha256": fragments_sha256,
    }
    document_ref = DocumentVersionRef(
        document_id=document_id,
        raw_source_sha256=raw_sha256,
        parse_version=1,
        context_version=1,
        fragments_sha256=fragments_sha256,
        document_version_ref="doc-version:sha256:" + _sha_json(version_payload),
        fragment_count=len(fragments),
    )
    context_sha256 = _sha_json({"fixture": case_id, "synthetic": True})
    context_payload = {
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "version": 1,
        "context_sha256": context_sha256,
    }
    snapshot = DiscoveryInputSnapshot(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        project_version=1,
        project_context_sha256=context_sha256,
        project_context_ref="project-version:sha256:" + _sha_json(context_payload),
        documents=(document_ref,),
    )
    located = tuple(
        LocatedFragment(document_ref, section_id, 1, item)
        for item in sorted(fragments, key=lambda fragment: fragment.locator)
    )
    return snapshot, {document_id: located}


def evaluate(legal_report_path: Path | None = None) -> dict[str, Any]:
    case_files = sorted(GOLDEN_DIR.glob("GC-*.json"))
    if not case_files:
        raise ValueError("no checked-in golden cases found")

    case_results: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    raw_match_count = 0
    distinct_candidate_count = 0
    matched_expected_patterns = 0
    quote_hash_matches = 0
    quote_count = 0
    fixture_locator_matches = 0
    fixture_locator_count = 0

    for path in case_files:
        case, raw = _load_fixture(path)
        case_id = case["case_id"]
        raw_sha256 = _sha_bytes(raw)
        fragments = _case_fragments(case)
        target_skill = case.get("skill_id") or CASE_SKILL.get(case_id)
        if target_skill not in SKILLS:
            raise ValueError(f"no registered target skill for {case_id}")
        expected = case["expected"]
        expected_count = int(expected.get("candidate_count", 1))
        snapshot, mapping = _freeze_case(case_id, raw_sha256, fragments)
        located_fragments = next(iter(mapping.values()))

        raw_by_skill = {
            skill_id: len(module.scan(located_fragments).matches)
            for skill_id, module in SKILLS.items()
        }
        raw_matches = sum(raw_by_skill.values())
        raw_match_count += raw_matches
        result = discover(snapshot, mapping)
        target_coverage = next(
            item for item in result.skill_coverages if item.skill_id == target_skill
        )
        target_candidates = [item for item in result.candidates if item.skill_id == target_skill]
        case_pattern_matched = len(target_candidates) == expected_count and (
            target_coverage.status == expected.get("coverage_status", "completed_with_candidates")
        )
        if case_pattern_matched:
            matched_expected_patterns += 1
        distinct_candidate_count += len(result.candidates)

        fixture_text_by_locator = {item.locator: item.text for item in fragments}
        for candidate in result.candidates:
            for excerpt in candidate.source_excerpts:
                quote_count += 1
                exact_text = fixture_text_by_locator.get(excerpt.locator)
                quote_valid = (
                    exact_text == excerpt.quote
                    and _sha_bytes(excerpt.quote.encode("utf-8")) == excerpt.quote_sha256
                )
                quote_hash_matches += int(quote_valid)
                fixture_locator_count += 1
                fixture_locator_matches += int(exact_text is not None)

        case_results.append(
            {
                "case_id": case_id,
                "fixture_path": path.relative_to(ROOT).as_posix(),
                "fixture_sha256": raw_sha256,
                "label_status": "candidate_unconfirmed",
                "expert_confirmed_risk": False,
                "expert_confirmed_nonrisk": False,
                "target_skill": target_skill,
                "expected_candidate_count": expected_count,
                "actual_target_candidate_count": len(target_candidates),
                "actual_candidates_by_skill": raw_by_skill,
                "deduplicated_candidate_count": len(result.candidates),
                "raw_rule_match_count": raw_matches,
                "coverage_status": target_coverage.status,
                "expected_pattern_captured": case_pattern_matched,
                "candidate_rule_ids": sorted({item.rule_id for item in target_candidates}),
                "candidate_locators": sorted(
                    {
                        excerpt.locator
                        for item in target_candidates
                        for excerpt in item.source_excerpts
                    }
                ),
                "candidate_quote_hashes_match_fixture": all(
                    _sha_bytes(excerpt.quote.encode("utf-8")) == excerpt.quote_sha256
                    and fixture_text_by_locator.get(excerpt.locator) == excerpt.quote
                    for item in target_candidates
                    for excerpt in item.source_excerpts
                ),
                "engine_result_sha256": result.result_sha256,
                "fixture_excerpt_page": case.get("document_excerpt", {}).get("page"),
                "source_file_parse_measured": False,
                "legal_evidence_expected": bool(expected.get("requires_legal_evidence", False)),
                "human_review_expected": bool(expected.get("requires_human_review", True)),
            }
        )
        manifest.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "size_bytes": len(raw),
                "sha256": raw_sha256,
                "synthetic": True,
                "label_status": "candidate_unconfirmed",
            }
        )

    aggregate_manifest_sha = _sha_json(manifest)
    rule_source_files = sorted(
        [
            *(ROOT / "src/bidding_compliance/domain/rules").glob("*.py"),
            *(ROOT / "src/bidding_compliance/domain/skills").glob("*.py"),
        ]
    )
    rule_source_manifest = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha_bytes(path.read_bytes()),
        }
        for path in rule_source_files
    ]
    ocr_summary = _ocr_baseline_summary()
    legal_summary = _legal_retrieval_summary(legal_report_path)
    total_duplicates_merged = max(0, raw_match_count - distinct_candidate_count)
    return {
        "schema_version": "task0019-capability-baseline-v1",
        "evaluation_scope": (
            "offline deterministic rule candidate discovery over checked-in synthetic fixtures"
        ),
        "external_model_calls": 0,
        "real_tender_or_law_text_transferred": False,
        "candidate_source_identity": {
            "repository_head": _git_head(),
            "evaluator_sha256": _sha_bytes(Path(__file__).read_bytes()),
            "ruleset_sha256": ruleset_sha256(tuple(sorted(SKILLS))),
            "rule_source_manifest_sha256": _sha_json(rule_source_manifest),
            "fixture_manifest_sha256": aggregate_manifest_sha,
            "thresholds_sha256": _sha_bytes((ROOT / "evals/thresholds.yaml").read_bytes()),
            "ocr_report_sha256": ocr_summary["report_sha256"],
            "legal_report_sha256": legal_summary.get("report_sha256"),
        },
        "dataset": {
            "version": "checked-in GC-0001 through GC-0005; no expert adjudication supplied",
            "case_count": len(manifest),
            "expert_confirmed_risks": 0,
            "expert_confirmed_nonrisks": 0,
            "candidate_unconfirmed": len(manifest),
            "unlabelled": 0,
            "regulatory_basis_pending_verification": True,
            "manifest_sha256": aggregate_manifest_sha,
            "cases": manifest,
        },
        "metrics": {
            "fixture_expected_pattern_capture": {
                "numerator": matched_expected_patterns,
                "denominator": len(case_results),
                "ratio": matched_expected_patterns / len(case_results),
                "interpretation": (
                    "deterministic fixture pattern coverage only; not expert risk recall"
                ),
            },
            "risk_precision": None,
            "risk_recall": None,
            "false_positive_rate": None,
            "raw_rule_matches": raw_match_count,
            "deduplicated_candidates": distinct_candidate_count,
            "duplicates_merged": total_duplicates_merged,
            "duplicate_rate": (
                total_duplicates_merged / raw_match_count if raw_match_count else None
            ),
            "candidate_quote_and_fixture_locator_correctness": {
                "quote_hash_matches": quote_hash_matches,
                "quote_count": quote_count,
                "fixture_locator_matches": fixture_locator_matches,
                "fixture_locator_count": fixture_locator_count,
                "source_file_locator_accuracy": None,
                "interpretation": (
                    "validated against fixture excerpts; original source files are absent"
                ),
            },
        },
        "cases": case_results,
        "parser_and_ocr": ocr_summary,
        "legal_retrieval": legal_summary,
        "unmeasured_layers": {
            "per_case_secure_file_parse_and_page_layout": (
                "not_measured: golden cases contain JSON excerpts, not source files"
            ),
            "ocr_quality_on_real_tenders": (
                "not_measured: no authorized real source document was used"
            ),
            "expert_precision_recall": (
                "not_measured: zero expert-confirmed risk and nonrisk labels"
            ),
            "real_llm_semantic_quality": (
                "not_measured: no Qwen/DeepSeek or other online model call"
            ),
            "m5_acceptance_thresholds": "not_claimed",
        },
    }


def _git_head() -> str | None:
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603, S607 - fixed local git command
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--legal-retrieval-report", type=Path)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    legal_report = args.legal_retrieval_report
    if legal_report is not None and not legal_report.is_absolute():
        legal_report = ROOT / legal_report
    result = evaluate(legal_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise SystemExit(f"Refusing to overwrite an existing evaluation report: {output}") from exc
    print(
        json.dumps(
            {
                "report": output.relative_to(ROOT).as_posix(),
                "fixture_manifest_sha256": result["dataset"]["manifest_sha256"],
                "fixture_expected_pattern_capture": result["metrics"][
                    "fixture_expected_pattern_capture"
                ],
                "risk_precision": None,
                "risk_recall": None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
