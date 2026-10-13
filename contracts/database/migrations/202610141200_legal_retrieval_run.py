"""TASK-0006: append-only tenant-scoped retrieval runs, no existing-table changes."""

import sqlalchemy as sa
from alembic import op

revision = "202610141200"
down_revision = "202610131300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_retrieval_run",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "run_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"],
        ),
        sa.CheckConstraint("context_version >= 1"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(result_hash) = 64"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE legal_retrieval_run ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE legal_retrieval_run FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON legal_retrieval_run "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute(
            "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON legal_retrieval_run "
            "FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
        )
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER legal_run_{action.lower()} BEFORE {action} "
                "ON legal_retrieval_run BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
            )


def downgrade() -> None:
    # Explicitly destructive: stop writes and back up run history before downgrading.
    op.drop_table("legal_retrieval_run")
