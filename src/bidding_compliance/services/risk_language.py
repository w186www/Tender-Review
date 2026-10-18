"""Keep unverified model prose within the independently computed evidence boundary."""

import re

_LEGAL_ASSERTION = re.compile(r"违反|违法|违规|不合法|不合规|依法应|依据[^。；\n]{0,40}第.{1,12}条")


def unverified_risk_text(text: str) -> str:
    """Remove unsupported legal assertions without transforming original citations."""
    sentences = re.split(r"(?<=[。；！？\n])", text)
    safe = [
        "该法律判断缺少有效法规支持，需人工核验。" if _LEGAL_ASSERTION.search(part) else part
        for part in sentences
        if part
    ]
    return "".join(dict.fromkeys(safe)) or "需人工核验原文及适用法规。"
