"""Bounded ingestion and immutable, content-addressed legal snapshots (NFR-008)."""

import hashlib
import html
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from .contracts import (
    LegalClause,
    LegalHit,
    LegalIndex,
    LegalManifest,
    LegalVersion,
    RetrievalQuery,
    SourceExclusion,
    SourceMap,
    SourceSpan,
    TextExclusion,
)
from .extraction import PDFExtractor, extract_html

ARTICLE = re.compile(
    r"(?m)^[ \t\u3000]*(第[一二三四五六七八九十百千万零〇两0-9]+条"
    r"(?:之[一二三四五六七八九十]+)?)[ \t\u3000]+"
)
CHAPTER = re.compile(r"(?m)^[ \t\u3000]*第[一二三四五六七八九十百]+[章节][^\n]*\n?")
TOC = re.compile(r"[.．…]{3,}\s*[0-9]+\s*$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bounded(root: Path, relative: str, maximum: int = 2_000_000) -> bytes:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("legal input must be a file within the corpus root")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("legal input exceeds resource limit")
    return data


def split_clauses(text: str, version: LegalVersion) -> tuple[LegalClause, ...]:
    """Keep exact Unicode offsets; headers/chapters cannot masquerade as articles."""
    matches = [
        m
        for m in ARTICLE.finditer(text)
        if not TOC.search(
            text[m.start() : text.find("\n", m.start()) if "\n" in text[m.start() :] else len(text)]
        )
    ]
    ranges: list[tuple[str | None, int, int]] = []
    if matches:
        seen: set[str] = set()
        for i, match in enumerate(matches):
            article = match.group(1)
            if article in seen:
                raise ValueError("duplicate article markers; manual source cleanup required")
            seen.add(article)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chapter = CHAPTER.search(text, match.start(), end)
            if chapter:
                end = chapter.start()
            ranges.append((article, match.start(), end))
    else:
        # Notices without numbered articles remain searchable references.
        delimiter = text.find("-" * 60)
        start = text.find("\n", delimiter) + 1 if delimiter >= 0 else 0
        ranges.append((None, start, len(text)))
    clauses = []
    for article, start, end in ranges:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        for offset in range(start, end, 8000):
            stop = min(offset + 8000, end)
            quote = text[offset:stop]
            key = f"{version.law_id}\0{version.version}\0{version.text_hash}\0{offset}:{stop}"
            clauses.append(
                LegalClause(
                    clause_id=digest(key.encode()),
                    law_id=version.law_id,
                    version=version.version,
                    article=article,
                    start=offset,
                    end=stop,
                    quote=quote,
                    quote_hash=digest(quote.encode()),
                )
            )
    if not clauses:
        raise ValueError("empty legal text")
    return tuple(clauses)


def map_source(
    raw: bytes,
    source: bytes,
    version: LegalVersion,
    extractor: PDFExtractor | None = None,
) -> SourceMap:
    text = raw.decode("utf-8")
    spans: tuple[SourceSpan, ...]
    raw_exclusions: tuple[SourceExclusion, ...] = ()
    algorithm: Literal["identity-1", "moj-html-map-1", "pdf-glyph-map-1"]
    if version.source_format == "text":
        if source != raw:
            raise ValueError("text source requires identical bytes, not an unproved cleaned text")
        mapped, spans = (
            text,
            (
                SourceSpan(
                    start=0,
                    end=len(text),
                    kind="text",
                    byte_start=0,
                    byte_end=len(source),
                ),
            ),
        )
        algorithm = "identity-1"
    elif version.source_format == "moj_html":
        mapped, spans = extract_html(source, version.extraction_header)
        algorithm = "moj-html-map-1"
    else:
        if extractor is None:
            from .source_sandbox import DockerPDFExtractor

            extractor = DockerPDFExtractor(os.environ.get("LEGAL_SOURCE_IMAGE", ""))
        extracted = extractor.extract(source)
        mapped, spans, raw_exclusions = extracted.text, extracted.spans, extracted.raw_exclusions
        algorithm = "pdf-glyph-map-1"
    if mapped != text:
        raise ValueError("source extraction does not reproduce cleaned legal text")
    previous = 0
    for span in spans:
        if span.start != previous or span.end > len(text):
            raise ValueError("source mapping has a gap or overlap")
        fragment = text[span.start : span.end]
        if span.kind in {"text", "html_text", "html_entity"}:
            assert span.byte_start is not None and span.byte_end is not None
            if span.byte_end > len(source):
                raise ValueError("source byte interval is out of bounds")
            decoded = source[span.byte_start : span.byte_end].decode("utf-8")
            if span.kind == "html_entity":
                decoded = html.unescape(decoded)
            if decoded != fragment:
                raise ValueError("source byte mapping mismatch")
        elif span.kind == "separator" and fragment not in {" ", "\n"}:
            raise ValueError("generated source separator cannot supply legal text")
        previous = span.end
    if previous != len(text):
        raise ValueError("source mapping does not cover cleaned legal text")
    return SourceMap(
        law_id=version.law_id,
        version=version.version,
        source_hash=version.source_hash,
        text_hash=version.text_hash,
        extraction_version=algorithm,
        spans=spans,
        raw_exclusions=raw_exclusions,
    )


def exclusions(
    text: str,
    version: LegalVersion,
    pieces: tuple[LegalClause, ...],
) -> list[TextExclusion]:
    output: list[TextExclusion] = []
    previous = 0
    for clause in (*pieces,):
        if clause.start > previous:
            gap = text[previous : clause.start]
            reason: Literal["whitespace", "preamble", "chapter", "toc"]
            reason = "whitespace" if not gap.strip() else "preamble" if previous == 0 else "chapter"
            if gap.strip() and TOC.search(gap.strip().splitlines()[-1]):
                reason = "toc"
            if previous and gap.strip() and not CHAPTER.fullmatch(gap.strip() + "\n"):
                if version.verification == "verified":
                    raise ValueError("unexplained legal text exclusion")
            output.append(
                TextExclusion(
                    law_id=version.law_id,
                    version=version.version,
                    start=previous,
                    end=clause.start,
                    reason=reason,
                )
            )
        previous = clause.end
    if previous < len(text):
        if text[previous:].strip() and version.verification == "verified":
            raise ValueError("unexplained trailing legal text")
        output.append(
            TextExclusion(
                law_id=version.law_id,
                version=version.version,
                start=previous,
                end=len(text),
                reason="whitespace",
            )
        )
    return output


def ingest(
    root: Path,
    manifest: LegalManifest,
    extractor: PDFExtractor | None = None,
) -> LegalIndex:
    return ingest_artifacts(manifest, lambda name: read_bounded(root, name), extractor)


def ingest_artifacts(
    manifest: LegalManifest,
    read: Callable[[str], bytes],
    extractor: PDFExtractor | None = None,
) -> LegalIndex:
    clauses: list[LegalClause] = []
    maps: list[SourceMap] = []
    gaps: list[TextExclusion] = []
    total = 0
    for version in manifest.versions:
        raw = read(version.text_path)
        source = read(version.source_snapshot_path)
        if max(len(raw), len(source)) > 2_000_000:
            raise ValueError("legal artifact budget exceeded")
        total += len(raw) + len(source)
        if total > 50_000_000:
            raise ValueError("corpus exceeds ingestion budget")
        if digest(raw) != version.text_hash or digest(source) != version.source_hash:
            raise ValueError("legal source hash mismatch")
        pieces = split_clauses(raw.decode("utf-8"), version)
        articles = {c.article for c in pieces}
        if (
            version.expected_articles is not None
            and tuple(dict.fromkeys(c.article for c in pieces if c.article is not None))
            != version.expected_articles
        ):
            raise ValueError("legal article coverage mismatch")
        if any(effect.article not in articles for effect in version.clause_effects):
            raise ValueError("clause effect refers to a missing article")
        if any(scope.article not in articles for scope in version.clause_scopes):
            raise ValueError("clause scope refers to a missing article")
        clauses.extend(pieces)
        origin = map_source(raw, source, version, extractor)
        if any(
            span.kind == "header" and any(c.start < span.end and c.end > span.start for c in pieces)
            for span in origin.spans
        ):
            raise ValueError("generated header cannot be cited as legal text")
        maps.append(origin)
        gaps.extend(exclusions(raw.decode("utf-8"), version, pieces))
    return LegalIndex(
        manifest=manifest,
        clauses=tuple(clauses),
        source_maps=tuple(maps),
        text_exclusions=tuple(gaps),
    )


def index_hash(index: LegalIndex) -> str:
    return digest(index.model_dump_json().encode())


def save_index(index: LegalIndex, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = index.model_dump_json().encode()
    path = directory / (digest(data) + ".json")
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("immutable legal snapshot collision") from None
    return path


def load_index(root: Path, path: Path, expected_hash: str) -> LegalIndex:
    with path.open("rb") as stream:
        data = stream.read(50_000_001)
    if len(data) > 50_000_000 or digest(data) != expected_hash:
        raise ValueError("index hash mismatch or resource limit")
    index = LegalIndex.model_validate_json(data)
    # Rebuild locators and quotations rather than trusting serialized evidence.
    if ingest(root, index.manifest) != index:
        raise ValueError("legal index does not reproduce its sources")
    return index


def resolve_evidence(
    root: Path,
    index: LegalIndex,
    hit: LegalHit,
    query: RetrievalQuery,
    *,
    reader: Callable[[str], bytes] | None = None,
) -> str:
    """Resolve formal artifact URI through the frozen index, never through caller paths/URLs."""
    hit = LegalHit.model_validate(hit.model_dump())
    query = RetrievalQuery.model_validate(query.model_dump())
    clause = next((c for c in index.clauses if c.clause_id == hit.evidence_id), None)
    version = next(
        (
            v
            for v in index.manifest.versions
            if (v.law_id == hit.law_id and v.version == hit.version)
        ),
        None,
    )
    if (
        clause is None
        or version is None
        or (
            clause.law_id != version.law_id
            or clause.version != version.version
            or clause.quote != hit.quote
            or clause.quote_hash != hit.quote_hash
            or hit.locator != f"{version.text_path}#chars={clause.start}:{clause.end}"
            or hit.text_hash != version.text_hash
            or hit.source_hash != version.source_hash
            or hit.source_uri != version.source_uri
            or hit.title != version.title
            or hit.article != clause.article
            or hit.evidence.kind
            != (
                "policy"
                if version.authority
                in {
                    "policy",
                    "reference",
                }
                else "law"
            )
        )
    ):
        raise ValueError("evidence does not match frozen legal index")
    # Resolve the date/scope against frozen metadata, not against a caller's eligibility flag.
    from .retrieval import (
        applicable_frameworks,
        clause_exclusions,
        clause_window,
        confirmation_reason,
    )

    reason = confirmation_reason(version, clause.article, query)
    start, end, _, _ = clause_window(version, clause.article)
    if (
        clause_exclusions(version, clause.article, query)
        or hit.reason != reason
        or hit.effective_from != start
        or hit.effective_to != end
        or hit.applicable_frameworks != applicable_frameworks(version, clause.article, query)
        or hit.evidence.jurisdiction != query.region
        or (reason != "valid" and not query.include_references)
    ):
        raise ValueError("evidence does not match frozen legal applicability")
    read = reader or (lambda name: read_bounded(root, name))
    raw = read(version.text_path)
    source = read(version.source_snapshot_path)
    if digest(raw) != hit.evidence.source_hash or digest(source) != version.source_hash:
        raise ValueError("legal evidence artifact hash mismatch")
    quote = raw.decode("utf-8")[clause.start : clause.end]
    if quote != hit.evidence.quote or digest(quote.encode("utf-8")) != clause.quote_hash:
        raise ValueError("legal evidence artifact locator mismatch")
    return quote


def evidence_origins(
    root: Path,
    index: LegalIndex,
    hit: LegalHit,
    query: RetrievalQuery,
    *,
    reader: Callable[[str], bytes] | None = None,
) -> tuple[SourceSpan, ...]:
    resolve_evidence(root, index, hit, query, reader=reader)
    clause = next(c for c in index.clauses if c.clause_id == hit.evidence_id)
    version = next(
        v for v in index.manifest.versions if (v.law_id == hit.law_id and v.version == hit.version)
    )
    mapping = next(
        m for m in index.source_maps if (m.law_id == hit.law_id and m.version == hit.version)
    )
    read = reader or (lambda name: read_bounded(root, name))
    source = read(version.source_snapshot_path)
    text = read(version.text_path).decode("utf-8")
    output = []
    for span in mapping.spans:
        start, end = max(span.start, clause.start), min(span.end, clause.end)
        if start >= end:
            continue
        payload = span.model_dump()
        if span.kind in {"text", "html_text"}:
            assert span.byte_start is not None
            payload["byte_start"] = span.byte_start + len(text[span.start : start].encode("utf-8"))
            payload["byte_end"] = span.byte_start + len(text[span.start : end].encode("utf-8"))
            if source[payload["byte_start"] : payload["byte_end"]].decode() != text[start:end]:
                raise ValueError("evidence origin mismatch")
        payload.update(start=start, end=end)
        output.append(SourceSpan.model_validate(payload))
    if sum(s.end - s.start for s in output) != len(hit.quote):
        raise ValueError("evidence origin coverage mismatch")
    return tuple(output)
