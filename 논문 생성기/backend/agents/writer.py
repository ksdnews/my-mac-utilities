"""
SCI 논문 생성기 — Phase 2(초안 작성) 에이전트: 집필가 + 인용 관리자
역할: 섹션별 본문 작성(집필가) / 참고문헌 포맷팅 + 인용 마커 삽입(인용 관리자)

두 역할은 원래 별도 클래스(WriterAgent, CitationManagerAgent)였으나, 실제 생성 로직과 시스템
프롬프트를 전혀 바꾸지 않고 파일/클래스만 통합했다 (agent_label·system_prompt_override로 원래의
로그 이름과 프롬프트를 그대로 유지 — 출력 품질에는 영향 없음).
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.base_agent import BaseAgent
from backend.agents.language_utils import language_instruction
from backend.config import PHASE_MODELS, get_paper_type_config

WRITER_SYSTEM_PROMPT = """You are the Writer agent of an academic writing pipeline. You expand an approved
outline into full academic prose, one section at a time.

Writing rules (non-negotiable):
- Formal academic English suitable for SCI(E) journal submission.
- One idea per sentence. Prefer active voice unless passive is conventional for the field (e.g. Methods).
- Define technical terms and introduce abbreviations at first use: "Full Term (ABBR)".
- Base every claim strictly on the section's thesis/key_points and the researcher's raw notes given to you.
  Do NOT invent data, statistics, citations, or outcomes that were not given to you.
- Where the given information is insufficient to fully support a sentence, write
  "[NEEDS DATA: <what is missing>]" inline instead of fabricating specifics.
- Stay consistent with sections already drafted (given to you as context) - do not contradict earlier
  numbers or claims.
- Discussion-type sections must explain WHY results occurred and how they relate to prior work, not restate
  Results verbatim.
- Respond with a single JSON object {"paragraphs": ["...", "..."]} only, no markdown fences, no commentary.
"""

CITATION_MANAGER_SYSTEM_PROMPT = """You are the Citation Manager agent of an academic writing pipeline.
You do two things, and only these two things:

1. Reformat the researcher's raw, unformatted reference list into the requested citation style
   (APA / IEEE / Vancouver), producing a clean, correctly ordered reference list.
2. Insert in-text citation markers into the drafted manuscript text, but ONLY where a specific reference
   from the given list topically and genuinely supports that specific sentence's claim.

Strict rules:
- NEVER invent a reference that is not in the given raw list.
- NEVER cite a reference for a claim it does not actually support, even if the manuscript would "look
  better" with a citation there. It is fine, and expected, for many sentences to remain uncited.
- Do not change the wording of sentences except to insert citation markers at the correct point
  (end of the relevant clause or sentence).
- Respond with a single JSON object only, no markdown fences, no commentary.
"""

CITATION_MANAGER_LABEL = "인용 관리자"


class WriterAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="집필가",
            name_en="Writer",
            system_prompt=WRITER_SYSTEM_PROMPT,
            model_name=PHASE_MODELS["phase2"],
            phase=2,
        )

    async def write_section(
        self,
        session_id: str,
        paper_input: dict,
        outline: dict,
        section: dict,
        drafted_so_far: Dict[str, List[str]],
    ) -> List[str]:
        section_key = section.get("key", "section")
        await self.log(session_id, f"'{section_key}' 섹션 작성 중...", "PROGRESS")

        pt_config = get_paper_type_config(paper_input.get("paper_type", "original_research"))
        word_lo, word_hi = pt_config["target_word_count"]
        n_sections = max(len(outline.get("sections", [])), 1)
        section_word_budget = (word_lo // n_sections, word_hi // n_sections)

        context_so_far = ""
        if drafted_so_far:
            parts = []
            for k, paragraphs in drafted_so_far.items():
                parts.append(f"--- {k} (already written) ---\n" + "\n".join(paragraphs))
            context_so_far = "\n\n".join(parts)

        prompt = f"""Write the "{section_key}" section now.

