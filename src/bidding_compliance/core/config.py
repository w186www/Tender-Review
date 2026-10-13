"""Validated configuration; secret values never appear in its representation."""

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
