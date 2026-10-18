"""TASK-0019 offline capability evaluation checks for synthetic fixtures."""

from scripts.evaluate_review_capabilities import evaluate


def test_task0019_all_five_synthetic_patterns_are_discovered_without_gold_claims():
    result = evaluate()

    assert result["external_model_calls"] == 0
    assert result["dataset"]["case_count"] == 5
    assert result["dataset"]["candidate_unconfirmed"] == 5
    assert result["dataset"]["expert_confirmed_risks"] == 0
    assert result["dataset"]["expert_confirmed_nonrisks"] == 0
    assert result["metrics"]["fixture_expected_pattern_capture"]["numerator"] == 5
    assert result["metrics"]["fixture_expected_pattern_capture"]["denominator"] == 5
    assert result["metrics"]["risk_precision"] is None
    assert result["metrics"]["risk_recall"] is None
    assert all(case["label_status"] == "candidate_unconfirmed" for case in result["cases"])
    assert all(case["candidate_quote_hashes_match_fixture"] for case in result["cases"])
    assert all(case["source_file_parse_measured"] is False for case in result["cases"])


def test_task0019_evaluation_is_repeatable_for_the_same_fixture_and_ruleset():
    first = evaluate()
    second = evaluate()

    assert first["candidate_source_identity"] == second["candidate_source_identity"]
    assert first["dataset"] == second["dataset"]
    assert first["metrics"] == second["metrics"]
    assert first["cases"] == second["cases"]
