"""TASK0006-001/002: time/scope, exact evidence, snapshots and authorization."""

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from extract_legal_snapshot import extract
from generate_legal_contracts import ROOT
from pydantic import ValidationError
from sqlalchemy.orm import Session
from verify_contracts import load_contracts, load_openapi, validator_for_contract

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.legal.contracts import (
    LegalIndex,
    LegalManifest,
    LegalVersion,
    RetrievalQuery,
    RetrievalResult,
)
from bidding_compliance.legal.corpus import digest, ingest, load_index, save_index, split_clauses
from bidding_compliance.legal.retrieval import CharacterEmbedding, LegalRetriever
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import AuthSession, Project, Tenant, User
from bidding_compliance.services.legal import retrieve_for_project


def version(root, **changes):
    text = "合成法规\n第一条 合成投标保证金不得超过限额。\n第二条 合成品牌限制。\n"
    path = root / "law.txt"
    path.write_text(text, encoding="utf-8", newline="\n")
    payload = dict(
        law_id="synthetic",
        title="合成法规",
        version="1",
        text_path="law.txt",
        text_hash=digest(path.read_bytes()),
        source_uri="https://example.gov.cn/law",
        source_snapshot_path="law.txt",
        source_hash=digest(path.read_bytes()),
        captured_on="2026-10-14",
        verification="verified",
        verified_through="2026-10-14",
        effective_from="2020-01-01",
        effective_to=None,
        end_status="confirmed_open",
        jurisdictions=["CN/福建"],
        procurement_types=["government"],
        project_types=["works"],
        authority="regulation",
        verification_note="仅测试用合成法规，非真实法律依据。",
        expected_articles=["第一条", "第二条"],
        applicability=dict(
            procurement_methods=["tender", "non_tender"],
            buyer_types=["government_entity", "enterprise", "other"],
            subject_types=["works", "goods", "services"],
            legal_frameworks=["tendering", "government_procurement"],
        ),
    )
    if changes.get("effective_to") and "end_status" not in changes:
        changes["end_status"] = "confirmed_end"
    return LegalVersion.model_validate_json(json.dumps({**payload, **changes}))


def query(**changes):
    payload = dict(
        text="投标保证金",
        review_date="2026-10-14",
        region="CN/福建/福州",
        procurement_type="government",
        project_type="works",
    )
    combined = {**payload, **changes}
    combined.setdefault("procurement_method", "tender")
    combined.setdefault(
        "buyer_type",
        {"government": "government_entity", "enterprise": "enterprise", "other": "other"}[
            combined["procurement_type"]
        ],
    )
    combined.setdefault("subject_type", combined["project_type"])
    return RetrievalQuery.model_validate_json(json.dumps(combined))


def search(root, metadata, request=None):
    index = ingest(root, LegalManifest(versions=(metadata,)))
    return LegalRetriever(index).search(request or query())


def test_exact_article_source_and_determinism(tmp_path):
    metadata = version(tmp_path)
    result = search(tmp_path, metadata)
    assert result == search(tmp_path, metadata)
    hit = result.hits[0]
    assert hit.article == "第一条"
    assert hit.eligible_for_confirmation and hit.reason == "valid"
    assert hit.source_uri == metadata.source_uri and hit.source_hash == metadata.source_hash
    start, end = map(int, hit.locator.split("=")[1].split(":"))
    text = (tmp_path / metadata.text_path).read_text(encoding="utf-8")
    assert text[start:end] == hit.quote
    assert digest(hit.quote.encode()) == hit.quote_hash
    docs, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator_for_contract(
        ROOT,
        "contracts/schemas/legal-result.schema.json",
        docs,
        registry,
        api,
    ).validate(result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "change",
    [
        {"region": "CN/广东"},
        {"procurement_type": "enterprise"},
        {"project_type": "goods"},
        {"review_date": "2019-12-31"},
    ],
)
def test_scope_filter_before_ranking(tmp_path, change):
    assert not search(tmp_path, version(tmp_path), query(**change)).hits


def test_end_date_exclusive_and_current_at_review_date(tmp_path):
    metadata = version(tmp_path, effective_to="2026-10-14")
    assert not search(tmp_path, metadata).hits
    result = search(tmp_path, metadata, query(review_date="2026-10-13"))
    assert result.hits[0].version_status == "verified_current"


