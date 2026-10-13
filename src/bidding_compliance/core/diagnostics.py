"""Operator-only exception diagnostics without message text, source lines or locals."""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path


class DiagnosticFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        chains: list[dict[str, object]] = []
        exception = record.exc_info[1] if record.exc_info else None
        visited: set[int] = set()
        while exception is not None and id(exception) not in visited and len(chains) < 10:
            visited.add(id(exception))
            frames = [
                {
                    "file": Path(frame.f_code.co_filename).name,
                    "line": line,
                    "function": frame.f_code.co_name,
                }
                for frame, line in traceback.walk_tb(exception.__traceback__)
            ]
            chains.append(
                {
                    "exception_type": type(exception).__name__,
                    "exception_module": type(exception).__module__,
                    "stack": frames,
                }
            )
            exception = exception.__cause__ or exception.__context__
        data: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "event": "request_exception",
            "request_id": getattr(record, "request_id", ""),
            "exceptions": chains,
            "chain_truncated": exception is not None,
        }
        return json.dumps(data, ensure_ascii=False, allow_nan=False)


class DiagnosticStderrHandler(logging.Handler):
    """Resolve stderr at emit time so capture/sink redirection never uses a stale stream."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except Exception:
            # Logging.handleError would print the original record/exception and leak inputs.
            sys.stderr.write('{"event":"diagnostic_write_failed"}\n')


def report_exception(exception: BaseException, request_id: str) -> None:
    logger = logging.getLogger("bidding_compliance.diagnostics")
    logger.propagate = False
    if not logger.handlers:
        handler = DiagnosticStderrHandler()
        handler.setFormatter(DiagnosticFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.error(
        "request_exception",
        extra={"request_id": request_id},
        exc_info=(type(exception), exception, exception.__traceback__),
    )
