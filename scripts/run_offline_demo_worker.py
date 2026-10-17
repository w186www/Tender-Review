"""Consume the isolated demo's persisted ingestion queue with the existing worker."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.persistence.models import IngestionJob

ROOT = Path(__file__).resolve().parents[1]


def _next_queued_document(engine: Engine, tenant_id: str) -> str | None:
    with engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        statement = (
            select(IngestionJob.document_id)
            .where(IngestionJob.tenant_id == tenant_id, IngestionJob.status == "queued")
            .order_by(IngestionJob.document_id)
            .limit(1)
        )
        return connection.execute(statement).scalar_one_or_none()


def _process_document(tenant_id: str, document_id: str) -> int:
    command = [
        sys.executable,
        str(ROOT / "scripts/process_document.py"),
        "--tenant",
        tenant_id,
        "--document",
        document_id,
    ]
    try:
        # The DB document ID remains an argv data value; shell execution is disabled.
        result = subprocess.run(  # noqa: S603 -- fixed local Python and script path
            command,
            cwd=ROOT,
            check=False,
            shell=False,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        print("Offline demo document worker exceeded its 15 minute limit.", flush=True)
        return 124
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, choices=["tenant-a"])
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if not 0.25 <= args.poll_seconds <= 10:
        parser.error("--poll-seconds must be between 0.25 and 10")

    settings = Settings()
    engine = make_engine(settings)
    print("Offline demo ingestion worker started for the synthetic tenant.", flush=True)
    try:
        while True:
            document_id = _next_queued_document(engine, args.tenant)
            if document_id is None:
                time.sleep(args.poll_seconds)
                continue
            exit_code = _process_document(args.tenant, document_id)
            if exit_code:
                print(
                    "Offline demo ingestion attempt returned a failure; "
                    "the persisted document status remains authoritative.",
                    flush=True,
                )
            else:
                print("Offline demo document processing completed.", flush=True)
    except KeyboardInterrupt:
        print("Offline demo ingestion worker stopping.", flush=True)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
