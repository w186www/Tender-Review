"""ClamAV INSTREAM; no scan bypass or clean result on unavailable/stale definitions."""

import socket
import struct
import time
from datetime import UTC, datetime, timedelta

from bidding_compliance.core.config import Settings

from .ports import IngestionError


class ClamAVScanner:
    def __init__(self, settings: Settings) -> None:
        if settings.clamd_host is None:
            raise RuntimeError("ClamAV endpoint required")
        self.host = settings.clamd_host
        self.port = settings.clamd_port
        self.timeout = settings.clamd_timeout_seconds
        self.max_age = settings.clamd_max_database_age_seconds

    def read_reply(self, connection: socket.socket) -> bytes:
        reply = bytearray()
        deadline = time.monotonic() + self.timeout
        while len(reply) < 4096:
            if time.monotonic() > deadline:
                raise IngestionError("SCANNER_UNAVAILABLE")
            part = connection.recv(min(4096 - len(reply), 1024))
            if not part:
                break
            reply.extend(part)
            if b"\0" in part:
                break
        if b"\0" not in reply:
            raise IngestionError("SCANNER_UNAVAILABLE")
        return bytes(reply).split(b"\0", 1)[0]

    def scan(self, payload: bytes) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.sendall(b"zVERSION\0")
                version = self.read_reply(conn).decode("ascii")
            try:
                fields = version.split("/")
                if len(fields) != 3 or int(fields[1]) <= 0:
                    raise ValueError("missing database")
                published = datetime.strptime(fields[2], "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
                age = datetime.now(UTC) - published
                if age > timedelta(seconds=self.max_age) or age < timedelta(days=-1):
                    raise ValueError("stale definitions")
            except ValueError as exc:
                raise IngestionError("SCANNER_STALE") from exc
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                deadline = time.monotonic() + self.timeout
                conn.sendall(b"zINSTREAM\0")
                for offset in range(0, len(payload), 65536):
                    if time.monotonic() > deadline:
                        raise IngestionError("SCANNER_UNAVAILABLE")
                    chunk = payload[offset : offset + 65536]
                    conn.sendall(struct.pack("!I", len(chunk)) + chunk)
                conn.sendall(struct.pack("!I", 0))
                result = self.read_reply(conn)
            if result == b"stream: OK":
                return
            if result.startswith(b"stream: ") and result.endswith(b" FOUND"):
                raise IngestionError("MALICIOUS_CONTENT")
            raise IngestionError("SCANNER_UNAVAILABLE")
        except (OSError, UnicodeError) as exc:
            raise IngestionError("SCANNER_UNAVAILABLE") from exc
