"""Password verification, bounded JWT claims and revocable database sessions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.core.tracing import get_request_id
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import AuditEvent, AuthSession, Tenant, User

PASSWORDS = PasswordHasher()
# Unknown users perform the same Argon2 verification work without a fixed usable account.
_DUMMY_HASH = PASSWORDS.hash(str(uuid4()))


def audit(
    session: Session, tenant: str, actor: str | None, action: str, resource: str | None = None
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant,
            event_id=str(uuid4()),
            actor_id=actor,
            action=action,
            resource_id=resource,
            request_id=get_request_id(),
            occurred_at=datetime.now(UTC),
        )
    )


def signing_key(settings: Settings) -> str:
    if settings.auth_signing_key is None:
        raise RuntimeError("authentication configuration required")
    return settings.auth_signing_key.get_secret_value()


def login(
    session: Session, settings: Settings, tenant_id: str, username: str, password: str
) -> str:
    key = signing_key(settings)
    tenant = session.get(Tenant, tenant_id)
    user = session.scalar(
        select(User).where(User.tenant_id == tenant_id, User.username == username)
    )
    valid = False
    try:
        valid = PASSWORDS.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        pass
    set_tenant(session, tenant_id)
    if not valid or user is None or not user.active or tenant is None or not tenant.active:
        if tenant is not None:
            audit(session, tenant_id, None, "auth.failed")
            session.commit()
        raise PermissionError("authentication failed")
    now = datetime.now(UTC)
    session_id = str(uuid4())
    session.add(
        AuthSession(
            tenant_id=tenant_id,
            user_id=user.user_id,
            session_id=session_id,
            expires_at=now + timedelta(seconds=settings.auth_ttl_seconds),
            revoked=False,
        )
    )
    if PASSWORDS.check_needs_rehash(user.password_hash):
        user.password_hash = PASSWORDS.hash(password)
    token = jwt.encode(
        {
            "sub": user.user_id,
            "tenant_id": tenant_id,
            "jti": session_id,
            "iat": now,
            "exp": now + timedelta(seconds=settings.auth_ttl_seconds),
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
        },
        key,
        algorithm="HS256",
    )
    audit(session, tenant_id, user.user_id, "auth.login")
    session.commit()
    return token


def authenticate(session: Session, settings: Settings, token: str) -> Principal:
    key = signing_key(settings)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": ["sub", "tenant_id", "jti", "iat", "exp", "iss", "aud"]},
        )
        if any(
            not isinstance(claims[k], str) or not 1 <= len(claims[k]) <= 64
            for k in ("sub", "tenant_id", "jti")
        ):
            raise PermissionError("invalid identity")
    except jwt.InvalidTokenError as exc:
        raise PermissionError("invalid token") from exc
    tenant_id = claims["tenant_id"]
    tenant = session.get(Tenant, tenant_id)
    user = session.get(User, (tenant_id, claims["sub"]))
    record = session.get(AuthSession, (tenant_id, claims["jti"]))
    if (
        tenant is None
        or not tenant.active
        or user is None
        or not user.active
        or record is None
        or record.revoked
        or record.user_id != user.user_id
        or record.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
    ):
        raise PermissionError("identity unavailable")
    set_tenant(session, tenant_id)
    return Principal(tenant_id, user.user_id, user.username, Role(user.role), record.session_id)
