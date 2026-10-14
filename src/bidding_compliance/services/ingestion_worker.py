"""Explicit durable job execution; authenticated API requests never run this worker."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, or_, update
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.ingestion.ports import (
    DocumentParser,
    IngestionError,
    MalwareScanner,
    ObjectStore,
)
from bidding_compliance.ingestion.quality import digest, quality
from bidding_compliance.ingestion.schemas import (
    DocumentResponse,
    FileFormat,
    IngestionPolicy,
    Issue,
    SectionResponse,
)
from bidding_compliance.ingestion.storage import object_key
from bidding_compliance.persistence.database import require_runtime_role, set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentContextVersion,
    DocumentSection,
    IngestionJob,
    Tenant,
    User,
)
from bidding_compliance.services.documents import infer_context, response
from bidding_compliance.services.identity import audit


def current_actor(session: Session, tenant: str, user_id: str) -> Principal:
    user, organization = session.get(User, (tenant, user_id)), session.get(Tenant, tenant)
    if (
        user is None
        or not user.active
        or organization is None
        or not organization.active
        or user.role != Role.REVIEWER
    ):
        raise IngestionError("ACTOR_FORBIDDEN")
    return Principal(tenant, user.user_id, user.username, Role(user.role), "worker")


def execute(
    engine: Engine,
    tenant: str,
    document_id: str,
    parser: DocumentParser,
    scanner: MalwareScanner,
    store: ObjectStore,
    policy: IngestionPolicy,
) -> DocumentResponse:
    lease, now = str(uuid4()), datetime.now(UTC)
    with Session(engine, expire_on_commit=False) as session:
        require_runtime_role(session)
        set_tenant(session, tenant)
        document = session.get(Document, (tenant, document_id))
        job = session.get(IngestionJob, (tenant, document_id))
        if document is None or job is None:
            raise LookupError("job unavailable")
        if job.status == "succeeded":
            return response(document)
        if job.status == "failed" or job.attempts >= policy.max_attempts:
            raise FileExistsError("attempts exhausted or permanently rejected")
        changed = session.execute(
            update(IngestionJob)
            # Let the database evaluate the lease comparison. SQLite loads timestamps
            # without offsets; ORM Python evaluation would compare naive/aware values.
            .execution_options(synchronize_session="fetch")
            .where(
                IngestionJob.tenant_id == tenant,
                IngestionJob.document_id == document_id,
                IngestionJob.status.in_(["queued", "running"]),
                IngestionJob.attempts < policy.max_attempts,
                or_(IngestionJob.lease_until.is_(None), IngestionJob.lease_until < now),
            )
            .values(
                status="running",
                lease_id=lease,
                lease_until=now + timedelta(seconds=policy.job_lease_seconds),
                attempts=IngestionJob.attempts + 1,
            )
            .returning(IngestionJob.document_id)
        )
        if changed.scalar_one_or_none() is None:
            raise FileExistsError("job is already leased")
        document.status, document.issues = "parsing", []
        project, reference, source_hash, user_id, format = (
            document.project_id,
            document.object_ref,
            document.sha256,
            job.submitted_by,
            document.file_format,
        )
        audit(session, tenant, user_id, "document.processing", document_id)
        session.commit()
    error: Issue | None = None
    parsed = None
    try:
        with Session(engine) as session:
            set_tenant(session, tenant)
            current_actor(session, tenant, user_id)
        if reference != object_key(tenant, project, document_id):
            raise IngestionError("HASH_MISMATCH")
        payload = store.get(reference, policy.max_upload_bytes)
        if hashlib.sha256(payload).hexdigest() != source_hash:
            raise IngestionError("HASH_MISMATCH")
        scanner.scan(payload)
        # DB format is revalidated through the closed parser request implementation.
        from typing import cast

        parsed = parser.parse(payload, cast(FileFormat, format), policy)
        if (
            parsed.source_hash != source_hash
            or parsed.format != format
            or len(parsed.fragments) > policy.max_fragments
            or sum(len(f.text) for f in parsed.fragments) > policy.max_text_chars
            or any(f.text_sha256 != digest(f.text) for f in parsed.fragments)
        ):
            raise IngestionError("HASH_MISMATCH")
        if any(f.source == "manual" for f in parsed.fragments):
            raise IngestionError("PARSE_FAILED")
    except IngestionError as exc:
        error = exc.code
    except Exception as exc:
        from bidding_compliance.core.diagnostics import report_exception

        report_exception(exc, lease)
        error = "PARSE_FAILED"
    with Session(engine, expire_on_commit=False) as session:
        set_tenant(session, tenant)
        # Lock and compare lease: a delayed old worker cannot publish after takeover.
        job_query = session.query(IngestionJob).filter_by(tenant_id=tenant, document_id=document_id)
        record = job_query.with_for_update().one()
        if record.lease_id != lease or record.status != "running":
            raise FileExistsError("lease superseded")
        document = session.get(Document, (tenant, document_id))
        if document is None:
            raise LookupError("document unavailable")
        try:
            current_actor(session, tenant, user_id)
        except IngestionError as exc:
            error = exc.code
        if error is not None:
            retryable = error in {"SCANNER_UNAVAILABLE", "PARSE_TIMEOUT", "PARSE_FAILED"}
            record.status = (
                "queued" if retryable and record.attempts < policy.max_attempts else "failed"
            )
            document.status = "failed" if retryable else "rejected"
            document.issues = [error]
            audit(session, tenant, user_id, "document.processing_rejected", document_id)
        elif parsed is not None:
            # Recompute quality outside the parser; a claimed 'passed' cannot bypass this gate.
            passed = quality(parsed.fragments, policy)
            document.status = "needs_confirmation" if passed else "needs_review"
            document.issues = [] if passed else ["LOW_QUALITY"]
            document.parse_version, document.context_version = 1, 1
            document.parse_provenance = (
                parsed.ocr_runtime.model_dump(mode="json")
                if parsed.ocr_runtime is not None
                else None
            )
            items = []
            for ordinal, fragment in enumerate(parsed.fragments):
                identifier = str(uuid4())
                session.add(
                    DocumentSection(
                        tenant_id=tenant,
                        document_id=document_id,
                        section_id=identifier,
                        ordinal=ordinal,
                        automatic=fragment.model_dump(),
                        revision=1,
                    )
                )
                items.append(
                    SectionResponse(
                        section_id=identifier,
                        source_hash=source_hash,
                        automatic=fragment,
                        effective=fragment,
                        revision=1,
                    )
                )
            context = infer_context(document_id, items)
            session.add(
                DocumentContextVersion(
                    tenant_id=tenant,
                    document_id=document_id,
                    version=1,
                    payload=context.model_dump(),
                    changed_by=user_id,
                    changed_at=datetime.now(UTC),
                )
            )
            record.status = "succeeded"
            audit(session, tenant, user_id, "document.parsed", document_id)
        else:
            raise IngestionError("PARSE_FAILED")
        record.lease_id, record.lease_until = None, None
        session.commit()
        return response(document)
