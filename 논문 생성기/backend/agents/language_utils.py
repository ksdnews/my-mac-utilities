"""
SCI 논문 생성기 — 출력 언어(영문/국문) 관련 공통 유틸리티
각 에이전트의 시스템 프롬프트에 언어 지침을 덧붙이는 데 사용한다. 나머지 콘텐츠 규칙(논리 구조,
근거 없는 내용 금지, 인용 규칙 등)은 언어와 무관하게 그대로 유지되므로 별도로 번역하지 않는다.
"""

EN_LANGUAGE_INSTRUCTION = (
    "\n\n[Output language] Write all natural-language content in formal academic English suitable for "
    "SCI(E) journal submission."
)

KO_LANGUAGE_INSTRUCTION = (
    "\n\n[Output language] Write all natural-language content — titles, prose paragraphs, summaries, "
    "review comments, questions, defenses — in formal, academic Korean (한국어), following the writing "
    "conventions of KCI(한국학술지인용색인)-indexed domestic Korean journals rather than SCI(E) "
    "international journals. Keep every JSON field name/key exactly as specified in the schema (in "
    "English) — only the field VALUES should be Korean text. When a technical/scientific term is more "
    "commonly recognized in English, give the Korean term first with the English term in parentheses at "
    "first use, e.g. \"수면 잠재기(sleep latency)\"."
)


def language_instruction(language: str) -> str:
    return KO_LANGUAGE_INSTRUCTION if language == "ko" else EN_LANGUAGE_INSTRUCTION


def resolve_language(paper_input: dict = None, draft: dict = None) -> str:
    """draft에 저장된 language를 우선하고, 없으면 paper_input(세션)의 language를 사용한다."""
    if draft and draft.get("language"):
        return draft["language"]
    if paper_input and paper_input.get("language"):
        return paper_input["language"]
    return "en"
