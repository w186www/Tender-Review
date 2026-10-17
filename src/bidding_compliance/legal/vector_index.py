"""Resumable, local exact vector artifact store, separate from legal publications."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import EmbeddingModelIdentity, LegalClause, LegalIndex, RetrievalQuery
from .corpus import index_hash
from .hashing import canonical_hash
from .retrieval import clause_exclusions, confirmation_reason

INDEXER_VERSION = "sqlite-exact-cosine-f32le-v1"

# Defaults mirror the DashScope embedding request ceilings. A caller that pre-authorizes
# planned batches must pass exactly the limits it approved.
MAX_ITEM_UTF8_BYTES = 8192
MAX_BATCH_UTF8_BYTES = 32768


class DenseEmbeddingProvider(Protocol):
    identity: EmbeddingModelIdentity
    max_batch_items: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """A deterministic grouping of clauses into provider requests.

    ``excluded`` holds clauses that cannot be sent at all because one clause alone exceeds
    the per-item byte ceiling; they are reported instead of being silently truncated.
    """

    batches: tuple[tuple[LegalClause, ...], ...]
    excluded: tuple[LegalClause, ...]

    @property
    def item_count(self) -> int:
        return sum(len(batch) for batch in self.batches)

    @property
    def clause_ids(self) -> tuple[str, ...]:
        return tuple(clause.clause_id for batch in self.batches for clause in batch)


def plan_batches(
    clauses: Sequence[LegalClause],
    *,
    max_items: int,
    max_item_bytes: int,
    max_batch_bytes: int,
) -> BatchPlan:
    """Group clauses in the given order under per-item and per-batch UTF-8 byte ceilings.

    Pure and repeatable: the same clauses and limits always yield the same batches,
    independent of what is already cached, so a caller can pre-authorize exactly the
    requests a later build will send. A batch holds at most ``max_items`` clauses and at
    most ``max_batch_bytes`` UTF-8 bytes. Clauses above ``max_item_bytes`` are excluded.
    """
    if max_items < 1 or max_item_bytes < 1 or max_batch_bytes < 1:
        raise ValueError("batch plan bounds must be positive")
    if max_batch_bytes < max_item_bytes:
        raise ValueError("a batch ceiling below the item ceiling cannot hold one clause")
    batches: list[tuple[LegalClause, ...]] = []
    excluded: list[LegalClause] = []
    current: list[LegalClause] = []
    current_bytes = 0
    for clause in clauses:
        size = len(clause.quote.encode("utf-8"))
        if size > max_item_bytes:
            excluded.append(clause)
            continue
        if current and (len(current) >= max_items or current_bytes + size > max_batch_bytes):
            batches.append(tuple(current))
            current, current_bytes = [], 0
        current.append(clause)
        current_bytes += size
    if current:
        batches.append(tuple(current))
    return BatchPlan(tuple(batches), tuple(excluded))


class VectorIndexManifest(BaseModel):
    """Content-addressed description of a complete vector index (vectors stay in SQLite)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_version: Literal["v1alpha1"] = "v1alpha1"
    build_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    build_version: Literal["sqlite-exact-cosine-f32le-v1"] = "sqlite-exact-cosine-f32le-v1"
    legal_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    publication_id: str = Field(min_length=1, max_length=36)
    revision_id: str = Field(min_length=1, max_length=36)
    embedding_identity: EmbeddingModelIdentity
    item_count: int = Field(ge=0)
    source_item_count: int | None = Field(default=None, ge=0)
    coverage_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    items_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @staticmethod
    def build_identity(
        identity: EmbeddingModelIdentity,
        legal_snapshot_sha256: str,
        publication_id: str | None,
        revision_id: str | None,
        coverage_sha256: str | None = None,
    ) -> str:
        payload = {
                "build_version": INDEXER_VERSION,
                "legal_snapshot_sha256": legal_snapshot_sha256,
                "publication_id": publication_id,
                "revision_id": revision_id,
                "embedding_identity_sha256": identity.identity_sha256,
            }
        if coverage_sha256 is not None:
            payload["coverage_sha256"] = coverage_sha256
        return canonical_hash(payload)

    @classmethod
    def create(cls, **values: object) -> VectorIndexManifest:
        body = {**values, "manifest_sha256": "0" * 64}
        provisional = cls.model_construct(**cast(Any, body))
        payload = provisional.model_dump(mode="json", exclude={"manifest_sha256"})
        if payload.get("coverage_sha256") is None:
            payload.pop("coverage_sha256", None)
            payload.pop("source_item_count", None)
        return cls.model_validate({**payload, "manifest_sha256": canonical_hash(payload)})

    @model_validator(mode="after")
    def hash_and_revision_binding(self) -> Self:
        expected_build = self.build_identity(
            self.embedding_identity,
            self.legal_snapshot_sha256,
            self.publication_id,
            self.revision_id,
            self.coverage_sha256,
        )
        if self.build_id != expected_build:
            raise ValueError("vector build identity mismatch")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.coverage_sha256 is None:
            payload.pop("coverage_sha256", None)
            payload.pop("source_item_count", None)
        if self.manifest_sha256 != canonical_hash(payload):
            raise ValueError("vector manifest hash mismatch")
        if self.embedding_identity.dimensions is None:
            raise ValueError("dense vector identity must declare dimensions")
        if (self.coverage_sha256 is None) != (self.source_item_count is None):
            raise ValueError("partial vector coverage requires source count and coverage hash")
        if self.source_item_count is not None and self.item_count > self.source_item_count:
            raise ValueError("vector coverage exceeds the frozen source")
        return self


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    clause_id: str
    score: float


