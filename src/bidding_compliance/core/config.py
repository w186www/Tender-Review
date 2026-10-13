"""Validated configuration; secret values never appear in its representation."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
        frozen=True,
    )

    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="APP_LOG_LEVEL"
    )
    host: str = Field(default="127.0.0.1", min_length=1, validation_alias="APP_HOST")
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="APP_PORT")
    base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:8000"), validation_alias="APP_BASE_URL"
    )
    database_url: SecretStr | None = Field(
        default=None, repr=False, validation_alias="DATABASE_URL"
    )
    redis_url: SecretStr | None = Field(default=None, repr=False, validation_alias="REDIS_URL")
    object_storage_endpoint: AnyHttpUrl | None = Field(
        default=None, validation_alias="OBJECT_STORAGE_ENDPOINT"
    )
    object_storage_bucket: str = Field(
        default="bidding-compliance", validation_alias="OBJECT_STORAGE_BUCKET"
    )
    model_profile: str = Field(default="local-development", validation_alias="MODEL_PROFILE")
    auth_signing_key: SecretStr | None = Field(
        default=None, repr=False, validation_alias="AUTH_SIGNING_KEY"
    )
    auth_issuer: str = Field(default="bidding-compliance", validation_alias="AUTH_ISSUER")
    auth_audience: str = Field(default="bidding-api", validation_alias="AUTH_AUDIENCE")
    auth_ttl_seconds: int = Field(default=900, ge=60, le=3600, validation_alias="AUTH_TTL_SECONDS")
    object_storage_mode: Literal["local", "s3"] = Field(
        default="local", validation_alias="OBJECT_STORAGE_MODE"
    )
    object_storage_root: Path = Field(
        default=Path("data/runtime/objects"), validation_alias="OBJECT_STORAGE_ROOT"
    )
    object_storage_access_id: SecretStr | None = Field(
        default=None, repr=False, validation_alias="OBJECT_STORAGE_ACCESS_ID"
    )
    object_storage_access_secret: SecretStr | None = Field(
        default=None, repr=False, validation_alias="OBJECT_STORAGE_ACCESS_SECRET"
    )
    parser_image: str | None = Field(
        default=None, pattern="^sha256:[a-f0-9]{64}$", validation_alias="PARSER_IMAGE"
    )
    clamd_host: str | None = Field(default=None, validation_alias="CLAMD_HOST")
    clamd_port: int = Field(default=3310, ge=1, le=65535, validation_alias="CLAMD_PORT")
    clamd_timeout_seconds: int = Field(
        default=20, ge=1, le=60, validation_alias="CLAMD_TIMEOUT_SECONDS"
    )
    clamd_max_database_age_seconds: int = Field(
        default=604800,
        ge=3600,
        le=604800,
        validation_alias="CLAMD_MAX_DATABASE_AGE_SECONDS",
    )

    @field_validator("auth_signing_key")
    @classmethod
    def validate_signing_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode()) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("base_url", "object_storage_endpoint")
    @classmethod
    def reject_private_url_parts(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and any((value.username, value.password, value.query, value.fragment)):
            raise ValueError("public endpoint URLs must not contain credentials, query or fragment")
        return value

    @property
    def docs_enabled(self) -> bool:
        return self.app_env in {"development", "test"}
