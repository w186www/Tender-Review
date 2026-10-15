"""Run the real TASK-0011 browser acceptance suite in disposable local services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from defusedxml import ElementTree as ET
from sqlalchemy import text
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.ingestion.ports import IngestionError
from bidding_compliance.ingestion.scanner import ClamAVScanner
from bidding_compliance.ingestion.storage import S3ObjectStore
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import LegalOperatorGrant, Tenant, User
from bidding_compliance.services.identity import PASSWORDS

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "src/frontend"
PROFILE = "task0009-offline-verification"
CAPABILITIES = ["ingest", "verify", "publish", "disable", "rollback"]


def _run(command: list[str], *, timeout: int = 180, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed local tools and generated arguments; no shell
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def _docker(*arguments: str, timeout: int = 240, env: dict[str, str] | None = None) -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is required for the real isolated E2E run")
    return _run([docker, *arguments], timeout=timeout, env=env)


def _image_id(reference: str) -> str:
    try:
        return _docker("image", "inspect", reference, "--format", "{{.Id}}")
    except subprocess.CalledProcessError:
        if reference == "bidding-parser:task0005":
            _docker("build", "-f", "Dockerfile.parser", "-t", reference, ".", timeout=900)
        elif reference == "tender-minio-verification:task5":
            _docker(
                "build",
                "-f",
                "Dockerfile.minio-verification",
                "-t",
                reference,
                ".",
                timeout=900,
            )
        else:
            _docker("pull", reference, timeout=900)
        return _docker("image", "inspect", reference, "--format", "{{.Id}}")


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _container_port(name: str, port: int) -> int:
    line = _docker("port", name, str(port)).splitlines()[0]
    return int(line.rsplit(":", 1)[1])


def _start_container(
    name: str,
    image: str,
    port: int,
    *,
    environment: dict[str, str] | None = None,
    extra: tuple[str, ...] = (),
    command: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
) -> int:
    args = [
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        "tender-verification=task0011-e2e",
        "-p",
        f"127.0.0.1::{port}",
    ]
    for label in labels:
        args.extend(("--label", label))
    if extra:
        args.extend(extra)
    for key in sorted(environment or {}):
        args.extend(("--env", key))
    args.append(image)
    args.extend(command)
    docker_env = os.environ.copy()
    for secret_name in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID"):
        docker_env.pop(secret_name, None)
    _docker(*args, env=docker_env | (environment or {}))
    return _container_port(name, port)


def _wait_http(url: str, process: subprocess.Popen[bytes] | None, log: Path) -> None:
    deadline = time.monotonic() + 90
    with httpx.Client(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"service exited early; inspect {log}")
            try:
                response = client.get(url)
                if response.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.5)
    raise RuntimeError(f"service did not become ready; inspect {log}")


def _bootstrap_legal_publication(api_url: str, admin: dict[str, str]) -> dict[str, str]:
    """Seed the isolated test tenant's starting legal snapshot through real auth/API."""
    with httpx.Client(base_url=api_url, timeout=180, trust_env=False) as client:
        login = client.post(
            "/api/v1/auth/token",
            json={
                "tenant_id": admin["tenant"],
                "username": admin["username"],
                "password": admin["password"],
            },
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        draft = client.post(
            "/api/v1/admin/legal/drafts",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_draft_sequence": 0,
                "reason": "TASK-0011 隔离浏览器验收初始法规快照",
            },
        )
        draft.raise_for_status()
        payload = draft.json()
        revision_id = payload["draft_revision_id"]
        if not revision_id:
            raise RuntimeError("isolated legal bootstrap did not create a revision")
        publication = client.post(
            "/api/v1/admin/legal/publications",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_sequence": payload["sequence"],
                "expected_draft_sequence": payload["draft_sequence"],
                "operation": "publish",
                "revision_id": revision_id,
                "reason": "TASK-0011 隔离浏览器验收启用初始法规快照",
            },
        )
        publication.raise_for_status()
        state = publication.json()
        publication_id = state["publication_id"]
        if not publication_id:
            raise RuntimeError("isolated legal bootstrap did not publish a revision")
        return {"revision_id": revision_id, "publication_id": publication_id}


