"""Mandatory real Docker/public-PDF origin mapping evidence for TASK-0006 D07."""

import json
import os
from pathlib import Path

from bidding_compliance.legal.corpus import ARTICLE, digest
from bidding_compliance.legal.source_sandbox import DockerPDFExtractor

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    fixture = json.loads(
        (ROOT / "config/legal/validation-sources.json").read_text(encoding="utf-8")
    )
    source = next(x for x in fixture["sources"] if x["kind"] == "pdf_mapping_fixture")
    raw = (ROOT / source["snapshot_path"]).read_bytes()
    assert digest(raw) == source["sha256"]
    result = DockerPDFExtractor(os.environ["PARSER_VERIFY_IMAGE"]).extract(raw)
    assert len(list(ARTICLE.finditer(result.text))) == 84
    assert {s.page for s in result.spans if s.kind == "pdf_glyph"} == set(range(1, 16))
    assert all(s.bbox for s in result.spans if s.kind == "pdf_glyph")
    # This pinned official PDF has no footer digits; do not invent excluded text.
    assert result.raw_exclusions == ()
    assert all(x.reason == "page_number" for x in result.raw_exclusions)
    assert sum(s.end - s.start for s in result.spans) == len(result.text)
    print("PASS: isolated real official PDF, 84 articles/15 pages, glyph coverage and exclusions")


if __name__ == "__main__":
    main()