【Manuscript title】{outline.get('title', '')}
【Logic chain (must stay consistent with this)】{json.dumps(outline.get('logic_chain', {}), ensure_ascii=False)}
【This section's thesis】{section.get('thesis', '')}
【Key points to cover】
{chr(10).join(f'- {p}' for p in section.get('key_points', []))}
【Known information gaps for this section】{section.get('gap_warning') or '(none)'}
【Approx. target length for this section】{section_word_budget[0]}-{section_word_budget[1]} words

【Researcher's raw notes (source of truth - do not go beyond this)】
- Field: {paper_input.get('field') or '(not specified)'}
- Purpose: {paper_input.get('purpose') or '(not specified)'}
- Methods notes: {paper_input.get('methods_notes') or '(not specified)'}
- Results notes: {paper_input.get('results_notes') or '(not specified)'}
- Extra instructions: {paper_input.get('extra_instructions') or '(none)'}
- Notes for writer (from Strategist): {outline.get('notes_for_writer', '')}

【Sections already written (for consistency - do not contradict)】
{context_so_far or '(none yet - this is the first section)'}

Return {{"paragraphs": [...]}} now."""

        result_text = await self.generate(
            prompt=prompt,
            session_id=session_id,
            temperature=0.5,
            json_mode=True,
            system_prompt_override=WRITER_SYSTEM_PROMPT + language_instruction(paper_input.get("language", "en")),
        )

        paragraphs = self._parse_paragraphs(result_text)
        await self.log(session_id, f"'{section_key}' 섹션 작성 완료 ({len(paragraphs)}문단)", "SUCCESS")
        return paragraphs

    async def revise_draft(
        self,
        session_id: str,
        draft_sections: Dict[str, List[str]],
        feedback: str,
        fact_check: dict = None,
        language_check: dict = None,
        language: str = "en",
    ) -> Dict[str, List[str]]:
        """Gate 2(1차 검증) 이후 사용자 피드백 + 팩트체커/교정관 지적사항을 반영해 초안을 부분 수정"""
        await self.log(session_id, f"검증 결과 및 피드백 반영 수정 시작: {feedback[:50] if feedback else '(체커 지적사항만 반영)'}", "PROGRESS")

        issues_summary = json.dumps(
            {
                "unsupported_claims": (fact_check or {}).get("unsupported_claims", []),
                "reproducibility_issues": (fact_check or {}).get("reproducibility_issues", []),
                "awkward_sentences": (language_check or {}).get("awkward_sentences", []),
                "abbreviation_issues": (language_check or {}).get("abbreviation_issues", []),
            },
            ensure_ascii=False, indent=2,
        )

        prompt = f"""Here is a drafted manuscript, along with reviewer-flagged issues and (optionally) the
researcher's own feedback. Revise the manuscript to address them.

【Current drafted sections (JSON: section key -> list of paragraphs)】
{json.dumps(draft_sections, ensure_ascii=False, indent=2)}

【Fact Checker / Language Editor flagged issues to address】
{issues_summary}

【Researcher's additional feedback (may be empty)】
{feedback or '(none - address only the flagged issues above)'}

Revision rules:
1. Fix the flagged issues and any researcher feedback. Do not change parts that were not flagged.
2. Keep the same JSON schema: same section keys, and do not remove paragraphs unless the fix requires it.
3. Where an "unsupported claim" cannot be fixed with available information, replace it with an explicit
   "[NEEDS DATA: ...]" marker instead of inventing support for it.

