"""Consistent UTC serialization for database timestamps across dialects."""

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_utc(value: datetime) -> str:
    return as_utc(value).isoformat()