def _wait_scanner(scanner: ClamAVScanner) -> None:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            scanner.scan(b"Synthetic TASK-0011 clean scanner readiness probe.")
            return
        except IngestionError as exc:
            if exc.code == "SCANNER_STALE":
                raise RuntimeError("isolated ClamAV definitions are stale") from exc
            time.sleep(2)
    raise RuntimeError("isolated ClamAV did not become ready")


def _create_runtime_role(admin_url: str, password: str) -> None:
    engine = make_engine(Settings(_env_file=None, database_url=admin_url))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE ROLE task0011_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '"
                + password
                + "'"
            )
            grants = (
                "GRANT USAGE ON SCHEMA public TO task0011_runtime",
                "GRANT SELECT ON tenant, app_user, legal_operator_grant, legal_corpus_state, "
                "legal_corpus_revision, legal_publication, legal_law_identity "
                "TO task0011_runtime",
                "GRANT UPDATE(password_hash) ON app_user TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE ON auth_session, project TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE ON ingestion_job TO task0011_runtime",
                "GRANT SELECT, INSERT ON legal_retrieval_run TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE ON legal_corpus_state TO task0011_runtime",
                "GRANT SELECT, INSERT ON legal_corpus_revision, legal_publication, "
                "legal_law_identity, audit_event TO task0011_runtime",
                "GRANT SELECT, INSERT ON project_version, idempotency_record, document, "
                "review_task TO task0011_runtime",
                "GRANT UPDATE ON document TO task0011_runtime",
                "GRANT UPDATE ON review_task TO task0011_runtime",
                "GRANT SELECT, INSERT ON document_section, section_revision, "
                "document_context_version TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE ON review_engine_run TO task0011_runtime",
                "GRANT SELECT, INSERT ON review_artifact, review_decision, review_result, "
                "review_report_content, review_report TO task0011_runtime",
                "GRANT SELECT, INSERT ON review_configuration_revision, "
                "review_configuration_event TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE ON review_configuration_state TO task0011_runtime",
                "GRANT SELECT ON checkpoint_migrations TO task0011_runtime",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, "
                "checkpoint_writes TO task0011_runtime",
            )
            for statement in grants:
                connection.execute(text(statement))
    finally:
        engine.dispose()


def _seed_identities(admin_url: str) -> dict[str, dict[str, str]]:
    engine = make_engine(Settings(_env_file=None, database_url=admin_url))
    credentials: dict[str, dict[str, str]] = {}
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    Tenant(tenant_id="tenant-a", name="TASK-0011 合成租户甲", active=True),
                    Tenant(tenant_id="tenant-b", name="TASK-0011 合成租户乙", active=True),
                ]
            )
            session.flush()
            accounts = [
                ("tenant-a", "admin"),
                ("tenant-a", "reviewer"),
                ("tenant-a", "auditor"),
                ("tenant-a", "operator"),
                ("tenant-b", "reviewer"),
            ]
            for tenant, username in accounts:
                password = secrets.token_urlsafe(24)
                credentials[f"{tenant}:{username}"] = {
                    "tenant": tenant,
                    "username": username,
                    "password": password,
                }
                session.add(
                    User(
                        tenant_id=tenant,
                        user_id=username,
                        username=username,
                        role=(
                            username
                            if username in {"admin", "reviewer", "auditor", "operator"}
                            else "reviewer"
                        ),
                        password_hash=PASSWORDS.hash(password),
                        active=True,
                    )
                )
            session.flush()
            session.add(
                LegalOperatorGrant(
                    tenant_id="tenant-a",
                    user_id="admin",
                    active=True,
                    capabilities=CAPABILITIES,
                )
            )
            session.commit()
        return credentials
    finally:
        engine.dispose()


