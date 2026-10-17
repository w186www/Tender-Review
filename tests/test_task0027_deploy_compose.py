"""Deployment wiring: real-model variables reach only model-calling services.

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

# Exactly the variables the two real-model paths resolve:
# task0023_real_ai_app.py (credentials), resolve_real_runtime_authorization (identity,
# ledger, audit, per-file registry, legacy allowlist), the operator CLI actor, and the
# product-postgres assembly (tenant policy/account identity).
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
        "PRODUCT_TENANT_ID",
        "PRODUCT_PROVIDER",
        "PRODUCT_PURPOSE",
        "PRODUCT_MODEL",
        "PRODUCT_BUDGET_AUTHORIZATION_ID",
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


def test_api_and_review_worker_receive_every_real_model_variable_as_optional_interpolations():
    document = compose()
    for service in ("api", "review-worker"):
        merged = environment(document, service)
        assert REAL_MODEL_VARIABLES <= set(merged), service
        for name in REAL_MODEL_VARIABLES:
            value = merged[name]
            # `${NAME:-...}` resolves from deploy/.env (600, gitignored) and stays optional:
            # a blank value is a legal, non-fatal configuration.
            assert re.fullmatch(r"\$\{" + name + r":-([^}]*)\}", value), (service, name, value)
            assert value.count(":-") == 1
        # The deployment default remains the offline mode.
        assert merged["DEPLOY_REVIEW_MODE"] == "${DEPLOY_REVIEW_MODE:-offline}"


def test_ingestion_worker_and_every_other_non_model_service_never_receive_model_variables():
    document = compose()
    for name in document["services"]:
        if name in {"api", "review-worker"}:
            continue
        merged = environment(document, name)
        leaked = REAL_MODEL_VARIABLES & set(merged)
        assert not leaked, (name, sorted(leaked))
        assert not (CREDENTIAL_VARIABLES & set(merged)), name
    # The shared anchor merged into worker and init must stay free of them; the model-call
    # anchor is merged only into api and review-worker.
    assert not (REAL_MODEL_VARIABLES & set(document["x-app-environment"]))
    assert REAL_MODEL_VARIABLES <= set(document["x-real-model-environment"])
    # Only the model-calling services decide the review mode.
    assert "DEPLOY_REVIEW_MODE" not in environment(document, "worker")
    assert "DEPLOY_REVIEW_MODE" not in environment(document, "init")
    assert "DEPLOY_REVIEW_MODE" not in environment(document, "nginx")


def test_env_template_documents_the_variables_without_a_real_value():
    text = ENV_TEMPLATE.read_text(encoding="utf-8")
    uncommented = dict(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=(.*)$", text))
    for name in CREDENTIAL_VARIABLES:
        # Present as documentation, never as an active assignment with a value.
        assert f"#{name}=" in text or name in uncommented, name
        assert uncommented.get(name) in (None, ""), name
    assert "#DEC007_AUTHORIZATION_ACTOR=" in text
    assert "#DEC007_AUTHORIZATION_ID=DEC-007-2026-10-16" in text
    for name in (
        "PRODUCT_TENANT_ID",
        "PRODUCT_PROVIDER",
        "PRODUCT_PURPOSE",
        "PRODUCT_MODEL",
        "PRODUCT_BUDGET_AUTHORIZATION_ID",
    ):
        assert f"#{name}=" in text, name


def test_offline_entry_point_stays_offline_when_the_real_variables_are_blank():
    entry = (ROOT / "deploy" / "api_entry.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DEPLOY_REVIEW_MODE", "offline")' in entry
    # The offline assembly cannot reach the real-model path at all: it never imports it.
    offline = (ROOT / "scripts" / "task0011_e2e_app.py").read_text(encoding="utf-8")
    assert "real_ai_runtime" not in offline
    assert "real_embedding_runtime" not in offline


def test_the_api_container_carries_its_compose_project_name_for_the_controlled_round():
    """The one-off validation container inherits the api service's project name.

    ``scripts/task0027_real_ai_validation_app.py`` compares the host evidence's compose
    project with the current deployment; the project name is a deployment constant, never a
    secret and never operator input.
    """
    document = compose()
    api = environment(document, "api")
    assert api["DEPLOY_COMPOSE_PROJECT"] == document["name"] == "tender-review-demo"
    assert "DEPLOY_COMPOSE_PROJECT" not in environment(document, "review-worker")
    for name in document["services"]:
        if name == "api":
            continue
        assert "DEPLOY_COMPOSE_PROJECT" not in environment(document, name), name


def test_frontend_mode_switch_documents_the_dec007_value():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "dec007-real-qwen" in dockerfile
    template = ENV_TEMPLATE.read_text(encoding="utf-8")
    assert "dec007-real-qwen" in template
    app = (ROOT / "src" / "frontend" / "src" / "app.tsx").read_text(encoding="utf-8")
    assert '"dec007-real-qwen"' in app


def test_the_validation_image_tag_is_opt_in_and_never_replaces_the_demo_tag():
    """The controlled-round image is a per-command override, never the new default.

    ``IMAGE_TAG=task0027-validation $D build api`` creates an independent tag; every other
    command (``up``, ``build``, ``run`` without the override) still resolves the online
    ``:demo`` tag from deploy/.env, so a validation build can never replace the image the
    deployment serves.
    """
    document = compose()
    for service, image in (
        ("api", "tender-review-api"),
        ("worker", "tender-review-api"),
        ("init", "tender-review-api"),
        ("nginx", "tender-review-web"),
    ):
        assert document["services"][service]["image"] == f"{image}:${{IMAGE_TAG:-demo}}"
    assert re.search(r"(?m)^IMAGE_TAG=demo$", ENV_TEMPLATE.read_text(encoding="utf-8"))
    assert "task0027-validation" in (ROOT / "deploy" / "README-demo.md").read_text(
        encoding="utf-8"
    )


def test_bootstrap_up_starts_the_durable_review_worker():
    """A fresh or restarted stack must claim the durable review queue.

    ``docker-compose.demo.yml`` defines ``review-worker``; the bootstrap entry point is the
    documented fresh-install path and must start it together with the API and ingestion
    worker. Otherwise every review stays queued with no executor.
    """
    text = (ROOT / "deploy" / "bootstrap.sh").read_text(encoding="utf-8")
    starts = [
        line
        for line in text.splitlines()
        if "up -d" in line and "postgres minio clamav" not in line
    ]
    assert any(
        "review-worker" in line and "api" in line and "worker" in line for line in starts
    ), starts
