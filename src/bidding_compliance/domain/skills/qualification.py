"""Qualification skill: explicit bidder-local-registration requirements only."""

import re

from bidding_compliance.domain.rules.models import (
    LocatedFragment,
    RuleDefinition,
    RuleMatch,
    RuleReference,
    SkillDefinition,
    SkillScan,
)

DEFINITION = SkillDefinition(
    skill_id="qualification_review",
    skill_version="1.0.0",
    category="qualification",
    rules=(RuleReference(rule_id="TASK0007.QUAL.LOCAL-REGISTRATION", rule_version="1.0.0"),),
)
RULES = (
    RuleDefinition(
        rule_id="TASK0007.QUAL.LOCAL-REGISTRATION",
        rule_version="1.0.0",
        category="qualification",
        check_id="local_registration_restriction",
        applicability="fragment",
        explanation_template="资格内容明确要求投标人/供应商在指定本地行政区域注册或设立分支机构，需复核其适用依据。",
        equivalence_group="qualification:local-registration",
    ),
)
_RESTRICTION = re.compile(r"本市|本地|当地|项目所在地|本行政区域")
_REGISTRATION = re.compile(r"注册|登记|设立分公司|设立分支机构")
_BIDDER = re.compile(r"投标人|供应商|申请人|响应人|承包人|投标单位")
_UNRESTRICTED = re.compile(
    r"不限(?:制)?(?:地区|地域|注册地)|不限制注册地|允许外地(?:企业|投标人)(?:参加|投标)|全国企业均可"
)
_SCOPE = re.compile(r"资格|资质|投标人条件")


def scan(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    if not any(
        _SCOPE.search(item.fragment.section) or _SCOPE.search(item.fragment.text)
        for item in fragments
    ):
        return SkillScan((), "not_applicable")
    rule = RULES[0]
    matches = []
    for located in fragments:
        fragment = located.fragment
        if not fragment.text.strip():
            continue
        if (
            _BIDDER.search(fragment.text)
            and _RESTRICTION.search(fragment.text)
            and _REGISTRATION.search(fragment.text)
            and not _UNRESTRICTED.search(fragment.text)
        ):
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    problem_key="local-registration-restriction",
                    reason=rule.explanation_template,
                    sources=(located,),
                )
            )
    return SkillScan(tuple(matches))
