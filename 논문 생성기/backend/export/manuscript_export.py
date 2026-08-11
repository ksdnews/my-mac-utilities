"""
SCI 논문 생성기 — 원고를 Markdown / PDF로 내보내기 (DOCX는 docx_generator.py 담당)
한글(language="ko") PDF는 Noto Sans KR 서브셋 폰트를 임베드해 렌더링한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.export.docx_generator import SECTION_LABELS, NUMBERED_KEYS_EXCLUDED, _label_for

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from xml.sax.saxutils import escape as xml_escape

FONT_DIR = Path(__file__).parent / "fonts"
KOREAN_FONT_PATH = FONT_DIR / "NotoSansKR-Subset.ttf"
KOREAN_FONT_NAME = "NotoSansKR"

_korean_font_registered = False


def _ensure_korean_font() -> str:
    """Noto Sans KR 서브셋 폰트를 reportlab에 등록(최초 1회)하고 폰트 이름을 반환한다."""
    global _korean_font_registered
    if not _korean_font_registered:
        pdfmetrics.registerFont(TTFont(KOREAN_FONT_NAME, str(KOREAN_FONT_PATH)))
        _korean_font_registered = True
    return KOREAN_FONT_NAME


def _pdf_font(language: str) -> str:
    return _ensure_korean_font() if language == "ko" else "Times-Roman"


def _pdf_bold_font(language: str) -> str:
    # NotoSansKR-Subset.ttf는 서브셋이라 별도 Bold 웨이트가 없으므로 동일 폰트를 굵게 대체 표기(태그)로 사용
    return _ensure_korean_font() if language == "ko" else "Times-Bold"


# =============================================
# Markdown
# =============================================
def build_manuscript_markdown(draft: dict) -> str:
    is_ko = draft.get("language", "en") == "ko"
    lines: list[str] = []

    lines.append(f"# {draft.get('title') or ('제목 없음' if is_ko else 'Untitled Manuscript')}")
    lines.append("")

    keywords = draft.get("keywords") or []
    if keywords:
        label = "**주요어:**" if is_ko else "**Keywords:**"
        lines.append(f"{label} {', '.join(keywords)}")
        lines.append("")

    sections = draft.get("sections", {})
    section_order = draft.get("section_order") or list(sections.keys())
    missing_text = "*[NEEDS DATA: 이 섹션에 대해 생성된 내용이 없습니다]*" if is_ko else "*[NEEDS DATA: no content generated for this section]*"

    number = 1
    for key in section_order:
        label = _label_for(key)
        heading = f"## {label}" if key in NUMBERED_KEYS_EXCLUDED else f"## {number}. {label}"
        if key not in NUMBERED_KEYS_EXCLUDED:
            number += 1
        lines.append(heading)
        lines.append("")
        paragraphs = sections.get(key, [])
        if not paragraphs:
            lines.append(missing_text)
        else:
            for p in paragraphs:
                lines.append(p)
                lines.append("")
        lines.append("")

    lines.append("## References")
    lines.append("")
    reference_list = draft.get("reference_list") or []
    if not reference_list:
        lines.append("*[NEEDS DATA: 참고문헌이 제공되지 않았습니다]*" if is_ko else "*[NEEDS DATA: no references provided]*")
    else:
        for ref in reference_list:
            lines.append(f"- {ref}")

    return "\n".join(lines).strip() + "\n"


# =============================================
# PDF
# =============================================
def build_manuscript_pdf(draft: dict, output_path: str) -> None:
    language = draft.get("language", "en")
    is_ko = language == "ko"
    body_font = _pdf_font(language)
    bold_font = _pdf_bold_font(language)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
        title=draft.get("title") or "Manuscript",
    )

    title_style = ParagraphStyle(
        "Title", fontName=bold_font, fontSize=15, leading=20, alignment=TA_CENTER, spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "Heading", fontName=bold_font, fontSize=13, leading=18, spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", fontName=body_font, fontSize=12, leading=24,  # 2배 줄간격에 가깝게
        alignment=TA_JUSTIFY, spaceAfter=10, firstLineIndent=18,
    )
    meta_style = ParagraphStyle("Meta", fontName=body_font, fontSize=11, leading=16, spaceAfter=10)
    ref_style = ParagraphStyle(
        "Ref", fontName=body_font, fontSize=12, leading=20, spaceAfter=8,
        leftIndent=20, firstLineIndent=-20,
    )
    missing_style = ParagraphStyle("Missing", fontName=body_font, fontSize=12, leading=20, spaceAfter=10)

    def esc(text: str) -> str:
        return xml_escape(text or "")

    story = []
    story.append(Paragraph(esc(draft.get("title") or ("제목 없음" if is_ko else "Untitled Manuscript")), title_style))

    keywords = draft.get("keywords") or []
    if keywords:
        label = "주요어: " if is_ko else "Keywords: "
        story.append(Paragraph(f"<b>{label}</b>{esc(', '.join(keywords))}", meta_style))

    sections = draft.get("sections", {})
    section_order = draft.get("section_order") or list(sections.keys())
    missing_text = "[NEEDS DATA: 이 섹션에 대해 생성된 내용이 없습니다]" if is_ko else "[NEEDS DATA: no content generated for this section]"

    number = 1
    for key in section_order:
        label = _label_for(key)
        heading_text = label if key in NUMBERED_KEYS_EXCLUDED else f"{number}. {label}"
        if key not in NUMBERED_KEYS_EXCLUDED:
            number += 1
        story.append(Paragraph(esc(heading_text), heading_style))

        paragraphs = sections.get(key, [])
        if not paragraphs:
            story.append(Paragraph(f"<i>{esc(missing_text)}</i>", missing_style))
        else:
            for p in paragraphs:
                story.append(Paragraph(esc(p), body_style))

    story.append(Paragraph("References", heading_style))
    reference_list = draft.get("reference_list") or []
    if not reference_list:
        no_refs = "[NEEDS DATA: 참고문헌이 제공되지 않았습니다]" if is_ko else "[NEEDS DATA: no references provided]"
        story.append(Paragraph(f"<i>{esc(no_refs)}</i>", missing_style))
    else:
        for ref in reference_list:
            story.append(Paragraph(esc(ref), ref_style))

    doc.build(story)
