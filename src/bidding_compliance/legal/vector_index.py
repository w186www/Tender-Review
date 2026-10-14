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

from .contracts import EmbeddingModelIdentity, LegalIndex, RetrievalQuery
from .corpus import index_hash
from .hashing import canonical_hash
from .retrieval import clause_exclusions, confirmation_reason

INDEXER_VERSION = "sqlite-exact-cosine-f32le-v1"


class DenseEmbeddingProvider(Protocol):
    identity: EmbeddingModelIdentity
    max_batch_items: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


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
    items_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @staticmethod
    def build_identity(
        identity: EmbeddingModelIdentity,
        legal_snapshot_sha256: str,
        publication_id: str | None,
        revision_id: str | None,
    ) -> str:
        return canonical_hash(
            {
                "build_version": INDEXER_VERSION,
                "legal_snapshot_sha256": legal_snapshot_sha256,
                "publication_id": publication_id,
                "revision_id": revision_id,
                "embedding_identity_sha256": identity.identity_sha256,
            }
        )

    @classmethod
    def create(cls, **values: object) -> VectorIndexManifest:
        body = {**values, "manifest_sha256": "0" * 64}
        provisional = cls.model_construct(**cast(Any, body))
        payload = provisional.model_dump(mode="json", exclude={"manifest_sha256"})
        return cls.model_validate({**payload, "manifest_sha256": canonical_hash(payload)})

    @model_validator(mode="after")
    def hash_and_revision_binding(self) -> Self:
        expected_build = self.build_identity(
            self.embedding_identity,
            self.legal_snapshot_sha256,
            self.publication_id,
            self.revision_id,
        )
        if self.build_id != expected_build:
            raise ValueError("vector build identity mismatch")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != canonical_hash(payload):
            raise ValueError("vector manifest hash mismatch")
        if self.embedding_identity.dimensions is None:
            raise ValueError("dense vector identity must declare dimensions")
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
                """
            )

    def _build_key(
        self,
        index: LegalIndex,
        provider: DenseEmbeddingProvider,
        publication_id: str | None,
        revision_id: str | None,
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
        )

    def build(
        self,
        index: LegalIndex,
        provider: DenseEmbeddingProvider,
        *,
        publication_id: str,
        revision_id: str,
        batch_size: int | None = None,
    ) -> VectorIndexManifest:
        """Build/reuse/resume an index, committing successful batches as checkpoints."""
        if provider.identity.provider == "character":
            raise ValueError("dense vector artifacts require a dense embedding provider")
        legal_sha = _legal_snapshot_hash(index)
        build_id = self._build_key(index, provider, publication_id, revision_id)
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
            index.clauses, key=lambda item: (item.law_id, item.version, item.clause_id)
        )
        with self._connect() as db:
            existing = db.execute(
                "SELECT identity_sha256, identity_json, legal_snapshot_sha256, publication_id, "
                "revision_id, build_version, dimensions, status, item_count, items_sha256, "
                "manifest_sha256 FROM vector_build WHERE build_id = ?",
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
            elif tuple(existing[:7]) != expected:
                raise ValueError("vector build id is bound to conflicting metadata")
            elif existing[7] == "complete":
                manifest = self.manifest(build_id)
                if manifest.item_count != len(clauses):
                    raise ValueError("completed vector build item count differs from source")
                return manifest

        for offset in range(0, len(clauses), size):
            batch = clauses[offset : offset + size]
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
                vectors = provider.embed([clause.quote for clause in missing])
                if len(vectors) != len(missing):
                    raise ValueError("provider returned a different number of vectors")
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
                "SELECT identity_json, legal_snapshot_sha256, publication_id, revision_id "
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
