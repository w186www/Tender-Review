"""Filtered BM25 + local vector retrieval with deterministic RRF fusion (FR-006)."""

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal, Protocol

from .contracts import (
    Applicability,
    EvidenceRef,
    Excluded,
    ExclusionReason,
    Framework,
    LegalClause,
    LegalHit,
    LegalIndex,
    LegalVersion,
    Reason,
    RetrievalQuery,
    RetrievalRankingTrace,
    RetrievalResult,
    RetrievalRuntimeSnapshot,
    VersionStatus,
)
from .corpus import index_hash
from .embedding_provider import character_embedding_identity


def terms(text: str) -> list[str]:
    result: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            result.extend(token[i : i + 2] for i in range(max(1, len(token) - 1)))
        else:
            result.append(token)
    return result


class Embedding(Protocol):
    version: str

    def encode(self, texts: Sequence[str]) -> Sequence[Mapping[str, float]]: ...


class CharacterEmbedding:
    """Offline sparse character vectors; no semantic or provider claims."""

    version = "character-bigram-1"

    def encode(self, texts: Sequence[str]) -> Sequence[Mapping[str, float]]:
        return [dict(Counter(terms(text))) for text in texts]


def cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if any(not math.isfinite(x) for x in (*left.values(), *right.values())):
        raise ValueError("invalid embedding")
    norm = math.sqrt(sum(x * x for x in left.values()) * sum(x * x for x in right.values()))
    return sum(x * right.get(k, 0) for k, x in left.items()) / norm if norm else 0.0


def scope_exclusions(version: LegalVersion, query: RetrievalQuery) -> list[ExclusionReason]:
    reasons: list[ExclusionReason] = []
    if not (
        "CN" in version.jurisdictions
        or any(
            query.region == region or query.region.startswith(region + "/")
            for region in version.jurisdictions
        )
    ):
        reasons.append("jurisdiction_mismatch")
    if query.procurement_type not in version.procurement_types:
        reasons.append("procurement_mismatch")
    if query.project_type not in version.project_types:
        reasons.append("project_type_mismatch")
    if version.effective_from and query.review_date < version.effective_from:
        reasons.append("not_yet_effective")
    if version.effective_to and query.review_date >= version.effective_to:
        reasons.append("expired")
    return reasons


def scope_matches(version: LegalVersion, query: RetrievalQuery) -> bool:
    return not scope_exclusions(version, query)


def clause_window(
    version: LegalVersion,
    article: str | None,
) -> tuple[date | None, date | None, str, bool]:
    effect = next((x for x in version.clause_effects if x.article == article), None)
    starts = [
        x
        for x in (version.effective_from, effect.effective_from if effect else None)
        if x is not None
    ]
    ends = [
        x for x in (version.effective_to, effect.effective_to if effect else None) if x is not None
    ]
    status = (
        "unknown"
        if version.end_status == "unknown" or (effect and effect.end_status == "unknown")
        else "confirmed_end"
        if ends
        else "confirmed_open"
    )
    return (
        max(starts) if starts else None,
        min(ends) if ends else None,
        status,
        (effect is None or effect.verification == "verified"),
    )


def clause_exclusions(
    version: LegalVersion,
    article: str | None,
    query: RetrievalQuery,
) -> list[ExclusionReason]:
    reasons = scope_exclusions(version, query)
    start, end, _, _ = clause_window(version, article)
    if start and query.review_date < start and "not_yet_effective" not in reasons:
        reasons.append("not_yet_effective")
    if end and query.review_date >= end and "expired" not in reasons:
        reasons.append("expired")
    scopes = [version.applicability]
    scopes.extend(x.scope for x in version.clause_scopes if x.article == article)
    for scope in scopes:
        if scope is not None:
            reasons.extend(x for x in applicability_exclusions(scope, query) if x not in reasons)
    if version.applicability is not None and not applicable_frameworks(version, article, query):
        if "framework_mismatch" not in reasons:
            reasons.append("framework_mismatch")
    return reasons