@pytest.mark.parametrize(
    "changes,reason",
    [
        (
            {"verification": "unverified", "effective_from": None, "verified_through": None},
            "unverified",
        ),
        ({"verified_through": "2026-10-13"}, "outside_verification_horizon"),
    ],
)
def test_references_cannot_confirm(tmp_path, changes, reason):
    metadata = version(tmp_path, **changes)
    assert not search(tmp_path, metadata).hits
    result = search(tmp_path, metadata, query(include_references=True))
    assert result.hits and all(not h.eligible_for_confirmation for h in result.hits)
    assert all(h.version_status == "unverified" and h.reason == reason for h in result.hits)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_uri": "https://evil.example/law"},
        {"source_uri": "http://example.gov.cn/law"},
        {"source_uri": "https://name:secret@example.gov.cn/law"},
        {"verified_through": None},
        {"effective_from": None},
        {"effective_to": "2019-01-01"},
        {"authority": "reference"},
        {"jurisdictions": [""]},
    ],
)
def test_invalid_metadata_rejected(tmp_path, changes):
    with pytest.raises(ValidationError):
        version(tmp_path, **changes)


def test_duplicate_and_overlapping_versions_rejected(tmp_path):
    first = version(tmp_path)
    for second in (first, version(tmp_path, version="2", effective_from="2025-01-01")):
        with pytest.raises(ValidationError):
            LegalManifest(versions=(first, second))


