"""Technical-parameter skill: explicit exclusive brand/model language."""

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
    skill_id="technical_review",
    skill_version="1.0.0",
    category="technical",
    rules=(RuleReference(rule_id="TASK0007.TECH.EXCLUSIVE-BRAND", rule_version="1.0.0"),),
)
RULES = (
    RuleDefinition(
        rule_id="TASK0007.TECH.EXCLUSIVE-BRAND",
        rule_version="1.0.0",
        category="technical",
        check_id="exclusive_brand_requirement",
        applicability="fragment",
        explanation_template="技术参数中出现明确排他品牌/型号措辞；请核验其必要性及是否允许等效替代。",
        equivalence_group="technical:exclusive-brand",
    ),
)
_EXCLUSIVE = re.compile(
    r"只接受|仅接受|仅限(?:使用)?|指定采用|必须采用|必须使用|不得采用其他|不接受其他"
)
_BRAND = re.compile(r"品牌|型号|产品")
_ALTERNATIVE = re.compile(r"仅供参考|允许同等|允许等效|可(?:以)?采用同等|接受等效|可用等效|可替代")
_SCOPE = re.compile(r"技术|参数|设备|产品|规格|品牌|型号")


def scan(fragments: tuple[LocatedFragment, ...]) -> SkillScan:
    if not any(
        _SCOPE.search(item.fragment.section) or _SCOPE.search(item.fragment.text)
        for item in fragments
    ):
        return SkillScan((), "not_applicable")
    rule = RULES[0]
    matches = []
    ambiguous = False
    for located in fragments:
        text = located.fragment.text
        if not text.strip():
            continue
        category_context = bool(
            re.search(r"技术|设备|产品|参数|规格|型号", located.fragment.section)
        )
        explicit_subject = bool(re.search(r"设备|产品|系统|材料|型号|品牌", text))
        exclusive = _EXCLUSIVE.search(text)
        brand = _BRAND.search(text)
        if not (exclusive and brand and (category_context or explicit_subject)):
            continue
        if _ALTERNATIVE.search(text):
            if exclusive and brand:
                ambiguous = True
            continue
        matches.append(
            RuleMatch(
                rule_id=rule.rule_id,
                problem_key="exclusive-brand-or-model",
                reason=rule.explanation_template,
                sources=(located,),
            )
        )
    if ambiguous:
        return SkillScan(tuple(matches), "incomplete", "ambiguous_technical_requirement")
    return SkillScan(tuple(matches))
