"""End-to-end acceptance of a deployed stack, driven through the public reverse proxy.

Runs the same business flow the workbench drives, against whatever host you point it at:

    python deploy/verify_deployment.py --base-url http://127.0.0.1:8080

It creates a project, uploads a synthetic DOCX, waits for the isolated parser, confirms the
document context, runs the LangGraph review, records a human decision for every finding,
publishes the result, downloads both report formats and checks the downloaded bytes against
the server-side content hash. Only synthetic data is used; no supplier request is made.

This is deployment verification tooling. It contains no review logic: every step calls the
repository's existing authenticated API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

API = "/api/v1"


class CheckFailed(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, tenant: str, username: str, password: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=120, trust_env=False)
        self.tenant = tenant
        self.username = username
        self.password = password
        self.token: str | None = None
        self.steps: list[dict[str, object]] = []

    def record(self, step: str, detail: object) -> None:
        entry = {
            "step": step,
            "at": datetime.now(UTC).isoformat(),
            "detail": detail,
        }
        self.steps.append(entry)
        print(f"[ok] {step}: {json.dumps(detail, ensure_ascii=False)[:220]}", flush=True)

    def headers(self, idempotent: bool = False) -> dict[str, str]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotent:
            headers["Idempotency-Key"] = uuid.uuid4().hex
        return headers

    def expect(self, response: httpx.Response, *codes: int) -> httpx.Response:
        if response.status_code not in codes:
            raise CheckFailed(
                f"{response.request.method} {response.request.url.path} -> "
                f"{response.status_code}: {response.text[:400]}"
            )
        return response

    def login(self) -> None:
        response = self.expect(
            self.http.post(
                f"{API}/auth/token",
                json={
                    "tenant_id": self.tenant,
                    "username": self.username,
                    "password": self.password,
                },
            ),
            200,
        )
        self.token = response.json()["access_token"]
        identity = self.expect(self.http.get(f"{API}/auth/me", headers=self.headers()), 200).json()
        self.record("login", {"username": identity.get("username"), "role": identity.get("role")})

    def create_project(self) -> str:
        body = {
            "name": f"部署验收合成项目 {uuid.uuid4().hex[:8]}",
            "procurement_type": "government",
            "project_type": "works",
            "region": "合成地区",
            "procurement_method": "tender",
            "buyer_type": "government_entity",
            "subject_type": "works",
            "legal_frameworks": ["tendering"],
        }
        response = self.expect(
            self.http.post(f"{API}/projects", json=body, headers=self.headers(idempotent=True)),
            201,
        )
        project_id = response.json()["project_id"]
        self.record("create_project", {"project_id": project_id})
        return project_id

    def upload(self, project_id: str, payload: bytes, filename: str) -> str:
        response = self.expect(
            self.http.post(
                f"{API}/projects/{project_id}/documents",
                files={"file": (filename, payload, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers=self.headers(idempotent=True),
            ),
            202,
        )
        document = response.json()
        self.record(
            "upload_document",
            {
                "document_id": document["document_id"],
                "status": document["status"],
                "sha256": document["sha256"],
                "size_bytes": document["size_bytes"],
            },
        )
        if document["sha256"] != hashlib.sha256(payload).hexdigest():
            raise CheckFailed("the server-side digest does not match the uploaded bytes")
        return document["document_id"]

    def wait_for_document(self, project_id: str, document_id: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            document = self.expect(
                self.http.get(
                    f"{API}/projects/{project_id}/documents/{document_id}", headers=self.headers()
                ),
                200,
            ).json()
            if document["status"] != last:
                print(f"     document status: {document['status']}", flush=True)
                last = document["status"]
            # "quarantined" is the state an upload starts in, not a verdict.
            if document["status"] in {"needs_confirmation", "ready"}:
                return document
            if document["status"] in {"rejected", "failed"}:
                raise CheckFailed(
                    f"document intake ended as {document['status']} issues={document.get('issues')}"
                )
            time.sleep(3)
        raise CheckFailed(f"document did not reach a confirmable state (last {last})")

    def confirm_context(self, project_id: str, document_id: str, project_name: str) -> int:
        context = self.expect(
            self.http.get(
                f"{API}/projects/{project_id}/documents/{document_id}/context",
                headers=self.headers(),
            ),
            200,
        ).json()
        body = {
            "expected_version": context["version"],
            "reason": "部署验收：确认合成标书的适用上下文",
            "context": {
                "name": project_name,
                "procurement_type": "government",
                "project_type": "works",
                "region": "合成地区",
                "procurement_method": "tender",
                "buyer_type": "government_entity",
                "subject_type": "works",
                "legal_frameworks": ["tendering"],
            },
        }
        confirmed = self.expect(
            self.http.post(
                f"{API}/projects/{project_id}/documents/{document_id}/context",
                json=body,
                headers=self.headers(),
            ),
            200,
        ).json()
        # The endpoint answers with the updated Document, not with the context record.
        self.record(
            "confirm_context",
            {
                "status": confirmed["status"],
                "context_version": confirmed["context_version"],
                "parse_version": confirmed["parse_version"],
            },
        )
        if confirmed["status"] != "ready":
            raise CheckFailed(f"context confirmation left the document as {confirmed['status']}")
        return confirmed["context_version"]

    def start_review(self, project_id: str, document_id: str, timeout: float) -> dict:
        task = self.expect(
            self.http.post(
                f"{API}/projects/{project_id}/reviews",
                json={"document_ids": [document_id]},
                headers=self.headers(idempotent=True),
            ),
            202,
        ).json()
        self.record(
            "start_review",
            {"review_task_id": task["review_task_id"], "run_id": task["run_id"], "status": task["status"]},
        )
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            task = self.expect(
                self.http.get(f"{API}/reviews/{task['review_task_id']}", headers=self.headers()),
                200,
            ).json()
            if task["status"] != last:
                print(f"     review status: {task['status']}", flush=True)
                last = task["status"]
            if task["status"] in {"waiting_human", "result_published", "failed", "cancelled"}:
                self.record(
                    "review_finished",
                    {
                        "status": task["status"],
                        "failure_code": task.get("failure_code"),
                        "model_runtime": task.get("model_runtime"),
                    },
                )
                if task["status"] == "failed":
                    raise CheckFailed(f"review failed with {task.get('failure_code')}")
                return task
            time.sleep(3)
        raise CheckFailed(f"review did not settle (last {last})")

    def findings(self, task: dict) -> dict:
        findings = self.expect(
            self.http.get(
                f"{API}/review-tasks/{task['review_task_id']}/runs/{task['run_id']}/findings",
                headers=self.headers(),
            ),
            200,
        ).json()
        self.record(
            "list_findings",
            {
                "count": len(findings["findings"]),
                "pending": len(findings["pending_finding_ids"]),
                "status": findings["status"],
            },
        )
        return findings

    def decide(self, task: dict, findings: dict) -> int:
        decided = 0
        for finding in findings["findings"]:
            if finding["finding_id"] not in findings["pending_finding_ids"]:
                continue
            self.expect(
                self.http.post(
                    f"{API}/review-tasks/{task['review_task_id']}/runs/{task['run_id']}"
                    f"/findings/{finding['finding_id']}/decisions",
                    json={
                        "decision": "accept",
                        "expected_snapshot_hash": findings["snapshot_hash"],
                        "reason": "部署验收：人工复核接受该疑点并保留其证据状态",
                    },
                    headers=self.headers(idempotent=True),
                ),
                200,
            )
            decided += 1
        self.record("submit_decisions", {"decided": decided})
        return decided

    def publish(self, task: dict) -> str:
        result = self.expect(
            self.http.post(
                f"{API}/review-tasks/{task['review_task_id']}/runs/{task['run_id']}/publish",
                headers=self.headers(idempotent=True),
            ),
            200,
        ).json()
        self.record("publish_result", result)
        return result["result_id"]

    def reports(self, result_id: str, output_dir: Path) -> list[dict]:
        artifacts = []
        for output_format in ("docx", "pdf"):
            metadata = self.expect(
                self.http.post(
                    f"{API}/review-results/{result_id}/reports/{output_format}",
                    headers=self.headers(idempotent=True),
                ),
                200,
            ).json()
            content = self.expect(
                self.http.get(f"{API}/reports/{metadata['report_id']}/content", headers=self.headers()),
                200,
            ).content
            digest = hashlib.sha256(content).hexdigest()
            if digest != metadata["content_hash"]:
                raise CheckFailed(
                    f"{output_format}: downloaded bytes do not match the server content hash"
                )
            path = output_dir / f"review-report.{output_format}"
            path.write_bytes(content)
            artifacts.append(
                {
                    "format": output_format,
                    "report_id": metadata["report_id"],
                    "bytes": len(content),
                    "sha256": digest,
                    "matches_content_hash": True,
                    "path": str(path),
                }
            )
            self.record(
                f"download_report_{output_format}",
                {"bytes": len(content), "sha256": digest, "content_hash_match": True},
            )
        return artifacts

    def report_text(self, path: Path) -> str:
        if path.suffix == ".docx":
            from docx import Document as WordDocument

            return "\n".join(p.text for p in WordDocument(str(path)).paragraphs)
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="public origin, e.g. http://127.0.0.1:8080")
    parser.add_argument("--tenant", default="tenant-a")
    parser.add_argument("--username", default="reviewer")
    parser.add_argument("--password", default=None, help="defaults to DEMO_REVIEWER_PASSWORD")
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(".verification/task0026-deploy"))
    parser.add_argument("--document-timeout", type=float, default=600)
    parser.add_argument("--review-timeout", type=float, default=900)
    args = parser.parse_args()

    password = args.password or __import__("os").environ.get("DEMO_REVIEWER_PASSWORD", "")
    if not password:
        print("missing --password or DEMO_REVIEWER_PASSWORD", file=sys.stderr)
        return 2

    fixture = args.fixture
    if fixture is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from generate_demo_fixture import DEFAULT_OUTPUT, create_fixture

        fixture = DEFAULT_OUTPUT
        if not fixture.exists():
            path, digest = create_fixture(fixture)
            print(f"synthetic fixture created: {path} sha256={digest}", flush=True)
    payload = fixture.read_bytes()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    client = Client(args.base_url, args.tenant, args.username, password)
    started = time.monotonic()
    evidence: dict[str, object] = {
        "base_url": args.base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "fixture": {"path": str(fixture), "sha256": hashlib.sha256(payload).hexdigest()},
        "steps": client.steps,
    }
    try:
        client.login()
        project_id = client.create_project()
        document_id = client.upload(project_id, payload, fixture.name)
        client.wait_for_document(project_id, document_id, args.document_timeout)
        client.confirm_context(project_id, document_id, f"部署验收合成项目 {project_id[:8]}")
        task = client.start_review(project_id, document_id, args.review_timeout)
        findings = client.findings(task)
        client.decide(task, findings)
        result_id = client.publish(task)
        artifacts = client.reports(result_id, output_dir)
        evidence["result"] = {
            "project_id": project_id,
            "document_id": document_id,
            "review_task_id": task["review_task_id"],
            "run_id": task["run_id"],
            "review_status": task["status"],
            "model_runtime": task.get("model_runtime"),
            "finding_count": len(findings["findings"]),
            "evidence_statuses": sorted({f["evidence_status"] for f in findings["findings"]}),
            "result_id": result_id,
            "reports": artifacts,
        }
        evidence["status"] = "passed"
    except CheckFailed as exc:
        evidence["status"] = "failed"
        evidence["failure"] = str(exc)
        print(f"\nFAILED: {exc}", file=sys.stderr)
    evidence["duration_seconds"] = round(time.monotonic() - started, 1)
    evidence["steps"] = client.steps
    (output_dir / "deployment-acceptance.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nevidence: {output_dir / 'deployment-acceptance.json'}", flush=True)
    print(f"status: {evidence['status']}", flush=True)
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