def test_immutable_snapshot_tamper_and_source_tamper(tmp_path):
    index = ingest(tmp_path, LegalManifest(versions=(version(tmp_path),)))
    path = save_index(index, tmp_path / "indexes")
    assert save_index(index, path.parent) == path
    assert load_index(tmp_path, path, path.stem) == index
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["clauses"][0]["quote"] = "伪造原文"
    data = json.dumps(payload).encode()
    fake = tmp_path / "fake.json"
    fake.write_bytes(data)
    with pytest.raises(ValueError, match="reproduce"):
        load_index(tmp_path, fake, digest(data))
    with pytest.raises(ValueError, match="hash"):
        load_index(tmp_path, fake, path.stem)
    (tmp_path / "law.txt").write_text("改动", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_index(tmp_path, path, path.stem)


def test_path_escape_size_and_duplicate_articles(tmp_path):
    metadata = version(tmp_path)
    from bidding_compliance.legal.corpus import read_bounded

    with pytest.raises(ValueError, match="within"):
        read_bounded(tmp_path, "../outside.txt")
    with pytest.raises(ValueError, match="resource"):
        read_bounded(tmp_path, "law.txt", maximum=1)
    with pytest.raises(ValueError, match="duplicate"):
        split_clauses("第一条 甲\n第一条 乙", metadata)


def test_long_article_and_chapters_preserve_locators(tmp_path):
    metadata = version(tmp_path)
    text = "第一条 " + "甲" * 9000 + "\n第二章 新章\n第二条 乙\n"
    clauses = split_clauses(text, metadata)
    assert [c.article for c in clauses] == ["第一条", "第一条", "第二条"]
    assert all(text[c.start : c.end] == c.quote for c in clauses)
    assert all("第二章" not in c.quote for c in clauses)
    assert "".join(c.quote for c in clauses[:2]) == "第一条 " + "甲" * 9000


def test_unlocated_notice_is_reference(tmp_path):
    metadata = version(tmp_path)
    (tmp_path / "law.txt").write_text("通知：投标保证金事项。", encoding="utf-8")
    raw = (tmp_path / "law.txt").read_bytes()
    metadata = metadata.model_copy(
        update={
            "text_hash": digest(raw),
            "source_hash": digest(raw),
            "expected_articles": (),
        }
    )
    assert not search(tmp_path, metadata).hits
    hit = search(tmp_path, metadata, query(include_references=True)).hits[0]
    assert hit.reason == "unlocated" and not hit.eligible_for_confirmation


def test_real_corpus_official_extraction_and_verified_retrieval():
    manifest = LegalManifest.model_validate_json((ROOT / "config/legal/manifest.json").read_bytes())
    index = ingest(ROOT, manifest)
    assert len(manifest.versions) == 43
    current = next(v for v in manifest.versions if v.verification == "verified")
    assert (ROOT / current.text_path).read_text(encoding="utf-8") == extract(
        (ROOT / current.source_snapshot_path).read_bytes()
    )
    articles = [
        c for c in index.clauses if c.version == current.version and c.law_id == current.law_id
    ]
    assert len(articles) == 84
    result = LegalRetriever(index).search(query())
    assert result.hits[0].article == "第二十六条"
    assert all(h.eligible_for_confirmation for h in result.hits)
    assert all(h.version == current.version for h in result.hits)
    assert not LegalRetriever(index).search(query(review_date="2026-10-15")).hits


def test_generated_legal_contracts_are_current():
    for name, model in (
        ("legal-manifest", LegalManifest),
        ("legal-index", LegalIndex),
        ("legal-query", RetrievalQuery),
        ("legal-result", RetrievalResult),
    ):
        schema = json.loads((ROOT / f"contracts/schemas/{name}.schema.json").read_text())
        schema.pop("$id")
        schema.pop("$schema")
        assert schema == model.model_json_schema()


def test_project_authorization_precedes_embedding_and_uses_database_scope(tmp_path):
    engine = make_engine(
        Settings(
            _env_file=None,
            app_env="test",
            database_url="sqlite:///" + str(tmp_path / "db.sqlite"),
        )
    )
    migrate(engine)
    index = ingest(tmp_path, LegalManifest(versions=(version(tmp_path),)))

    class Counting(CharacterEmbedding):
        calls = 0

        def encode(self, texts):
            self.calls += 1
            return super().encode(texts)

    adapter = Counting()
    retriever = LegalRetriever(index, adapter)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all([Tenant(tenant_id=t, name=t, active=True) for t in ("a", "b")])
        db.flush()
        db.add_all(
            [
                User(
                    tenant_id=t,
                    user_id="u",
                    username="u",
                    role="reviewer",
                    password_hash=str(uuid4()),
                    active=True,
                )
                for t in ("a", "b")
            ]
        )
        db.flush()
        db.add(
            AuthSession(
                tenant_id="a",
                user_id="u",
                session_id="s",
                expires_at=now + timedelta(hours=1),
                revoked=False,
            )
        )
        for tenant, region in (("a", "CN/福建/福州"), ("b", "CN/广东")):
            db.add(
                Project(
                    tenant_id=tenant,
                    project_id="p",
                    version=1,
                    created_by="u",
                    created_at=now,
                    context=dict(
                        region=region,
                        procurement_type="government",
                        project_type="works",
                        procurement_method="tender",
                        buyer_type="government_entity",
                        subject_type="works",
                    ),
                )
            )
        db.add(
            Project(
                tenant_id="b",
                project_id="foreign",
                version=1,
                created_by="u",
                created_at=now,
                context=dict(
                    region="CN/福建/福州",
                    procurement_type="government",
                    project_type="works",
                    procurement_method="tender",
                    buyer_type="government_entity",
                    subject_type="works",
                ),
            )
        )
        db.commit()
        principal = Principal("a", "u", "u", Role.REVIEWER, "s")
        result = retrieve_for_project(
            db, principal, "p", retriever, text="投标保证金", review_date=date(2026, 10, 14)
        )
        assert result.hits and result.query.region == "CN/福建/福州"
        assert adapter.calls == 1
        with pytest.raises(LookupError):
            retrieve_for_project(
                db,
                principal,
                "foreign",
                retriever,
                text="投标保证金",
                review_date=date(2026, 10, 14),
            )
        auth = db.get(AuthSession, ("a", "s"))
        auth.revoked = True
        db.commit()
        with pytest.raises(PermissionError):
            retrieve_for_project(
                db, principal, "p", retriever, text="投标保证金", review_date=date(2026, 10, 14)
            )
        assert adapter.calls == 1
    engine.dispose()


def test_retrieval_exclusion_diagnostics_are_bounded_for_large_corpora():
    from bidding_compliance.legal.retrieval import MAX_EXCLUDED_ITEMS

    manifest = LegalManifest.model_validate_json(
        (ROOT / "config/legal/manifest.json").read_bytes()
    )
    index = ingest(ROOT, manifest)
    result = LegalRetriever(index).search(
        query(
            region="CN/天津",
            procurement_type="enterprise",
            project_type="services",
            procurement_method="non_tender",
            buyer_type="enterprise",
            subject_type="services",
            review_date="2026-10-17",
        )
    )
    assert len(result.excluded) <= MAX_EXCLUDED_ITEMS
