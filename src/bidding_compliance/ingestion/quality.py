"""Pure text quality operations; importing this module never loads a file parser."""

import hashlib

from .schemas import Fragment, IngestionPolicy


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def quality(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    if sum(len(f.text.strip()) for f in fragments) < policy.min_text_chars:
        return False
    if any(f.source == "ocr" and not f.text.strip() for f in fragments):
        return False
    if any("(cid:" in f.text or "\ufffd" in f.text for f in fragments):
        return False
    ocr = [f.confidence or 0 for f in fragments if f.source == "ocr"]
    return not ocr or sum(ocr) / len(ocr) >= policy.min_ocr_confidence
