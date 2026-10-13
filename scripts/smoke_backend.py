"""Start the real backend, validate localhost HTTP responses, then stop only that child."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from verify_contracts import load_contracts, load_openapi, validator_for_contract

ROOT = Path(__file__).resolve().parents[1]


def smoke() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "APP_LOG_LEVEL": "INFO",
            "PYTHONUTF8": "1",
            "APP_BASE_URL": f"http://127.0.0.1:{port}",
        }
    )
    process = subprocess.Popen(  # noqa: S603 -- fixed local module; no shell or untrusted executable
        [
            sys.executable,
            "-m",
            "bidding_compliance.api",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        documents, registry, errors = load_contracts(ROOT)
        api, api_errors = load_openapi(ROOT)
        if errors or api_errors:
            raise RuntimeError("contract precheck failed")
        deadline = time.monotonic() + 20
        health = None
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "backend exited before health check; inspect local configuration"
                    )
                try:
                    health = client.get("/api/v1/health")
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            if health is None or health.status_code != 200:
                raise RuntimeError("backend did not become healthy within 20 seconds")
            validator_for_contract(
                ROOT,
                "contracts/openapi.yaml#/paths/~1health/get/responses/200/content/application~1json/schema",
                documents,
                registry,
                api,
            ).validate(health.json())
            UUID(health.headers["x-request-id"])
            identifier = str(uuid4())
            missing = client.get("/missing", headers={"X-Request-ID": identifier})
            validator_for_contract(
                ROOT, "contracts/openapi.yaml#/components/schemas/Error", documents, registry, api
            ).validate(missing.json())
            if (
                missing.status_code != 404
                or missing.json()["code"] != "NOT_FOUND"
                or missing.json()["request_id"] != identifier
                or missing.headers["x-request-id"] != identifier
            ):
                raise RuntimeError("live error response or request correlation mismatch")
            print(f"PASS: live HTTP health=200, missing=404, request IDs matched; port={port}")
            print(f"Health: {health.json()}")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def main() -> int:
    try:
        smoke()
    except Exception as exc:
        # The error messages above are controlled and do not include child stdout or settings.
        print(f"FAILED: live backend smoke check ({type(exc).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
