"""Storage, malware and parser ports; no vendor SDKs in their consumers."""

from typing import Protocol

from .schemas import FileFormat, IngestionPolicy, Issue, ParsedDocument


class IngestionError(Exception):
    def __init__(self, code: Issue) -> None:
        self.code = code
        super().__init__(code)


class ObjectStore(Protocol):
    def put(self, key: str, payload: bytes) -> None: ...
    def get(self, key: str, max_bytes: int) -> bytes: ...
    def delete(self, key: str) -> None: ...


class MalwareScanner(Protocol):
    def scan(self, payload: bytes) -> None: ...


class DocumentParser(Protocol):
    def parse(
        self, payload: bytes, format: FileFormat, policy: IngestionPolicy
    ) -> ParsedDocument: ...
