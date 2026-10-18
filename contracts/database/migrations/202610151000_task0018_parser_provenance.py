"""TASK-0018 additive parser provenance; existing document/history rows stay untouched."""

from alembic import op
import sqlalchemy as sa

revision = "202610151000"
down_revision = "202610142000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document", sa.Column("parse_provenance", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("document", "parse_provenance")
