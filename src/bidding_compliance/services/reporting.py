"""Render structured immutable review results into Chinese Word and PDF reports."""

from __future__ import annotations

from io import BytesIO
from typing import Any


def _text(value: object, default: str = "未提供") -> str:
    return value if isinstance(value, str) and value.strip() else default


def render_docx(report: dict[str, Any]) -> bytes:
    from docx import Document as WordDocument
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    document = WordDocument()
    section = document.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.different_first_page_header_footer = False
    styles = document.styles
    for style_name in ("Normal", "Title", "Heading 1", "Heading 2"):
        style = styles[style_name]
        style.font.name = "宋体"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        style.font.size = Pt(10 if style_name == "Normal" else 16 if style_name == "Title" else 12)
    header = section.header.paragraphs[0]
    header.text = "招标文件智能合规审查报告"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"报告 {report['report_id']}  |  结果 {report['result_id']}  |  第 ")
    _word_field(footer, "PAGE")
    footer.add_run(" 页")

    title = document.add_heading("招标文件合规审查报告", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in (
        ("项目", _text(report.get("project_name"), report["project_id"])),
        ("审查任务", report["review_task_id"]),
        ("结果版本", report["result_id"]),
        ("执行批次", report["run_id"]),
        ("输入快照", report["snapshot_hash"]),
        ("报告版本", report["report_id"]),
        ("生成时间（UTC）", report["generated_at"]),
    ):
        row = table.add_row()
        row.cells[0].text, row.cells[1].text = label, str(value)
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    document.add_heading("一、审查范围与说明", level=1)
    document.add_paragraph(
        "本报告依据已发布的不可变审查结果快照生成。报告记录候选风险、可核验的证据状态及人工复核决定。"
        "系统当前未批准规则与法规条款的充分支持绑定，证据状态最高为 suspected；"
        "本报告不构成法律意见，"
        "不替代采购人及专业人员的审查责任。"
    )
    snapshot = report.get("input_snapshot", {})
    document.add_paragraph("被审查文档版本：")
    docs = snapshot.get("documents", [])
    if docs:
        for item in docs:
            document.add_paragraph(
                f"文档 {item['document_id']}，SHA-256 {item['raw_source_sha256']}，"
                f"解析版本 {item['parse_version']}，上下文版本 {item['context_version']}。",
                style="List Bullet",
            )
    else:
        document.add_paragraph("快照没有文档清单。")

    findings = report["findings"]
    document.add_heading("二、风险汇总", level=1)
    rejected = sum(item["review_status"] == "rejected" for item in findings)
    accepted = sum(item["review_status"] == "accepted" for item in findings)
    modified = sum(item["review_status"] == "modified" for item in findings)
    document.add_paragraph(
        f"风险条目 {len(findings)} 项；接受 {accepted} 项，修改 {modified} 项，驳回 {rejected} 项。"
        "驳回项目不计入已接受风险。"
    )
    summary = document.add_table(rows=1, cols=4)
    summary.style = "Table Grid"
    for cell, label in zip(summary.rows[0].cells, ("类别", "条目", "接受", "驳回"), strict=True):
        cell.text = label
    categories = ("qualification", "technical", "evaluation", "contract", "procedure")
    category_names = {
        "qualification": "资格审查",
        "technical": "技术要求",
        "evaluation": "评标办法",
        "contract": "合同条款",
        "procedure": "招标程序",
    }
    for category in categories:
        rows = [item for item in findings if item["category"] == category]
        row = summary.add_row()
        for cell, value in zip(
            row.cells,
            (
                category_names[category],
                str(len(rows)),
                str(sum(item["review_status"] == "accepted" for item in rows)),
                str(sum(item["review_status"] == "rejected" for item in rows)),
            ),
            strict=True,
        ):
            cell.text = value

    document.add_heading("三、风险及复核明细", level=1)
    if not findings:
        document.add_paragraph("本次审查未发现候选风险；该表述仅对应此任务与输入快照。")
    for index, finding in enumerate(findings, start=1):
        document.add_heading(f"{index}. {finding['title']}", level=2)
        document.add_paragraph(
            f"类别：{category_names[finding['category']]}　严重程度：{finding['severity']}"
        )
        document.add_paragraph(f"描述：{finding['description']}")
        document.add_paragraph(
            f"证据状态：{finding['evidence_status']}（独立 Evidence Checker 结果）"
        )
        document.add_paragraph(f"人工复核：{finding['review_status']}")
        review = finding.get("human_review", {})
        if review:
            document.add_paragraph(
                f"复核人：{review['reviewer_id']}　时间：{review['decided_at']}\n"
                f"理由：{review['reason']}"
            )
        document.add_paragraph(f"调整建议：{finding['recommendation']}")
        for cite in finding["citations"]:
            location = cite.get("page")
            page_label = f"第 {location} 页" if location is not None else "原文无可靠页码"
            document.add_paragraph(
                f"原文证据：文档 {cite['document_id']}，版本 {cite['raw_source_sha256']}，"
                f"{page_label}，定位 {cite['locator']}，"
                f"片段 {cite['section_id']}@{cite['section_revision']}。"
            )
            document.add_paragraph(f"“{cite['quote']}”")
        laws = [
            item
            for item in finding.get("evidence", [])
            if item.get("kind") in {"law", "policy", "internal_rule"}
        ]
        if laws:
            for law in laws:
                reference = f"{law.get('title', '法规证据')} {law.get('article') or '条款未提供'}"
                document.add_paragraph(
                    f"法规或规则证据：{reference}；状态 {law['version_status']}。"
                )
                document.add_paragraph(f"“{law['quote']}”")
        else:
            document.add_paragraph("法规或规则证据：本条结果未包含可引用的法规条款，不补造条文。")
    document.add_heading("四、限制与免责声明", level=1)
    document.add_paragraph(
        "报告只呈现指定不可变结果版本。证据不足或规则关联未批准时，不得据此认定确定性法律违规；"
        "原文页码仅在解析数据提供且已校验时显示。报告不含伪造签名或审批效力。"
    )
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _word_field(paragraph: Any, name: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = name
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, instruction, end))


