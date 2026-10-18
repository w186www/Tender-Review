"""Offline legal ingestion and reproducible query CLI; never fetch query content."""

import argparse
from pathlib import Path

from bidding_compliance.legal.contracts import LegalManifest, RetrievalQuery
from bidding_compliance.legal.corpus import ingest, load_index, read_bounded, save_index
from bidding_compliance.legal.retrieval import LegalRetriever

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--manifest", default="config/legal/manifest.json")
    build.add_argument("--output", type=Path, default=ROOT / ".verification/legal")
    query = sub.add_parser("query")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--hash", required=True)
    query.add_argument("--query", required=True, help="repository-relative query JSON")
    args = parser.parse_args()
    if args.command == "build":
        manifest = LegalManifest.model_validate_json(read_bounded(args.root, args.manifest))
        index = ingest(args.root, manifest)
        path = save_index(index, args.output)
        print(f"{path.name}: {len(manifest.versions)} versions, {len(index.clauses)} clauses")
    else:
        index = load_index(args.root, args.index, args.hash)
        request = RetrievalQuery.model_validate_json(read_bounded(args.root, args.query))
        print(LegalRetriever(index).search(request).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