def _start_process(
    name: str,
    command: list[str],
    environment: dict[str, str],
    cwd: Path,
    logs: dict[str, Any],
) -> subprocess.Popen[bytes]:
    stream = (logs["folder"] / f"{name}.log").open("wb")
    logs["streams"].append(stream)
    options: dict[str, Any] = {
        "cwd": cwd,
        "env": environment,
        "stdout": stream,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(  # noqa: S603 -- fixed local service command; no shell
        command, **options
    )
    logs["processes"].append((name, process))
    return process


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _junit_summary(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"tests": 0, "failures": 1, "errors": 0, "skipped": 0}
    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        nodes = list(root.findall("testsuite"))
    else:
        nodes = [root]
    return {
        key: sum(int(node.get(attribute, "0")) for node in nodes)
        for key, attribute in (
            ("tests", "tests"),
            ("failures", "failures"),
            ("errors", "errors"),
            ("skipped", "skipped"),
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--online-qwen",
        action="store_true",
        help="run the separately gated TASK-0021 synthetic-data Qwen browser flow",
    )
    parser.add_argument(
        "--dec-002-approved",
        action="store_true",
        help="operator attests the exact DEC-002 proposal was approved before this run",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="serve an interactive loopback-only offline demo until Ctrl+C, then clean up",
    )
    parser.add_argument(
        "--keep-services",
        action="store_true",
        help="keep isolated API, Vite, PostgreSQL, MinIO, and ClamAV alive for local preview",
    )
    args = parser.parse_args()
    if args.online_qwen != args.dec_002_approved:
        parser.error("online Qwen requires --online-qwen and --dec-002-approved together")
    if args.serve and args.keep_services:
        parser.error("--serve owns service lifetime and cannot be combined with --keep-services")
    if args.online_qwen and (args.serve or args.keep_services):
        parser.error("online Qwen credentials and services may not be kept after the isolated run")
    if args.online_qwen and (
        not os.environ.get("DASHSCOPE_API_KEY") or not os.environ.get("BAILIAN_WORKSPACE_ID")
    ):
        parser.error(
            "approved online mode requires local DASHSCOPE_API_KEY and BAILIAN_WORKSPACE_ID"
        )
    run_id = uuid4().hex
    online_qwen = args.online_qwen
    folder_prefix = "task0021-qwen-e2e" if online_qwen else "task0011-e2e"
    folder = ROOT / ".verification" / f"{folder_prefix}-{run_id}"
    folder.mkdir(parents=True)
    logs: dict[str, Any] = {"folder": folder, "streams": [], "processes": []}
    containers: list[str] = []
    success = False
    credentials: dict[str, dict[str, str]] = {}
    state: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "repository_head": _run(["git", "rev-parse", "HEAD"]),
        "browser": "Microsoft Edge via Playwright channel msedge",
        "review_adapter": (
            "ModelGatewayService::BailianQwenChatAdapter"
            if online_qwen
            else "scripts/check_review_engine.py::OfflineReviewGateway"
        ),
        "execution_mode": (
            "online Qwen synthetic-only TASK-0021 demo"
            if online_qwen
            else "offline-deterministic synthetic demo"
        ),
        "network_policy": (
            "loopback services plus one fixed Beijing Bailian HTTPS call"
            if online_qwen
            else "loopback-only services; no online model route"
        ),
        "artifacts": str(folder),
        "status": "running",
    }
    try:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI is required for TASK-0011 real browser E2E")
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required for Playwright browser E2E")
        python = (
            str(ROOT / ".venv/Scripts/python.exe")
            if os.name == "nt"
            else str(ROOT / ".venv/bin/python")
        )
        if not Path(python).exists():
            python = sys.executable
        state["python"] = python

        parser_image = _image_id("bidding-parser:task0018-ocrfix2")
        minio_image = _image_id("tender-minio-verification:task5")
        clam_image = _image_id("clamav/clamav:stable")
        state["images"] = {"parser": parser_image, "minio": minio_image, "clamav": clam_image}

        suffix = run_id[:12]
        postgres_password = secrets.token_hex(24)
        database = f"task0011_{suffix}"
        postgres_name = f"task0011-pg-{suffix}"
        minio_name = f"task0011-minio-{suffix}"
        clam_name = f"task0011-clam-{suffix}"
        minio_access = f"task0011{suffix}"
        minio_secret = secrets.token_urlsafe(32)
        port = _start_container(
            postgres_name,
            "postgres:16",
            5432,
            environment={
                "POSTGRES_DB": database,
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": postgres_password,
            },
            extra=(
                "--health-cmd",
                "pg_isready",
                "--health-interval",
                "2s",
                "--health-retries",
                "40",
            ),
        )
        containers.append(postgres_name)
        state["containers"] = containers
        minio_port = _start_container(
            minio_name,
            minio_image,
            9000,
            environment={
                "MINIO_ROOT_USER": minio_access,
                "MINIO_ROOT_PASSWORD": minio_secret,
            },
            command=("server", "/data"),
        )
        containers.append(minio_name)
        clam_port = _start_container(
            clam_name,
            clam_image,
            3310,
            extra=("--memory=3g",),
        )
        containers.append(clam_name)
        state["containers"] = containers

        admin_url = (
            f"postgresql+psycopg://postgres:{quote(postgres_password)}@127.0.0.1:{port}/{database}"
        )
        admin_settings = Settings(
            _env_file=None,
            app_env="test",
            database_url=admin_url,
            auth_signing_key=secrets.token_urlsafe(48),
            object_storage_mode="s3",
            object_storage_endpoint=f"http://127.0.0.1:{minio_port}",
            object_storage_bucket=f"task0011-{suffix}",
            object_storage_access_id=minio_access,
            object_storage_access_secret=minio_secret,
            parser_image=parser_image,
            clamd_host="127.0.0.1",
            clamd_port=clam_port,
        )
        runtime_password = secrets.token_hex(24)
        runtime_url = (
            f"postgresql+psycopg://task0011_runtime:{quote(runtime_password)}"
            f"@127.0.0.1:{port}/{database}"
        )
        state["service_ports"] = {"postgres": port, "minio": minio_port, "clamav": clam_port}
        admin_engine = make_engine(admin_settings)
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with admin_engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            migrate(admin_engine)
        finally:
            admin_engine.dispose()
        _create_runtime_role(admin_url, runtime_password)
        credentials = _seed_identities(admin_url)

        store = S3ObjectStore(admin_settings)
        store.client.create_bucket(Bucket=admin_settings.object_storage_bucket)
        _wait_scanner(ClamAVScanner(admin_settings))
        state["data_plane"] = (
            "PostgreSQL 16 migration + runtime RLS role, S3 object storage and ClamAV ready"
        )
        fixture = folder / "synthetic-tender.docx"
        _run(
            [
                python,
                str(ROOT / "scripts/generate_demo_fixture.py"),
                "--output",
                str(fixture),
            ]
        )
        fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
        state["synthetic_fixture"] = str(fixture)
        state["synthetic_fixture_sha256"] = fixture_sha256
        if online_qwen:
            state["model_audit"] = str(folder / "qwen-model-audit.jsonl")

        api_port, no_review_api_port = _port(), _port()
        ui_port, no_review_ui_port = _port(), _port()
        signing_key = secrets.token_urlsafe(48)
        server_env = os.environ.copy()
        server_env.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(ROOT / "src"),
                        str(ROOT),
                        str(ROOT / "scripts"),
                        os.environ.get("PYTHONPATH", ""),
                    ]
                ),
                "APP_ENV": "test",
                "APP_HOST": "127.0.0.1",
                "APP_PORT": str(api_port),
                "APP_BASE_URL": f"http://127.0.0.1:{api_port}",
                "APP_LOG_LEVEL": "WARNING",
                "DATABASE_URL": runtime_url,
                "AUTH_SIGNING_KEY": signing_key,
                "MODEL_PROFILE": "task0021-online-qwen" if online_qwen else PROFILE,
                "OBJECT_STORAGE_MODE": "s3",
                "OBJECT_STORAGE_ENDPOINT": f"http://127.0.0.1:{minio_port}",
                "OBJECT_STORAGE_BUCKET": admin_settings.object_storage_bucket,
                "OBJECT_STORAGE_ACCESS_ID": minio_access,
                "OBJECT_STORAGE_ACCESS_SECRET": minio_secret,
                "PARSER_IMAGE": parser_image,
                "CLAMD_HOST": "127.0.0.1",
                "CLAMD_PORT": str(clam_port),
            }
        )
        if online_qwen:
            server_env.update(
                {
                    "TASK0021_ONLINE_APPROVED": "1",
                    "TASK0021_ALLOWED_SYNTHETIC_DOC_SHA256": fixture_sha256,
                    "TASK0021_MODEL_AUDIT_PATH": str(folder / "qwen-model-audit.jsonl"),
                }
            )
        api_process = _start_process(
            "api-review-engine",
            [
                python,
                str(ROOT / "scripts/task0011_e2e_server.py"),
                "--app",
                "scripts.task0021_online_e2e_app:app"
                if online_qwen
                else "scripts.task0011_e2e_app:app",
                "--port",
                str(api_port),
            ],
            server_env,
            ROOT,
            logs,
        )
        no_review_env = server_env.copy()
        for secret_name in (
            "DASHSCOPE_API_KEY",
            "BAILIAN_WORKSPACE_ID",
            "TASK0021_ONLINE_APPROVED",
            "TASK0021_ALLOWED_SYNTHETIC_DOC_SHA256",
            "TASK0021_MODEL_AUDIT_PATH",
        ):
            no_review_env.pop(secret_name, None)
        no_review_env["APP_PORT"] = str(no_review_api_port)
        no_review_env["APP_BASE_URL"] = f"http://127.0.0.1:{no_review_api_port}"
        no_review_process = _start_process(
            "api-no-review-executor",
            [
                python,
                str(ROOT / "scripts/task0011_e2e_server.py"),
                "--app",
                "scripts.task0011_e2e_no_review_app:app",
                "--port",
                str(no_review_api_port),
            ],
            no_review_env,
            ROOT,
            logs,
        )
        _wait_http(
            f"http://127.0.0.1:{api_port}/api/v1/health",
            api_process,
            folder / "api-review-engine.log",
        )
        _wait_http(
            f"http://127.0.0.1:{no_review_api_port}/api/v1/health",
            no_review_process,
            folder / "api-no-review-executor.log",
        )
        safe_service_env = server_env.copy()
        for secret_name in (
            "DASHSCOPE_API_KEY",
            "BAILIAN_WORKSPACE_ID",
            "TASK0021_ONLINE_APPROVED",
            "TASK0021_ALLOWED_SYNTHETIC_DOC_SHA256",
            "TASK0021_MODEL_AUDIT_PATH",
        ):
            safe_service_env.pop(secret_name, None)
        _start_process(
            "offline-demo-ingestion-worker",
            [
                python,
                str(ROOT / "scripts/run_offline_demo_worker.py"),
                "--tenant",
                "tenant-a",
            ],
            safe_service_env,
            ROOT,
            logs,
        )
        state["base_legal_publication"] = _bootstrap_legal_publication(
            f"http://127.0.0.1:{api_port}", credentials["tenant-a:admin"]
        )

        vite = str(FRONTEND / "node_modules/vite/bin/vite.js")
        main_ui_env = safe_service_env.copy()
        main_ui_env["BIDDING_API_TARGET"] = f"http://127.0.0.1:{api_port}"
        main_ui_env["VITE_REVIEW_MODE"] = "online-qwen" if online_qwen else "offline-deterministic"
        main_ui = _start_process(
            "vite-review-engine",
            [node, vite, "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"],
            main_ui_env,
            FRONTEND,
            logs,
        )
        no_review_ui_env = safe_service_env.copy()
        no_review_ui_env["BIDDING_API_TARGET"] = f"http://127.0.0.1:{no_review_api_port}"
        no_review_ui = _start_process(
            "vite-no-review-executor",
            [node, vite, "--host", "127.0.0.1", "--port", str(no_review_ui_port), "--strictPort"],
            no_review_ui_env,
            FRONTEND,
            logs,
        )
        _wait_http(f"http://127.0.0.1:{ui_port}/login", main_ui, folder / "vite-review-engine.log")
        _wait_http(
            f"http://127.0.0.1:{no_review_ui_port}/login",
            no_review_ui,
            folder / "vite-no-review-executor.log",
        )

        if args.serve:
            state["browser"] = "manual browser session supplied by the operator"
            state["status"] = "serving"
            state["preview_urls"] = {"web": f"http://127.0.0.1:{ui_port}/login"}
            reviewer = credentials["tenant-a:reviewer"]
            admin = credentials["tenant-a:admin"]
            print("离线确定性演示已启动，所有服务仅监听本机 loopback。")
            print(f"网页：http://127.0.0.1:{ui_port}/login")
            print(f"合成 DOCX：{fixture}")
            print(f"管理员账号：{admin['tenant']} / {admin['username']} / {admin['password']}")
            print(
                f"审核员账号：{reviewer['tenant']} / {reviewer['username']} / "
                f"{reviewer['password']}"
            )
            print("模式：固定 OfflineReviewGateway；不是 Qwen/DeepSeek 真实语义审查。")
            print("操作完成后在此终端按 Ctrl+C，服务和临时容器会停止清理。")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                state["status"] = "stopped"
                print("正在停止演示服务并清理临时容器。")
            return 0

        junit = folder / "playwright-junit.xml"
        browser_output = folder / "playwright-artifacts"
        e2e_env = safe_service_env.copy()
        e2e_env.update(
            {
                "E2E_BASE_URL": f"http://127.0.0.1:{ui_port}",
                "E2E_NO_REVIEW_BASE_URL": f"http://127.0.0.1:{no_review_ui_port}",
                "E2E_ADMIN_DATABASE_URL": admin_url,
                "E2E_PYTHON": python,
                "E2E_SYNTHETIC_FIXTURE": str(fixture),
                "E2E_JUNIT_PATH": str(junit),
                "E2E_OUTPUT_DIR": str(browser_output),
            }
        )
        if online_qwen:
            e2e_env["E2E_EXPECT_PROVIDER"] = "bailian"
            e2e_env["E2E_MODEL_AUDIT_PATH"] = str(folder / "qwen-model-audit.jsonl")
        role_env = {
            "ADMIN": "tenant-a:admin",
            "REVIEWER": "tenant-a:reviewer",
            "AUDITOR": "tenant-a:auditor",
            "OPERATOR": "tenant-a:operator",
            "CROSS_TENANT_REVIEWER": "tenant-b:reviewer",
        }
        for prefix, key in role_env.items():
            account = credentials[key]
            e2e_env[f"E2E_{prefix}_TENANT"] = account["tenant"]
            e2e_env[f"E2E_{prefix}_USERNAME"] = account["username"]
            e2e_env[f"E2E_{prefix}_PASSWORD"] = account["password"]

        playwright_cli = FRONTEND / "node_modules/@playwright/test/cli.js"
        if not playwright_cli.is_file():
            raise RuntimeError(
                "locked Playwright dependency is missing; install frontend dependencies"
            )
        command = [node, str(playwright_cli), "test", "--workers=1"]
        e2e_log = (folder / "playwright.log").open("wb")
        logs["streams"].append(e2e_log)
        result = subprocess.run(  # noqa: S603 -- fixed Node executable and local Playwright CLI
            command,
            cwd=FRONTEND,
            env=e2e_env,
            stdout=e2e_log,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
            shell=False,
        )
        junit_summary = _junit_summary(junit)
        state["browser_execution"] = {
            **junit_summary,
            "exit_code": result.returncode,
            "report": str(junit),
            "log": str(folder / "playwright.log"),
            "artifact_directory": str(browser_output),
        }
        if (
            result.returncode != 0
            or junit_summary["tests"] == 0
            or any(junit_summary[key] for key in ("failures", "errors", "skipped"))
        ):
            raise RuntimeError(
                "Playwright browser E2E did not pass; inspect its real JUnit and logs"
            )

        state["status"] = "passed"
        success = True
        if args.keep_services:
            state["kept_for_preview"] = True
            state["preview_urls"] = {
                "web": f"http://127.0.0.1:{ui_port}/login",
                "no_review_executor_demo": f"http://127.0.0.1:{no_review_ui_port}/login",
            }
            state["preview_accounts"] = sorted(role_env)
            print(f"E2E passed: {junit_summary['tests']} real browser cases.")
            print(f"Preview: http://127.0.0.1:{ui_port}/login")
            print("Admin login: tenant-a / admin / " + credentials["tenant-a:admin"]["password"])
            print(
                "Reviewer login: tenant-a / reviewer / "
                + credentials["tenant-a:reviewer"]["password"]
            )
            print(f"Isolated service records: {folder}")
        else:
            print(f"E2E passed: {junit_summary['tests']} real browser cases.")
            print(f"Isolated service records: {folder}")
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["finished_at"] = datetime.now(UTC).isoformat()
        (folder / "run.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not (success and args.keep_services):
            for _name, process in reversed(logs["processes"]):
                _stop_process(process)
            for name in reversed(containers):
                try:
                    _docker("stop", "--time", "10", name, timeout=30)
                except subprocess.CalledProcessError as exc:
                    print(f"Could not stop isolated container {name}: {exc}", file=sys.stderr)
        for stream in logs["streams"]:
            stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
