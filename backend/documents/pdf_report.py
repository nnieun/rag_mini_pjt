import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


REPORT_DIR = Path(__file__).resolve().parents[1] / "generated_reports"
# 한글 글리프가 있는 글꼴을 먼저 찾는다. RAG_PDF_FONT로 직접 지정할 수 있다.
FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


_FONT_PATH: Path | None = None


def has_korean_font() -> bool:
    """True when the registered report font is not the DejaVu fallback (no Hangul)."""
    _font_name()
    return _FONT_PATH is not None and "dejavu" not in _FONT_PATH.name.lower()


def _font_name() -> str:
    global _FONT_PATH
    name = "LawReportFont"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    configured = os.getenv("RAG_PDF_FONT")
    candidates = ((Path(configured),) if configured else ()) + FONT_CANDIDATES
    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix.lower() == ".ttc":
                pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception:
            continue
        _FONT_PATH = path
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


HIGH_IMPACT_LABEL = {"yes": "해당", "no": "해당 없음", "uncertain": "판단 보류"}
REVIEW_LABEL = {
    "approved": "승인됨",
    "rejected": "반려됨",
    "not_required": "검토 불필요",
    None: "검토 대기",
}


def _cell(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), style)


def _table(rows: list[list[Any]], widths: list[float], style: ParagraphStyle, header: ParagraphStyle) -> Table:
    data = [[_cell(value, header) for value in rows[0]]] + [
        [_cell(value, style) for value in row] for row in rows[1:]
    ]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa5b1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _source_label(document: dict) -> str:
    return " ".join(
        str(document.get(key) or "") for key in ("article", "paragraph", "item", "subitem")
    ).strip()


def create_compliance_pdf(
    *,
    service_name: str,
    assessment: dict[str, Any],
    sources: dict[str, dict],
    categories: dict[str, str],
    review: dict[str, Any] | None = None,
    run_id: str = "",
) -> tuple[Path, str]:
    """AI 기본법 준수 점검 보고서.

    목별 판단표(제2조제4호 가~카), 의무 체크리스트, 인용 조문 원문, 가정과
    "법률 자문 아님" 고지를 담는다. `assessment`는 ComplianceAssessment.model_dump().
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"compliance-report-{uuid4().hex}.pdf"
    path = REPORT_DIR / filename
    font = _font_name()
    body = ParagraphStyle("Body", fontName=font, fontSize=10, leading=15)
    cell = ParagraphStyle("Cell", fontName=font, fontSize=8.5, leading=12)
    header = ParagraphStyle("Header", fontName=font, fontSize=8.5, leading=12)
    h1 = ParagraphStyle("H1", fontName=font, fontSize=17, leading=23)
    h2 = ParagraphStyle("H2", fontName=font, fontSize=12.5, leading=18, spaceBefore=6)
    small = ParagraphStyle("Small", fontName=font, fontSize=8, leading=12)
    width = A4[0] - 36 * mm

    review = review or {}
    selected = set(assessment.get("high_impact_categories") or [])
    obligations = assessment.get("obligations") or []
    cited = [sid for item in obligations for sid in item.get("source_ids") or []]
    cited_ids = [sid for sid in dict.fromkeys(cited) if sid in sources]

    story: list[Any] = [
        Paragraph(escape(f"AI 기본법 준수 점검 보고서: {service_name or '서비스'}"), h1),
        Spacer(1, 4 * mm),
        _table(
            [
                ["항목", "결과"],
                ["고영향 인공지능", HIGH_IMPACT_LABEL.get(assessment.get("high_impact"), "-")],
                ["해당 목(제2조제4호)", ", ".join(f"{c}목" for c in sorted(selected)) or "-"],
                ["생성형 인공지능", "예" if assessment.get("is_generative") else "아니오"],
                ["판단 신뢰도", f"{float(assessment.get('confidence') or 0):.2f}"],
                ["사람 검토", REVIEW_LABEL.get(review.get("status"), review.get("status") or "검토 대기")
                 + (f" ({review.get('reviewer')})" if review.get("reviewer") else "")],
            ],
            [width * 0.32, width * 0.68], cell, header,
        ),
    ]
    if assessment.get("summary"):
        story += [Spacer(1, 3 * mm), Paragraph(escape(assessment["summary"]), body)]

    story += [
        Spacer(1, 5 * mm),
        Paragraph("1. 고영향 인공지능 영역 판단 (제2조제4호)", h2),
        _table(
            [["목", "영역", "판단"]]
            + [[f"{key}목", label, "해당" if key in selected else "-"] for key, label in categories.items()],
            [width * 0.08, width * 0.74, width * 0.18], cell, header,
        ),
        Spacer(1, 5 * mm),
        Paragraph("2. 의무 체크리스트", h2),
        _table(
            [["", "조문", "의무", "해당 여부", "해야 할 일", "근거"]]
            + [
                [
                    "[ ]" if item.get("applies") in {"해당", "해당 가능"} else "",
                    item.get("article", ""),
                    item.get("title", ""),
                    item.get("applies", ""),
                    "\n".join(item.get("actions") or []) or item.get("reason", ""),
                    ", ".join(item.get("source_ids") or []),
                ]
                for item in obligations
            ],
            [width * 0.05, width * 0.14, width * 0.25, width * 0.12, width * 0.34, width * 0.10],
            cell, header,
        ),
        Spacer(1, 5 * mm),
        Paragraph("3. 인용 조문", h2),
    ]
    if cited_ids:
        for sid in cited_ids:
            document = sources[sid]
            content = re.sub(r"\s+", " ", str(document.get("content") or ""))[:1200]
            story.append(
                Paragraph(
                    f"<b>[{escape(sid)}] {escape(_source_label(document))}</b> "
                    f"{escape(str(document.get('title') or ''))}<br/>{escape(content)}",
                    cell,
                )
            )
            story.append(Spacer(1, 2 * mm))
    else:
        story.append(Paragraph("인용된 조문 없음", body))

    if assessment.get("assumptions"):
        story += [
            Spacer(1, 4 * mm),
            Paragraph("4. 판단에 쓴 가정", h2),
            Paragraph("<br/>".join(f"- {escape(a)}" for a in assessment["assumptions"]), body),
        ]
    if review.get("comment"):
        story += [Spacer(1, 3 * mm), Paragraph(f"<b>검토 의견</b> {escape(review['comment'])}", body)]

    story += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            + (f" / 실행 ID: {escape(run_id)}" if run_id else "")
            + "<br/><b>법률 자문 아님.</b> "
            + escape(assessment.get("disclaimer") or "본 문서는 AI 기본법 원문 기반 자동 점검 결과이며 법률 자문을 대신하지 않습니다."),
            small,
        ),
    ]
    SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="AI 기본법 준수 점검 보고서",
    ).build(story)
    return path, f"/reports/{filename}"
