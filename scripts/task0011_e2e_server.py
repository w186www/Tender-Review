"""Launch an isolated Uvicorn app with an asyncio selector loop."""

from __future__ import annotations

import argparse
import asyncio

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    config = uvicorn.Config(
        args.app,
        host="127.0.0.1",
        port=args.port,
        loop="none",
        log_level="info",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
