"""
SCI 논문 생성기 — Phase 3(1차 검증) 에이전트: 팩트체커 + 교정관
역할: 주장 근거/재현성/윤리 정보 검증(팩트체커) / 문장 명료성·약어 일관성 검토(교정관)

두 역할은 원래 별도 클래스(FactCheckerAgent, LanguageEditorAgent)였으나, 실제 생성 로직과 시스템
프롬프트를 전혀 바꾸지 않고 파일/클래스만 통합했다 (agent_label·system_prompt_override로 원래의
로그 이름과 프롬프트를 그대로 유지 — 출력 품질에는 영향 없음).
"""
import json
import re
from pathlib import Path
from typing import Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.base_agent import BaseAgent
from backend.agents.language_utils import language_instruction, resolve_language
from backend.config import PHASE_MODELS

FACT_CHECKER_SYSTEM_PROMPT = """You are the Fact Checker agent of an academic writing pipeline. You verify
a drafted manuscript against the researcher's own raw notes - you do NOT have access to external literature,
so you can only check internal consistency and whether claims are traceable to what the researcher provided.

What to flag:
1. Unsupported claims: any specific number, statistic, or definitive claim in the draft that is NOT
   traceable to the researcher's raw notes (methods_notes / results_notes / purpose) and is NOT already
   marked with "[NEEDS DATA: ...]".
2. Reproducibility gaps in Methods: missing sample size, missing key parameters, missing statistical test
   names - things a reader would need to replicate the study.
3. Ethics/transparency gaps: whether the manuscript (or the researcher's ethics_statement) mentions IRB/animal
   ethics approval, conflict of interest, and data availability where relevant to this type of study.

Do NOT flag "[NEEDS DATA: ...]" placeholders themselves as unsupported claims - those are already correctly
marked as gaps, which is the desired behavior.
Respond with a single JSON object only, no markdown fences, no commentary.
"""

LANGUAGE_EDITOR_SYSTEM_PROMPT = """You are the Language Editor agent of an academic writing pipeline. You
review drafted manuscript text for clarity and style suitable for SCI(E) journal submission.

What to flag:
1. Sentences that cram more than one distinct idea together and would read more clearly split in two.
2. Unnecessary passive voice (outside Methods, where passive is conventional).
3. Technical terms used without a definition at first use.
4. Abbreviation inconsistency: an abbreviation used before being defined, or defined but never used again,
   or used in two different expanded forms.

Be selective - flag only genuine issues that would matter to a journal reviewer, not stylistic nitpicks.
Respond with a single JSON object only, no markdown fences, no commentary.
"""

LANGUAGE_EDITOR_LABEL = "교정관"