def render_pdf(report: dict[str, Any]) -> bytes:
    from reportlab.lib import colors  # type: ignore[import-untyped]
    from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.lib.units import mm  # type: ignore[import-untyped]
    from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "CJKTitle",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=18,
            leading=24,
            alignment=1,
        )
    )
    styles.add(
        ParagraphStyle(
            "CJKHeading",
            parent=styles["Heading2"],
            fontName="STSong-Light",
            fontSize=12,
            leading=18,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            "CJKBody",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=9,
            leading=14,
            wordWrap="CJK",
        )
    )

    def para(value: object, style: str = "CJKBody") -> Paragraph:
        from xml.sax.saxutils import escape

        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    story: list[Any] = [para("招标文件合规审查报告", "CJKTitle"), Spacer(1, 8)]
    meta = [
        [para("项目"), para(_text(report.get("project_name"), report["project_id"]))],
        [para("审查任务 / 结果版本"), para(f"{report['review_task_id']} / {report['result_id']}")],
        [para("运行 / 输入快照"), para(f"{report['run_id']} / {report['snapshot_hash']}")],
        [
            para("报告版本 / 生成时间 UTC"),
            para(f"{report['report_id']} / {report['generated_at']}"),
        ],
    ]
    table = Table(meta, colWidths=(42 * mm, 128 * mm), repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([table, Spacer(1, 10), para("一、审查说明", "CJKHeading")])
    story.append(
        para(
            "本报告依据已发布的不可变结果快照生成。规则与法规条款的充分支持绑定尚未批准，"
            "证据状态最高为 suspected。本报告不构成法律意见。"
        )
    )
    story.append(para("二、风险汇总", "CJKHeading"))
    findings = report["findings"]
    counts = [
        sum(item["review_status"] == status for item in findings)
        for status in ("accepted", "modified", "rejected")
    ]
    story.append(
        para(
            f"共 {len(findings)} 项；接受 {counts[0]} 项，修改 {counts[1]} 项，"
            f"驳回 {counts[2]} 项。"
            "驳回项目不计入已接受风险。"
        )
    )
    labels = {
        "qualification": "资格审查",
        "technical": "技术要求",
        "evaluation": "评标办法",
        "contract": "合同条款",
        "procedure": "招标程序",
    }
    summary_rows = [[para("类别"), para("条目"), para("接受"), para("驳回")]]
    for category, name in labels.items():
        rows = [item for item in findings if item["category"] == category]
        summary_rows.append(
            [
                para(name),
                para(len(rows)),
                para(sum(x["review_status"] == "accepted" for x in rows)),
                para(sum(x["review_status"] == "rejected" for x in rows)),
            ]
        )
    summary = Table(summary_rows, colWidths=(90 * mm, 30 * mm, 25 * mm, 25 * mm), repeatRows=1)
    summary.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.extend([summary, Spacer(1, 10), para("三、风险及复核明细", "CJKHeading")])
    if not findings:
        story.append(para("本次审查未发现候选风险；该表述仅对应此任务与输入快照。"))
    for index, item in enumerate(findings, 1):
        story.append(para(f"{index}. {item['title']}", "CJKHeading"))
        story.append(
            para(
                f"类别：{labels[item['category']]}；严重程度：{item['severity']}；证据状态：{item['evidence_status']}；人工复核：{item['review_status']}"
            )
        )
        story.append(para(f"描述：{item['description']}"))
        review = item.get("human_review", {})
        if review:
            story.append(
                para(
                    f"复核人：{review['reviewer_id']}；时间：{review['decided_at']}；理由：{review['reason']}"
                )
            )
        story.append(para(f"调整建议：{item['recommendation']}"))
        for cite in item["citations"]:
            page = f"第 {cite['page']} 页" if cite.get("page") is not None else "原文无可靠页码"
            story.append(
                para(
                    f"原文定位：文档 {cite['document_id']}，SHA-256 {cite['raw_source_sha256']}，"
                    f"{page}，{cite['locator']}，片段 "
                    f"{cite['section_id']}@{cite['section_revision']}。"
                )
            )
            story.append(para(f"原文摘录：{cite['quote']}"))
        laws = [
            e
            for e in item.get("evidence", [])
            if e.get("kind") in {"law", "policy", "internal_rule"}
        ]
        if laws:
            for law in laws:
                story.append(
                    para(
                        f"法规/规则：{law.get('title', '证据')} "
                        f"{law.get('article') or '条款未提供'}；状态 {law['version_status']}。"
                    )
                )
                story.append(para(law["quote"]))
        else:
            story.append(para("法规或规则证据：未提供可引用条款，不补造条文。"))
    story.extend(
        [
            para("四、限制与免责声明", "CJKHeading"),
            para(
                "本报告仅呈现指定结果版本。证据不足或规则关联未批准时，不得据此认定确定性法律违规。报告不含伪造签名或审批效力。"
            ),
        ]
    )
    buffer = BytesIO()

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.drawCentredString(
            A4[0] / 2,
            10 * mm,
            f"报告 {report['report_id']}  |  结果 {report['result_id']}  |  {document.page}",
        )
        canvas.restoreState()

    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="招标文件合规审查报告",
        author="招标文件智能合规审查系统",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
