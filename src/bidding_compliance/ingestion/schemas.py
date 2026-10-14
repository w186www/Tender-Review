"""Versioned cross-module data; generated JSON Schemas are checked against these models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


FileFormat = Literal["pdf", "docx", "png", "jpeg"]
Issue = Literal[
    "TYPE_MISMATCH",
    "SIZE_LIMIT",
    "MALICIOUS_CONTENT",
    "ARCHIVE_LIMIT",
    "INVALID_FILE",
    "ENCRYPTED_FILE",
    "PAGE_LIMIT",
    "IMAGE_LIMIT",
    "TEXT_LIMIT",
    "OCR_LIMIT",
    "LOW_QUALITY",
    "SCANNER_UNAVAILABLE",
    "SCANNER_STALE",
    "PARSE_TIMEOUT",
    "PARSE_FAILED",
    "HASH_MISMATCH",
    "ACTOR_FORBIDDEN",
    "OUTPUT_LIMIT",
]


class IngestionPolicy(Closed):
    max_upload_bytes: int = Field(ge=1, le=10485760)
    max_pages: int = Field(ge=1, le=300)
    max_ocr_pages: int = Field(ge=1, le=30)
    max_image_pixels: int = Field(ge=1, le=20000000)
    max_zip_entries: int = Field(ge=1, le=2000)
    max_uncompressed_bytes: int = Field(ge=1, le=104857600)
    max_compression_ratio: int = Field(ge=1, le=100)
    max_fragments: int = Field(ge=1, le=10000)
    max_text_chars: int = Field(ge=1, le=2000000)
    min_text_chars: int = Field(ge=1, le=1000)
    min_ocr_confidence: float = Field(ge=0, le=1)
    parser_timeout_seconds: int = Field(ge=1, le=60)
    parser_output_bytes: int = Field(ge=1, le=8388608)
    job_lease_seconds: int = Field(ge=120, le=300)
    max_attempts: int = Field(ge=1, le=3)


class Fragment(Closed):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"coordinate_system": {"const": "ooxml"}},
                        "required": ["coordinate_system"],
                    },
                    "then": {"properties": {"page": {"type": "null"}, "bbox": {"type": "null"}}},
                    "else": {
                        "required": ["page", "bbox"],
                        "properties": {
                            "page": {"type": "integer", "minimum": 1},
                            "bbox": {
                                "type": "array",
                                "minItems": 4,
                                "maxItems": 4,
                                "items": {"type": "number", "minimum": 0},
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "table_cell"}}, "required": ["kind"]},
                    "then": {
                        "required": ["table", "row", "column"],
                        "properties": {
                            key: {"type": "integer", "minimum": 0}
                            for key in ("table", "row", "column")
                        },
                    },
                },
            ],
        },
    )
    locator: str = Field(min_length=1, max_length=500)
    page: int | None = Field(default=None, ge=1, le=300)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    coordinate_system: Literal["pdf_points", "image_pixels", "ooxml"]
    kind: Literal["paragraph", "table_cell", "ocr"]
    section: str = Field(default="", max_length=300)
    text: str = Field(max_length=8000)
    text_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    source: Literal["native", "ocr", "manual"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    table: int | None = Field(default=None, ge=0)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_locator(self) -> "Fragment":
        if self.kind == "table_cell" and any(
            v is None for v in (self.table, self.row, self.column)
        ):
            raise ValueError("table cell indices required")
        if self.coordinate_system == "ooxml":
            if self.page is not None or self.bbox is not None:
                raise ValueError("OOXML locations must not invent rendered pages")
        elif self.page is None or self.bbox is None:
            raise ValueError("page and bounds required")
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if min(self.bbox) < 0 or x1 < x0 or y1 < y0:
                raise ValueError("invalid bounds")
        return self


class ParsedDocument(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    source_hash: str = Field(pattern="^[a-f0-9]{64}$")
    format: FileFormat
    page_count: int | None = Field(default=None, ge=1, le=300)
    fragments: list[Fragment] = Field(max_length=10000)
    quality: Literal["passed", "requires_review"]
    issues: list[Issue] = Field(max_length=20)


class ParserRequest(Closed):
    format: FileFormat
    payload_base64: str = Field(max_length=13981016)
    policy: IngestionPolicy


class ParserResponse(Closed):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["result"],
                    "properties": {"result": {"type": "object"}, "error": {"type": "null"}},
                },
                {
                    "required": ["error"],
                    "properties": {"error": {"type": "string"}, "result": {"type": "null"}},
                },
            ]
        },
    )
    result: ParsedDocument | None = None
    error: Issue | None = None

    @model_validator(mode="after")
    def exclusive(self) -> "ParserResponse":
        if (self.result is None) == (self.error is None):
            raise ValueError("exactly one result or error required")
        return self


class DocumentResponse(Closed):
    document_id: str
    project_id: str
    status: Literal[
        "quarantined",
        "accepted",
        "rejected",
        "parsing",
        "needs_review",
        "needs_confirmation",
        "ready",
        "failed",
    ]
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    context_version: int = Field(default=0, ge=0)
    parse_version: int = Field(default=0, ge=0)
    issues: list[Issue] = Field(default_factory=list, max_length=20)


class SectionResponse(Closed):
    section_id: str
    source_hash: str = Field(pattern="^[a-f0-9]{64}$")
    automatic: Fragment
    effective: Fragment
    revision: int = Field(ge=1)


class SectionsResponse(Closed):
    document_id: str
    parse_version: int = Field(ge=1)
    items: list[SectionResponse]


class TextCorrection(Closed):
    section_id: str
    text: str = Field(min_length=1, max_length=8000)


class QualityCorrection(Closed):
    expected_parse_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    corrections: list[TextCorrection] = Field(min_length=1, max_length=10000)


class ContextCandidate(Closed):
    field: Literal[
        "procurement_type",
        "project_type",
        "region",
        "name",
        "industry",
        "budget_amount",
        "applicable_system",
    ]
    value: str | None
    confidence: float = Field(ge=0, le=1)
    section_id: str | None = None


class DocumentContext(Closed):
    document_id: str
    version: int = Field(ge=1)
    candidates: list[ContextCandidate]
    manual: "ContextFields | None" = None
    confirmed: bool
    reason: str | None = None


class ContextFields(Closed):
    name: str = Field(min_length=1, max_length=300)
    procurement_type: Literal["government", "enterprise", "other"]
    project_type: Literal["works", "goods", "services"]
    region: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    budget_amount: float | None = Field(default=None, ge=0, strict=True)
    applicable_system: str | None = Field(default=None, max_length=1000)
    procurement_method: Literal["tender", "non_tender", "unknown"] = "unknown"
    buyer_type: Literal["government_entity", "enterprise", "other", "unknown"] = "unknown"
    subject_type: Literal[
        "works", "works_related_goods", "works_related_services", "goods", "services", "unknown",
    ] = "unknown"
    legal_frameworks: list[Literal["tendering", "government_procurement"]] = Field(
        default_factory=list, max_length=2,
    )


class ContextConfirmation(Closed):
    expected_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    context: ContextFields


DocumentContext.model_rebuild()