class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="팩트체커",
            name_en="FactChecker",
            system_prompt=FACT_CHECKER_SYSTEM_PROMPT,
            model_name=PHASE_MODELS["phase3"],
            phase=3,
        )

    async def check_draft(self, session_id: str, paper_input: dict, draft: dict) -> dict:
        await self.log(session_id, "주장 근거 및 재현성/윤리 정보 검증 중...", "PROGRESS")

        draft_text = json.dumps(draft.get("sections", {}), ensure_ascii=False, indent=2)

        prompt = f"""Verify this drafted manuscript against the researcher's raw notes.

【Researcher's raw notes (the only source of truth)】
- Purpose: {paper_input.get('purpose') or '(not specified)'}
- Methods notes: {paper_input.get('methods_notes') or '(not specified)'}
- Results notes: {paper_input.get('results_notes') or '(not specified)'}
- Ethics statement (verbatim, provided by researcher - do not alter): {paper_input.get('ethics_statement') or '(EMPTY - not provided)'}

【Drafted manuscript sections】
{draft_text}

Return a single JSON object with exactly this schema:
{{
  "unsupported_claims": [
    {{"section": "<section key>", "excerpt": "<the exact problematic sentence or claim>", "issue": "<why it is unsupported>"}}
  ],
  "reproducibility_issues": [
    {{"excerpt": "<relevant Methods excerpt or 'Methods section overall'>", "issue": "<what is missing for replication>"}}
  ],
  "ethics_check": {{
    "has_ethics_statement": <true/false - based on whether the researcher's ethics_statement is non-empty>,
    "note": "<one sentence: what is missing (IRB approval / COI / data availability) if the ethics_statement is empty or incomplete, otherwise confirm it looks present>"
  }},
  "overall_note": "<1-2 sentence overall verdict>"
}}"""

        result_text = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.2, json_mode=True,
            system_prompt_override=FACT_CHECKER_SYSTEM_PROMPT + language_instruction(resolve_language(paper_input, draft)),
        )

        result = self._parse_json(result_text)
        n_unsupported = len(result.get("unsupported_claims", []))
        n_repro = len(result.get("reproducibility_issues", []))
        await self.log(
            session_id,
            f"검증 완료: 근거 부족 주장 {n_unsupported}건, 재현성 이슈 {n_repro}건",
            "SUCCESS",
        )
        return result

    async def check_language(self, session_id: str, draft: dict) -> dict:
        """교정관 역할: 문장 명료성 및 약어 일관성 검토"""
        await self.log(session_id, "문장 명료성 및 약어 일관성 검토 중...", "PROGRESS", agent_label=LANGUAGE_EDITOR_LABEL)

        draft_text = json.dumps(draft.get("sections", {}), ensure_ascii=False, indent=2)
        abbrev_hints = self._scan_abbreviations(draft.get("sections", {}))

        prompt = f"""Review this drafted manuscript text for language clarity.

【Drafted manuscript sections】
{draft_text}

【Abbreviation scan (mechanical pre-check - verify and refine this, do not just copy it)】
{json.dumps(abbrev_hints, ensure_ascii=False, indent=2)}

Return a single JSON object with exactly this schema:
{{
  "awkward_sentences": [
    {{"section": "<section key>", "excerpt": "<the sentence>", "issue": "<what's wrong>", "suggestion": "<a clearer rewrite>"}}
  ],
  "abbreviation_issues": [
    {{"abbreviation": "<ABBR>", "issue": "<e.g. 'used before being defined', 'defined but never used again'>"}}
  ],
  "overall_note": "<1-2 sentence overall verdict on the manuscript's language clarity>"
}}"""

        result_text = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.3, json_mode=True,
            agent_label=LANGUAGE_EDITOR_LABEL,
            system_prompt_override=LANGUAGE_EDITOR_SYSTEM_PROMPT + language_instruction(resolve_language(draft=draft)),
        )

        result = self._parse_language_json(result_text)
        n_awkward = len(result.get("awkward_sentences", []))
        n_abbrev = len(result.get("abbreviation_issues", []))
        await self.log(
            session_id, f"검토 완료: 문장 이슈 {n_awkward}건, 약어 이슈 {n_abbrev}건", "SUCCESS",
            agent_label=LANGUAGE_EDITOR_LABEL,
        )
        return result

    @staticmethod
    def _scan_abbreviations(sections: Dict[str, List[str]]) -> dict:
        """규칙 기반 사전 스캔 (API 호출 없음) - LLM에게 참고 정보로 제공"""
        full_text = " ".join(p for paragraphs in sections.values() for p in paragraphs)

        defined = dict(re.findall(r"\b([A-Za-z][A-Za-z \-]{2,40}?)\s\(([A-Z]{2,8})\)", full_text))
        all_abbrevs = set(re.findall(r"\b[A-Z]{2,8}\b", full_text))

        used_undefined = sorted(a for a in all_abbrevs if a not in defined.values())
        return {
            "defined_abbreviations": defined,
            "abbreviations_found_without_nearby_definition": used_undefined,
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(match.group()) if match else json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return {
                "unsupported_claims": [], "reproducibility_issues": [],
                "ethics_check": {"has_ethics_statement": False, "note": "검증 결과 파싱 실패"},
                "overall_note": "검증 결과를 파싱하지 못했습니다.",
            }

    @staticmethod
    def _parse_language_json(text: str) -> dict:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(match.group()) if match else json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return {"awkward_sentences": [], "abbreviation_issues": [], "overall_note": "검토 결과를 파싱하지 못했습니다."}
