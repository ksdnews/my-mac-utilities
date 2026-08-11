"""
SCI 논문 생성기 — Phase 4(최종 감사) 에이전트: 품질 감사관 + 동료 심사위원
역할: word limit·인용 교차검증·잔여 NEEDS DATA·윤리 정보 등 최종 점검 + 종합 검토(품질 감사관) /
     예상 심사위원 질문 + 디펜스 생성(동료 심사위원, "Reviewer 2" 시뮬레이션)

두 역할은 원래 별도 클래스(AuditorAgent, PeerReviewerAgent)였으나, 실제 생성 로직과 시스템 프롬프트를
전혀 바꾸지 않고 파일/클래스만 통합했다 (agent_label·system_prompt_override로 원래의 로그 이름과
프롬프트를 그대로 유지 — 출력 품질에는 영향 없음).
"""
import json
import re
from pathlib import Path
from typing import Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.base_agent import BaseAgent
from backend.agents.language_utils import language_instruction, resolve_language
from backend.config import PHASE_MODELS, get_paper_type_config

AUDITOR_SYSTEM_PROMPT = """You are the Auditor agent - the final quality gate before a manuscript is
considered submission-ready. You have been given the results of mechanical checks (word count, citation
cross-referencing, remaining data gaps) plus the manuscript itself. Write a concise final verdict for the
researcher: is this ready to submit as a draft to send to co-authors, and what remains to be done before
actual journal submission?

Be direct and specific. Do not repeat the raw check results verbatim - synthesize them into a short,
prioritized action list. Respond in plain text (not JSON), 5-10 sentences."""

PEER_REVIEWER_SYSTEM_PROMPT = """You are simulating a rigorous, skeptical peer reviewer (the archetypal
"Reviewer 2") evaluating this manuscript for an SCI(E) journal. Your job has two parts:

1. Raise the specific, pointed questions/criticisms a real reviewer would actually raise. Cover, where
   relevant to this manuscript: novelty/significance vs. existing literature, methodological rigor, sample
   size and statistical power, missing controls or confounds, alternative explanations for the results,
   generalizability of findings, internal consistency, and reproducibility gaps. Do NOT invent generic
   filler questions - each question must reference something specific and real in this manuscript.

2. Draft a response (defense) to each question, written the way the authors would respond in a
   response-to-reviewers letter.

Critical rule for defenses: if the manuscript's own data/notes genuinely support a strong rebuttal, write
one. But if a question exposes a real, unaddressed weakness (e.g., small sample size, a confound the
researcher never controlled for, a claim beyond what the data shows), do NOT fabricate a rebuttal or invent
new justifying data. Instead write an honest, professional concession: acknowledge the limitation, explain
its likely impact on interpretation, and propose how it could be addressed (e.g., as a stated limitation, a
revised claim, or a direction for future work). Reviewers respect honest limitation sections far more than
overreaching rebuttals - authors should never claim to have data they do not have.

Respond with a single JSON object only, no markdown fences, no commentary.
"""

PEER_REVIEWER_LABEL = "동료 심사위원"


class AuditorAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="품질 감사관",
            name_en="Auditor",
            system_prompt=AUDITOR_SYSTEM_PROMPT,
            model_name=PHASE_MODELS["phase4"],
            phase=4,
        )

    def run_static_checks(self, draft: dict, paper_input: dict) -> dict:
        """규칙 기반 최종 점검 (API 호출 없음)"""
        sections: Dict[str, List[str]] = draft.get("sections", {})
        full_text = " ".join(p for paragraphs in sections.values() for p in paragraphs)

        word_count = len(full_text.split())
        pt_config = get_paper_type_config(draft.get("paper_type", paper_input.get("paper_type", "original_research")))
        word_lo, word_hi = pt_config["target_word_count"]
        if word_count < word_lo:
            word_verdict = f"목표({word_lo}~{word_hi}단어)보다 짧음 ({word_count}단어)"
        elif word_count > word_hi:
            word_verdict = f"목표({word_lo}~{word_hi}단어)보다 김 ({word_count}단어)"
        else:
            word_verdict = f"목표 범위 내 ({word_count}단어)"

        needs_data_markers = re.findall(r"\[NEEDS DATA:[^\]]*\]", full_text)

        citation_style = draft.get("citation_style", "APA")
        reference_list = draft.get("reference_list", [])
        citation_check = self._cross_check_citations(full_text, reference_list, citation_style)

        ethics_statement = (paper_input.get("ethics_statement") or "").strip()

        return {
            "word_count": word_count,
            "word_count_target": [word_lo, word_hi],
            "word_count_verdict": word_verdict,
            "remaining_needs_data_count": len(needs_data_markers),
            "remaining_needs_data_samples": needs_data_markers[:10],
            "citation_check": citation_check,
            "has_ethics_statement": bool(ethics_statement),
        }

    @staticmethod
    def _cross_check_citations(full_text: str, reference_list: List[str], citation_style: str) -> dict:
        if citation_style == "IEEE" or citation_style == "Vancouver":
            in_text_markers = set(re.findall(r"\[(\d+)\]", full_text))
            ref_numbers = set()
            for ref in reference_list:
                m = re.match(r"\[(\d+)\]", ref.strip())
                if m:
                    ref_numbers.add(m.group(1))
            uncited_refs = sorted(ref_numbers - in_text_markers, key=lambda x: int(x))
            unlisted_citations = sorted(in_text_markers - ref_numbers, key=lambda x: int(x))
        else:  # APA-style (Author, Year)
            in_text_markers = set(re.findall(r"\(([A-Z][A-Za-z\-]+(?:\s(?:et al\.|&|and)\s[A-Za-z\-]+)?,\s*\d{4}[a-z]?)\)", full_text))
            ref_keys = set()
            for ref in reference_list:
                m = re.search(r"\(?(\d{4}[a-z]?)\)?", ref)
                if m:
                    ref_keys.add(m.group(1))
            cited_years = {re.search(r"\d{4}", m).group() for m in in_text_markers if re.search(r"\d{4}", m)}
            uncited_refs = sorted(ref_keys - cited_years)
            unlisted_citations = sorted(cited_years - ref_keys)

        return {
            "reference_count": len(reference_list),
            "in_text_citation_count": len(in_text_markers),
            "references_never_cited_in_text": uncited_refs,
            "in_text_citations_missing_from_reference_list": unlisted_citations,
        }

    async def final_review(self, session_id: str, draft: dict, paper_input: dict, static_checks: dict) -> str:
        await self.log(session_id, "최종 투고 준비도 종합 검토 중...", "PROGRESS")

        prompt = f"""Write the final verdict for this manuscript.

【Manuscript title】{draft.get('title', '')}
【Static check results】
{json.dumps(static_checks, ensure_ascii=False, indent=2)}

Write your verdict now."""

        review = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.4,
            system_prompt_override=AUDITOR_SYSTEM_PROMPT + language_instruction(resolve_language(paper_input, draft)),
        )
        await self.log(session_id, "최종 감사 완료", "SUCCESS")
        return review

    async def generate_review_qa(
        self, session_id: str, paper_input: dict, draft: dict, fact_check: dict, static_checks: dict,
    ) -> dict:
        """동료 심사위원 역할: 예상 심사위원 질문 + 디펜스 생성"""
        await self.log(session_id, "예상 심사위원 질문 및 디펜스 초안 작성 중...", "PROGRESS", agent_label=PEER_REVIEWER_LABEL)

        draft_text = json.dumps(draft.get("sections", {}), ensure_ascii=False, indent=2)

        prompt = f"""Review this manuscript as a critical peer reviewer and prepare a Q&A defense document.

【Manuscript title】{draft.get('title', '')}
【Manuscript sections】
{draft_text}

【Known gaps already flagged internally (do not treat these as hidden - the authors already know about them)】
- Unsupported claims found earlier: {json.dumps(fact_check.get('unsupported_claims', []), ensure_ascii=False)}
- Reproducibility issues found earlier: {json.dumps(fact_check.get('reproducibility_issues', []), ensure_ascii=False)}
- Remaining [NEEDS DATA] placeholders: {static_checks.get('remaining_needs_data_count', 0)}
- Ethics statement provided by researcher: {paper_input.get('ethics_statement') or '(EMPTY)'}

Return a single JSON object with exactly this schema:
{{
  "questions": [
    {{
      "category": "<one of: novelty, methodology, statistics, sample_size, alternative_explanation, generalizability, consistency, reproducibility, ethics, other>",
      "severity": "<major | minor>",
      "question": "<the specific question/criticism a reviewer would raise, phrased as they would phrase it>",
      "defense": "<the honest response - a real rebuttal if the manuscript supports one, or an honest concession + suggested fix if it does not>"
    }}
  ]
}}

Produce 6-10 questions, prioritizing the most damaging ones a real reviewer would actually raise first."""

        result_text = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.5, json_mode=True,
            agent_label=PEER_REVIEWER_LABEL,
            system_prompt_override=PEER_REVIEWER_SYSTEM_PROMPT + language_instruction(resolve_language(paper_input, draft)),
        )

        result = self._parse_review_qa_json(result_text)
        n_major = sum(1 for q in result.get("questions", []) if q.get("severity") == "major")
        await self.log(
            session_id,
            f"예상 질문 {len(result.get('questions', []))}건 작성 완료 (주요 이슈 {n_major}건)",
            "SUCCESS",
            agent_label=PEER_REVIEWER_LABEL,
        )
        return result

    @staticmethod
    def _parse_review_qa_json(text: str) -> dict:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(match.group()) if match else json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return {"questions": []}
