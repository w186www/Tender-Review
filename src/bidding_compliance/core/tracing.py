"""Per-request context, isolated between concurrent async tasks."""

from contextvars import ContextVar
from uuid import UUID, uuid4

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


def choose_request_id(header: str | None) -> str:
    # Arbitrary user strings are never echoed into headers or logs.
    if header is not None and len(header) <= 36:
        try:
            return str(UUID(header))
        except ValueError:
            pass
    return str(uuid4())


def get_request_id() -> str:
    return request_id_context.get() or str(uuid4())
