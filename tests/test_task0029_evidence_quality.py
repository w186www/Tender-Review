from bidding_compliance.services.evidence_checker import (
    actionable_recommendation,
    claim_evidence_mismatch,
    has_unsupported_normative_claim,
)


def test_machine_code_claim_cannot_be_supported_by_contact_fields():
    assert claim_evidence_mismatch(
        "机器码/加密锁号雷同",
        ["联系人及联系电话相同"],
    ) == ("machine_identifier",)


def test_matching_machine_identifier_claim_passes_subject_type_check():
    assert (
        claim_evidence_mismatch(
            "机器码或加密锁号雷同",
            ["投标文件记载机器码与加密锁号相同"],
        )
        == ()
    )


def test_generic_manual_verification_recommendation_gets_an_editable_action():
    recommendation = actionable_recommendation("technical", "建议人工核验后处理")
    assert "品牌响应表" in recommendation
    assert "同等性能替代条款" in recommendation


def test_unreferenced_normative_window_claim_is_detected():
    assert has_unsupported_normative_claim("法规通常要求更短的投标窗口")
    assert not has_unsupported_normative_claim("当前没有已确认适用条文支持该判断")
