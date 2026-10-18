"""Shared validation for the project context used by legal retrieval and review startup."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from bidding_compliance.ingestion.schemas import ContextFields
from bidding_compliance.legal.contracts import RetrievalQuery

_FIELD_MESSAGES = {
    "region": ("地区未映射", "请在项目上下文中选择受支持的省、市地区。"),
    "procurement_method": ("采购方式未确认", "请根据招标公告或采购文件确认采购方式。"),
    "buyer_type": ("采购主体未确认", "请根据采购人名称确认采购主体类型。"),
    "subject_type": ("标的类型未确认", "请根据采购范围确认工程、货物或服务类型。"),
    "project_type": ("项目类型无效", "请检查项目类型与采购标的类型是否一致。"),
    "legal_frameworks": ("适用制度冲突", "请按采购方式、主体和标的类型修正适用制度。"),
}


class ProjectContextIncomplete(ValueError):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__("project context is incomplete or inconsistent")


class ProjectDocumentContextMismatch(ValueError):
    def __init__(self, fields: list[str], document_id: str | None = None) -> None:
        self.fields = fields
        self.document_id = document_id
        super().__init__("document confirmation differs from the authoritative project context")


def _field_for_error(error: Mapping[str, Any]) -> tuple[str, str]:
    loc = error.get("loc", ())
    field = str(loc[0]) if loc else "legal_frameworks"
    message = str(error.get("msg", ""))
    if "REGION_UNMAPPED" in message:
        return "region", "unmapped"
    if "subject/project mismatch" in message:
        return "subject_type", "project_type_mismatch"
    if "buyer/procurement mismatch" in message:
        return "buyer_type", "procurement_type_mismatch"
    if "confirmed consistent legal frameworks" in message or "duplicate framework" in message:
        return "legal_frameworks", "framework_mismatch"
    if error.get("type") in {"missing", "none_required"}:
        return field, "missing"
    if error.get("type") == "literal_error" and error.get("input") == "unknown":
        return field, "unknown"
    return field, "invalid"


def project_context_issues(context: dict[str, Any]) -> list[dict[str, str]]:
    """Validate through the same RetrievalQuery contract used by legal retrieval."""
    try:
        RetrievalQuery.model_validate(
            {
                "text": "project context preflight",
                "review_date": "2000-01-01",
                "region": context.get("region"),
                "procurement_type": context.get("procurement_type"),
                "project_type": context.get("project_type"),
                "procurement_method": context.get("procurement_method"),
                "buyer_type": context.get("buyer_type"),
                "subject_type": context.get("subject_type"),
                "legal_frameworks": context.get("legal_frameworks", ()),
            }
        )
    except ValidationError as exc:
        issues_by_field: dict[str, dict[str, str]] = {}
        for error in exc.errors():
            field, code = _field_for_error(error)
            label, message = _FIELD_MESSAGES.get(
                field,
                ("项目上下文不一致", "请检查项目上下文中的采购制度和项目类型。"),
            )
            issues_by_field.setdefault(
                field, {"field": field, "code": code, "label": label, "message": message}
            )
        return [
            issues_by_field[field]
            for field in (
                "region",
                "procurement_method",
                "buyer_type",
                "subject_type",
                "project_type",
                "legal_frameworks",
            )
            if field in issues_by_field
        ]
    return []


def document_context_mismatch_fields(
    project_context: dict[str, Any], document_context: dict[str, Any]
) -> list[str]:
    """Document confirmation mirrors project fields; it never becomes a second authority."""
    project = ContextFields.model_validate(project_context).model_dump(mode="json")
    confirmed = ContextFields.model_validate(document_context).model_dump(mode="json")
    return [key for key in project if project[key] != confirmed[key]]
