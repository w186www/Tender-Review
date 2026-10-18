"""Fail-closed deployment-mode compatibility checks."""


def validate_deployment_mode(mode: str, app_env: str) -> None:
    """Prevent production from reopening the disconnected DEC-007 spending ledger."""
    normalized_mode = mode.strip().lower()
    normalized_env = app_env.strip().lower()
    if normalized_mode == "authorized-real" and normalized_env not in {"development", "test"}:
        raise RuntimeError(
            "authorized-real is disabled outside APP_ENV=development/test because its DEC-007 "
            "ledger is independent of the product PostgreSQL budget; use "
            "product-postgres or offline"
        )
