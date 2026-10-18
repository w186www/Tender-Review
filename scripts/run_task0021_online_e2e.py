"""Explicit DEC-002 gated entry point for the isolated synthetic Qwen browser E2E."""

from __future__ import annotations

import sys

from scripts.run_task0011_e2e import main as shared_main


def main() -> int:
    if "--dec-002-approved" not in sys.argv[1:]:
        raise SystemExit(
            "真实 Qwen E2E requires prior user approval of the exact DEC-002 proposal."
        )
    sys.argv[1:1] = ["--online-qwen"]
    return shared_main()


if __name__ == "__main__":
    raise SystemExit(main())
