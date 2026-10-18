"""Keep unverified model prose within the independently computed evidence boundary."""

import re

_LEGAL_ASSERTION = re.compile(
    r"违反|违法|违规|不合法|不合规|依法应|"
    r"(?:依据|根据|按照)[^。；\n]{0,100}第.{1,12}条|法定|法律规定|法规要求"
)
_DETERMINISTIC_LEGAL_ASSERTION = re.compile(r"违反|违法|违规|不合法|不合规|依法应")


def unverified_risk_text(
    text: str,
    *,
    has_selected_reference: bool = False,
    selected_citations: tuple[tuple[str, str | None], ...] = (),
) -> str:
    """Remove unsupported legal assertions without transforming original citations."""
    sentences = re.split(r"(?<=[。；！？\n])", text)
    unsupported = (
        "该法律判断尚未确认适用，需结合原文和法规参考人工核验。"
        if has_selected_reference
        else "该法律判断缺少有效法规支持，需人工核验。"
    )
    safe = []
    for part in sentences:
        if not part:
            continue
        if not _LEGAL_ASSERTION.search(part):
            safe.append(part)
            continue
        compact = re.sub(r"\s+", "", part)
        cited_titles = set(re.findall(r"《([^》]+)》", compact))
        matches_selected = has_selected_reference and any(
            re.sub(r"\s+", "", title) in cited_titles
            and (article is None or re.sub(r"\s+", "", article) in compact)
            for title, article in selected_citations
            if title
        )
        if matches_selected and not _DETERMINISTIC_LEGAL_ASSERTION.search(part):
            safe.append("按项目采用的库内版本作条件性参考分析（适用性待人工确认）：" + part)
        else:
            safe.append(unsupported)
    return "".join(dict.fromkeys(safe)) or "需人工核验原文及适用法规。"
