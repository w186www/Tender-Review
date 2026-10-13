"""Run with: python -m bidding_compliance.api --port 8000."""

import argparse
import logging
import sys
from typing import TypedDict

import uvicorn
from pydantic import ValidationError

from bidding_compliance.core.config import Settings
from bidding_compliance.core.logging import configure_logging

from .app import create_app


class CommandOverrides(TypedDict, total=False):
    host: str
    port: int


def main() -> int:
    parser = argparse.ArgumentParser(description="招标审核后端开发服务")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    overrides: CommandOverrides = {}
    if args.host is not None:
        overrides["host"] = str(args.host)
    if args.port is not None:
        overrides["port"] = int(args.port)
    try:
        settings = Settings(**overrides)
    except ValidationError:
        print("配置无效，请检查环境名称、日志级别、端口和URL。", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    logging.getLogger("bidding_compliance").info("server_starting")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
