"""Shallow upload checks do not decompress or execute document contents in the API."""

from pathlib import PurePosixPath

from .ports import IngestionError
from .schemas import FileFormat, IngestionPolicy

TYPES: dict[str, tuple[FileFormat, str, bytes]] = {
    ".pdf": ("pdf", "application/pdf", b"%PDF-"),
    ".docx": (
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    ".png": ("png", "image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("jpeg", "image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("jpeg", "image/jpeg", b"\xff\xd8\xff"),
}


def validate_upload(
    filename: str, media_type: str, payload: bytes, policy: IngestionPolicy
) -> FileFormat:
    if (
        not filename
        or len(filename) > 255
        or any(c in filename for c in ("/", "\\", ":"))
        or any(ord(c) < 32 for c in filename)
    ):
        raise IngestionError("TYPE_MISMATCH")
    if not payload or len(payload) > policy.max_upload_bytes:
        raise IngestionError("SIZE_LIMIT")
    profile = TYPES.get(PurePosixPath(filename).suffix.lower())
    if profile is None or media_type != profile[1] or not payload.startswith(profile[2]):
        raise IngestionError("TYPE_MISMATCH")
    return profile[0]
