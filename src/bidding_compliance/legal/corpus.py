"""Bounded ingestion and immutable, content-addressed legal snapshots (NFR-008)."""

import hashlib
import re
from pathlib import Path

from .contracts import LegalClause, LegalIndex, LegalManifest, LegalVersion

ARTICLE = re.compile(
    r"(?m)^[ \t\u3000]*(第[一二三四五六七八九十百千万零〇两0-9]+条"
    r"(?:之[一二三四五六七八九十]+)?)[ \t\u3000]+"
)
CHAPTER = re.compile(r"(?m)^[ \t\u3000]*第[一二三四五六七八九十百]+[章节][^\n]*\n?")


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
    matches = list(ARTICLE.finditer(text))
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
            clauses.append(LegalClause(
                clause_id=digest(key.encode()), law_id=version.law_id,
                version=version.version, article=article, start=offset, end=stop,
                quote=quote, quote_hash=digest(quote.encode()),
            ))
    if not clauses:
        raise ValueError("empty legal text")
    return tuple(clauses)


def ingest(root: Path, manifest: LegalManifest) -> LegalIndex:
    clauses: list[LegalClause] = []
    total = 0
    for version in manifest.versions:
        raw = read_bounded(root, version.text_path)
        source = read_bounded(root, version.source_snapshot_path)
        total += len(raw) + len(source)
        if total > 50_000_000:
            raise ValueError("corpus exceeds ingestion budget")
        if digest(raw) != version.text_hash or digest(source) != version.source_hash:
            raise ValueError("legal source hash mismatch")
        clauses.extend(split_clauses(raw.decode("utf-8"), version))
    return LegalIndex(manifest=manifest, clauses=tuple(clauses))


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
