"""TASK0002-001/002: runnable health, errors, tracing and configuration privacy."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance import __version__
from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.core.logging import JsonFormatter
from bidding_compliance.core.tracing import request_id_context


def make_app():
    return create_app(Settings(_env_file=None, app_env="test"))


def validate_response(name, data):
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    schema = (
        "contracts/openapi.yaml#/paths/~1health/get/responses/200/content/application~1json/schema"
        if name == "Health"
        else "contracts/openapi.yaml#/components/schemas/Error"
    )
    validator_for_contract(ROOT, schema, documents, registry, api).validate(data)


def test_health_matches_contract_and_runtime_operation():
    app = make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}
        validate_response("Health", response.json())
        UUID(response.headers["x-request-id"])
        runtime_spec = client.get("/openapi.json").json()
        assert runtime_spec["paths"]["/api/v1/health"]["get"]["operationId"] == "getHealth"
        assert runtime_spec["paths"]["/api/v1/projects"]["post"]["operationId"] == "createProject"


def test_valid_request_id_is_preserved_and_logged(caplog):
    identifier = str(uuid4())
    caplog.set_level(logging.INFO, logger="bidding_compliance.api")
    with TestClient(make_app()) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": identifier})
    assert response.headers["x-request-id"] == identifier
    record = next(record for record in caplog.records if record.msg == "request_completed")
    assert record.request_id == identifier
    assert record.route == "/api/v1/health"
    assert record.status_code == 200
    assert request_id_context.get() == ""


@pytest.mark.parametrize("value", ["not-a-uuid", "x" * 1000])
def test_invalid_request_id_is_not_echoed(value):
    with TestClient(make_app()) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": value})
    assert response.headers["x-request-id"] != value
    UUID(response.headers["x-request-id"])


@pytest.mark.parametrize(
    "method,path,status,code",
    [
        ("GET", "/missing", 404, "NOT_FOUND"),
        ("POST", "/api/v1/health", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_protocol_errors_use_shared_envelope(method, path, status, code):
    identifier = str(uuid4())
    with TestClient(make_app()) as client:
        response = client.request(method, path, headers={"X-Request-ID": identifier})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"] == identifier
    validate_response("Error", response.json())
    if status == 405:
        assert response.headers["allow"] == "GET"


def test_validation_error_does_not_echo_sensitive_input(caplog):
    app = make_app()

    @app.get("/_test/validate")
    async def validate(count: int):
        return {"count": count}

    sensitive = "synthetic-sensitive-input-0002"
    caplog.set_level(logging.INFO, logger="bidding_compliance.api")
    with TestClient(app) as client:
        response = client.get("/_test/validate", params={"count": sensitive})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"] == {"error_count": 1}
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert sensitive not in response.text + caplog.text
    validate_response("Error", response.json())


def test_unhandled_exception_is_sanitized_before_server_logging(caplog, capsys):
    app = make_app()
    sensitive = "synthetic-private-exception-0002"

    @app.get("/_test/failure")
    async def failure():
        raise RuntimeError(sensitive)

    caplog.set_level(logging.INFO, logger="bidding_compliance.api")
    # Default TestClient would re-raise an exception leaked through the ASGI server boundary.
    with TestClient(app) as client:
        response = client.get("/_test/failure")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert sensitive not in response.text + caplog.text
    assert any(record.msg == "request_failed" for record in caplog.records)
    assert all(
        record.exc_info is None
        for record in caplog.records
        if record.name == "bidding_compliance.api"
    )
    diagnostics = json.loads(capsys.readouterr().err)
    assert diagnostics["request_id"] == response.headers["x-request-id"]
    assert diagnostics["exceptions"][0]["exception_type"] == "RuntimeError"
    assert any(frame["function"] == "failure" for frame in diagnostics["exceptions"][0]["stack"])
    assert sensitive not in json.dumps(diagnostics)
    validate_response("Error", response.json())


def test_http_exception_details_and_extra_headers_are_not_exposed():
    app = make_app()
    sensitive = "synthetic-private-http-detail-0002"

    @app.get("/_test/http-error")
    async def failure():
        raise HTTPException(400, detail=sensitive, headers={"X-Private": sensitive})

    with TestClient(app) as client:
        response = client.get("/_test/http-error")
    assert response.status_code == 400
    assert sensitive not in response.text
    assert "x-private" not in response.headers


def test_concurrent_requests_keep_separate_contexts():
    app = make_app()

    @app.get("/_test/context")
    async def context():
        await asyncio.sleep(0.01)
        return {"request_id": request_id_context.get()}

    async def run():
        identifiers = [str(uuid4()) for _ in range(8)]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *[
                    client.get("/_test/context", headers={"X-Request-ID": identifier})
                    for identifier in identifiers
                ]
            )
        for identifier, response in zip(identifiers, responses, strict=True):
            assert response.json()["request_id"] == response.headers["x-request-id"] == identifier

    asyncio.run(run())
    assert request_id_context.get() == ""


def test_settings_env_overrides_dotenv_and_masks_secrets(tmp_path, monkeypatch):
    sensitive = "synthetic-config-private-0002"
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"APP_PORT=8011\nDATABASE_URL={sensitive}\nREDIS_URL={sensitive}\n", encoding="utf-8"
    )
    monkeypatch.setenv("APP_PORT", "8012")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = Settings(_env_file=dotenv)
    assert settings.port == 8012
    assert settings.database_url.get_secret_value() == sensitive
    assert sensitive not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize("field,value", [("port", 0), ("port", 65536), ("app_env", "unknown")])
def test_invalid_settings_fail_closed(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_production_hides_interactive_docs():
    with TestClient(create_app(Settings(_env_file=None, app_env="production"))) as client:
        for path in ("/docs", "/openapi.json", "/redoc"):
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/health").status_code == 200


@pytest.mark.parametrize("field", ["base_url", "object_storage_endpoint"])
@pytest.mark.parametrize("suffix", ["account:synthetic-private@", ""])
def test_public_endpoint_urls_cannot_carry_credentials(field, suffix):
    url = f"http://{suffix}localhost:8000"
    if not suffix:
        url += "?token=synthetic-private"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: url})


def test_json_formatter_ignores_arbitrary_payload_and_traceback():
    sensitive = "synthetic-log-private-0002"
    record = logging.LogRecord("bidding_compliance", logging.ERROR, "test", 1, sensitive, (), None)
    record.authorization = sensitive
    record.password = sensitive
    record.request_id = str(uuid4())
    try:
        raise RuntimeError(sensitive)
    except RuntimeError:
        record.exc_info = sys.exc_info()
    output = JsonFormatter().format(record)
    assert sensitive not in output
    assert json.loads(output)["event"] == "service_log"


def test_cli_invalid_configuration_stops_without_exposing_values():
    sensitive = "synthetic-invalid-private-url-0002"
    environment = os.environ.copy()
    environment.update({"APP_BASE_URL": sensitive, "PYTHONUTF8": "1"})
    result = subprocess.run(  # noqa: S603 -- controlled local module; no shell or user executable
        [sys.executable, "-m", "bidding_compliance.api"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert sensitive not in result.stdout + result.stderr
    assert "配置无效" in result.stderr