def applicability_exclusions(scope: Applicability, query: RetrievalQuery) -> list[ExclusionReason]:
    reasons: list[ExclusionReason] = []
    checks: list[tuple[ExclusionReason, bool]] = [
        ("method_mismatch", query.procurement_method in scope.procurement_methods),
        ("buyer_mismatch", query.buyer_type in scope.buyer_types),
        ("subject_mismatch", query.subject_type in scope.subject_types),
        ("framework_mismatch", bool(set(query.legal_frameworks) & set(scope.legal_frameworks))),
        (
            "procurement_mismatch",
            scope.procurement_types is None or query.procurement_type in scope.procurement_types,
        ),
        (
            "project_type_mismatch",
            scope.project_types is None or query.project_type in scope.project_types,
        ),
        (
            "jurisdiction_mismatch",
            scope.jurisdictions is None
            or any(
                query.region == r or query.region.startswith(r + "/") for r in scope.jurisdictions
            ),
        ),
    ]
    for mismatch, valid in checks:
        if not valid:
            reasons.append(mismatch)
    return reasons


def applicable_frameworks(
    version: LegalVersion,
    article: str | None,
    query: RetrievalQuery,
) -> tuple[Framework, ...]:
    if version.applicability is None:
        return ()
    frameworks = set(version.applicability.legal_frameworks)
    for rule in version.clause_scopes:
        if rule.article == article:
            frameworks.intersection_update(rule.scope.legal_frameworks)
    return tuple(f for f in query.legal_frameworks if f in frameworks)


def confirmation_reason(
    version: LegalVersion,
    article: str | None,
    query: RetrievalQuery,
) -> Reason:
    _, _, end_status, clause_verified = clause_window(version, article)
    return (
        "unverified"
        if version.verification == "unverified"
        else "outside_verification_horizon"
        if (version.verified_through is None or query.review_date > version.verified_through)
        else "unknown_end"
        if end_status == "unknown"
        else "clause_unverified"
        if not clause_verified
        else "unlocated"
        if article is None
        else "extraction_unverified"
        if version.expected_articles is None
        else "applicability_unverified"
        if version.applicability is None
        else "valid"
    )


