"""Versioned run configuration assembled from existing immutable capabilities."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidding_compliance.domain.rules.models import SkillId
from bidding_compliance.model_gateway.contracts import DataPolicy, ModelPolicy


class ModelPolicySnapshot(BaseModel):
    """Provider-neutral execution limits; credentials and provider routing are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    profile: str = Field(min_length=1, max_length=100)
    timeout_seconds: float = Field(gt=0, le=3600)
    max_attempts: int = Field(ge=1, le=3)
    max_input_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    temperature: float = Field(ge=0, le=2)
    data_policy: Literal["public", "internal", "confidential", "restricted"]

    @classmethod
    def from_policy(cls, policy: ModelPolicy) -> "ModelPolicySnapshot":
        return cls(
            profile=policy.profile,
            timeout_seconds=policy.timeout_seconds,
            max_attempts=policy.max_attempts,
            max_input_tokens=policy.max_input_tokens,
            max_output_tokens=policy.max_output_tokens,
            temperature=policy.temperature,
            data_policy=policy.data_policy.value,
        )

    def to_policy(self) -> ModelPolicy:
        return ModelPolicy(
            profile=self.profile,
            timeout_seconds=self.timeout_seconds,
            max_attempts=self.max_attempts,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            temperature=self.temperature,
            data_policy=DataPolicy(self.data_policy),
        )


class ReviewConfigurationSnapshot(BaseModel):
    """The complete immutable identity selected before a review run starts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["task0011.review-configuration.v1"] = "task0011.review-configuration.v1"
    legal_publication_id: str = Field(min_length=1, max_length=36)
    skill_ids: tuple[SkillId, ...] = Field(min_length=1, max_length=5)
    skill_versions: dict[str, str]
    rule_versions: dict[str, str]
    ruleset_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    model_policy: ModelPolicySnapshot

    @model_validator(mode="after")
    def unique_skills_and_versions(self) -> Self:
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("duplicate skill id")
        if set(self.skill_versions) != set(self.skill_ids):
            raise ValueError("skill version map differs from enabled skills")
        if not self.rule_versions:
            raise ValueError("configuration must bind at least one rule version")
        return self
