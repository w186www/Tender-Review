"""Pure text quality operations; importing this module never loads a file parser."""

import hashlib
import re
from collections import defaultdict
from datetime import date

from .schemas import Fragment, IngestionPolicy, Issue

_DATE = re.compile(
    r"(?<!\d)(\d{4})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?(?!\d)"
)
_MIN_DUPLICATE_FRAGMENT_CHARS = 20


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _has_ocr_numeric_low_confidence(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    return any(
        fragment.source == "ocr"
        and fragment.confidence is not None
        and re.search(r"\d", fragment.text)
        and fragment.confidence < policy.min_numeric_confidence
        for fragment in fragments
    )


def _has_invalid_date(fragments: list[Fragment]) -> bool:
    for fragment in fragments:
        for match in _DATE.finditer(fragment.text):
            year, month, day = (int(part) for part in match.groups())
            try:
                date(year, month, day)
            except ValueError:
                return True
    return False


def _duplicate_ratio(fragments: list[Fragment]) -> float:
    texts = [
        _normalized(fragment.text)
        for fragment in fragments
        if len(_normalized(fragment.text)) >= _MIN_DUPLICATE_FRAGMENT_CHARS
    ]
    total = sum(len(text) for text in texts)
    if total == 0:
        return 0.0
    counts: dict[str, int] = defaultdict(int)
    for text in texts:
        counts[text] += 1
    duplicated = sum(len(text) for text, count in counts.items() if count > 1)
    return duplicated / total


def _has_page_coverage_gap(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    pages = [fragment.page for fragment in fragments if fragment.page is not None]
    if not pages:
        return False
    expected = max(pages)
    if expected <= 1:
        return False
    return len(set(pages)) / expected < policy.min_page_coverage_ratio


def _has_reading_order_gap(fragments: list[Fragment]) -> bool:
    previous: int | None = None
    for fragment in fragments:
        if fragment.page is None:
            continue
        if previous is not None and fragment.page < previous:
            return True
        previous = fragment.page
    return False


def _has_table_structure_gap(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    tables: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for fragment in fragments:
        if (
            fragment.kind == "table_cell"
            and fragment.table is not None
            and fragment.row is not None
            and fragment.column is not None
        ):
            tables[fragment.table][fragment.row].add(fragment.column)
    for rows in tables.values():
        if len(rows) < 2:
            continue
        widths = [len(columns) for columns in rows.values()]
        modal = max(set(widths), key=widths.count)
        if any(abs(width - modal) > policy.max_table_row_deviation for width in widths):
            return True
    return False


def quality_issues(fragments: list[Fragment], policy: IngestionPolicy) -> list[Issue]:
    """Deterministic quality signals, including structural checks beyond average OCR score.

    The returned codes are the same codes recorded on the document for the reviewer; an
    empty list is the pass result. The checks never read a file or call a model, and a
    failure routes the document to ``needs_review`` rather than discarding its text.
    """
    issues: list[Issue] = []
    if sum(len(fragment.text.strip()) for fragment in fragments) < policy.min_text_chars:
        issues.append("LOW_QUALITY")
    if any(fragment.source == "ocr" and not fragment.text.strip() for fragment in fragments):
        issues.append("LOW_QUALITY")
    if any("(cid:" in fragment.text or "\ufffd" in fragment.text for fragment in fragments):
        issues.append("LOW_QUALITY")
    ocr = [
        fragment.confidence or 0
        for fragment in fragments
        if fragment.source == "ocr"
    ]
    if ocr and sum(ocr) / len(ocr) < policy.min_ocr_confidence:
        issues.append("LOW_QUALITY")
    if _has_ocr_numeric_low_confidence(fragments, policy):
        issues.append("LOW_CONFIDENCE_NUMERIC")
    if _has_invalid_date(fragments):
        issues.append("INVALID_DATE")
    if _duplicate_ratio(fragments) >= policy.max_duplicate_text_ratio:
        issues.append("DUPLICATE_TEXT")
    if _has_page_coverage_gap(fragments, policy):
        issues.append("PAGE_COVERAGE_GAP")
    if _has_reading_order_gap(fragments):
        issues.append("READING_ORDER_GAP")
    if _has_table_structure_gap(fragments, policy):
        issues.append("TABLE_STRUCTURE_GAP")
    return list(dict.fromkeys(issues))


def quality(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    return not quality_issues(fragments, policy)
