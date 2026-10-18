"""Trusted principal, independent of HTTP, database and model frameworks."""

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    OPERATOR = "operator"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    username: str
    role: Role
    session_id: str
    background_worker: bool = False
    execution_lease_id: str | None = None
    execution_generation: int | None = None

    def __post_init__(self) -> None:
        has_lease_id = self.execution_lease_id is not None
        has_generation = self.execution_generation is not None
        if has_lease_id != has_generation or self.background_worker != has_lease_id:
            raise ValueError("background execution requires a complete lease identity")

    def can_write_project(self) -> bool:
        return self.role == Role.REVIEWER
