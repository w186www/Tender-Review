"""Immutable, run-level model/parser provenance; call-level audit is separate."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidding_compliance.ingestion.schemas import OCRRuntimeIdentity
from bidding_compliance.legal.contracts import EmbeddingModelIdentity, RetrievalRuntimeSnapshot


class FrozenParserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: str = Field(min_length=1, max_length=128)
    identity: OCRRuntimeIdentity | None = None
    identity_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent_identity(self) -> Self:
        if self.identity is None:
            if self.identity_sha256 is not None:
                raise ValueError("parser hash has no identity")
        elif self.identity.identity_sha256 != self.identity_sha256:
            raise ValueError("parser identity hash mismatch")
        return self


class ReviewRuntimeProvenance(BaseModel):
    """Frozen at run creation; it contains no call payloads, keys, or call audit events."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_version: Literal["task0018.review-runtime.v1"] = "task0018.review-runtime.v1"
    parser_documents: tuple[FrozenParserIdentity, ...] = Field(max_length=100)
    embedding_identity: EmbeddingModelIdentity
    vector_index_build_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    retrieval: RetrievalRuntimeSnapshot
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_profile: str = Field(min_length=1, max_length=100)
    model_config_revision_id: str = Field(min_length=1, max_length=36)
    model_config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent_runtime(self) -> Self:
        if (
            self.retrieval.embedding_identity.identity_sha256
            != self.embedding_identity.identity_sha256
        ):
            raise ValueError("retrieval embedding identity differs from the run identity")
        if self.vector_index_build_id != self.retrieval.vector_index_build_id:
            raise ValueError(
                "review does not activate a vector index without matching retrieval identity"
            )
        if len({item.document_id for item in self.parser_documents}) != len(self.parser_documents):
            raise ValueError("duplicate parser provenance document")
        return self
