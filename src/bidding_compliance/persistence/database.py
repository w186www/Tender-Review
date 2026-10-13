"""Explicit migration and transaction-local tenant scope."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings


def make_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise RuntimeError("database configuration required")
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite") and settings.app_env not in {"development", "test"}:
        raise RuntimeError("SQLite is only supported in development and tests")
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(connection: Any, _: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def set_tenant(session: Session, tenant_id: str) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
        )


def migrate(engine: Engine, revision: str = "head") -> None:
    root = Path(__file__).resolve().parents[3]
    config = Config()
    config.set_main_option("path_separator", "os")
    config.set_main_option("script_location", str(root / "contracts/database"))
    config.set_main_option("version_locations", str(root / "contracts/database/migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
