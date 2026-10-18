from datetime import datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


REPORT_DIR = Path(__file__).resolve().parents[1] / "generated_reports"
FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


def _font_name() -> str:
    for path in FONT_CANDIDATES:
        if path.exists():
            name = "LawReportFont"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
    return "Helvetica"


def create_answer_pdf(
    *,
    title: str,
    question: str,
    answer: str,
    source_articles: list[str],
    include_sources: bool = True,
) -> tuple[Path, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"law-report-{uuid4().hex}.pdf"
    path = REPORT_DIR / filename
    font = _font_name()
    body = ParagraphStyle("Body", fontName=font, fontSize=10.5, leading=17)
    heading = ParagraphStyle("Heading", fontName=font, fontSize=18, leading=24)
    small = ParagraphStyle("Small", fontName=font, fontSize=8.5, leading=13)
    story = [
        Paragraph(escape(title), heading),
        Spacer(1, 7 * mm),
        Paragraph(f"<b>질문</b><br/>{escape(question)}", body),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>답변</b><br/>{escape(answer).replace(chr(10), '<br/>')}", body),
    ]
    if include_sources:
        sources = ", ".join(dict.fromkeys(source_articles)) or "표시된 출처 없음"
        story.extend(
            [Spacer(1, 5 * mm), Paragraph(f"<b>관련 조문</b><br/>{escape(sources)}", body)]
        )
    story.extend(
        [
            Spacer(1, 9 * mm),
            Paragraph(
                f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}<br/>"
                "본 문서는 AI 기본법 원문 기반 안내이며 법률 자문을 대신하지 않습니다.",
                small,
            ),
        ]
    )
    SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    ).build(story)
    return path, f"/reports/{filename}"
