"""Run the configured durable review worker without starting an HTTP API server."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import selectors
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

from bidding_compliance.core.logging import configure_logging  # noqa: E402


def load_engine(assembly_name: str | None):
    if assembly_name:
        assembly = importlib.import_module(assembly_name)
    else:
        assembly = importlib.import_module("api_entry").assembly
    engine = getattr(assembly, "review_engine", None)
    if engine is None:
        engine = getattr(getattr(assembly, "app", None), "state", None)
        engine = getattr(engine, "review_engine", None)
    if engine is None:
        raise RuntimeError("configured deployment assembly has no review engine")
    return engine


async def run(engine) -> None:
    await engine.run_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assembly",
        help="optional app assembly module used by isolated integration runs",
    )
    args = parser.parse_args()
    configure_logging(os.environ.get("APP_LOG_LEVEL", "INFO"))
    engine = load_engine(args.assembly)
    logging.getLogger("bidding_compliance").info("review_worker_started")
    try:
        if sys.platform == "win32":
            asyncio.run(
                run(engine),
                loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
            )
        else:
            asyncio.run(run(engine))
    except KeyboardInterrupt:
        logging.getLogger("bidding_compliance").info("review_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
