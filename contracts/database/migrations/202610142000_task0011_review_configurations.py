"""TASK-0011 tenant-scoped immutable configuration releases and CAS lifecycle."""

import sqlalchemy as sa
from alembic import op

revision = "202610142000"
down_revision = "202610141900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_configuration_revision",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "revision_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "revision_sequence"),
        sa.UniqueConstraint("tenant_id", "actor_id", "request_id"),
        sa.CheckConstraint("revision_sequence >= 1"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64"),
        sa.CheckConstraint("length(CAST(snapshot AS TEXT)) <= 1000000"),
    )
    op.create_table(
        "review_configuration_event",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=True),
        sa.Column("previous_active_id", sa.String(36), nullable=True),
        sa.Column("active_revision_id", sa.String(36), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expected_sequence", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "event_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "previous_active_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "active_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "sequence"),
        sa.UniqueConstraint("tenant_id", "actor_id", "request_id"),
        sa.CheckConstraint(
            "sequence >= 1 AND expected_sequence >= 0 AND sequence = expected_sequence + 1"
        ),
        sa.CheckConstraint("operation IN ('draft','publish','disable','rollback')"),
        sa.CheckConstraint("length(request_hash) = 64"),
        sa.CheckConstraint("(operation IN ('disable','draft') OR active_revision_id IS NOT NULL)"),
        sa.CheckConstraint(
            "(operation = 'disable' AND revision_id IS NULL) OR "
            "(operation != 'disable' AND revision_id IS NOT NULL)"
        ),
    )
    op.create_table(
        "review_configuration_state",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("active_revision_id", sa.String(36), nullable=True),
        sa.Column("draft_sequence", sa.Integer(), nullable=False),
        sa.Column("draft_revision_id", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "active_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "draft_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        sa.CheckConstraint("sequence >= 0 AND draft_sequence >= 0"),
    )

    if op.get_bind().dialect.name == "postgresql":
        admin = (
            "EXISTS (SELECT 1 FROM app_user u WHERE "
            "u.tenant_id = current_setting('app.tenant_id', true) AND "
            "u.user_id = current_setting('app.user_id', true) AND "
            "u.role = 'admin' AND u.active)"
        )
        for table in ("review_configuration_revision", "review_configuration_event"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_scope ON {table} FOR SELECT USING "
                "(tenant_id = current_setting('app.tenant_id', true))"
            )
            op.execute(
                f"CREATE POLICY admin_insert ON {table} FOR INSERT WITH CHECK "
                "(tenant_id = current_setting('app.tenant_id', true) AND "
                "actor_id = current_setting('app.user_id', true) AND " + admin + ")"
            )
            op.execute(
                f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
            )

        state = "review_configuration_state"
        op.execute(f"ALTER TABLE {state} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {state} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_scope ON {state} FOR SELECT USING "
            "(tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute(
            f"CREATE POLICY admin_insert ON {state} FOR INSERT WITH CHECK "
            "(tenant_id = current_setting('app.tenant_id', true) AND " + admin + ")"
        )
        op.execute(
            f"CREATE POLICY admin_update ON {state} FOR UPDATE USING "
            "(tenant_id = current_setting('app.tenant_id', true) AND "
            + admin
            + ") WITH CHECK (tenant_id = current_setting('app.tenant_id', true) AND "
            + admin
            + ")"
        )
        op.execute(
            """
CREATE FUNCTION review_configuration_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ev review_configuration_event%ROWTYPE;
BEGIN
 IF NEW.sequence <> OLD.sequence + 1 THEN
  RAISE EXCEPTION 'configuration state sequence must advance exactly once';
 END IF;
 SELECT * INTO ev FROM review_configuration_event
  WHERE tenant_id=NEW.tenant_id AND sequence=NEW.sequence;
 IF NOT FOUND OR ev.expected_sequence <> OLD.sequence
    OR ev.actor_id IS DISTINCT FROM current_setting('app.user_id', true)
    OR ev.previous_active_id IS DISTINCT FROM OLD.active_revision_id
    OR ev.active_revision_id IS DISTINCT FROM NEW.active_revision_id THEN
  RAISE EXCEPTION 'configuration state transition lacks its authorized event';
 END IF;
 IF NEW.draft_sequence <> OLD.draft_sequence THEN
  IF ev.operation <> 'draft' OR NEW.draft_sequence <> OLD.draft_sequence + 1
     OR NEW.draft_revision_id IS DISTINCT FROM ev.revision_id THEN
   RAISE EXCEPTION 'invalid configuration draft transition';
  END IF;
 ELSIF NEW.draft_revision_id IS DISTINCT FROM OLD.draft_revision_id THEN
  IF ev.operation <> 'publish' OR NEW.draft_revision_id IS NOT NULL
     OR OLD.draft_revision_id IS DISTINCT FROM ev.revision_id THEN
   RAISE EXCEPTION 'invalid configuration draft pointer transition';
  END IF;
 END IF;
 IF ev.operation = 'publish' AND (NEW.active_revision_id IS DISTINCT FROM ev.revision_id
    OR NEW.draft_revision_id IS NOT NULL) THEN
  RAISE EXCEPTION 'published configuration pointer mismatch';
 ELSIF ev.operation = 'rollback' AND NEW.active_revision_id IS DISTINCT FROM ev.revision_id THEN
  RAISE EXCEPTION 'rolled back configuration pointer mismatch';
 ELSIF ev.operation = 'disable' AND NEW.active_revision_id IS NOT NULL THEN
  RAISE EXCEPTION 'disabled configuration remains active';
 ELSIF ev.operation = 'draft'
    AND NEW.active_revision_id IS DISTINCT FROM OLD.active_revision_id THEN
  RAISE EXCEPTION 'draft creation changed active configuration';
 END IF;
 RETURN NEW;
END;
$$
"""
        )
        op.execute(
            "CREATE TRIGGER review_configuration_state_guard BEFORE UPDATE "
            "ON review_configuration_state FOR EACH ROW "
            "EXECUTE FUNCTION review_configuration_state_guard()"
        )
    elif op.get_bind().dialect.name == "sqlite":
        for table in ("review_configuration_revision", "review_configuration_event"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
                )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER review_configuration_state_guard ON review_configuration_state")
        op.execute("DROP FUNCTION review_configuration_state_guard()")
    for table in (
        "review_configuration_state",
        "review_configuration_event",
        "review_configuration_revision",
    ):
        op.drop_table(table)
