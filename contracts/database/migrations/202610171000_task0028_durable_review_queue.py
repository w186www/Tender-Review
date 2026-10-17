"""TASK-0028 additive durable review scheduling and worker lease metadata."""

from alembic import op
import sqlalchemy as sa

revision = "202610171000"
down_revision = "202610151000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_engine_run",
        sa.Column("action", sa.String(length=12), nullable=False, server_default="start"),
    )
    op.add_column(
        "review_engine_run",
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.execute("UPDATE review_engine_run SET scheduled_at = updated_at")
    op.add_column(
        "review_engine_run", sa.Column("lease_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "review_engine_run", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "review_engine_run",
        sa.Column("execution_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "review_engine_run",
            recreate="always",
            table_args=(
                sa.CheckConstraint(
                    "status IN ('queued','running','waiting_human','result_published','failed','cancelled')"
                ),
                sa.CheckConstraint("length(snapshot_hash) = 64"),
                sa.CheckConstraint("length(request_hash) = 64"),
                sa.CheckConstraint("retry_count BETWEEN 0 AND 2"),
            ),
        ) as batch:
            batch.create_check_constraint(
                "ck_review_engine_run_action", "action IN ('start','resume','retry')"
            )
            batch.create_check_constraint(
                "ck_review_engine_run_execution_generation", "execution_generation >= 0"
            )
    else:
        op.create_check_constraint(
            "ck_review_engine_run_action",
            "review_engine_run",
            "action IN ('start','resume','retry')",
        )
        op.create_check_constraint(
            "ck_review_engine_run_execution_generation",
            "review_engine_run",
            "execution_generation >= 0",
        )
    op.create_index(
        "review_engine_run_queue_idx",
        "review_engine_run",
        ["tenant_id", "status", "scheduled_at"],
    )
    op.create_table(
        "review_model_call",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("review_task_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("node_run_id", sa.String(length=200), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("document_hashes", sa.JSON(), nullable=False),
        sa.Column("usage_status", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("response_ref", sa.String(length=1000)),
        sa.Column("response_hash", sa.String(length=64)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("execution_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "call_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.CheckConstraint(
            "state IN ('prepared','reserved','dispatched','succeeded','failed','unknown')"
        ),
        sa.CheckConstraint("attempt >= 1 AND execution_generation >= 0"),
        sa.CheckConstraint("length(request_hash) = 64"),
        sa.CheckConstraint("response_hash IS NULL OR length(response_hash) = 64"),
        sa.CheckConstraint("usage_status IN ('not_applicable','reported','unknown')"),
    )
    op.create_index(
        "review_model_call_run_idx",
        "review_model_call",
        ["tenant_id", "review_task_id", "run_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE review_model_call ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE review_model_call FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_scope ON review_model_call USING "
            "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
            "(tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute(
            "CREATE POLICY actor_insert ON review_model_call AS RESTRICTIVE FOR INSERT "
            "WITH CHECK (actor_id = current_setting('app.user_id', true) AND EXISTS ("
            "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
            "AND u.user_id = review_model_call.actor_id AND u.role = 'reviewer' AND u.active))"
        )
        op.execute("""
CREATE FUNCTION review_model_call_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.call_id <> OLD.call_id
    OR NEW.review_task_id <> OLD.review_task_id OR NEW.run_id <> OLD.run_id
    OR NEW.actor_id <> OLD.actor_id OR NEW.node_run_id <> OLD.node_run_id
    OR NEW.attempt <> OLD.attempt OR NEW.request_hash <> OLD.request_hash
    OR NEW.document_hashes::jsonb IS DISTINCT FROM OLD.document_hashes::jsonb
    OR NEW.execution_generation <> OLD.execution_generation
    OR NEW.created_at <> OLD.created_at THEN
  RAISE EXCEPTION 'review model call identity is immutable';
 END IF;
 IF OLD.state <> 'dispatched' OR NEW.state NOT IN ('succeeded','failed','unknown') THEN
  RAISE EXCEPTION 'invalid review model call state transition';
 END IF;
 RETURN NEW;
END $$
""")
        op.execute(
            "CREATE TRIGGER review_model_call_guard BEFORE UPDATE ON review_model_call "
            "FOR EACH ROW EXECUTE FUNCTION review_model_call_guard()"
        )
    elif op.get_bind().dialect.name == "sqlite":
        op.execute("""
CREATE TRIGGER review_model_call_guard BEFORE UPDATE ON review_model_call
WHEN NEW.tenant_id IS NOT OLD.tenant_id OR NEW.call_id IS NOT OLD.call_id
 OR NEW.review_task_id IS NOT OLD.review_task_id OR NEW.run_id IS NOT OLD.run_id
 OR NEW.actor_id IS NOT OLD.actor_id OR NEW.node_run_id IS NOT OLD.node_run_id
 OR NEW.attempt IS NOT OLD.attempt OR NEW.request_hash IS NOT OLD.request_hash
 OR NEW.document_hashes IS NOT OLD.document_hashes
 OR NEW.execution_generation IS NOT OLD.execution_generation
 OR NEW.created_at IS NOT OLD.created_at
 OR OLD.state <> 'dispatched' OR NEW.state NOT IN ('succeeded','failed','unknown')
BEGIN SELECT RAISE(ABORT, 'invalid review model call update'); END
""")


def downgrade() -> None:
    op.drop_table("review_model_call")
    op.drop_index("review_engine_run_queue_idx", table_name="review_engine_run")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "review_engine_run",
            recreate="always",
            table_args=(
                sa.CheckConstraint(
                    "status IN ('queued','running','waiting_human','result_published','failed','cancelled')"
                ),
                sa.CheckConstraint("length(snapshot_hash) = 64"),
                sa.CheckConstraint("length(request_hash) = 64"),
                sa.CheckConstraint("retry_count BETWEEN 0 AND 2"),
            ),
        ) as batch:
            batch.drop_constraint("ck_review_engine_run_execution_generation", type_="check")
            batch.drop_constraint("ck_review_engine_run_action", type_="check")
            batch.drop_column("execution_generation")
            batch.drop_column("lease_until")
            batch.drop_column("lease_id")
            batch.drop_column("scheduled_at")
            batch.drop_column("action")
    else:
        op.drop_constraint(
            "ck_review_engine_run_execution_generation", "review_engine_run", type_="check"
        )
        op.drop_constraint("ck_review_engine_run_action", "review_engine_run", type_="check")
        op.drop_column("review_engine_run", "execution_generation")
        op.drop_column("review_engine_run", "lease_until")
        op.drop_column("review_engine_run", "lease_id")
        op.drop_column("review_engine_run", "scheduled_at")
        op.drop_column("review_engine_run", "action")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION review_model_call_guard()")
