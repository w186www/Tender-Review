"""Procedure skill: one unambiguous tender and opening time pair."""

import re
from datetime import datetime

from bidding_compliance.domain.rules.models import (
    LocatedFragment,
    RuleDefinition,
    RuleMatch,
    RuleReference,
    SkillDefinition,
    SkillScan,
)

DEFINITION = SkillDefinition(
    skill_id="procedure_review",
    skill_version="1.0.0",
    category="procedure",
    rules=(RuleReference(rule_id="TASK0007.PROCEDURE.TENDER-TIME", rule_version="1.0.0"),),
)
RULES = (
    RuleDefinition(
        rule_id="TASK0007.PROCEDURE.TENDER-TIME",
        rule_version="1.0.0",
        category="procedure",
        check_id="tender_time_order",
        applicability="document_timeline",
        explanation_template="同一文档中唯一一组投标截止与开标时间顺序矛盾；该结果仅为待复核候选。",
        equivalence_group="procedure:tender-opening-order",
    ),
)
_EVENT = re.compile(r"(?P<kind>投标(?:文件)?(?:递交)?截止(?:时间)?|递交截止时间|开标(?:时间|日期))")
_MULTI_ROUND = re.compile(r"第[一二三四五六七八九十\d]+(?:轮|次)|多轮|分阶段开标|二次报价")
_TIMESTAMP = re.compile(
    r"(?P<date>20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})"
    r"\s*(?P<time>\d{1,2}:\d{2})"
    r"\s*(?P<zone>北京时间|UTC[+-]\d{2}:?\d{2})?"
)


def _parse_time(text: str, start: int) -> tuple[datetime, str | None] | None:
    separator = re.match(r"\s*[：:]?\s*", text[start:])
    timestamp_start = start + (separator.end() if separator else 0)
    match = _TIMESTAMP.match(text, timestamp_start)
    if match is None:
        return None
    raw_date = match.group("date")
    try:
        if "年" in raw_date:
            day = datetime.strptime(raw_date, "%Y年%m月%d日").date()
        else:
            day = datetime.strptime(raw_date.replace("/", "-").replace(".", "-"), "%Y-%m-%d").date()
        hour, minute = (int(part) for part in match.group("time").split(":"))
        value = datetime(day.year, day.month, day.day, hour, minute)
    except ValueError:
        return None
    zone = match.group("zone")
    if zone and zone.startswith("UTC"):
        offset = zone[3:].replace(":", "")
        hours, minutes = int(offset[1:3]), int(offset[3:5])
        if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
            return None
    return value, zone


def _scan_document(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    cutoffs: list[tuple[LocatedFragment, datetime, str | None]] = []
    openings: list[tuple[LocatedFragment, datetime, str | None]] = []
    saw_event = False
    for item in fragments:
        text = item.fragment.text
        if _MULTI_ROUND.search(text):
            return SkillScan((), "incomplete", "ambiguous_tender_times")
        for event in _EVENT.finditer(text):
            saw_event = True
            timestamp = _parse_time(text, event.end())
            if timestamp is None:
                return SkillScan((), "incomplete", "ambiguous_tender_times")
            value, zone = timestamp
            target = cutoffs if "截止" in event.group("kind") else openings
            target.append((item, value, zone))
    if not saw_event:
        return SkillScan((), "not_applicable")
    if len(cutoffs) != 1 or len(openings) != 1:
        return SkillScan((), "incomplete", "ambiguous_tender_times")
    cutoff, opening = cutoffs[0], openings[0]
    if cutoff[2] is None or opening[2] is None:
        return SkillScan((), "incomplete", "missing_timezone")
    if cutoff[2] != opening[2]:
        return SkillScan((), "incomplete", "inconsistent_timezones")
    if opening[1] >= cutoff[1]:
        return SkillScan(())
    return SkillScan(
        (
            RuleMatch(
                rule_id=RULES[0].rule_id,
                problem_key="opening-precedes-tender-deadline",
                reason=(
                    f"投标截止为{cutoff[1].isoformat(timespec='minutes')}，"
                    f"开标为{opening[1].isoformat(timespec='minutes')}。"
                    + RULES[0].explanation_template
                ),
                sources=(cutoff[0], opening[0]),
            ),
        )
    )


def scan(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    by_document: dict[str, list[LocatedFragment]] = {}
    for item in fragments:
        by_document.setdefault(item.document.document_version_ref, []).append(item)
    results = [_scan_document(tuple(items)) for items in by_document.values()]
    matches = tuple(match for result in results for match in result.matches)
    incomplete = [result for result in results if result.status == "incomplete"]
    if incomplete:
        reason = next(
            (item.reason for item in incomplete if item.reason == "ambiguous_tender_times"),
            incomplete[0].reason,
        )
        return SkillScan(matches, "incomplete", reason)
    if results and all(result.status == "not_applicable" for result in results):
        return SkillScan(matches, "not_applicable")
    return SkillScan(matches)
