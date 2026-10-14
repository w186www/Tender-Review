"""TASK-0009 durable review runs, decisions, publication and LangGraph checkpoints."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "202610141800"
down_revision = "202610141700"
branch_labels = None
depends_on = None


def _json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def _tenant_table(name: str, actor_column: str | None = None) -> None:
    allowed = {
        "review_engine_run": "actor_id",
        "review_artifact": None,
        "review_decision": "reviewer_id",
        "review_result": "reviewer_id",
    }
    if name not in allowed or actor_column != allowed[name]:
        raise ValueError("tenant policy target is outside the migration allowlist")
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_scope ON {name} USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    if actor_column is not None:
        op.execute(  # noqa: S608 - interpolated identifiers are from the fixed allowlist above.
            f"CREATE POLICY actor_insert ON {name} AS RESTRICTIVE FOR INSERT WITH CHECK "
            f"({actor_column} = current_setting('app.user_id', true) AND EXISTS ("
            "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
            f"AND u.user_id = {name}.{actor_column} AND u.role = 'reviewer' AND u.active))"  # noqa: S608
        )


def _append_only(name: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
        )
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {name}_{action.lower()} BEFORE {action} ON {name} "
                "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
            )


def upgrade() -> None:
    op.create_table(
        "review_engine_run",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("review_task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("publication_id", sa.String(36)),
        sa.Column("revision_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "review_task_id", "run_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_task_id"],
            ["review_task.tenant_id", "review_task.review_task_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting_human','result_published','failed','cancelled')"
        ),
        sa.CheckConstraint("length(snapshot_hash) = 64"),
        sa.CheckConstraint("length(request_hash) = 64"),
        sa.CheckConstraint("retry_count BETWEEN 0 AND 2"),
    )
    op.create_table(
        "review_artifact",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.String(64), nullable=False),
        sa.Column("review_task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "artifact_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        sa.CheckConstraint("length(content_hash) = 64"),
        sa.CheckConstraint("length(CAST(content AS TEXT)) <= 20000000"),
    )
    op.create_table(
        "review_decision",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("review_task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("modified_finding", sa.JSON()),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "decision_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "reviewer_id", "request_id"),
        sa.UniqueConstraint("tenant_id", "review_task_id", "run_id", "finding_id"),
        sa.CheckConstraint("decision IN ('accept','modify','reject','confirm_no_findings')"),
        sa.CheckConstraint("length(snapshot_hash) = 64"),
    )
    op.create_table(
        "review_result",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("review_task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "result_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.UniqueConstraint("tenant_id", "review_task_id", "run_id", "snapshot_hash"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
        sa.CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
    )
    if op.get_bind().dialect.name == "postgresql":
        _tenant_table("review_engine_run", "actor_id")
        _tenant_table("review_artifact")
        _tenant_table("review_decision", "reviewer_id")
        _tenant_table("review_result", "reviewer_id")
    for table in ("review_artifact", "review_decision", "review_result"):
        _append_only(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
CREATE FUNCTION review_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.review_task_id <> OLD.review_task_id
    OR NEW.run_id <> OLD.run_id OR NEW.project_id <> OLD.project_id
    OR NEW.actor_id <> OLD.actor_id
    OR to_jsonb(NEW.snapshot) IS DISTINCT FROM to_jsonb(OLD.snapshot)
    OR NEW.snapshot_hash <> OLD.snapshot_hash OR NEW.request_hash <> OLD.request_hash
    OR NEW.publication_id IS DISTINCT FROM OLD.publication_id
    OR NEW.revision_id IS DISTINCT FROM OLD.revision_id OR NEW.created_at <> OLD.created_at THEN
  RAISE EXCEPTION 'review input snapshot is immutable';
 END IF;
 RETURN NEW;
END $$
""")
        op.execute(
            "CREATE TRIGGER review_run_guard BEFORE UPDATE ON review_engine_run "
            "FOR EACH ROW EXECUTE FUNCTION review_run_guard()"
        )
    else:
        op.execute("""
CREATE TRIGGER review_run_guard BEFORE UPDATE ON review_engine_run
WHEN NEW.tenant_id IS NOT OLD.tenant_id
 OR NEW.review_task_id IS NOT OLD.review_task_id
 OR NEW.run_id IS NOT OLD.run_id
 OR NEW.project_id IS NOT OLD.project_id
 OR NEW.actor_id IS NOT OLD.actor_id
 OR NEW.snapshot IS NOT OLD.snapshot
 OR NEW.snapshot_hash IS NOT OLD.snapshot_hash
 OR NEW.request_hash IS NOT OLD.request_hash
 OR NEW.publication_id IS NOT OLD.publication_id
 OR NEW.revision_id IS NOT OLD.revision_id
 OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'review input snapshot is immutable'); END
""")

    # The runtime role cannot execute the upstream checkpointer's DDL setup. These tables
    # match langgraph-checkpoint-postgres 3.1.x migrations and are stamped at version 9.
    op.create_table("checkpoint_migrations", sa.Column("v", sa.Integer(), primary_key=True))
    op.bulk_insert(sa.table("checkpoint_migrations", sa.column("v", sa.Integer())), [{"v": 9}])
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("checkpoint", _json_type(), nullable=False),
        sa.Column("metadata", _json_type(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary()),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )
    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text()),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    )
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.create_index(f"{table}_thread_id_idx", table, ["thread_id"])
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_checkpoint_scope ON {table} USING "
                "(thread_id LIKE current_setting('app.tenant_id', true) || ':%') WITH CHECK "
                "(thread_id LIKE current_setting('app.tenant_id', true) || ':%')"
            )


def downgrade() -> None:
    for table in (
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
        "checkpoint_migrations",
        "review_result",
        "review_decision",
        "review_artifact",
        "review_engine_run",
    ):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION review_run_guard()")
