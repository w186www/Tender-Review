"""Evaluation skill: complete, rectangular point-score tables only."""

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Literal

from bidding_compliance.domain.rules.models import (
    LocatedFragment,
    RuleDefinition,
    RuleMatch,
    RuleReference,
    SkillDefinition,
    SkillScan,
)

DEFINITION = SkillDefinition(
    skill_id="evaluation_review",
    skill_version="1.0.0",
    category="evaluation",
    rules=(RuleReference(rule_id="TASK0007.EVAL.SCORE-TOTAL", rule_version="1.0.0"),),
)
RULES = (
    RuleDefinition(
        rule_id="TASK0007.EVAL.SCORE-TOTAL",
        rule_version="1.0.0",
        category="evaluation",
        check_id="structured_score_total",
        applicability="structured_table",
        explanation_template="结构完整的评分表分项分值与其明示总分不一致；需人工检查评分口径与分值单位。",
        equivalence_group="evaluation:score-total-mismatch",
    ),
)
_SIGNAL = re.compile(r"评分表|评分标准|评审因素|分值|总分|满分|合计")
_SCORE_HEADER = re.compile(r"分值|分数|最高分|满分|得分|score", re.IGNORECASE)
_TOTAL_LABEL = re.compile(r"总分|满分|合计|总计")
_NUMBER = re.compile(r"(?<![\d.])(?P<value>\d+(?:\.\d+)?)(?P<unit>分|%)?(?![\d.])")


def _group_tables(
    fragments: tuple[LocatedFragment, ...],
) -> dict[tuple[str, int | None, int], list[LocatedFragment]]:
    groups: dict[tuple[str, int | None, int], list[LocatedFragment]] = defaultdict(list)
    for located in fragments:
        fragment = located.fragment
        if fragment.kind == "table_cell" and fragment.table is not None:
            groups[(located.document.document_version_ref, fragment.page, fragment.table)].append(
                located
            )
    return groups


def _score(text: str, header_has_points: bool) -> tuple[Decimal, str] | None:
    found = list(_NUMBER.finditer(text))
    if len(found) != 1:
        return None
    match = found[0]
    unit = match.group("unit") or ("分" if header_has_points else "")
    if not unit:
        return None
    try:
        return Decimal(match.group("value")), unit
    except InvalidOperation:
        return None


def _evaluate_table(cells: list[LocatedFragment]) -> tuple[RuleMatch | None, str | None]:
    rows: dict[int, dict[int, LocatedFragment]] = defaultdict(dict)
    for item in cells:
        fragment = item.fragment
        assert fragment.row is not None and fragment.column is not None
        if fragment.column in rows[fragment.row]:
            return None, "ambiguous_score_table"
        rows[fragment.row][fragment.column] = item
    if not rows or sorted(rows) != list(range(max(rows) + 1)):
        return None, "unsupported_score_table"
    widths = {len(row) for row in rows.values()}
    if len(widths) != 1 or not widths or next(iter(widths)) < 2:
        return None, "unsupported_score_table"
    width = next(iter(widths))
    if any(sorted(row) != list(range(width)) for row in rows.values()):
        return None, "unsupported_score_table"
    header = rows[0]
    score_columns = [
        column for column, item in header.items() if _SCORE_HEADER.search(item.fragment.text)
    ]
    if len(score_columns) != 1:
        return None, "unsupported_score_table"
    score_column = score_columns[0]
    header_has_points = bool(
        re.search(r"分值|分数|最高分|满分|得分", header[score_column].fragment.text)
    )

    totals: list[tuple[LocatedFragment, Decimal, str, int]] = []
    components: list[tuple[LocatedFragment, Decimal, str, int]] = []
    for row_index in range(1, len(rows)):
        row = rows[row_index]
        label_cells = [item for item in row.values() if _TOTAL_LABEL.search(item.fragment.text)]
        score = _score(row[score_column].fragment.text, header_has_points)
        if label_cells:
            if score is None:
                return None, "unsupported_score_table"
            totals.append((row[score_column], score[0], score[1], row_index))
        else:
            if score is None:
                return None, "unsupported_score_table"
            components.append((row[score_column], score[0], score[1], row_index))
    if len(totals) != 1 or not components or len(components) > 19:
        return None, "ambiguous_score_table" if len(totals) > 1 else "unsupported_score_table"
    total_cell, expected_total, total_unit, _ = totals[0]
    if any(unit != total_unit for _, _, unit, _ in components):
        return None, "unsupported_score_table"
    actual_total = sum((value for _, value, _, _ in components), Decimal(0))
    if actual_total == expected_total:
        return None, None
    source_cells = tuple(item for item, _, _, _ in components) + (total_cell,)
    return (
        RuleMatch(
            rule_id=RULES[0].rule_id,
            problem_key=f"score-total-{actual_total}-versus-{expected_total}-{total_unit}",
            reason=(
                f"评分表明示总分为{expected_total}{total_unit}，"
                f"完整分项合计为{actual_total}{total_unit}。" + RULES[0].explanation_template
            ),
            sources=source_cells,
        ),
        None,
    )


def scan(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    matches: list[RuleMatch] = []
    incomplete_reasons: list[Literal["unsupported_score_table", "ambiguous_score_table"]] = []
    by_document: dict[str, list[LocatedFragment]] = defaultdict(list)
    for item in fragments:
        by_document[item.document.document_version_ref].append(item)
    if not any(_SIGNAL.search(item.fragment.text) for item in fragments):
        return SkillScan((), "not_applicable")
    for items in by_document.values():
        groups = _group_tables(tuple(items))
        signal = any(_SIGNAL.search(item.fragment.text) for item in items)
        if not groups:
            if signal:
                incomplete_reasons.append("unsupported_score_table")
            continue
        signaled_tables = [
            cells
            for cells in groups.values()
            if any(_SIGNAL.search(item.fragment.text) for item in cells)
        ]
        if len(signaled_tables) > 1:
            incomplete_reasons.append("ambiguous_score_table")
            continue
        matching_signals = bool(signaled_tables)
        for cells in signaled_tables:
            match, reason = _evaluate_table(cells)
            if reason == "ambiguous_score_table":
                incomplete_reasons.append("ambiguous_score_table")
            elif reason is not None:
                incomplete_reasons.append("unsupported_score_table")
            elif match:
                matches.append(match)
        if signal and not matching_signals:
            incomplete_reasons.append("unsupported_score_table")
    if incomplete_reasons:
        if "ambiguous_score_table" in incomplete_reasons:
            return SkillScan(tuple(matches), "incomplete", "ambiguous_score_table")
        return SkillScan(tuple(matches), "incomplete", "unsupported_score_table")
    return SkillScan(tuple(matches))
