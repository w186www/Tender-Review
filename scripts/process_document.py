"""Run a queued document using its persisted submitting identity; no role override."""

import argparse

from bidding_compliance.core.config import Settings
from bidding_compliance.core.diagnostics import report_exception
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.sandbox import DockerParser
from bidding_compliance.ingestion.scanner import ClamAVScanner
from bidding_compliance.ingestion.storage import make_store
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.ingestion_worker import execute


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--document", required=True)
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if settings.parser_image is None:
            raise RuntimeError("parser image configuration required")
        engine = make_engine(settings)
        result = execute(
            engine,
            args.tenant,
            args.document,
            DockerParser(settings.parser_image),
            ClamAVScanner(settings),
            make_store(settings),
            load_policy(),
        )
        print("Document processing status:", result.status)
        return 0 if result.status in {"needs_review", "needs_confirmation", "ready"} else 1
    except Exception as exc:
        report_exception(exc, "worker")
        print("Document processing failed; inspect the safe diagnostics and document status.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
