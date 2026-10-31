"""Render the two submission reports from their Markdown sources."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent
MATERIALS = ROOT.parent
OUTPUT = ROOT
FONT = Path(r"C:\Windows\Fonts\Deng.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\Dengb.ttf")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("SubmissionSans", str(FONT)))
    pdfmetrics.registerFont(TTFont("SubmissionSansBold", str(FONT_BOLD)))


def styles():
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker", parent=base["Normal"], fontName="SubmissionSansBold", fontSize=10,
            leading=14, textColor=colors.HexColor("#9C6A2F"), alignment=TA_CENTER, spaceAfter=16,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Title"], fontName="SubmissionSansBold", fontSize=28,
            leading=38, textColor=colors.HexColor("#20323D"), alignment=TA_CENTER, spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle", parent=base["Normal"], fontName="SubmissionSans", fontSize=13,
            leading=22, textColor=colors.HexColor("#34495A"), alignment=TA_CENTER, spaceAfter=28,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], fontName="SubmissionSansBold", fontSize=21, wordWrap="CJK",
            leading=29, textColor=colors.HexColor("#20323D"), spaceAfter=13,
        ),
        "subheading": ParagraphStyle(
            "subheading", parent=base["Heading2"], fontName="SubmissionSansBold", fontSize=12,
            leading=18, textColor=colors.HexColor("#9C6A2F"), spaceBefore=8, spaceAfter=5, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="SubmissionSans", fontSize=10.2, wordWrap="CJK",
            leading=16.4, textColor=colors.HexColor("#20323D"), spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="SubmissionSans", fontSize=8.2,
            leading=12, textColor=colors.HexColor("#4D5D68"), spaceAfter=4,
        ),
        "table": ParagraphStyle(
            "table", parent=base["BodyText"], fontName="SubmissionSans", fontSize=8.6, wordWrap="CJK",
            leading=13.5, textColor=colors.HexColor("#20323D"),
        ),
        "table_head": ParagraphStyle(
            "table_head", parent=base["BodyText"], fontName="SubmissionSansBold", fontSize=8.6, wordWrap="CJK",
            leading=13.5, textColor=colors.HexColor("#20323D"),
        ),
    }


def is_subheading(line: str) -> bool:
    if line.startswith("图") or line.startswith("依据：") or "。" in line or "；" in line:
        return False
    return len(line) <= 28 and "|" not in line and not re.match(r"^\d{2} /", line)


def table_rows(lines: list[str], style) -> Table:
    rows = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.split("|")]
        paragraph_style = style["table_head"] if index == 0 else style["table"]
        rows.append([Paragraph(escape(cell), paragraph_style) for cell in cells])
    width = A4[0] - 100
    columns = len(rows[0])
    ratios = ([.19, .81] if rows[0][0].getPlainText() == "版本" else [.3, .7]) if columns == 2 else [.22, .40, .38]
    col_widths = [width * ratio for ratio in ratios]
    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1EB")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#DFE2E3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.white]),
            ]
        )
    )
    return table


class ScreenshotDetail(Flowable):
    def __init__(self, filename, rect, max_height):
        super().__init__()
        self.filename = str(MATERIALS / filename)
        self.rect = rect
        image = Image(self.filename)
        self.image_width, self.image_height = image.imageWidth, image.imageHeight
        self.scale = min((A4[0] - 100) / rect[2], max_height / rect[3])
        self.width, self.height = rect[2] * self.scale, rect[3] * self.scale
        self.hAlign = "CENTER"

    def draw(self):
        x, y, width, height = self.rect
        self.canv.saveState()
        clip = self.canv.beginPath()
        clip.rect(0, 0, self.width, self.height)
        self.canv.clipPath(clip, stroke=0)
        self.canv.drawImage(self.filename, -x * self.scale,
                           (y + height - self.image_height) * self.scale,
                           width=self.image_width * self.scale,
                           height=self.image_height * self.scale)
        self.canv.restoreState()


def add_figure(story, filename, caption, style, rect=None, max_height=450):
    path = MATERIALS / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    if rect:
        graphic = ScreenshotDetail(filename, rect, max_height)
    else:
        graphic = Image(str(path))
        scale = min((A4[0] - 100) / graphic.imageWidth, max_height / graphic.imageHeight)
        graphic.drawWidth = graphic.imageWidth * scale
        graphic.drawHeight = graphic.imageHeight * scale
    items = [Spacer(1, 8), graphic, Spacer(1, 8)]
    if caption:
        items.append(Paragraph(escape(caption), style["small"]))
    story.append(KeepTogether(items))


FIGURES = {
    "03": ("diagrams/agent-runtime.png", None, 450),
    "04": ("diagrams/agent-tool-map.png", None, 310),
    "05": ("images/04-anomaly-evidence.png", (310, 440, 1085, 540), 295),
    "06": ("images/05-subscription-evidence.png", (450, 185, 540, 625), 390),
    "07": ("images/11-transfer-confirmation.png", (410, 115, 620, 770), 440),
    "08": ("images/12-workflow-complete.png", (310, 285, 1080, 710), 335),
}


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D9DFE2"))
    canvas.line(50, 41, A4[0] - 50, 41)
    canvas.setFillColor(colors.HexColor("#5B6970"))
    canvas.setFont("SubmissionSans", 8)
    canvas.drawString(50, 27, "AI-Banking  |  本地模拟环境  |  竞赛提交版 v1.2")
    canvas.drawRightString(A4[0] - 50, 27, str(doc.page))
    canvas.restoreState()


def render(source_name: str, output_name: str, title: str, subtitle: str) -> None:
    style = styles()
    source = (ROOT / source_name).read_text(encoding="utf-8")
    sections = [part.strip() for part in source.split("\n---\n") if part.strip()]
    output = OUTPUT / output_name
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=50, rightMargin=50,
        topMargin=48, bottomMargin=58, title=title, author="AI-Banking 项目",
    )
    story = []
    for section_index, section in enumerate(sections):
        lines = [line.strip() for line in section.splitlines()]
        if section_index == 0:
            nonempty = [line for line in lines if line]
            story.extend(
                [
                    Spacer(1, 58),
                    Paragraph(nonempty[0], style["small"]),
                    Paragraph(title, style["cover_title"]),
                    Paragraph(subtitle, style["subheading"]),
                    Spacer(1, 22),
                    Paragraph(escape(nonempty[3]), style["body"]),
                    Spacer(1, 18),
                ]
            )
            metadata = [line for line in nonempty[3:] if "|" in line]
            if metadata:
                story.append(table_rows(metadata, style))
            guide_index = nonempty.index("阅读导引")
            story.append(Paragraph("阅读导引", style["subheading"]))
            story.append(Paragraph(escape(nonempty[guide_index + 1]), style["small"]))
            story.append(PageBreak())
            continue

        section_number = ""
        section_title = ""
        for line in lines:
            if re.match(r"^\d{2} /", line):
                section_number = line[:2]
                section_title = line
                break
        if section_title:
            story.append(Paragraph(section_title, style["section"]))
        technical = source_name == "technical-document-source.md"
        if (technical and section_number == "10") or (not technical and section_number == "06"):
            style["body"] = ParagraphStyle("compact_body", parent=style["body"], fontSize=9.3, leading=14.5)
            style["table"] = ParagraphStyle("compact_table", parent=style["table"], fontSize=8, leading=12)
            style["table_head"] = ParagraphStyle("compact_head", parent=style["table_head"], fontSize=8, leading=12)
        if technical and section_number == "04":
            filename, rect, height = FIGURES[section_number]
            add_figure(story, filename, "", style, rect, height)
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line or line == section_title:
                index += 1
                continue
            if "|" in line:
                group = []
                while index < len(lines) and "|" in lines[index]:
                    group.append(lines[index])
                    index += 1
                story.append(table_rows(group, style))
                story.append(Spacer(1, 3 * mm))
                continue
            if technical and line.startswith("图") and section_number in FIGURES:
                filename, rect, height = FIGURES[section_number]
                add_figure(story, filename, line, style, rect, height)
                index += 1
                continue
            if technical and line == "什么时候压缩？":
                story.append(Paragraph(line, style["subheading"]))
                add_figure(story, "diagrams/context-routing.png", "", style, max_height=123)
                index += 1
                continue
            if is_subheading(line):
                story.append(Paragraph(line, style["subheading"]))
            else:
                story.append(Paragraph(escape(line), style["body"]))
            index += 1
        if section_index < len(sections) - 1:
            story.append(PageBreak())
    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


if __name__ == "__main__":
    register_fonts()
    render(
        "technical-document-source.md",
        "technical-document.pdf",
        "技术文档",
        "让金融意图有依据，让每次执行有边界",
    )
    render(
        "security-self-assessment-source.md",
        "security-self-assessment.pdf",
        "安全自评报告",
        "权限分级、资金约束与已知风险",
    )
