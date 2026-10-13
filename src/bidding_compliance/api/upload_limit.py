"""Bound multipart data before it reaches the multipart spool/parser."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bidding_compliance.ingestion.policy import load_policy

from .errors import error_response


class UploadBodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.limit = load_policy().max_upload_bytes + 65536

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith("/documents")
        ):
            await self.app(scope, receive, send)
            return
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        if len(lengths) > 1:
            await error_response(400)(scope, receive, send)
            return
        if lengths:
            try:
                length = int(lengths[0])
            except ValueError:
                length = -1
            if length < 0:
                await error_response(400)(scope, receive, send)
                return
            if length > self.limit:
                await error_response(413)(scope, receive, send)
                return
        payload = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            payload.extend(message.get("body", b""))
            if len(payload) > self.limit:
                await error_response(413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(payload), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