def _vector_bytes(vector: Sequence[float], dimensions: int) -> bytes:
    if len(vector) != dimensions or any(not math.isfinite(float(value)) for value in vector):
        raise ValueError("embedding vector has invalid dimensions or values")
    return struct.pack("<" + "f" * dimensions, *(float(value) for value in vector))


def _unpack_vector(payload: bytes, dimensions: int) -> tuple[float, ...]:
    if len(payload) != dimensions * 4:
        raise ValueError("stored embedding byte length mismatch")
    vector = struct.unpack("<" + "f" * dimensions, payload)
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("stored embedding contains non-finite values")
    return vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class SQLiteVectorIndex:
    """Local durable index with immutable content cache and per-build checkpoints."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_build (
                    build_id TEXT PRIMARY KEY CHECK(length(build_id) = 64),
                    identity_sha256 TEXT NOT NULL CHECK(length(identity_sha256) = 64),
                    identity_json TEXT NOT NULL,
                    legal_snapshot_sha256 TEXT NOT NULL CHECK(length(legal_snapshot_sha256) = 64),
                    publication_id TEXT,
                    revision_id TEXT,
                    build_version TEXT NOT NULL,
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    status TEXT NOT NULL CHECK(status IN ('building', 'complete')),
                    item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count >= 0),
                    items_sha256 TEXT,
                    manifest_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS vector_cache (
                    identity_sha256 TEXT NOT NULL CHECK(length(identity_sha256) = 64),
                    law_id TEXT NOT NULL,
                    legal_version TEXT NOT NULL,
                    clause_id TEXT NOT NULL CHECK(length(clause_id) = 64),
                    text_sha256 TEXT NOT NULL CHECK(length(text_sha256) = 64),
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    vector_bytes BLOB NOT NULL,
                    vector_sha256 TEXT NOT NULL CHECK(length(vector_sha256) = 64),
                    PRIMARY KEY(identity_sha256, law_id, legal_version, clause_id, text_sha256)
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS vector_index_item (
                    build_id TEXT NOT NULL REFERENCES vector_build(build_id),
                    clause_id TEXT NOT NULL CHECK(length(clause_id) = 64),
                    law_id TEXT NOT NULL,
                    legal_version TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL CHECK(length(text_sha256) = 64),
                    vector_sha256 TEXT NOT NULL CHECK(length(vector_sha256) = 64),
                    PRIMARY KEY(build_id, clause_id)
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS vector_query_cache (
                    identity_sha256 TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_bytes BLOB NOT NULL,
                    vector_sha256 TEXT NOT NULL,
                    PRIMARY KEY(identity_sha256, text_sha256)
                ) WITHOUT ROWID;
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(vector_build)")}
            if "source_item_count" not in columns:
                db.execute("ALTER TABLE vector_build ADD COLUMN source_item_count INTEGER")
            if "coverage_sha256" not in columns:
                db.execute("ALTER TABLE vector_build ADD COLUMN coverage_sha256 TEXT")

    def _build_key(
        self,
        index: LegalIndex,
        provider: DenseEmbeddingProvider,
        publication_id: str | None,
        revision_id: str | None,
        coverage_sha256: str | None = None,
    ) -> str:
        if not publication_id or not revision_id:
            raise ValueError("published legal publication and revision identities are required")
        if provider.identity.dimensions is None:
            raise ValueError("dense provider identity must declare dimensions")
        if provider.max_batch_items < 1:
            raise ValueError("provider batch limit must be positive")
        return VectorIndexManifest.build_identity(
            provider.identity,
            _legal_snapshot_hash(index),
            publication_id,
            revision_id,
            coverage_sha256,
        )

    def planned_build_id(
        self,
        index: LegalIndex,
        provider: DenseEmbeddingProvider,
        *,
        publication_id: str,
        revision_id: str,
        clause_ids: Sequence[str],
    ) -> str:
        """Build id of an explicit clause selection, computable without any provider call.

        A caller can therefore decide whether an identical build already exists before it
        pre-authorizes batches or spends an external request.
        """
        selected = set(clause_ids)
        source_ids = {clause.clause_id for clause in index.clauses}
        if not selected or not selected <= source_ids:
            raise ValueError("vector subset must contain only frozen source clause ids")
        coverage_sha = canonical_hash(sorted(selected))
        return self._build_key(index, provider, publication_id, revision_id, coverage_sha)

    def build(
        self,
        index: LegalIndex,
        provider: DenseEmbeddingProvider,
        *,
        publication_id: str,
        revision_id: str,
        batch_size: int | None = None,
        clause_ids: Sequence[str] | None = None,
        send_full_batches: bool = False,
        max_item_bytes: int = MAX_ITEM_UTF8_BYTES,
        max_batch_bytes: int = MAX_BATCH_UTF8_BYTES,
    ) -> VectorIndexManifest:
        """Build/reuse/resume an index, committing successful batches as checkpoints.

        ``send_full_batches`` sends every planned batch as one request instead of only its
        cache misses. Batch membership then follows from the clause order, the batch size and
        the byte ceilings alone, so a caller can pre-authorize exactly the requests this
        method will send (``plan_batches`` with the same limits). Only clauses missing from
        the cache are written back; verified cached vectors are never overwritten.
        """
        if provider.identity.provider == "character":
            raise ValueError("dense vector artifacts require a dense embedding provider")
        legal_sha = _legal_snapshot_hash(index)
        selected_ids = set(clause_ids) if clause_ids is not None else None
        source_ids = {clause.clause_id for clause in index.clauses}
        if selected_ids is not None and (not selected_ids or not selected_ids <= source_ids):
            raise ValueError("vector subset must contain only frozen source clause ids")
        source_count = len(index.clauses) if selected_ids is not None else None
        dimensions = provider.identity.dimensions
        assert dimensions is not None
        size = min(batch_size or provider.max_batch_items, provider.max_batch_items)
        if size < 1:
            raise ValueError("batch size must be positive")
        identity_json = json.dumps(
            provider.identity.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        clauses = sorted(
            (
                clause for clause in index.clauses
                if selected_ids is None or clause.clause_id in selected_ids
            ),
            key=lambda item: (item.law_id, item.version, item.clause_id)
        )
        if send_full_batches:
            plan = plan_batches(
                clauses,
                max_items=size,
                max_item_bytes=max_item_bytes,
                max_batch_bytes=max_batch_bytes,
            )
            batch_groups: list[list[LegalClause]] = [list(batch) for batch in plan.batches]
            planned_ids = {clause.clause_id for batch in batch_groups for clause in batch}
            # Coverage is exactly what this build can index: clauses above the per-item
            # ceiling are reported by the caller and never enter an authorized batch.
            covered_ids = None if selected_ids is None else selected_ids & planned_ids
            expected_items = len(planned_ids)
            if selected_ids is not None and not covered_ids:
                raise ValueError("vector selection has no clause within the per-item ceiling")
        else:
            batch_groups = [
                list(clauses[offset : offset + size]) for offset in range(0, len(clauses), size)
            ]
            covered_ids = selected_ids
            expected_items = len(clauses)
        coverage_sha = canonical_hash(sorted(covered_ids)) if covered_ids is not None else None
        build_id = self._build_key(index, provider, publication_id, revision_id, coverage_sha)
        with self._connect() as db:
            existing = db.execute(
                "SELECT identity_sha256, identity_json, legal_snapshot_sha256, publication_id, "
                "revision_id, build_version, dimensions, status, item_count, items_sha256, "
                "manifest_sha256, source_item_count, coverage_sha256 "
                "FROM vector_build WHERE build_id = ?",
                (build_id,),
            ).fetchone()
            expected = (
                provider.identity.identity_sha256,
                identity_json,
                legal_sha,
                publication_id,
                revision_id,
                INDEXER_VERSION,
                dimensions,
            )
            if existing is None:
                db.execute(
                    "INSERT INTO vector_build (build_id, identity_sha256, identity_json, "
                    "legal_snapshot_sha256, publication_id, revision_id, build_version, "
                    "dimensions, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'building')",
                    (build_id, *expected),
                )
                db.execute(
                    "UPDATE vector_build SET source_item_count=?, coverage_sha256=? "
                    "WHERE build_id=?", (source_count, coverage_sha, build_id)
                )
            elif tuple(existing[:7]) != expected:
                raise ValueError("vector build id is bound to conflicting metadata")
            elif existing[11:] != (source_count, coverage_sha):
                raise ValueError("vector build coverage metadata conflicts")
            elif existing[7] == "complete":
                manifest = self.manifest(build_id)
                if manifest.item_count != expected_items:
                    raise ValueError("completed vector build item count differs from source")
                return manifest

        for batch in batch_groups:
            missing = []
            with self._connect() as db:
                for clause in batch:
                    text_sha = hashlib.sha256(clause.quote.encode("utf-8")).hexdigest()
                    cached = db.execute(
                        "SELECT dimensions, vector_bytes, vector_sha256 FROM vector_cache "
                        "WHERE identity_sha256=? AND law_id=? AND legal_version=? "
                        "AND clause_id=? AND text_sha256=?",
                        (
                            provider.identity.identity_sha256,
                            clause.law_id,
                            clause.version,
                            clause.clause_id,
                            text_sha,
                        ),
                    ).fetchone()
                    if cached is None:
                        missing.append(clause)
                    else:
                        if cached[0] != dimensions:
                            raise ValueError("cached vector dimension differs from identity")
                        _unpack_vector(cached[1], dimensions)
                        if hashlib.sha256(cached[1]).hexdigest() != cached[2]:
                            raise ValueError("cached vector checksum mismatch")
            generated: dict[str, tuple[bytes, str, object]] = {}
            if missing:
                payload = (
                    [clause.quote for clause in batch]
                    if send_full_batches
                    else [clause.quote for clause in missing]
                )
                vectors = provider.embed(payload)
                if len(vectors) != len(payload):
                    raise ValueError("provider returned a different number of vectors")
                if send_full_batches:
                    # Strict positional binding over the approved batch; only cache misses
                    # are accepted into the cache, so verified vectors are never replaced.
                    missing_ids = {clause.clause_id for clause in missing}
                    for clause, vector in zip(batch, vectors, strict=True):
                        encoded = _vector_bytes(vector, dimensions)
                        if clause.clause_id in missing_ids:
                            generated[clause.clause_id] = (
                                encoded,
                                hashlib.sha256(encoded).hexdigest(),
                                clause,
                            )
                else:
                    for clause, vector in zip(missing, vectors, strict=True):
                        encoded = _vector_bytes(vector, dimensions)
                        generated[clause.clause_id] = (
                            encoded,
                            hashlib.sha256(encoded).hexdigest(),
                            clause,
                        )
            with self._connect() as db:
                for clause in batch:
                    text_sha = hashlib.sha256(clause.quote.encode("utf-8")).hexdigest()
                    if clause.clause_id in generated:
                        encoded, vector_sha, _ = generated[clause.clause_id]
                        db.execute(
                            "INSERT OR IGNORE INTO vector_cache (identity_sha256, law_id, "
                            "legal_version, clause_id, text_sha256, dimensions, vector_bytes, "
                            "vector_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                provider.identity.identity_sha256,
                                clause.law_id,
                                clause.version,
                                clause.clause_id,
                                text_sha,
                                dimensions,
                                encoded,
                                vector_sha,
                            ),
                        )
                    cached = db.execute(
                        "SELECT dimensions, vector_bytes, vector_sha256 FROM vector_cache "
                        "WHERE identity_sha256=? AND law_id=? AND legal_version=? "
                        "AND clause_id=? AND text_sha256=?",
                        (
                            provider.identity.identity_sha256,
                            clause.law_id,
                            clause.version,
                            clause.clause_id,
                            text_sha,
                        ),
                    ).fetchone()
                    if cached is None or cached[0] != dimensions:
                        raise ValueError("vector cache insert could not be verified")
                    if hashlib.sha256(cached[1]).hexdigest() != cached[2]:
                        raise ValueError("vector cache checksum mismatch")
                    db.execute(
                        "INSERT OR IGNORE INTO vector_index_item (build_id, clause_id, law_id, "
                        "legal_version, text_sha256, vector_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            build_id,
                            clause.clause_id,
                            clause.law_id,
                            clause.version,
                            text_sha,
                            cached[2],
                        ),
                    )
                    linked = db.execute(
                        "SELECT law_id, legal_version, text_sha256, vector_sha256 "
                        "FROM vector_index_item WHERE build_id=? AND clause_id=?",
                        (build_id, clause.clause_id),
                    ).fetchone()
                    if linked != (clause.law_id, clause.version, text_sha, cached[2]):
                        raise ValueError("vector index binding conflict")

        manifest = self._create_manifest(build_id)
        with self._connect() as db:
            db.execute(
                "UPDATE vector_build SET status='complete', item_count=?, items_sha256=?, "
                "manifest_sha256=? WHERE build_id=? AND status='building'",
                (manifest.item_count, manifest.items_sha256, manifest.manifest_sha256, build_id),
            )
        return manifest

    @staticmethod
    def _items_digest(rows: list[tuple[str, str, str, str, str]]) -> str:
        return canonical_hash(
            [
                {
                    "clause_id": row[0],
                    "law_id": row[1],
                    "legal_version": row[2],
                    "text_sha256": row[3],
                    "vector_sha256": row[4],
                }
                for row in rows
            ]
        )

    def _create_manifest(self, build_id: str) -> VectorIndexManifest:
        with self._connect() as db:
            build = db.execute(
                "SELECT identity_json, legal_snapshot_sha256, publication_id, revision_id, "
                "source_item_count, coverage_sha256 "
                "FROM vector_build WHERE build_id=?",
                (build_id,),
            ).fetchone()
            if build is None:
                raise LookupError("vector build unavailable")
            identity = EmbeddingModelIdentity.model_validate_json(build[0])
        validated_rows = self._validated_index_items(build_id)
        items_sha = self._items_digest(
            [(row[0], row[1], row[2], row[3], row[4]) for row in validated_rows]
        )
        return VectorIndexManifest.create(
            build_id=build_id,
            legal_snapshot_sha256=build[1],
            publication_id=build[2],
            revision_id=build[3],
            embedding_identity=identity,
            item_count=len(validated_rows),
            source_item_count=build[4],
            coverage_sha256=build[5],
            items_sha256=items_sha,
        )

    def _validated_index_items(
        self, build_id: str
    ) -> list[tuple[str, str, str, str, str, bytes]]:
        """Require every indexed item to have a matching, intact cached vector."""
        with self._connect() as db:
            build = db.execute(
                "SELECT identity_sha256, dimensions FROM vector_build WHERE build_id=?",
                (build_id,),
            ).fetchone()
            if build is None:
                raise LookupError("vector build unavailable")
            rows = db.execute(
                "SELECT item.clause_id, item.law_id, item.legal_version, item.text_sha256, "
                "item.vector_sha256, cache.dimensions, cache.vector_bytes, cache.vector_sha256 "
                "FROM vector_index_item AS item JOIN vector_build AS build "
                "ON item.build_id=build.build_id LEFT JOIN vector_cache AS cache "
                "ON cache.identity_sha256=build.identity_sha256 "
                "AND cache.law_id=item.law_id AND cache.legal_version=item.legal_version "
                "AND cache.clause_id=item.clause_id AND cache.text_sha256=item.text_sha256 "
                "WHERE item.build_id=? ORDER BY item.clause_id",
                (build_id,),
            ).fetchall()

        validated: list[tuple[str, str, str, str, str, bytes]] = []
        dimensions = build[1]
        for (
            clause_id,
            law_id,
            legal_version,
            text_sha,
            item_sha,
            cache_dimensions,
            raw,
            cache_sha,
        ) in rows:
            if cache_dimensions is None or raw is None or cache_sha is None:
                raise ValueError("vector cache entry is missing for an index item")
            payload = bytes(raw)
            if cache_dimensions != dimensions:
                raise ValueError("vector cache dimension differs from its build")
            if item_sha != cache_sha or hashlib.sha256(payload).hexdigest() != cache_sha:
                raise ValueError("vector cache checksum mismatch")
            _unpack_vector(payload, dimensions)
            validated.append(
                (clause_id, law_id, legal_version, text_sha, item_sha, payload)
            )
        return validated

    def manifest(self, build_id: str) -> VectorIndexManifest:
        with self._connect() as db:
            row = db.execute(
                "SELECT status, item_count, items_sha256, manifest_sha256 FROM vector_build "
                "WHERE build_id=?",
                (build_id,),
            ).fetchone()
        if row is None or row[0] != "complete":
            raise LookupError("complete vector index unavailable")
        manifest = self._create_manifest(build_id)
        if (manifest.item_count, manifest.items_sha256, manifest.manifest_sha256) != row[1:]:
            raise ValueError("vector index manifest integrity mismatch")
        return manifest

    def indexed_clause_ids(self, build_id: str) -> frozenset[str]:
        """Validated complete coverage; a partial build is never reported as complete."""
        manifest = self.manifest(build_id)
        rows = self._validated_index_items(build_id)
        ids = frozenset(row[0] for row in rows)
        if manifest.coverage_sha256 is not None and (
            canonical_hash(sorted(ids)) != manifest.coverage_sha256
        ):
            raise ValueError("vector index coverage integrity mismatch")
        return ids

    def embed_query(self, provider: DenseEmbeddingProvider, text: str) -> tuple[float, ...]:
        """Durable query cache stores hashes and vectors, never request text."""
        dimensions = provider.identity.dimensions
        if dimensions is None or not text.strip():
            raise ValueError("dense query text and declared dimensions are required")
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = (provider.identity.identity_sha256, text_hash)
        with self._connect() as db:
            cached = db.execute(
                "SELECT dimensions, vector_bytes, vector_sha256 FROM vector_query_cache "
                "WHERE identity_sha256=? AND text_sha256=?", key
            ).fetchone()
        if cached is None:
            vectors = provider.embed([text])
            if len(vectors) != 1:
                raise ValueError("query provider returned invalid vector cardinality")
            raw = _vector_bytes(vectors[0], dimensions)
            checksum = hashlib.sha256(raw).hexdigest()
            with self._connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO vector_query_cache VALUES (?, ?, ?, ?, ?)",
                    (*key, dimensions, raw, checksum),
                )
                cached = db.execute(
                    "SELECT dimensions, vector_bytes, vector_sha256 FROM vector_query_cache "
                    "WHERE identity_sha256=? AND text_sha256=?", key
                ).fetchone()
        if cached is None or cached[0] != dimensions:
            raise ValueError("query vector cache dimension mismatch")
        if hashlib.sha256(cached[1]).hexdigest() != cached[2]:
            raise ValueError("query vector cache checksum mismatch")
        return _unpack_vector(cached[1], dimensions)

    def search_candidates(
        self,
        build_id: str,
        query_vector: Sequence[float],
        *,
        query_identity: EmbeddingModelIdentity,
        legal_index: LegalIndex,
        query: RetrievalQuery,
        publication_id: str,
        revision_id: str,
        top_k: int = 10,
    ) -> tuple[VectorSearchHit, ...]:
        """Filter verified, applicable law first; vector rank returns IDs only, never evidence."""
        if top_k < 1 or not publication_id or not revision_id:
            raise ValueError("invalid vector search parameters")
        manifest = self.manifest(build_id)
        if manifest.legal_snapshot_sha256 != index_hash(legal_index):
            raise ValueError("vector index belongs to a different legal snapshot")
        if (manifest.publication_id, manifest.revision_id) != (publication_id, revision_id):
            raise ValueError("vector index belongs to a different legal publication")
        if manifest.embedding_identity.identity_sha256 != query_identity.identity_sha256:
            raise ValueError("query and document vectors use different embedding identities")
        versions = {(item.law_id, item.version): item for item in legal_index.manifest.versions}
        eligible_clause_ids = set()
        for clause in legal_index.clauses:
            version = versions[(clause.law_id, clause.version)]
            if clause_exclusions(version, clause.article, query):
                continue
            if confirmation_reason(version, clause.article, query) == "valid":
                eligible_clause_ids.add(clause.clause_id)
        if not eligible_clause_ids:
            return ()
        dimensions = manifest.embedding_identity.dimensions
        assert dimensions is not None
        dense_query_vector = _unpack_vector(
            _vector_bytes(query_vector, dimensions), dimensions
        )
        rows = self._validated_index_items(build_id)
        if len(rows) != manifest.item_count:
            raise ValueError("vector cache item count differs from its manifest")
        scores: list[VectorSearchHit] = []
        for clause_id, _law_id, _legal_version, _text_sha, _vector_sha, raw_vector in rows:
            if clause_id not in eligible_clause_ids:
                continue
            scores.append(
                VectorSearchHit(
                    clause_id,
                    _cosine(dense_query_vector, _unpack_vector(raw_vector, dimensions)),
                )
            )
        scores.sort(key=lambda hit: (-hit.score, hit.clause_id))
        return tuple(scores[:top_k])


def _legal_snapshot_hash(index: LegalIndex) -> str:
    return index_hash(index)
