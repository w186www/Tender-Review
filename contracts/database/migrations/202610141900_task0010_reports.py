"""TASK-0010 immutable reviewer before/after state and report artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "202610141900"
down_revision = "202610141800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_decision", sa.Column("before_state", sa.JSON(), nullable=True))
    op.add_column("review_decision", sa.Column("after_state", sa.JSON(), nullable=True))
    op.add_column("review_decision", sa.Column("request_trace_id", sa.String(36), nullable=True))
    op.create_table(
        "review_report_content",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("report_content_id", sa.String(36), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "report_content_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "result_id"], ["review_result.tenant_id", "review_result.result_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "result_id", "template_version"),
        sa.CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
        sa.CheckConstraint("length(CAST(content AS TEXT)) <= 20000000"),
    )
    op.create_table(
        "review_report",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("report_content_id", sa.String(36), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "report_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "result_id"], ["review_result.tenant_id", "review_result.result_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "report_content_id"],
            ["review_report_content.tenant_id", "review_report_content.report_content_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "result_id", "format", "template_version"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
        sa.CheckConstraint("format IN ('docx','pdf')"),
        sa.CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
        sa.CheckConstraint("length(content) > 0 AND length(content) <= 20000000"),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in ("review_report_content", "review_report"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_scope ON {table} USING "
                "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
                "(tenant_id = current_setting('app.tenant_id', true))"
            )
            op.execute(
                f"CREATE POLICY actor_insert ON {table} AS RESTRICTIVE FOR INSERT WITH CHECK "
                f"(actor_id = current_setting('app.user_id', true) AND EXISTS ("
                "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
                f"AND u.user_id = {table}.actor_id AND u.role = 'reviewer' AND u.active))"
            )
            op.execute(
                f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
            )
    elif op.get_bind().dialect.name == "sqlite":
        for table in ("review_report_content", "review_report"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
                )


def downgrade() -> None:
    op.drop_table("review_report")
    op.drop_table("review_report_content")
    op.drop_column("review_decision", "request_trace_id")
    op.drop_column("review_decision", "after_state")
    op.drop_column("review_decision", "before_state")
