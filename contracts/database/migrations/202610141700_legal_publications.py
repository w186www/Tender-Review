"""TASK-0006 D02: immutable byte revisions/history and atomic independent draft/publication CAS."""

import sqlalchemy as sa
from alembic import op

revision = "202610141700"
down_revision = "202610141600"
branch_labels = None
depends_on = None


def actor_fk():
    return sa.ForeignKeyConstraint(
        ["actor_tenant", "actor_id"],
        ["app_user.tenant_id", "app_user.user_id"],
    )


def upgrade() -> None:
    op.create_table(
        "legal_law_identity",
        sa.Column("title_key", sa.String(500), nullable=False),
        sa.Column("law_id", sa.String(128), nullable=False),
        sa.Column("actor_tenant", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("title_key"),
        actor_fk(),
        sa.CheckConstraint("operation IN ('ingest','verify')"),
    )
    op.create_table(
        "legal_corpus_revision",
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("legal_corpus_revision.revision_id")),
        sa.Column("draft_sequence", sa.Integer(), nullable=False),
        sa.Column("actor_tenant", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("index_hash", sa.String(64), nullable=False),
        sa.Column("bundle", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("revision_id"),
        actor_fk(),
        sa.UniqueConstraint("draft_sequence"),
        sa.UniqueConstraint("actor_tenant", "actor_id", "request_id"),
        sa.CheckConstraint("draft_sequence >= 1"),
        sa.CheckConstraint("operation IN ('ingest','verify')"),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND length(index_hash) = 64 AND length(request_hash) = 64"
        ),
    )
    op.create_table(
        "legal_publication",
        sa.Column("publication_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.String(36), sa.ForeignKey("legal_publication.publication_id")),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("legal_publication.publication_id")),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("legal_corpus_revision.revision_id")),
        sa.Column("actor_tenant", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("publication_id"),
        actor_fk(),
        sa.UniqueConstraint("sequence"),
        sa.UniqueConstraint("actor_tenant", "actor_id", "request_id"),
        sa.CheckConstraint("sequence >= 1"),
        sa.CheckConstraint("operation IN ('publish','disable','rollback')"),
        sa.CheckConstraint("length(request_hash) = 64"),
        sa.CheckConstraint(
            "(operation = 'disable' AND revision_id IS NULL) OR "
            "(operation != 'disable' AND revision_id IS NOT NULL)"
        ),
        sa.CheckConstraint(
            "(operation = 'rollback' AND target_id IS NOT NULL) OR "
            "(operation != 'rollback' AND target_id IS NULL)"
        ),
    )
    op.create_table(
        "legal_corpus_state",
        sa.Column("singleton", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "publication_id", sa.String(36), sa.ForeignKey("legal_publication.publication_id")
        ),
        sa.Column("draft_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "draft_revision_id", sa.String(36), sa.ForeignKey("legal_corpus_revision.revision_id")
        ),
        sa.PrimaryKeyConstraint("singleton"),
        sa.CheckConstraint("singleton = 1 AND sequence >= 0 AND draft_sequence >= 0"),
    )
    state = sa.table(
        "legal_corpus_state",
        sa.column("singleton"),
        sa.column("sequence"),
        sa.column("publication_id"),
        sa.column("draft_sequence"),
        sa.column("draft_revision_id"),
    )
    op.bulk_insert(
        state,
        [
            dict(
                singleton=1,
                sequence=0,
                publication_id=None,
                draft_sequence=0,
                draft_revision_id=None,
            )
        ],
    )
    if op.get_bind().dialect.name == "postgresql":
        grant = (
            "EXISTS (SELECT 1 FROM legal_operator_grant g WHERE g.active AND "
            "g.tenant_id = current_setting('app.tenant_id', true) AND "
            "g.user_id = current_setting('app.user_id', true) AND "
        )
        for name in (
            "legal_law_identity",
            "legal_corpus_revision",
            "legal_publication",
            "legal_corpus_state",
        ):
            op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY public_legal_read ON {name} FOR SELECT USING (true)")
        for name in ("legal_law_identity", "legal_corpus_revision", "legal_publication"):
            op.execute(
                f"CREATE POLICY authorized_legal_insert ON {name} FOR INSERT WITH CHECK ("
                "actor_tenant = current_setting('app.tenant_id', true) AND "
                "actor_id = current_setting('app.user_id', true) AND "
                + grant
                + f"g.capabilities::jsonb ? {name}.operation))"
            )
            op.execute(
                f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION reject_history_change()"
            )
        predicate = grant + (
            "(g.capabilities::jsonb ? 'ingest' OR g.capabilities::jsonb ? 'verify' OR "
            "g.capabilities::jsonb ? 'publish' OR g.capabilities::jsonb ? 'disable' OR "
            "g.capabilities::jsonb ? 'rollback'))"
        )
        op.execute(
            "CREATE POLICY authorized_legal_state ON legal_corpus_state FOR UPDATE "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        op.execute("""
CREATE FUNCTION legal_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.sequence <> OLD.sequence OR NEW.publication_id IS DISTINCT FROM OLD.publication_id THEN
  IF NOT EXISTS (
   SELECT 1 FROM legal_publication p JOIN legal_operator_grant g
    ON g.tenant_id=p.actor_tenant AND g.user_id=p.actor_id
   WHERE p.publication_id=NEW.publication_id AND p.sequence=OLD.sequence+1
    AND p.previous_id IS NOT DISTINCT FROM OLD.publication_id AND g.active
    AND g.tenant_id=current_setting('app.tenant_id',true)
    AND g.user_id=current_setting('app.user_id',true) AND g.capabilities::jsonb ? p.operation
  ) THEN RAISE EXCEPTION 'invalid or unauthorized legal publication transition'; END IF;
 END IF;
 IF NEW.draft_sequence <> OLD.draft_sequence
    OR NEW.draft_revision_id IS DISTINCT FROM OLD.draft_revision_id THEN
  IF NOT EXISTS (
   SELECT 1 FROM legal_corpus_revision r JOIN legal_operator_grant g
    ON g.tenant_id=r.actor_tenant AND g.user_id=r.actor_id
   WHERE r.revision_id=NEW.draft_revision_id AND r.draft_sequence=OLD.draft_sequence+1
    AND r.parent_id IS NOT DISTINCT FROM OLD.draft_revision_id AND g.active
    AND g.tenant_id=current_setting('app.tenant_id',true)
    AND g.user_id=current_setting('app.user_id',true) AND g.capabilities::jsonb ? r.operation
  ) THEN RAISE EXCEPTION 'invalid or unauthorized legal draft transition'; END IF;
 END IF;
 RETURN NEW;
END $$
""")
        op.execute(
            "CREATE TRIGGER legal_state_guard BEFORE UPDATE ON legal_corpus_state "
            "FOR EACH ROW EXECUTE FUNCTION legal_state_guard()"
        )
        op.execute("""ALTER TABLE legal_corpus_revision ADD CONSTRAINT verified_requires_verifier
CHECK (operation = 'verify' OR NOT jsonb_path_exists(bundle::jsonb,
'$.index.manifest.versions[*] ? (@.verification == "verified")'))""")
    else:
        for name in ("legal_law_identity", "legal_corpus_revision", "legal_publication"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {name}_{action.lower()} BEFORE {action} ON {name} "
                    "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
                )
        op.execute("""CREATE TRIGGER legal_state_publication BEFORE UPDATE ON legal_corpus_state
WHEN (NEW.sequence != OLD.sequence OR NEW.publication_id IS NOT OLD.publication_id)
AND NOT EXISTS (SELECT 1 FROM legal_publication p WHERE p.publication_id=NEW.publication_id
AND p.sequence=OLD.sequence+1 AND p.previous_id IS OLD.publication_id)
BEGIN SELECT RAISE(ABORT, 'invalid legal publication transition'); END""")
        op.execute("""CREATE TRIGGER legal_state_draft BEFORE UPDATE ON legal_corpus_state
WHEN (NEW.draft_sequence != OLD.draft_sequence OR NEW.draft_revision_id IS NOT OLD.draft_revision_id)
AND NOT EXISTS (SELECT 1 FROM legal_corpus_revision r WHERE r.revision_id=NEW.draft_revision_id
AND r.draft_sequence=OLD.draft_sequence+1 AND r.parent_id IS OLD.draft_revision_id)
BEGIN SELECT RAISE(ABORT, 'invalid legal draft transition'); END""")
        op.execute("""CREATE TRIGGER verified_requires_verifier BEFORE INSERT ON legal_corpus_revision
WHEN NEW.operation='ingest' AND EXISTS (SELECT 1 FROM json_each(NEW.bundle,
'$.index.manifest.versions') v WHERE json_extract(v.value,'$.verification')='verified')
BEGIN SELECT RAISE(ABORT, 'verified revision requires verifier'); END""")


def downgrade() -> None:
    # Stop writes/back up global history; existing tenant retrieval runs are untouched.
    op.drop_table("legal_corpus_state")
    op.drop_table("legal_publication")
    op.drop_table("legal_corpus_revision")
    op.drop_table("legal_law_identity")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION legal_state_guard()")
