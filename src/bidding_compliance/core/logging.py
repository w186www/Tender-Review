"""Allowlisted JSON logs: no bodies, raw URLs, config values or tracebacks."""

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig

from .diagnostics import DiagnosticFormatter, DiagnosticStderrHandler

EVENTS = {"request_completed", "request_failed", "server_starting"}
FIELDS = {"request_id", "method", "route", "status_code", "duration_ms", "error_code"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = (
            record.msg if isinstance(record.msg, str) and record.msg in EVENTS else "service_log"
        )
        data: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": event,
        }
        for field in FIELDS:
            if field in record.__dict__:
                data[field] = record.__dict__[field]
        # Deliberately ignore message interpolation, arbitrary extras and exc_info.
        return json.dumps(data, ensure_ascii=False, allow_nan=False)


def configure_logging(level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "safe_json": {"()": JsonFormatter},
                "operator_diagnostic": {"()": DiagnosticFormatter},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "safe_json",
                    "stream": "ext://sys.stdout",
                },
                "diagnostic": {"()": DiagnosticStderrHandler, "formatter": "operator_diagnostic"},
            },
            "loggers": {
                "bidding_compliance": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "bidding_compliance.diagnostics": {
                    "handlers": ["diagnostic"],
                    "level": "ERROR",
                    "propagate": False,
                },
            },
        }
    )
