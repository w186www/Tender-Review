"""Generate legal boundary Schemas; --check rejects drift."""

import argparse
import json
from pathlib import Path

from bidding_compliance.legal.contracts import (
    LegalIndex,
    LegalManifest,
    RetrievalQuery,
    RetrievalResult,
    SourceExtractionRequest,
    SourceExtractionResult,
    SourceMap,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    failed = False
    for model, name in (
        (LegalManifest, "legal-manifest"), (LegalIndex, "legal-index"),
        (RetrievalQuery, "legal-query"), (RetrievalResult, "legal-result"),
        (SourceMap, "legal-source-map"),
        (SourceExtractionRequest, "legal-source-request"),
        (SourceExtractionResult, "legal-source-result"),
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
