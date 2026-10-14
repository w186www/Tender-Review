"""Global operations are explicit capabilities, independent of tenant RBAC."""

from typing import Literal, Self

from pydantic import Field, model_validator

from .contracts import Closed

LegalOperation = Literal["ingest", "verify", "publish", "disable", "rollback"]
OPERATIONS = frozenset({"ingest", "verify", "publish", "disable", "rollback"})


class OperatorCapabilities(Closed):
    active: bool = Field(strict=True)
    capabilities: tuple[LegalOperation, ...] = Field(
        max_length=5, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("duplicate global legal capability")
        return self
