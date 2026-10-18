from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from bidding_compliance.core.deployment_mode import validate_deployment_mode

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["product-postgres", "offline"])
def test_product_and_offline_modes_remain_available_in_production(mode: str) -> None:
    validate_deployment_mode(mode, "production")


def test_authorized_real_is_rejected_in_production() -> None:
    with pytest.raises(RuntimeError, match="disabled outside APP_ENV=development/test"):
        validate_deployment_mode("authorized-real", "production")


def test_authorized_real_remains_available_for_local_development() -> None:
    validate_deployment_mode("authorized-real", "development")


@pytest.mark.parametrize(
    "entrypoint,extra_env",
    [
        ("deploy/api_entry.py", {"DEPLOY_REVIEW_MODE": "authorized-real"}),
        ("scripts/task0023_real_ai_app.py", {}),
    ],
)
def test_production_startup_rejects_legacy_real_assembly(
    entrypoint: str,
    extra_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    for name, value in extra_env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(ROOT / entrypoint), run_name="__main__")
    assert exit_info.value.code == 2
    assert "authorized-real is disabled outside APP_ENV=development/test" in capsys.readouterr().err
