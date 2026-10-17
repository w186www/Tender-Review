"""Generate deterministic skill/rule boundary schemas; --check rejects drift."""

import argparse
import json
from pathlib import Path

from bidding_compliance.domain.rules.models import (
    DiscoveryDocumentRequest,
    DiscoveryInputSnapshot,
    DiscoveryResult,
    RuleDefinition,
    SkillDefinition,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    failed = False
    for model, name in (
        (RuleDefinition, "rule-definition"),
        (SkillDefinition, "skill-definition"),
        (DiscoveryDocumentRequest, "candidate-discovery-document-request"),
        (DiscoveryInputSnapshot, "candidate-discovery-input"),
        (DiscoveryResult, "candidate-discovery-result"),
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://bidding-compliance.local/schemas/{name}.schema.json"
        rendered = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        path = ROOT / "contracts/schemas" / (name + ".schema.json")
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                print(f"DRIFT: {path.name}")
                failed = True
        else:
            path.write_text(rendered, encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