Return {{"<section key>": ["<paragraph>", ...], ...}} for ALL sections now."""

        result_text = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.3, json_mode=True,
            system_prompt_override=WRITER_SYSTEM_PROMPT + language_instruction(language),
        )

        try:
            match = re.search(r"\{.*\}", result_text, re.DOTALL)
            revised = json.loads(match.group()) if match else json.loads(result_text)
            if not isinstance(revised, dict) or not revised:
                raise ValueError("empty or invalid revision result")
        except (json.JSONDecodeError, AttributeError, ValueError):
            await self.log(session_id, "수정 결과 파싱 실패 - 기존 초안을 유지합니다.", "WARNING")
            revised = draft_sections

        await self.log(session_id, "초안 수정 완료", "SUCCESS")
        return revised

    @staticmethod
    def _parse_paragraphs(text: str) -> List[str]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group()) if match else json.loads(text)
            paragraphs = data.get("paragraphs", [])
            return [p for p in paragraphs if isinstance(p, str) and p.strip()]
        except (json.JSONDecodeError, AttributeError):
            # 파싱 실패 시 원문 텍스트를 문단 단위로라도 보존
            return [p.strip() for p in text.split("\n\n") if p.strip()] or ["[NEEDS DATA: generation failed]"]

    async def format_and_insert_citations(
        self,
        session_id: str,
        paper_input: dict,
        draft_sections: Dict[str, List[str]],
    ) -> Tuple[Dict[str, List[str]], List[str]]:
        """인용 관리자 역할. Returns (annotated_sections, formatted_reference_list). 참고문헌 원문이
        없으면 초안을 그대로 반환하고 빈 목록을 돌려준다 (API 호출 없음 - 비용 절감)."""
        references_raw = (paper_input.get("references_raw") or "").strip()
        citation_style = paper_input.get("citation_style", "APA")

        if not references_raw:
            await self.log(
                session_id,
                "참고문헌 원문이 없어 인용 삽입을 건너뜁니다. 참고문헌 목록은 비어 있는 상태로 남습니다.",
                "INFO",
                agent_label=CITATION_MANAGER_LABEL,
            )
            return draft_sections, []

        await self.log(
            session_id, f"참고문헌 정리({citation_style}) 및 본문 인용 삽입 중...", "PROGRESS",
            agent_label=CITATION_MANAGER_LABEL,
        )

        draft_json = json.dumps(draft_sections, ensure_ascii=False, indent=2)

        prompt = f"""Reformat the raw reference list below into {citation_style} style, and insert in-text
citation markers into the drafted manuscript sections where genuinely supported.

【Raw reference list (as given by the researcher, one per line, unformatted)】
{references_raw}

【Citation style to produce】{citation_style}

【Drafted manuscript sections (JSON: section key -> list of paragraphs)】
{draft_json}

Return a single JSON object with exactly this schema:
{{
  "formatted_references": ["<reference formatted in {citation_style} style>", ...],
  "annotated_sections": {{"<section key>": ["<paragraph, with in-text citation markers inserted where genuinely supported>", ...], ...}}
}}

The "annotated_sections" must have exactly the same keys and the same number of paragraphs per key as the
input sections - you are only inserting citation markers into existing text, not rewriting content."""

        result_text = await self.generate(
            prompt=prompt,
            session_id=session_id,
            temperature=0.2,
            json_mode=True,
            agent_label=CITATION_MANAGER_LABEL,
            system_prompt_override=CITATION_MANAGER_SYSTEM_PROMPT + language_instruction(paper_input.get("language", "en")),
        )

        try:
            match = re.search(r"\{.*\}", result_text, re.DOTALL)
            data = json.loads(match.group()) if match else json.loads(result_text)
            annotated = data.get("annotated_sections") or draft_sections
            references = data.get("formatted_references") or []
        except (json.JSONDecodeError, AttributeError):
            await self.log(
                session_id, "인용 삽입 결과 파싱 실패 - 원본 초안을 그대로 유지합니다.", "WARNING",
                agent_label=CITATION_MANAGER_LABEL,
            )
            annotated, references = draft_sections, []

        await self.log(
            session_id, f"참고문헌 {len(references)}건 정리 완료, 본문에 인용 마커 삽입 완료", "SUCCESS",
            agent_label=CITATION_MANAGER_LABEL,
        )
        return annotated, references
