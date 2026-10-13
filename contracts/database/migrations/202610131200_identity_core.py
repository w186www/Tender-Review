"""TASK-0004 initial core schema, frozen definitions; downgrade destroys stored data."""

from alembic import op
import sqlalchemy as sa

revision = "202610131200"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Frozen initial schema.
    op.create_table(
        "tenant",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "app_user",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("role IN ('admin','reviewer','auditor','operator')"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
        sa.UniqueConstraint("tenant_id", "username"),
    )
    op.create_table(
        "audit_event",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.tenant_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "event_id"),
    )
    op.create_table(
        "auth_session",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "session_id"),
    )
    op.create_table(
        "idempotency_record",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "key_hash"),
    )
    op.create_table(
        "project",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id"),
    )
    op.create_table(
        "document",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_ref", sa.String(length=1000), nullable=False),
        sa.CheckConstraint(
            "status IN ('quarantined','accepted','rejected','parsing','ready','failed')"
        ),
        sa.CheckConstraint("length(sha256) = 64"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.project_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "document_id"),
        sa.UniqueConstraint("tenant_id", "project_id", "document_id"),
    )
    op.create_table(
        "project_version",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "changed_by"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.project_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "version"),
    )
    op.create_table(
        "review_task",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("review_task_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting_human','succeeded','failed','cancelled')"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.project_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "review_task_id"),
    )
    # ### end Alembic commands ###
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE project ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE project FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON project USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("ALTER TABLE project_version ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE project_version FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON project_version USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("ALTER TABLE document ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE document FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON document USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("ALTER TABLE review_task ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE review_task FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON review_task USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("ALTER TABLE idempotency_record ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE idempotency_record FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON idempotency_record USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON audit_event USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute(
            "CREATE FUNCTION reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only table'; END; $$"
        )
        op.execute(
            "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
        )
        op.execute(
            "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON project_version FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
        )
    elif op.get_bind().dialect.name == "sqlite":
        for table in ("audit_event", "project_version"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
                )


def downgrade() -> None:
    # Frozen initial schema.
    op.drop_table("review_task")
    op.drop_table("project_version")
    op.drop_table("document")
    op.drop_table("project")
    op.drop_table("idempotency_record")
    op.drop_table("auth_session")
    op.drop_table("audit_event")
    op.drop_table("app_user")
    op.drop_table("tenant")
    # ### end Alembic commands ###
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_history_change()")
