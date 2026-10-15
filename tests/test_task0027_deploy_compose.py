"""Deployment wiring: real-model variables reach the api service and nothing else.

The compose file and the env template are deployment configuration, not business logic, so
these checks parse them instead of starting anything: a supplier credential must never be
merged into a service that does not call a model, every injected value must stay an optional
env-file interpolation with an empty default, and the offline mode stays the default.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.demo.yml"
ENV_TEMPLATE = ROOT / "deploy" / "demo.env.example"

# Exactly the variables the authorized-real path resolves:
# task0023_real_ai_app.py (credentials), resolve_real_runtime_authorization (identity,
# ledger, audit, per-file registry, legacy allowlist) and the operator CLI actor.
REAL_MODEL_VARIABLES = frozenset(
    {
        "DASHSCOPE_API_KEY",
        "BAILIAN_WORKSPACE_ID",
        "DEC007_AUTHORIZATION_ID",
        "DEC007_AUTHORIZATION_REGISTRY",
        "DEC007_LEDGER_PATH",
        "DEC007_MODEL_AUDIT_PATH",
        "DEC007_AUTHORIZATION_ACTOR",
        "DEC005_AUTHORIZATION_ID",
        "DEC005_ALLOWED_DOCUMENT_SHA256",
        "DEC005_ALLOWED_SYNTHETIC_SHA256",
    }
)
CREDENTIAL_VARIABLES = frozenset(
    {
        "DASHSCOPE_API_KEY",
        "BAILIAN_WORKSPACE_ID",
        "DEC007_AUTHORIZATION_REGISTRY",
        "DEC007_LEDGER_PATH",
        "DEC007_MODEL_AUDIT_PATH",
    }
)


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def environment(document: dict, service: str) -> dict[str, str]:
    value = document["services"][service].get("environment") or {}
    assert isinstance(value, dict)
    return value


def test_api_receives_every_real_model_variable_as_an_optional_interpolation():
    document = compose()
    api = environment(document, "api")
    assert REAL_MODEL_VARIABLES <= set(api)
    for name in REAL_MODEL_VARIABLES:
        value = api[name]
        # `${NAME:-...}` resolves from deploy/.env (600, gitignored) and stays optional:
        # a blank value is a legal, non-fatal configuration.
        assert re.fullmatch(r"\$\{" + name + r":-([^}]*)\}", value), (name, value)
        assert value.count(":-") == 1
    # The deployment default remains the offline mode.
    assert api["DEPLOY_REVIEW_MODE"] == "${DEPLOY_REVIEW_MODE:-offline}"


def test_worker_and_every_other_service_never_receive_the_model_variables():
    document = compose()
    for name in document["services"]:
        if name == "api":
            continue
        merged = environment(document, name)
        leaked = REAL_MODEL_VARIABLES & set(merged)
        assert not leaked, (name, sorted(leaked))
        assert not (CREDENTIAL_VARIABLES & set(merged)), name
    # The shared anchor merged into worker and init must stay free of them as well; only
    # the api-only anchor carries them.
    assert not (REAL_MODEL_VARIABLES & set(document["x-app-environment"]))
    assert REAL_MODEL_VARIABLES <= set(document["x-real-model-environment"])
    # No service but the api decides the review mode.
    assert "DEPLOY_REVIEW_MODE" not in environment(document, "worker")
    assert "DEPLOY_REVIEW_MODE" not in environment(document, "init")


def test_env_template_documents_the_variables_without_a_real_value():
    text = ENV_TEMPLATE.read_text(encoding="utf-8")
    uncommented = dict(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=(.*)$", text))
    for name in CREDENTIAL_VARIABLES:
        # Present as documentation, never as an active assignment with a value.
        assert f"#{name}=" in text or name in uncommented, name
        assert uncommented.get(name) in (None, ""), name
    assert "#DEC007_AUTHORIZATION_ACTOR=" in text
    assert "#DEC007_AUTHORIZATION_ID=DEC-007-2026-10-16" in text


def test_offline_entry_point_stays_offline_when_the_real_variables_are_blank():
    entry = (ROOT / "deploy" / "api_entry.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DEPLOY_REVIEW_MODE", "offline")' in entry
    # The offline assembly cannot reach the real-model path at all: it never imports it.
    offline = (ROOT / "scripts" / "task0011_e2e_app.py").read_text(encoding="utf-8")
    assert "real_ai_runtime" not in offline
    assert "real_embedding_runtime" not in offline


def test_frontend_mode_switch_documents_the_dec007_value():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "dec007-real-qwen" in dockerfile
    template = ENV_TEMPLATE.read_text(encoding="utf-8")
    assert "dec007-real-qwen" in template
    app = (ROOT / "src" / "frontend" / "src" / "app.tsx").read_text(encoding="utf-8")
    assert '"dec007-real-qwen"' in app
