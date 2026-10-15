"""Prove that a restart or a full container rebuild does not lose deployment data.

    python deploy/verify_persistence.py --base-url http://127.0.0.1:8080 \
        --evidence .verification/task0026-deploy/deployment-acceptance.json

Reads the artefacts the acceptance run recorded, then re-reads them through the public API
and compares hashes. Run it once before the restart and again afterwards: the second run
must reproduce the same project, document, published result and report bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

API = "/api/v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--tenant", default="tenant-a")
    parser.add_argument("--username", default="reviewer")
    parser.add_argument("--password", default=None)
    parser.add_argument("--label", required=True, help="stage label, e.g. 'before' or 'after'")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    password = args.password or __import__("os").environ.get("DEMO_REVIEWER_PASSWORD", "")
    if not password:
        print("missing --password or DEMO_REVIEWER_PASSWORD", file=sys.stderr)
        return 2

    recorded = json.loads(args.evidence.read_text(encoding="utf-8"))
    if recorded.get("status") != "passed":
        print("the acceptance evidence is not a passing run", file=sys.stderr)
        return 2
    result = recorded["result"]

    with httpx.Client(base_url=args.base_url, timeout=120, trust_env=False) as http:
        login = http.post(
            f"{API}/auth/token",
            json={"tenant_id": args.tenant, "username": args.username, "password": password},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        snapshot: dict[str, object] = {
            "label": args.label,
            "checked_at": datetime.now(UTC).isoformat(),
        }

        project = http.get(f"{API}/projects/{result['project_id']}", headers=headers)
        project.raise_for_status()
        snapshot["project"] = {"project_id": project.json()["project_id"], "found": True}

        document = http.get(
            f"{API}/projects/{result['project_id']}/documents/{result['document_id']}",
            headers=headers,
        )
        document.raise_for_status()
        body = document.json()
        snapshot["document"] = {
            "document_id": body["document_id"],
            "status": body["status"],
            "sha256": body["sha256"],
            "parse_version": body["parse_version"],
            "context_version": body["context_version"],
        }

        task = http.get(f"{API}/reviews/{result['review_task_id']}", headers=headers)
        task.raise_for_status()
        snapshot["review_task"] = {
            "review_task_id": task.json()["review_task_id"],
            "status": task.json()["status"],
            "result_id": task.json().get("result_id"),
        }

        reports = []
        for artifact in result["reports"]:
            metadata = http.get(
                f"{API}/review-results/{result['result_id']}/reports", headers=headers
            )
            metadata.raise_for_status()
            match = next(
                (r for r in metadata.json()["items"] if r["report_id"] == artifact["report_id"]),
                None,
            )
            if match is None:
                reports.append({"format": artifact["format"], "found": False})
                continue
            content = http.get(f"{API}/reports/{artifact['report_id']}/content", headers=headers)
            content.raise_for_status()
            digest = hashlib.sha256(content.content).hexdigest()
            reports.append(
                {
                    "format": artifact["format"],
                    "found": True,
                    "bytes": len(content.content),
                    "sha256": digest,
                    "matches_recorded_sha256": digest == artifact["sha256"],
                }
            )
        snapshot["reports"] = reports

    ok = (
        snapshot["document"]["status"] == "ready"
        and snapshot["review_task"]["status"] == "result_published"
        and all(r.get("found") and r.get("matches_recorded_sha256") for r in snapshot["reports"])
    )
    snapshot["verdict"] = "passed" if ok else "failed"
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {args.output}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
