"""Pure text quality operations; importing this module never loads a file parser."""

import hashlib
import re
from collections import defaultdict
from datetime import date

from .schemas import Fragment, IngestionPolicy, Issue, OCRWordRecord

_DATE = re.compile(
    r"(?<!\d)(\d{4})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?(?!\d)"
)
_MIN_DUPLICATE_FRAGMENT_CHARS = 8
_TOC_ENTRY_PREFIX = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3}){1,3}[.)、,，]?|\d{1,3}[.)、,，]|"
    r"第[一二三四五六七八九十百千万零〇0-9]+[章节篇]|"
    r"[一二三四五六七八九十百]+[、.])$"
)
_TOC_PAGE_NUMBER = re.compile(r"^\d{1,3}$")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _ocr_word_key(word: OCRWordRecord) -> tuple[int, int, int, int, int]:
    return (word.page_num, word.block_num, word.par_num, word.line_num, word.word_num)


def _toc_entry_prefix_word(words: list[OCRWordRecord]) -> OCRWordRecord | None:
    ordered = sorted(words, key=lambda item: item.word_num)
    if len(ordered) < 3 or not _TOC_PAGE_NUMBER.fullmatch(ordered[-1].text.strip()):
        return None
    try:
        if int(ordered[-1].text) > 300:
            return None
    except ValueError:
        return None
    if not _TOC_ENTRY_PREFIX.fullmatch(ordered[0].text.strip()):
        return None
    title = ordered[1:-1]
    if not any(
        any("\u3400" <= character <= "\u9fff" or character.isalpha() for character in item.text)
        for item in title
    ):
        return None
    return ordered[0]


def _table_of_contents_section_number_keys(
    fragments: list[Fragment],
) -> set[tuple[int, int, int, int, int]]:
    """Identify section-number prefixes only on pages strongly shaped like a TOC.

    Numeric confidence remains strict for body values. An explicit directory heading plus
    several numbered entries, or at least twelve repeated contents rows without that heading,
    is required to classify a page. Continuation pages need six entries and must follow a
    recognized contents page.
    """
    lines: dict[tuple[int, int, int, int], list[OCRWordRecord]] = defaultdict(list)
    toc_heading_pages: set[int] = set()
    for fragment in fragments:
        if fragment.source != "ocr":
            continue
        if fragment.page is not None and "目录" in _normalized(fragment.text):
            toc_heading_pages.add(fragment.page)
        for word in fragment.ocr_words:
            lines.setdefault(
                (word.page_num, word.block_num, word.par_num, word.line_num), []
            ).append(word)

    prefixes_by_page: dict[int, set[tuple[int, int, int, int, int]]] = defaultdict(set)
    for (page, _block, _paragraph, _line), words in lines.items():
        prefix = _toc_entry_prefix_word(words)
        if prefix is not None:
            prefixes_by_page[page].add(_ocr_word_key(prefix))

    toc_pages: set[int] = set()
    for page in sorted({key[0] for key in lines}):
        entry_count = len(prefixes_by_page.get(page, set()))
        if page in toc_heading_pages and entry_count >= 3:
            toc_pages.add(page)
        elif page - 1 in toc_pages and entry_count >= 6:
            toc_pages.add(page)
        elif entry_count >= 12:
            toc_pages.add(page)

    return {
        key
        for page in toc_pages
        for key in prefixes_by_page.get(page, set())
    }


def _has_ocr_numeric_low_confidence(fragments: list[Fragment], policy: IngestionPolicy) -> bool:
    toc_section_numbers = _table_of_contents_section_number_keys(fragments)
    for fragment in fragments:
        if fragment.source != "ocr":
            continue
        if fragment.ocr_words:
            if any(
                re.search(r"\d", word.text)
                and word.confidence < policy.min_numeric_confidence
                and _ocr_word_key(word) not in toc_section_numbers
                for word in fragment.ocr_words
            ):
                return True
        elif (
            fragment.confidence is not None
            and re.search(r"\d", fragment.text)
            and fragment.confidence < policy.min_numeric_confidence
        ):
            # Historical parser output has only fragment-level confidence; retain its
            # conservative gate until the document is reparsed with word records.
            return True
    return False


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
    duplicated = sum(len(text) * count for text, count in counts.items() if count > 1)
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
        # Merged/header rows legitimately have fewer cells. Flag only systematic extra-cell
        # extraction or a severe width jump, not every merged cell in a real tender table.
        wider = [width for width in widths if width > modal + policy.max_table_row_deviation]
        if not wider:
            continue
        anomalous = len(wider)
        if max(wider) > modal + 1 and anomalous >= max(1, (len(rows) + 3) // 4):
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
        word.confidence
        for fragment in fragments
        if fragment.source == "ocr" and fragment.ocr_words
        for word in fragment.ocr_words
    ]
    ocr.extend(
        fragment.confidence or 0
        for fragment in fragments
        if fragment.source == "ocr" and not fragment.ocr_words
    )
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
