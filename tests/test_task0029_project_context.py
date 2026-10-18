from bidding_compliance.services.project_context import (
    document_context_mismatch_fields,
    project_context_issues,
)


def valid_context(**changes):
    return {
        "name": "学校维修工程",
        "procurement_type": "government",
        "project_type": "works",
        "region": "安徽省滁州市",
        "procurement_method": "tender",
        "buyer_type": "government_entity",
        "subject_type": "works",
        "legal_frameworks": ["tendering", "government_procurement"],
        **changes,
    }


def test_task0029_review_context_accepts_mapped_tender_project():
    assert project_context_issues(valid_context()) == []


def test_task0029_review_context_identifies_unknown_fields_before_execution():
    issues = project_context_issues(
        valid_context(
            procurement_method="unknown",
            buyer_type="unknown",
            subject_type="unknown",
        )
    )
    assert {item["field"] for item in issues} == {
        "procurement_method",
        "buyer_type",
        "subject_type",
    }


def test_task0029_review_context_rejects_unmapped_region():
    issues = project_context_issues(valid_context(region="滁州市某新区"))
    assert issues[0]["field"] == "region"
    assert issues[0]["code"] == "unmapped"


def test_task0029_review_context_rejects_framework_conflict():
    issues = project_context_issues(valid_context(legal_frameworks=["government_procurement"]))
    assert any(
        item["field"] == "legal_frameworks" and item["code"] == "framework_mismatch"
        for item in issues
    )


def test_task0029_document_context_is_only_a_mirror_of_project_context():
    project = valid_context()
    assert document_context_mismatch_fields(project, project) == []
    assert document_context_mismatch_fields(project, {**project, "region": "北京"}) == ["region"]
