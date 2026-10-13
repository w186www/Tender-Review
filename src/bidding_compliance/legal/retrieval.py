"""Filtered BM25 + local vector retrieval with deterministic RRF fusion (FR-006)."""

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Protocol

from .contracts import (
    LegalHit,
    LegalIndex,
    LegalVersion,
    Reason,
    RetrievalQuery,
    RetrievalResult,
    VersionStatus,
)
from .corpus import index_hash


def terms(text: str) -> list[str]:
    result: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            result.extend(token[i:i + 2] for i in range(max(1, len(token) - 1)))
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


def scope_matches(version: LegalVersion, query: RetrievalQuery) -> bool:
    return (
        ("CN" in version.jurisdictions or any(
            query.region == region or query.region.startswith(region + "/")
            for region in version.jurisdictions
        ))
        and query.procurement_type in version.procurement_types
        and query.project_type in version.project_types
        and (version.effective_from is None or query.review_date >= version.effective_from)
        and (version.effective_to is None or query.review_date < version.effective_to)
    )


class LegalRetriever:
    def __init__(self, index: LegalIndex, embedding: Embedding | None = None) -> None:
        self.index = index
        self.embedding = embedding or CharacterEmbedding()
        # A changed adapter needs a new reproducibility contract and evaluation.
        if self.embedding.version != "character-bigram-1":
            raise ValueError("embedding version not supported by this retrieval snapshot")
        self.snapshot_hash = index_hash(index)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        versions = {(v.law_id, v.version): v for v in self.index.manifest.versions}
        eligible = []
        for clause in self.index.clauses:
            version = versions[(clause.law_id, clause.version)]
            if not scope_matches(version, query):
                continue
            reason: Reason = (
                "unverified" if version.verification == "unverified"
                else "outside_verification_horizon" if (
                    version.verified_through is None or query.review_date > version.verified_through
                ) else "unlocated" if clause.article is None else "valid"
            )
            if reason == "valid" or query.include_references:
                eligible.append((clause, version, reason))
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
        vector: list[tuple[str, float]] = []
        if eligible:
            embeddings = self.embedding.encode([query.text] + [c.quote for c, _, _ in eligible])
            if len(embeddings) != len(eligible) + 1:
                raise ValueError("embedding cardinality mismatch")
            vector = [(clause.clause_id, cosine(embeddings[0], value))
                      for (clause, _, _), value in zip(eligible, embeddings[1:], strict=True)]
        for ranking in (lexical, vector):
            for rank, (key, _) in enumerate(
                sorted((x for x in ranking if x[1] > 0), key=lambda x: (-x[1], x[0])), 1
            ):
                scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
        lookup = {c.clause_id: (c, v, reason) for c, v, reason in eligible}
        hits = []
        for key, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:query.limit]:
            clause, version, reason = lookup[key]
            status: VersionStatus = (
                "unverified" if reason != "valid" else
                "verified_historical" if version.effective_to else "verified_current"
            )
            hits.append(LegalHit(
                evidence_id=key, law_id=version.law_id, title=version.title,
                article=clause.article, version=version.version, quote=clause.quote,
                quote_hash=clause.quote_hash, source_uri=version.source_uri,
                source_hash=version.source_hash, text_hash=version.text_hash,
                locator=f"{version.text_path}#chars={clause.start}:{clause.end}",
                effective_from=version.effective_from, effective_to=version.effective_to,
                version_status=status, eligible_for_confirmation=reason == "valid",
                reason=reason, score=score,
            ))
        return RetrievalResult(snapshot_hash=self.snapshot_hash, query=query, hits=tuple(hits))
