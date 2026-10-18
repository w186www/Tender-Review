"""Contract skill: unfilled placeholders at named key-term locations."""

import re
from collections import defaultdict

from bidding_compliance.domain.rules.models import (
    LocatedFragment,
    RuleDefinition,
    RuleMatch,
    RuleReference,
    SkillDefinition,
    SkillScan,
)

DEFINITION = SkillDefinition(
    skill_id="contract_review",
    skill_version="1.1.0",
    category="contract",
    rules=(RuleReference(rule_id="TASK0007.CONTRACT.KEY-PLACEHOLDER", rule_version="1.1.0"),),
)
RULES = (
    RuleDefinition(
        rule_id="TASK0007.CONTRACT.KEY-PLACEHOLDER",
        rule_version="1.1.0",
        category="contract",
        check_id="contract_key_placeholder",
        applicability="fragment",
        explanation_template="合同关键字段包含未填写占位内容，需确认合同条款是否完整。",
        equivalence_group="contract:key-placeholder",
    ),
)
_KEY = re.compile(r"付款(?:期限|时间|方式)|结算方式|合同价款|违约(?:责任|条款)|履约保证金|质保期")
_PLACEHOLDER = re.compile(r"待定|待填写|待填|待补充|待协商|[_＿]{3,}|[□口]{2,}")
_PLACEHOLDER_ONLY = re.compile(
    r"^[\s【】\[\]()（）:：。；;,_＿□口-]*(?:待定|待填写|待填|待补充|待协商|[_＿]{3,}|[□口]{2,})[\s【】\[\]()（）:：。；;,_＿□口-]*$"
)
_SCOPE = re.compile(r"合同|协议")
_CONTRACT_START = re.compile(r"合同条款及格式|合同协议书|专用合同条款|通用合同条款")
_CONTRACT_END = re.compile(r"(?:第[一二三四五六七八九十]+章\s*)?投标文件格式|采购文件格式")


def _contract_pages(fragments: tuple[LocatedFragment, ...]) -> set[tuple[str, int]]:
    """Infer a PDF contract chapter from its explicit title through the next document chapter."""
    by_document: dict[str, list[LocatedFragment]] = defaultdict(list)
    for item in fragments:
        by_document[item.document.document_version_ref].append(item)
    scoped_pages: set[tuple[str, int]] = set()
    for document_ref, items in by_document.items():
        start_pages = [
            item.fragment.page
            for item in items
            if item.fragment.page is not None
            and (
                _CONTRACT_START.search(item.fragment.text)
                or _CONTRACT_START.search(item.fragment.section)
            )
        ]
        if not start_pages:
            continue
        start = min(start_pages)
        end_pages = [
            item.fragment.page
            for item in items
            if item.fragment.page is not None
            and item.fragment.page > start
            and (
                _CONTRACT_END.search(item.fragment.text)
                or _CONTRACT_END.search(item.fragment.section)
            )
        ]
        end = (
            min(end_pages) if end_pages else max(item.fragment.page or start for item in items) + 1
        )
        scoped_pages.update((document_ref, page) for page in range(start, end))
    return scoped_pages


def _in_scope(item: LocatedFragment, scoped_pages: set[tuple[str, int]]) -> bool:
    fragment = item.fragment
    return bool(
        _SCOPE.search(fragment.section)
        or _SCOPE.search(fragment.text)
        or (
            fragment.page is not None
            and (item.document.document_version_ref, fragment.page) in scoped_pages
        )
    )


def _table_groups(
    fragments: tuple[LocatedFragment, ...],
) -> dict[tuple[str, int | None, int, int], list[LocatedFragment]]:
    groups: dict[tuple[str, int | None, int, int], list[LocatedFragment]] = defaultdict(list)
    for item in fragments:
        fragment = item.fragment
        if (
            fragment.kind == "table_cell"
            and fragment.table is not None
            and fragment.row is not None
        ):
            groups[
                (
                    item.document.document_version_ref,
                    fragment.page,
                    fragment.table,
                    fragment.row,
                )
            ].append(item)
    return groups


def scan(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    scoped_pages = _contract_pages(fragments)
    if not any(_in_scope(item, scoped_pages) for item in fragments):
        return SkillScan((), "not_applicable")
    rule = RULES[0]
    matches: list[RuleMatch] = []
    consumed: set[tuple[str, str, str]] = set()
    for item in fragments:
        text = item.fragment.text.strip()
        if _in_scope(item, scoped_pages) and _KEY.search(text) and _PLACEHOLDER.search(text):
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    problem_key="key-contract-term-unfilled",
                    reason=rule.explanation_template,
                    sources=(item,),
                )
            )
            consumed.add(
                (item.document.document_version_ref, item.section_id, item.fragment.locator)
            )
    for cells in _table_groups(fragments).values():
        if len(cells) > 20:
            continue
        ordered = sorted(cells, key=lambda item: item.fragment.column or 0)
        for key_cell, value_cell in zip(ordered, ordered[1:], strict=False):
            if (
                key_cell.fragment.column is not None
                and value_cell.fragment.column == key_cell.fragment.column + 1
                and _in_scope(key_cell, scoped_pages)
                and _KEY.search(key_cell.fragment.text)
                and _PLACEHOLDER_ONLY.fullmatch(value_cell.fragment.text.strip())
                and (
                    key_cell.document.document_version_ref,
                    key_cell.section_id,
                    key_cell.fragment.locator,
                )
                not in consumed
                and (
                    value_cell.document.document_version_ref,
                    value_cell.section_id,
                    value_cell.fragment.locator,
                )
                not in consumed
            ):
                matches.append(
                    RuleMatch(
                        rule_id=rule.rule_id,
                        problem_key="key-contract-term-unfilled",
                        reason=(rule.explanation_template + "字段名与占位值位于同一表格行。"),
                        sources=(key_cell, value_cell),
                    )
                )
                consumed.update(
                    {
                        (
                            key_cell.document.document_version_ref,
                            key_cell.section_id,
                            key_cell.fragment.locator,
                        ),
                        (
                            value_cell.document.document_version_ref,
                            value_cell.section_id,
                            value_cell.fragment.locator,
                        ),
                    }
                )
    return SkillScan(tuple(matches))
