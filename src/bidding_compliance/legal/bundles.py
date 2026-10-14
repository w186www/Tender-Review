"""Capture once and reproduce immutable legal revisions without mutable repository files."""

import base64
from pathlib import Path

from .contracts import LegalManifest, SourceExtractionResult
from .corpus import digest, ingest_artifacts, read_bounded
from .extraction import PDFExtractor
from .management_contracts import CorpusBundle, LegalArtifact, VerificationSource


def artifact_bytes(bundle: CorpusBundle) -> dict[str, bytes]:
    return {a.path: base64.b64decode(a.data_base64, validate=True) for a in bundle.artifacts}


def capture_bundle(
    root: Path,
    manifest: LegalManifest,
    proofs: tuple[VerificationSource, ...],
    extractor: PDFExtractor | None = None,
) -> CorpusBundle:
    names = {p for v in manifest.versions for p in (v.text_path, v.source_snapshot_path)}
    names.update(s.path for s in proofs)
    captured: dict[str, bytes] = {}
    artifacts = []
    for name in sorted(names):
        # Validate public namespace before reading, never expose a private upload or .env.
        LegalArtifact.public_namespace(name)
        if not (root / name).resolve().is_relative_to(root.resolve() / "knowledge" / "legal"):
            raise ValueError("public legal artifact cannot resolve to a private path")
        raw = read_bounded(root, name)
        captured[name] = raw
        artifacts.append(
            LegalArtifact(
                path=name,
                sha256=digest(raw),
                data_base64=base64.b64encode(raw).decode(),
            )
        )
    index = ingest_artifacts(manifest, captured.__getitem__, extractor)
    bundle = CorpusBundle(index=index, artifacts=tuple(artifacts), verification_sources=proofs)
    if len(bundle.model_dump_json().encode()) > 50_000_000:
        raise ValueError("serialized legal revision budget exceeded")
    return bundle


def validate_bundle(bundle: CorpusBundle) -> CorpusBundle:
    bundle = CorpusBundle.model_validate(bundle.model_dump())
    raw = artifact_bytes(bundle)

    class FrozenPDF:
        # PDF extraction was proved by the isolated worker before the immutable row was inserted.
        # Reads verify row/bundle hashes and reproduce the frozen map, not mutable working files.
        def extract(self, payload: bytes) -> SourceExtractionResult:
            source_hash = digest(payload)
            version = next(
                v
                for v in bundle.index.manifest.versions
                if (v.source_hash == source_hash and v.source_format == "pdf")
            )
            mapping = next(
                m
                for m in bundle.index.source_maps
                if (m.law_id == version.law_id and m.version == version.version)
            )
            return SourceExtractionResult(
                text=raw[version.text_path].decode("utf-8"),
                spans=mapping.spans,
                raw_exclusions=mapping.raw_exclusions,
            )

    if ingest_artifacts(bundle.index.manifest, raw.__getitem__, FrozenPDF()) != bundle.index:
        raise ValueError("frozen legal revision cannot reproduce its index")
    return bundle
