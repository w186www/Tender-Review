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

    def can_write_project(self) -> bool:
        return self.role == Role.REVIEWER
