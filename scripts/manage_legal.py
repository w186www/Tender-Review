"""Explicit authenticated corpus operations; no tenant role or model output grants permission."""

import argparse
import getpass
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.corpus import read_bounded
from bidding_compliance.legal.management_contracts import (
    PublicationRequest,
    RevisionRequest,
    VerificationSource,
)
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.identity import authenticate, login
from bidding_compliance.services.legal_management import create_revision, publish, read_state

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--request-id", default=None, help="reuse this ID when retrying the same request"
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("state")
    revision = sub.add_parser("revision")
    revision.add_argument("--manifest", default="config/legal/manifest.json")
    revision.add_argument("--proofs", default="config/legal/verification-sources.json")
    revision.add_argument("--expected-draft-sequence", type=int, required=True)
    revision.add_argument("--reason", required=True)
    for name in ("publish", "disable", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("--expected-sequence", type=int, required=True)
        command.add_argument("--reason", required=True)
        if name == "publish":
            command.add_argument("--revision-id", required=True)
            command.add_argument("--expected-draft-sequence", type=int, required=True)
        if name == "rollback":
            command.add_argument("--target-publication-id", required=True)
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings)
    try:
        with Session(engine) as session:
            # Existing credential only; no password/token in argv or output.
            token = login(
                session, settings, args.tenant, args.username, getpass.getpass("Password: ")
            )
            principal = authenticate(session, settings, token)
            if args.operation == "state":
                state = read_state(session, principal)
                print(
                    json.dumps(
                        dict(
                            sequence=state.sequence,
                            publication_id=state.publication_id,
                            draft_sequence=state.draft_sequence,
                            draft_revision_id=state.draft_revision_id,
                        )
                    )
                )
            elif args.operation == "revision":
                manifest = LegalManifest.model_validate_json(read_bounded(ROOT, args.manifest))
                proofs = tuple(
                    VerificationSource.model_validate(x)
                    for x in json.loads(read_bounded(ROOT, args.proofs))
                )
                row = create_revision(
                    session,
                    principal,
                    ROOT,
                    manifest,
                    RevisionRequest(
                        request_id=args.request_id or str(uuid4()),
                        expected_draft_sequence=args.expected_draft_sequence,
                        reason=args.reason,
                        verification_sources=proofs,
                    ),
                )
                print(
                    json.dumps(
                        dict(
                            revision_id=row.revision_id,
                            draft_sequence=row.draft_sequence,
                            content_hash=row.content_hash,
                            index_hash=row.index_hash,
                        )
                    )
                )
            else:
                row = publish(
                    session,
                    principal,
                    PublicationRequest(
                        request_id=args.request_id or str(uuid4()),
                        operation=args.operation,
                        expected_sequence=args.expected_sequence,
                        reason=args.reason,
                        revision_id=getattr(args, "revision_id", None),
                        expected_draft_sequence=getattr(args, "expected_draft_sequence", None),
                        target_publication_id=getattr(args, "target_publication_id", None),
                    ),
                )
                print(
                    json.dumps(
                        dict(
                            publication_id=row.publication_id,
                            sequence=row.sequence,
                            revision_id=row.revision_id,
                            operation=row.operation,
                        )
                    )
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
