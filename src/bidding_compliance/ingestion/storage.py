"""Opaque immutable object keys; raw paths and credentials never appear in responses."""

import hashlib
import re
from pathlib import Path
from uuid import UUID

import boto3
from botocore.config import Config

from bidding_compliance.core.config import Settings

from .ports import IngestionError, ObjectStore

KEY = re.compile(r"^[a-f0-9]{64}/[a-f0-9-]{36}/[a-f0-9-]{36}$")


def object_key(tenant: str, project: str, document: str) -> str:
    return "/".join(
        [hashlib.sha256(tenant.encode()).hexdigest(), str(UUID(project)), str(UUID(document))]
    )


def check_key(key: str) -> None:
    if not KEY.fullmatch(key):
        raise IngestionError("HASH_MISMATCH")


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        check_key(key)
        path = self.root / key
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise IngestionError("HASH_MISMATCH")
        return path

    def put(self, key: str, payload: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)

    def get(self, key: str, max_bytes: int) -> bytes:
        with self.path(key).open("rb") as handle:
            payload = handle.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise IngestionError("SIZE_LIMIT")
        return payload

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        if (
            settings.object_storage_endpoint is None
            or settings.object_storage_access_id is None
            or settings.object_storage_access_secret is None
        ):
            raise RuntimeError("S3 configuration required")
        self.client = boto3.client(
            "s3",
            endpoint_url=str(settings.object_storage_endpoint),
            region_name="us-east-1",
            aws_access_key_id=settings.object_storage_access_id.get_secret_value(),
            aws_secret_access_key=settings.object_storage_access_secret.get_secret_value(),
            config=Config(
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )
        self.bucket = settings.object_storage_bucket

    def put(self, key: str, payload: bytes) -> None:
        check_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType="application/octet-stream",
            IfNoneMatch="*",
        )

    def get(self, key: str, max_bytes: int) -> bytes:
        check_key(key)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            payload = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(payload) > max_bytes:
            raise IngestionError("SIZE_LIMIT")
        return payload

    def delete(self, key: str) -> None:
        check_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)


def make_store(settings: Settings) -> ObjectStore:
    if settings.object_storage_mode == "s3":
        return S3ObjectStore(settings)
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Local object storage is not enabled in production")
    return LocalObjectStore(settings.object_storage_root)
