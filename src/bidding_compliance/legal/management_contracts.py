"""Global operations are explicit capabilities, independent of tenant RBAC."""

import base64
import hashlib
from datetime import date
from pathlib import PurePosixPath
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .contracts import Closed, LegalIndex

LegalOperation = Literal["ingest", "verify", "publish", "disable", "rollback"]
OPERATIONS = frozenset({"ingest", "verify", "publish", "disable", "rollback"})


class OperatorCapabilities(Closed):
    active: bool = Field(strict=True)
    capabilities: tuple[LegalOperation, ...] = Field(
        max_length=5, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("duplicate global legal capability")
        return self


class VerificationSource(Closed):
    law_id: str
    version: str
    source_uri: str = Field(pattern=r"^https://[^/@]+\.gov\.cn/")
    path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    captured_on: date

    @field_validator("source_uri")
    @classmethod
    def official_uri(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or not url.hostname.endswith(".gov.cn")
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or "\\" in value
        ):
            raise ValueError("verification source must be an official HTTPS URI")
        return value


class LegalArtifact(Closed):
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_base64: str = Field(max_length=2666668)

    @field_validator("path")
    @classmethod
    def public_namespace(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or path.parts[:2] != ("knowledge", "legal")
        ):
            raise ValueError("only public legal artifacts may enter a publication")
        return value

    @model_validator(mode="after")
    def valid_bytes(self) -> Self:
        raw = base64.b64decode(self.data_base64, validate=True)
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("legal artifact hash/budget mismatch")
        return self


class CorpusBundle(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    index: LegalIndex
    artifacts: tuple[LegalArtifact, ...] = Field(min_length=1, max_length=3000)
    verification_sources: tuple[VerificationSource, ...] = ()

    @model_validator(mode="after")
    def complete_artifacts(self) -> Self:
        artifacts = {a.path: a for a in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("duplicate legal artifact path")
        expected = {
            p for v in self.index.manifest.versions for p in (v.text_path, v.source_snapshot_path)
        }
        expected.update(s.path for s in self.verification_sources)
        if expected != set(artifacts):
            raise ValueError("incomplete or unrelated legal artifact closure")
        if sum(len(base64.b64decode(a.data_base64)) for a in self.artifacts) > 50_000_000:
            raise ValueError("legal bundle budget exceeded")
        for source in self.verification_sources:
            if source.source_hash != artifacts[source.path].sha256:
                raise ValueError("verification source artifact mismatch")
        for version in self.index.manifest.versions:
            if (
                artifacts[version.text_path].sha256 != version.text_hash
                or artifacts[version.source_snapshot_path].sha256 != version.source_hash
            ):
                raise ValueError("revision manifest artifact mismatch")
            if version.verification == "verified" and not any(
                p.law_id == version.law_id and p.version == version.version
                for p in self.verification_sources
            ):
                raise ValueError("verified revision requires frozen verification source")
        return self


class RevisionRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_draft_sequence: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    verification_sources: tuple[VerificationSource, ...] = ()


class PublicationRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_sequence: int = Field(ge=0, strict=True)
    operation: Literal["publish", "disable", "rollback"]
    reason: str = Field(min_length=1, max_length=1000)
    revision_id: str | None = None
    expected_draft_sequence: int | None = Field(default=None, ge=0, strict=True)
    target_publication_id: str | None = None

    @model_validator(mode="after")
    def coherent_operation(self) -> Self:
        if self.operation == "publish":
            if self.revision_id is None or self.expected_draft_sequence is None:
                raise ValueError("publication requires explicit draft revision and sequence")
            if self.target_publication_id is not None:
                raise ValueError("publish cannot specify rollback target")
        elif self.operation == "rollback":
            if self.target_publication_id is None or self.revision_id is not None:
                raise ValueError("rollback requires a unique published target")
        elif self.revision_id is not None or self.target_publication_id is not None:
            raise ValueError("disable has no revision or rollback target")
        return self
