"""Reproduce the reviewed ordinance text from the pinned official HTML snapshot."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://xzfg.moj.gov.cn/front/law/detail?LawID=339&Query="


class Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.parts: list[str] = []
        self.lines: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "h2"}:
            self.active = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "h2"} and self.active:
            line = "".join(self.parts).strip()
            if line:
                self.lines.append(line)
            self.active = False


def extract(snapshot: bytes) -> str:
    html = snapshot.decode("utf-8")
    marker = '<div class="law-chapter">'
    if html.count(marker) != 1:
        raise ValueError("official page structure changed")
    body = html.split(marker, 1)[1].split("</main>", 1)[0]
    parser = Paragraphs()
    parser.feed(body)
    text = "\n".join(parser.lines)
    if "第三次修订" not in text or "第八十四条" not in text:
        raise ValueError("incomplete source snapshot")
    header = (
        "法规名称：中华人民共和国招标投标法实施条例\n"
        "版本说明：2019年第三次修订\n"
        f"来源：{SOURCE}\n抓取日期：2026-10-14\n" + "-" * 60 + "\n"
    )
    return header + text + "\n"


if __name__ == "__main__":
    raw = (ROOT / "knowledge/legal/snapshots/ordinance-2019.html").read_bytes()
    target = ROOT / "knowledge/legal/versions/中华人民共和国招标投标法实施条例-2019.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(extract(raw), encoding="utf-8", newline="\n")
