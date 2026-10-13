"""Guard the reviewed scanner and model policy boundaries instead of weakening checks."""

import shutil
import subprocess
from dataclasses import asdict

import pytest
from verify_contracts import ROOT, check_secrets, load_contracts, validator_for_contract

from bidding_compliance.model_gateway import DataPolicy, ModelPolicy


@pytest.mark.parametrize(
    "name,quoted", [("config.yaml", True), (".env.example", False), ("example.json", True)]
)
def test_secret_assignments_are_detected_in_templates_and_source(tmp_path, name, quoted):
    value = "inert-scanner-test-value"
    prefix = "API_" + "KEY="
    text = prefix + (repr(value) if quoted else value) + "\n"
    (tmp_path / name).write_text(text, encoding="utf-8")
    assert check_secrets(tmp_path)


def test_local_env_is_ignored_but_tracked_env_is_blocked(tmp_path):
    (tmp_path / ".env").write_text("local-only=not-a-real-secret\n", encoding="utf-8")
    assert not check_secrets(tmp_path)
    git_binary = shutil.which("git")
    assert git_binary is not None
    for arguments in (["init"], ["add", "-f", ".env"]):
        subprocess.run(  # noqa: S603,S607 -- isolated test repo; no network or user files
            [git_binary, "-C", str(tmp_path), *arguments],
            check=True,
            capture_output=True,
        )
    assert any("forbidden tracked" in error for error in check_secrets(tmp_path))


def test_existing_placeholder_rule_is_preserved(tmp_path):
    (tmp_path / ".env.example").write_text(
        "API_" + "KEY=change-me-example-placeholder\n", encoding="utf-8"
    )
    assert not check_secrets(tmp_path)


@pytest.mark.parametrize("kind", ["", "RSA ", "EC ", "OPENSSH "])
def test_private_key_blocks_are_detected(tmp_path, kind):
    (tmp_path / "config.pem").write_text(
        "-----BEGIN " + kind + "PRIVATE KEY-----", encoding="utf-8"
    )
    assert check_secrets(tmp_path)


@pytest.mark.parametrize("policy", list(DataPolicy))
def test_data_policy_matches_schema(policy):
    value = ModelPolicy(profile="review", timeout_seconds=30, data_policy=policy)
    docs, registry, errors = load_contracts(ROOT)
    assert not errors
    validator = validator_for_contract(
        ROOT, "contracts/schemas/model-policy.schema.json", docs, registry, {}
    )
    validator.validate(asdict(value))
    declared = docs[(ROOT / "contracts/schemas/model-policy.schema.json").resolve()]["properties"][
        "data_policy"
    ]["enum"]
    assert set(declared) == {item.value for item in DataPolicy}


def test_unknown_data_policy_is_rejected():
    with pytest.raises(ValueError):
        ModelPolicy(profile="review", timeout_seconds=30, data_policy="unlimited")
