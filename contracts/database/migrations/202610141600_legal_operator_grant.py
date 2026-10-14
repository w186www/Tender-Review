"""TASK-0006 D05: global legal permissions are provisioned only by database operations."""

import sqlalchemy as sa
from alembic import op

revision = "202610141600"
down_revision = "202610141200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_operator_grant",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE legal_operator_grant ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE legal_operator_grant FORCE ROW LEVEL SECURITY")
        # No runtime write policy: tenant admin must never grant global permissions to itself.
        op.execute(
            "CREATE POLICY read_own_legal_grant ON legal_operator_grant FOR SELECT USING "
            "(tenant_id = current_setting('app.tenant_id', true) AND "
            "user_id = current_setting('app.user_id', true))"
        )


def downgrade() -> None:
    # Provisioning records are lost: back up before explicit downgrade.
    op.drop_table("legal_operator_grant")
