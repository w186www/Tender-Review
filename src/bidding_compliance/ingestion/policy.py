"""Policy from a reviewed configuration, never from uploaded document contents."""

import json
from pathlib import Path

from .schemas import IngestionPolicy


def load_policy() -> IngestionPolicy:
    # JSON is also YAML; the checked-in policy is converted by the contract setup step.
    path = Path(__file__).resolve().parents[3] / "config/ingestion.yaml"
    return IngestionPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
