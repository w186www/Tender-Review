"""HTTPX transport ownership helpers for injected test transports."""

from __future__ import annotations

import httpx


class BorrowedTransport(httpx.AsyncBaseTransport):
    """Use a caller-owned transport without closing it after one adapter request."""

    def __init__(self, delegate: httpx.AsyncBaseTransport) -> None:
        self._delegate = delegate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._delegate.handle_async_request(request)

    async def aclose(self) -> None:
        # The creator owns this injected transport and may reuse it across attempts.
        return None
