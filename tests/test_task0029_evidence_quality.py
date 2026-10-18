from bidding_compliance.services.evidence_checker import (
    actionable_recommendation,
    claim_evidence_mismatch,
    has_unsupported_normative_claim,
    model_source_quotes_are_verified,
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


def test_generic_qualification_description_does_not_mismatch_machine_code_evidence():
    assert claim_evidence_mismatch(
        "机器码雷同认定标准缺失；应复核资格审查不合格情形",
        ["投标文件制作机器码、文件创建标识码及造价软件加密锁号信息雷同的"],
    ) == ()


def test_scoring_claim_anchors_match_equations_and_jk_values():
    assert claim_evidence_mismatch(
        "J值触发后商务标不得分",
        ["其中J=9%，则商务标不得分。"],
    ) == ()
    assert claim_evidence_mismatch(
        "K值抽取后计算评标基准价",
        ["招标人在线抽取K值，评标委员会据此计算F值。"],
    ) == ()


def test_model_source_quote_must_match_a_revalidated_primary_or_related_excerpt():
    primary = "a" * 64
    related = "b" * 64
    unverified = "c" * 64
    verified_quotes = {primary, related}

    assert model_source_quotes_are_verified([primary], verified_quotes)
    assert model_source_quotes_are_verified([related], verified_quotes)
    assert not model_source_quotes_are_verified([unverified], verified_quotes)
    assert not model_source_quotes_are_verified([], verified_quotes)


def test_generic_manual_verification_recommendation_gets_an_editable_action():
    recommendation = actionable_recommendation("technical", "建议人工核验后处理")
    assert "品牌响应表" in recommendation
    assert "同等性能替代条款" in recommendation


def test_unreferenced_normative_window_claim_is_detected():
    assert has_unsupported_normative_claim("法规通常要求更短的投标窗口")
    assert not has_unsupported_normative_claim("当前没有已确认适用条文支持该判断")
