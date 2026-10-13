"""Real Uvicorn process + migrated local database + authenticated HTTP lifecycle."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import Tenant, User
from bidding_compliance.services.identity import PASSWORDS

ROOT = Path(__file__).resolve().parents[1]


def smoke() -> None:
    folder = ROOT / ".verification" / ("identity-smoke-" + uuid4().hex)
    folder.mkdir(parents=True)
    url = "sqlite:///" + (folder / "smoke.db").as_posix()
    settings = Settings(_env_file=None, app_env="test", database_url=url)
    engine = make_engine(settings)
    migrate(engine)
    password, key = str(uuid4()), str(uuid4()) + str(uuid4())
    with Session(engine) as db:
        db.add(Tenant(tenant_id="synthetic", name="synthetic", active=True))
        db.flush()
        db.add(
            User(
                tenant_id="synthetic",
                user_id="reviewer",
                username="reviewer",
                role="reviewer",
                password_hash=PASSWORDS.hash(password),
                active=True,
            )
        )
        db.commit()
    engine.dispose()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = os.environ.copy()
    environment.update(APP_ENV="test", DATABASE_URL=url, AUTH_SIGNING_KEY=key, PYTHONUTF8="1")
    process = subprocess.Popen(  # noqa: S603 - fixed local backend module, no shell
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
    issued_tokens: list[str] = []
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("backend did not start")
                try:
                    assert client.get("/api/v1/health").status_code == 200
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            response = client.post(
                "/api/v1/auth/token",
                json=dict(tenant_id="synthetic", username="reviewer", password=password),
            )
            assert response.status_code == 200
            token = response.json()["access_token"]
            issued_tokens.append(token)
            headers = {"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid4())}
            body = dict(
                name="synthetic",
                procurement_type="government",
                project_type="works",
                region="synthetic",
            )
            created = client.post("/api/v1/projects", headers=headers, json=body)
            assert created.status_code == 201
            path = "/api/v1/projects/" + created.json()["project_id"]
            assert client.get(path, headers=headers).json() == created.json()
            assert (
                client.put(path, headers=headers, json={**body, "expected_version": 1}).json()[
                    "version"
                ]
                == 2
            )
            assert len(client.get(path + "/versions", headers=headers).json()["items"]) == 2
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
            assert client.get(path, headers=headers).status_code == 401
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            output, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=5)
        assert password not in output + errors and key not in output + errors
        assert all(token not in output + errors for token in issued_tokens)
    print("PASS: real HTTP login, project create/read/version, logout/revocation; child stopped")


if __name__ == "__main__":
    try:
        smoke()
    except Exception as exc:
        print(f"FAILED: live identity check ({type(exc).__name__})")
        raise SystemExit(1) from None
