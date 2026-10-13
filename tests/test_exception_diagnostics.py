"""SEC-007/NFR-006: retain safe diagnosis without leaking message text or regular logs."""

import asyncio
import json
from uuid import uuid4

import pytest

from bidding_compliance.api.middleware import RequestContextMiddleware
from bidding_compliance.core.diagnostics import report_exception
from bidding_compliance.core.tracing import request_id_context


def test_diagnostic_retains_cause_types_and_frames_only(capsys, caplog):
    sensitive = "synthetic-private-diagnostic-text"
    try:
        try:
            raise KeyError(sensitive)
        except KeyError as cause:
            raise RuntimeError(sensitive) from cause
    except RuntimeError as exception:
        report_exception(exception, str(uuid4()))
    record = json.loads(capsys.readouterr().err)
    assert [item["exception_type"] for item in record["exceptions"]] == ["RuntimeError", "KeyError"]
    assert all(item["stack"] for item in record["exceptions"])
    assert sensitive not in json.dumps(record) + caplog.text
    assert all(
        "source" not in frame and "locals" not in frame
        for item in record["exceptions"]
        for frame in item["stack"]
    )
    assert not any(log.name == "bidding_compliance.diagnostics" for log in caplog.records)


def test_exception_after_response_started_keeps_cause(capsys):
    original = RuntimeError("synthetic-private-stream-error")

    async def failing_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise original

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
    with pytest.raises(RuntimeError) as captured:
        asyncio.run(RequestContextMiddleware(failing_app)(scope, receive, send))
    assert captured.value.__cause__ is original
    assert sent[0]["status"] == 200
    assert request_id_context.get() == ""
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["exceptions"][0]["exception_type"] == "RuntimeError"
    assert "synthetic-private-stream-error" not in json.dumps(diagnostic)