class LegalRetriever:
    retrieval_version: Literal["bm25-char-cosine-rrf-5", "bm25-dense-cosine-rrf-1"] = (
        "bm25-char-cosine-rrf-5"
    )
    def __init__(self, index: LegalIndex, embedding: Embedding | None = None) -> None:
        self.index = index
        self.embedding = embedding or CharacterEmbedding()
        # A changed adapter needs a new reproducibility contract and evaluation.
        if self.embedding.version != "character-bigram-1":
            raise ValueError("embedding version not supported by this retrieval snapshot")
        self.snapshot_hash = index_hash(index)

    def runtime_snapshot(self, top_k: int) -> RetrievalRuntimeSnapshot:
        return RetrievalRuntimeSnapshot(
            top_k=top_k,
            embedding_identity=character_embedding_identity(),
        )

    def _vector_ranking(
        self, query: RetrievalQuery, eligible: list[tuple[LegalClause, LegalVersion, Reason]]
    ) -> list[tuple[str, float]]:
        if not eligible:
            return []
        embeddings = self.embedding.encode([query.text] + [c.quote for c, _, _ in eligible])
        if len(embeddings) != len(eligible) + 1:
            raise ValueError("embedding cardinality mismatch")
        return [
            (clause.clause_id, cosine(embeddings[0], value))
            for (clause, _, _), value in zip(eligible, embeddings[1:], strict=True)
        ]

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        query = RetrievalQuery.model_validate(query.model_dump())
        versions = {(v.law_id, v.version): v for v in self.index.manifest.versions}
        excluded: list[Excluded] = []
        for version in versions.values():
            reasons = scope_exclusions(version, query)
            if version.verification == "unverified":
                reasons.append("unverified")
            elif version.verified_through is None or query.review_date > version.verified_through:
                reasons.append("outside_verification_horizon")
            if version.end_status == "unknown":
                reasons.append("unknown_end")
            if reasons:
                excluded.append(
                    Excluded(
                        law_id=version.law_id,
                        version=version.version,
                        reasons=tuple(reasons),
                    )
                )
        eligible = []
        for clause in self.index.clauses:
            version = versions[(clause.law_id, clause.version)]
            reasons = clause_exclusions(version, clause.article, query)
            reason = confirmation_reason(version, clause.article, query)
            if reason != "valid" and reason not in reasons:
                reasons.append(reason)
            if reasons and not any(
                x.law_id == version.law_id
                and x.version == version.version
                and x.article == clause.article
                and x.reasons == tuple(reasons)
                for x in excluded
            ):
                excluded.append(
                    Excluded(
                        law_id=version.law_id,
                        version=version.version,
                        article=clause.article,
                        reasons=tuple(reasons),
                    )
                )
            if clause_exclusions(version, clause.article, query):
                continue
            if reason == "valid" or query.include_references:
                eligible.append((clause, version, reason))
            elif reason == "unlocated" and not any(
                x.law_id == version.law_id
                and x.version == version.version
                and "unlocated" in x.reasons
                for x in excluded
            ):
                excluded.append(
                    Excluded(
                        law_id=version.law_id,
                        version=version.version,
                        reasons=("unlocated",),
                    )
                )
        scores: dict[str, float] = {}
        counts = [Counter(terms(c.quote)) for c, _, _ in eligible]
        query_terms = set(terms(query.text))
        document_frequency = Counter(term for count in counts for term in count)
        n = len(counts)
        average = sum(sum(c.values()) for c in counts) / n if n else 1.0
        lexical: list[tuple[str, float]] = []
        for (clause, _, _), count in zip(eligible, counts, strict=True):
            score = 0.0
            length = sum(count.values())
            for term in sorted(query_terms):
                frequency = count[term]
                df = document_frequency[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.2 * (0.25 + 0.75 * length / (average or 1))
                score += idf * frequency * 2.2 / denominator
            lexical.append((clause.clause_id, score))
        vector = self._vector_ranking(query, eligible)
        traces: dict[str, dict[str, Any]] = {}
        for label, ranking in (("bm25", lexical), ("vector", vector)):
            raw_scores = dict(ranking)
            for rank, (key, _) in enumerate(
                sorted((x for x in ranking if x[1] > 0), key=lambda x: (-x[1], x[0])), 1
            ):
                scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
                traces.setdefault(key, {}).update(
                    {f"{label}_rank": rank, f"{label}_score": raw_scores[key]}
                )
        lookup = {c.clause_id: (c, v, reason) for c, v, reason in eligible}
        hits = []
        for key, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[: query.limit]:
            clause, version, reason = lookup[key]
            effective_from, effective_to, _, _ = clause_window(version, clause.article)
            status: VersionStatus = (
                "unverified"
                if reason != "valid"
                else "verified_historical"
                if (version.effective_to is not None and query.review_date >= version.effective_to)
                else "verified_current"
            )
            hits.append(
                LegalHit(
                    evidence_id=key,
                    law_id=version.law_id,
                    title=version.title,
                    article=clause.article,
                    version=version.version,
                    quote=clause.quote,
                    quote_hash=clause.quote_hash,
                    source_uri=version.source_uri,
                    source_hash=version.source_hash,
                    text_hash=version.text_hash,
                    locator=f"{version.text_path}#chars={clause.start}:{clause.end}",
                    effective_from=effective_from,
                    effective_to=effective_to,
                    version_status=status,
                    eligible_for_confirmation=reason == "valid",
                    reason=reason,
                    score=score,
                    applicable_frameworks=applicable_frameworks(version, clause.article, query),
                    evidence=EvidenceRef(
                        evidence_id=key,
                        kind="policy"
                        if version.authority
                        in {
                            "policy",
                            "reference",
                        }
                        else "law",
                        title=version.title,
                        article=clause.article,
                        quote=clause.quote,
                        source_uri="artifact://legal-text/" + version.text_hash,
                        source_hash=version.text_hash,
                        locator=f"chars={clause.start}:{clause.end}",
                        effective_from=effective_from,
                        effective_to=effective_to,
                        version_status=status,
                        jurisdiction=query.region,
                    ),
                )
            )
        matched_versions = {(lookup[key][0].law_id, lookup[key][0].version) for key in scores}
        for version_key, version in versions.items():
            if version_key not in matched_versions and not any(
                x.law_id == version.law_id and x.version == version.version for x in excluded
            ):
                excluded.append(
                    Excluded(
                        law_id=version.law_id,
                        version=version.version,
                        reasons=("no_text_match",),
                    )
                )
        return RetrievalResult(
            retrieval_version=self.retrieval_version,
            snapshot_hash=self.snapshot_hash,
            query=query,
            hits=tuple(hits),
            excluded=tuple(excluded),
            citable_evidence=tuple(
                hit.evidence_id for hit in hits if hit.eligible_for_confirmation
            ),
            ranking_trace=(
                tuple(
                    RetrievalRankingTrace(
                        clause_id=hit.evidence_id, fused_score=hit.score,
                        **traces[hit.evidence_id],
                    )
                    for hit in hits
                )
                if self.retrieval_version == "bm25-dense-cosine-rrf-1" else ()
            ),
        )
