"""Strict JSON and local-only Draft 2020-12 response validation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .errors import GatewayErrorCode, ModelGatewayError

MAX_SCHEMA_BYTES = 256_000
MAX_RESPONSE_BYTES = 2_000_000


def _collect_refs(value: Any, refs: list[str]) -> None:
    if isinstance(value, Mapping):
        for ref_key in ("$ref", "$dynamicRef"):
            ref = value.get(ref_key)
            if ref is not None:
                if not isinstance(ref, str) or not ref.startswith("#"):
                    raise ModelGatewayError(
                        GatewayErrorCode.SCHEMA_INVALID,
                        "Remote JSON Schema references are forbidden.",
                    )
                refs.append(ref)
        for child in value.values():
            _collect_refs(child, refs)
    elif isinstance(value, list):
        for child in value:
            _collect_refs(child, refs)


def _validate_local_pointer(schema: Mapping[str, Any], ref: str) -> None:
    if ref == "#":
        return
    if not ref.startswith("#/"):
        raise ValueError("only JSON Pointer local references are supported")
    current: Any = schema
    for segment in ref[2:].split("/"):
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdecimal() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            raise ValueError("local JSON Schema reference does not resolve")


def validate_schema(schema: Mapping[str, Any]) -> None:
    try:
        declared_draft = schema.get("$schema")
        if declared_draft not in (None, "https://json-schema.org/draft/2020-12/schema"):
            raise ValueError("only JSON Schema Draft 2020-12 is supported")
        raw = json.dumps(schema, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_SCHEMA_BYTES:
            raise ValueError("schema too large")
        refs: list[str] = []
        _collect_refs(schema, refs)
        for ref in refs:
            _validate_local_pointer(schema, ref)
        Draft202012Validator.check_schema(schema)
    except Exception:
        raise ModelGatewayError(
            GatewayErrorCode.SCHEMA_INVALID, "The output schema is invalid or exceeds limits."
        ) from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-standard JSON constant")


def parse_and_validate(content: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        if not content or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("empty or oversized response")
        value = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        if not isinstance(value, dict):
            raise ValueError("top level is not an object")
        Draft202012Validator(schema).validate(value)
        return value
    except Exception:
        raise ModelGatewayError(
            GatewayErrorCode.RESPONSE_INVALID,
            "Provider response is not valid JSON matching the requested schema.",
        ) from None
