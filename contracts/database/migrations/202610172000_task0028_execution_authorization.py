"""TASK-0028 U05 tenant execution policy, per-file authorization and durable budget.

Additive migration after the durable review queue. It creates the product-mode
authorization/budget authority in PostgreSQL, with tenant RLS and append-only guards.
No existing table, row, ledger file or registry is rewritten.
"""

from alembic import op
import sqlalchemy as sa


revision = "202610172000"
down_revision = "202610171000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_execution_policy",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("allowed_providers", sa.JSON(), nullable=False),
        sa.Column("allowed_purposes", sa.JSON(), nullable=False),
        sa.Column("budget_cny", sa.Numeric(18, 8), nullable=False),
        sa.Column("max_call_cny", sa.Numeric(18, 8), nullable=False),
        sa.Column("max_embedding_batch_cny", sa.Numeric(18, 8), nullable=False),
        sa.Column("max_authorization_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.CheckConstraint("policy_version >= 1", name="ck_model_execution_policy_version"),
        sa.CheckConstraint("budget_cny >= 0", name="ck_model_execution_policy_budget"),
        sa.CheckConstraint("max_call_cny > 0", name="ck_model_execution_policy_call"),
        sa.CheckConstraint(
            "max_embedding_batch_cny > 0", name="ck_model_execution_policy_embedding"
        ),
        sa.CheckConstraint(
            "max_authorization_ttl_seconds BETWEEN 60 AND 2592000",
            name="ck_model_execution_policy_ttl",
        ),
    )
    op.create_table(
        "document_external_authorization",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("authorization_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("parse_version", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by", sa.String(length=64)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(length=500)),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="api"),
        sa.Column("source_record_id", sa.String(length=128)),
        sa.PrimaryKeyConstraint("tenant_id", "authorization_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_id"],
            ["document.tenant_id", "document.project_id", "document.document_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revoked_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        sa.CheckConstraint(
            "state IN ('active','revoked')",
            name="ck_document_external_authorization_state",
        ),
        sa.CheckConstraint(
            "length(document_sha256) = 64 AND parse_version >= 1",
            name="ck_document_external_authorization_identity",
        ),
        sa.CheckConstraint(
            "expires_at > approved_at",
            name="ck_document_external_authorization_expiry",
        ),
        sa.CheckConstraint(
            "(state = 'active' AND revoked_by IS NULL AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) OR (state = 'revoked' "
            "AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_document_external_authorization_revocation",
        ),
    )
    op.create_index(
        "document_external_authorization_active_idx",
        "document_external_authorization",
        ["tenant_id", "document_id", "document_sha256", "parse_version", "purpose", "provider"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "model_budget_account",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("authorization_id", sa.String(length=64), nullable=False),
        sa.Column("limit_cny", sa.Numeric(18, 8), nullable=False),
        sa.Column("reserved_cny", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("spent_cny", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "authorization_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.CheckConstraint(
            "limit_cny >= 0 AND reserved_cny >= 0 AND spent_cny >= 0 "
            "AND reserved_cny + spent_cny <= limit_cny",
            name="ck_model_budget_account_balance",
        ),
    )
    op.create_table(
        "model_budget_reservation",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("reservation_id", sa.String(length=64), nullable=False),
        sa.Column("authorization_id", sa.String(length=64), nullable=False),
        sa.Column("review_task_id", sa.String(length=64)),
        sa.Column("review_run_id", sa.String(length=36)),
        sa.Column("call_id", sa.String(length=128)),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("ceiling_cny", sa.Numeric(18, 8), nullable=False),
        sa.Column("charge_cny", sa.Numeric(18, 8)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="product"),
        sa.Column("source_ref", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "reservation_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "authorization_id"],
            ["model_budget_account.tenant_id", "model_budget_account.authorization_id"],
        ),
        sa.CheckConstraint("kind IN ('llm','embedding')", name="ck_model_budget_reservation_kind"),
        sa.CheckConstraint(
            "status IN ('reserved','dispatched','settled','unknown','released')",
            name="ck_model_budget_reservation_status",
        ),
        sa.CheckConstraint(
            "ceiling_cny > 0 AND (charge_cny IS NULL OR "
            "(charge_cny >= 0 AND charge_cny <= ceiling_cny))",
            name="ck_model_budget_reservation_charge",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="ck_model_budget_reservation_request"
        ),
        sa.CheckConstraint(
            "(kind = 'llm' AND (review_task_id IS NOT NULL OR source = 'ledger_import')) "
            "OR kind = 'embedding'",
            name="ck_model_budget_reservation_task",
        ),
    )
    op.create_index(
        "model_budget_reservation_call_idx",
        "model_budget_reservation",
        ["tenant_id", "call_id"],
        unique=True,
        postgresql_where=sa.text("call_id IS NOT NULL"),
        sqlite_where=sa.text("call_id IS NOT NULL"),
    )
    op.create_index(
        "model_budget_reservation_status_idx",
        "model_budget_reservation",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_table(
        "ledger_import",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("import_id", sa.String(length=64), nullable=False),
        sa.Column("authorization_id", sa.String(length=64), nullable=False),
        sa.Column("source_ledger_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_registry_sha256", sa.String(length=64)),
        sa.Column("source_counts", sa.JSON(), nullable=False),
        sa.Column("source_sums", sa.JSON(), nullable=False),
        sa.Column("imported_counts", sa.JSON(), nullable=False),
        sa.Column("imported_sums", sa.JSON(), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_by", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "import_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "authorization_id"],
            ["model_budget_account.tenant_id", "model_budget_account.authorization_id"],
        ),
        sa.CheckConstraint(
            "length(source_ledger_sha256) = 64",
            name="ck_ledger_import_ledger_digest",
        ),
        sa.CheckConstraint(
            "source_registry_sha256 IS NULL OR length(source_registry_sha256) = 64",
            name="ck_ledger_import_registry_digest",
        ),
    )
    op.create_index(
        "ledger_import_source_idx",
        "ledger_import",
        ["tenant_id", "authorization_id", "source_ledger_sha256", "source_registry_sha256"],
        unique=True,
    )

    if op.get_bind().dialect.name == "postgresql":
        _postgres_security()
    elif op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()


def _postgres_security() -> None:
    op.execute("ALTER TABLE model_execution_policy ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_execution_policy FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON model_execution_policy USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute("ALTER TABLE document_external_authorization ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_external_authorization FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON document_external_authorization USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "CREATE POLICY actor_insert ON document_external_authorization AS RESTRICTIVE "
        "FOR INSERT WITH CHECK (approved_by = current_setting('app.user_id', true) AND EXISTS ("
        "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
        "AND u.user_id = document_external_authorization.approved_by "
        "AND u.role = 'reviewer' AND u.active))"
    )
    op.execute(
        "CREATE POLICY actor_update ON document_external_authorization AS RESTRICTIVE "
        "FOR UPDATE USING (current_setting('app.user_id', true) IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
        "AND u.user_id = current_setting('app.user_id', true) "
        "AND u.role = 'reviewer' AND u.active)) WITH CHECK ("
        "revoked_by = current_setting('app.user_id', true) AND EXISTS ("
        "SELECT 1 FROM app_user u WHERE u.tenant_id = current_setting('app.tenant_id', true) "
        "AND u.user_id = document_external_authorization.revoked_by "
        "AND u.role = 'reviewer' AND u.active))"
    )
    op.execute("ALTER TABLE model_budget_account ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_budget_account FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON model_budget_account USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute("ALTER TABLE model_budget_reservation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_budget_reservation FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON model_budget_reservation USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute("ALTER TABLE ledger_import ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ledger_import FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON ledger_import USING "
        "(tenant_id = current_setting('app.tenant_id', true)) WITH CHECK "
        "(tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute("""
CREATE FUNCTION document_external_authorization_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'external authorization records are append-only';
 END IF;
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.authorization_id <> OLD.authorization_id
    OR NEW.project_id <> OLD.project_id OR NEW.document_id <> OLD.document_id
    OR NEW.document_sha256 <> OLD.document_sha256 OR NEW.parse_version <> OLD.parse_version
    OR NEW.purpose <> OLD.purpose OR NEW.provider <> OLD.provider
    OR NEW.policy_version <> OLD.policy_version OR NEW.reason <> OLD.reason
    OR NEW.approved_by <> OLD.approved_by OR NEW.approved_at <> OLD.approved_at
    OR NEW.expires_at <> OLD.expires_at OR NEW.source <> OLD.source
    OR NEW.source_record_id IS DISTINCT FROM OLD.source_record_id THEN
  RAISE EXCEPTION 'external authorization identity is immutable';
 END IF;
 IF OLD.state <> 'active' OR NEW.state <> 'revoked' THEN
  RAISE EXCEPTION 'invalid external authorization state transition';
 END IF;
 RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER document_external_authorization_guard "
        "BEFORE UPDATE OR DELETE ON document_external_authorization "
        "FOR EACH ROW EXECUTE FUNCTION document_external_authorization_guard()"
    )
    op.execute("""
CREATE FUNCTION model_budget_reservation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'budget reservations are append-only';
 END IF;
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.reservation_id <> OLD.reservation_id
    OR NEW.authorization_id <> OLD.authorization_id
    OR NEW.review_task_id IS DISTINCT FROM OLD.review_task_id
    OR NEW.review_run_id IS DISTINCT FROM OLD.review_run_id
    OR NEW.call_id IS DISTINCT FROM OLD.call_id OR NEW.kind <> OLD.kind
    OR NEW.request_hash <> OLD.request_hash OR NEW.ceiling_cny <> OLD.ceiling_cny
    OR NEW.source <> OLD.source OR NEW.source_ref IS DISTINCT FROM OLD.source_ref
    OR NEW.created_at <> OLD.created_at THEN
  RAISE EXCEPTION 'budget reservation identity is immutable';
 END IF;
 IF NEW.status <> OLD.status AND OLD.status = 'reserved' AND NEW.status NOT IN ('dispatched','settled','unknown','released') THEN
  RAISE EXCEPTION 'invalid budget reservation state transition';
 END IF;
 IF NEW.status <> OLD.status AND OLD.status = 'dispatched' AND NEW.status NOT IN ('settled','unknown') THEN
  RAISE EXCEPTION 'invalid budget reservation state transition';
 END IF;
 IF NEW.status <> OLD.status AND OLD.status IN ('settled','unknown','released') THEN
  RAISE EXCEPTION 'budget reservation is already final';
 END IF;
 IF NEW.status IN ('settled','unknown') AND NEW.charge_cny IS NULL THEN
  RAISE EXCEPTION 'final budget reservation requires a charge';
 END IF;
 IF NEW.status = 'released' AND NEW.charge_cny IS DISTINCT FROM 0 THEN
  RAISE EXCEPTION 'released budget reservation must carry a zero charge';
 END IF;
 IF NEW.status IN ('reserved','dispatched') AND NEW.charge_cny IS NOT NULL THEN
  RAISE EXCEPTION 'unsettled budget reservation cannot carry a charge';
 END IF;
 RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER model_budget_reservation_guard "
        "BEFORE UPDATE OR DELETE ON model_budget_reservation "
        "FOR EACH ROW EXECUTE FUNCTION model_budget_reservation_guard()"
    )
    op.execute("""
CREATE FUNCTION model_budget_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'budget accounts are append-only';
 END IF;
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.authorization_id <> OLD.authorization_id THEN
  RAISE EXCEPTION 'budget account identity is immutable';
 END IF;
 RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER model_budget_account_guard BEFORE UPDATE OR DELETE "
        "ON model_budget_account FOR EACH ROW EXECUTE FUNCTION model_budget_account_guard()"
    )
    op.execute("""
CREATE FUNCTION ledger_import_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'ledger import records are append-only';
END $$
""")
    op.execute(
        "CREATE TRIGGER ledger_import_guard BEFORE UPDATE OR DELETE ON ledger_import "
        "FOR EACH ROW EXECUTE FUNCTION ledger_import_guard()"
    )


def _sqlite_guards() -> None:
    op.execute("""
CREATE TRIGGER document_external_authorization_update_guard
BEFORE UPDATE ON document_external_authorization
WHEN NEW.tenant_id IS NOT OLD.tenant_id OR NEW.authorization_id IS NOT OLD.authorization_id
 OR NEW.project_id IS NOT OLD.project_id OR NEW.document_id IS NOT OLD.document_id
 OR NEW.document_sha256 IS NOT OLD.document_sha256 OR NEW.parse_version IS NOT OLD.parse_version
 OR NEW.purpose IS NOT OLD.purpose OR NEW.provider IS NOT OLD.provider
 OR NEW.policy_version IS NOT OLD.policy_version OR NEW.reason IS NOT OLD.reason
 OR NEW.approved_by IS NOT OLD.approved_by OR NEW.approved_at IS NOT OLD.approved_at
 OR NEW.expires_at IS NOT OLD.expires_at OR NEW.source IS NOT OLD.source
 OR NEW.source_record_id IS NOT OLD.source_record_id
 OR OLD.state <> 'active' OR NEW.state <> 'revoked'
BEGIN SELECT RAISE(ABORT, 'invalid external authorization update'); END
""")
    op.execute("""
CREATE TRIGGER document_external_authorization_delete_guard
BEFORE DELETE ON document_external_authorization
BEGIN SELECT RAISE(ABORT, 'external authorization records are append-only'); END
""")
    op.execute("""
CREATE TRIGGER model_budget_reservation_update_guard
BEFORE UPDATE ON model_budget_reservation
WHEN NEW.tenant_id IS NOT OLD.tenant_id OR NEW.reservation_id IS NOT OLD.reservation_id
 OR NEW.authorization_id IS NOT OLD.authorization_id
 OR NEW.review_task_id IS NOT OLD.review_task_id
 OR NEW.review_run_id IS NOT OLD.review_run_id OR NEW.call_id IS NOT OLD.call_id
 OR NEW.kind IS NOT OLD.kind OR NEW.request_hash IS NOT OLD.request_hash
 OR NEW.ceiling_cny IS NOT OLD.ceiling_cny OR NEW.source IS NOT OLD.source
 OR NEW.source_ref IS NOT OLD.source_ref OR NEW.created_at IS NOT OLD.created_at
 OR (NEW.status <> OLD.status AND OLD.status = 'reserved' AND NEW.status NOT IN ('dispatched','settled','unknown','released'))
 OR (NEW.status <> OLD.status AND OLD.status = 'dispatched' AND NEW.status NOT IN ('settled','unknown'))
 OR (NEW.status <> OLD.status AND OLD.status IN ('settled','unknown','released'))
 OR (NEW.status IN ('settled','unknown') AND NEW.charge_cny IS NULL)
 OR (NEW.status = 'released' AND NEW.charge_cny IS NOT 0)
 OR (NEW.status IN ('reserved','dispatched') AND NEW.charge_cny IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'invalid budget reservation update'); END
""")
    op.execute("""
CREATE TRIGGER model_budget_reservation_delete_guard
BEFORE DELETE ON model_budget_reservation
BEGIN SELECT RAISE(ABORT, 'budget reservations are append-only'); END
""")
    op.execute("""
CREATE TRIGGER model_budget_account_delete_guard
BEFORE DELETE ON model_budget_account
BEGIN SELECT RAISE(ABORT, 'budget accounts are append-only'); END
""")
    op.execute("""
CREATE TRIGGER ledger_import_update_guard
BEFORE UPDATE ON ledger_import
BEGIN SELECT RAISE(ABORT, 'ledger import records are append-only'); END
""")
    op.execute("""
CREATE TRIGGER ledger_import_delete_guard
BEFORE DELETE ON ledger_import
BEGIN SELECT RAISE(ABORT, 'ledger import records are append-only'); END
""")


def downgrade() -> None:
    op.drop_table("ledger_import")
    op.drop_table("model_budget_reservation")
    op.drop_table("model_budget_account")
    op.drop_index(
        "document_external_authorization_active_idx",
        table_name="document_external_authorization",
    )
    op.drop_table("document_external_authorization")
    op.drop_table("model_execution_policy")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION ledger_import_guard()")
        op.execute("DROP FUNCTION model_budget_account_guard()")
        op.execute("DROP FUNCTION model_budget_reservation_guard()")
        op.execute("DROP FUNCTION document_external_authorization_guard()")
