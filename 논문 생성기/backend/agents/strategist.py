"""
SCI 논문 생성기 — Phase 1(기획) 에이전트: 전략 분석가 + 총괄 디렉터
역할: 연구 갭 분석 + 논문 논리 구조(아웃라인) 설계 (전략 분석가) / 입력 점검 + 최종 검토(총괄 디렉터)

두 역할은 원래 별도 클래스(StrategistAgent, DirectorAgent)였으나, 실제 생성 로직과 시스템 프롬프트를
전혀 바꾸지 않고 파일/클래스만 통합했다 (agent_label·system_prompt_override로 원래의 로그 이름과
프롬프트를 그대로 유지 — 출력 품질에는 영향 없음).
"""
import json
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.base_agent import BaseAgent
from backend.agents.language_utils import language_instruction
from backend.config import PHASE_MODELS, get_paper_type_config

STRATEGIST_SYSTEM_PROMPT = """You are the Strategist agent of an academic writing pipeline. Your job is to
design the logical architecture of an SCI(E) manuscript BEFORE any prose is written.

Core principles:
- Identify the research gap: what existing work has NOT addressed, based on what the researcher told you.
- Build an unbroken logic chain: Background -> Gap -> Purpose/Hypothesis -> (later) Conclusion must answer
  the same question posed by Purpose. Never let these drift apart.
- Design one clear thesis statement (the core point) per section, not vague topic labels.
- Do NOT write full prose paragraphs yourself - you design structure and thesis statements only, which a
  separate Writer agent will later expand into full text.
- Base everything strictly on what the researcher provided. Where information is insufficient for a strong
  thesis statement, say so explicitly in that section's "gap_warning" field instead of inventing content.
- Respond with a single JSON object only, no markdown code fences, no commentary outside the JSON.
"""

DIRECTOR_SYSTEM_PROMPT = """You are the Director agent overseeing an academic manuscript planning pipeline.
Your role is quality control, not drafting: you review the Strategist's outline and explain to the
researcher, in plain terms, whether it is ready for approval and what to watch for.

Review checklist:
- Does the logic chain (background -> gap -> purpose -> expected_conclusion) actually hold together?
- Is the section structure appropriate for the requested paper type?
- Are there any "gap_warning" notes the researcher must resolve before drafting begins?
Respond in plain text (not JSON), 4-8 sentences, addressed directly to the researcher."""

DIRECTOR_LABEL = "총괄 디렉터"


class StrategistAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="전략 분석가",
            name_en="Strategist",
            system_prompt=STRATEGIST_SYSTEM_PROMPT,
            model_name=PHASE_MODELS["phase1"],
            phase=1,
        )

    def check_input_completeness(self, paper_input: dict) -> list[dict]:
        """규칙 기반 입력 점검 (API 호출 없음, 총괄 디렉터 역할). {"level", "message"} 목록 반환."""
        warnings = []

        if not (paper_input.get("topic") or "").strip() and not (paper_input.get("purpose") or "").strip():
            warnings.append({"level": "warning", "message": "논문 주제와 연구 목적이 모두 비어 있습니다. 최소 하나는 입력해야 의미 있는 아웃라인이 나옵니다."})

        if not (paper_input.get("methods_notes") or "").strip():
            warnings.append({"level": "info", "message": "연구 방법 메모가 비어 있어 Methods 섹션은 플레이스홀더 위주로 설계됩니다."})

        if not (paper_input.get("results_notes") or "").strip():
            warnings.append({"level": "info", "message": "결과 메모가 비어 있어 Results 섹션은 플레이스홀더 위주로 설계됩니다."})

        if not (paper_input.get("references_raw") or "").strip():
            warnings.append({"level": "info", "message": "참고문헌 원문이 없어 References는 빈 목록으로 시작합니다. Phase 2에서 직접 추가할 수 있습니다."})

        paper_type = paper_input.get("paper_type", "original_research")
        pt_config = get_paper_type_config(paper_type)
        warnings.append({
            "level": "info",
            "message": f"목표 유형: {pt_config['label']} (목표 분량 약 {pt_config['target_word_count'][0]}"
                       f"~{pt_config['target_word_count'][1]}단어, {pt_config['target_pages'][0]}"
                       f"~{pt_config['target_pages'][1]}페이지)",
        })

        return warnings

    async def review_and_summarize(self, session_id: str, paper_input: dict, outline: dict) -> str:
        """총괄 디렉터 역할: Phase 1 결과 최종 검토 요약"""
        await self.log(session_id, "Phase 1 결과 검토 중...", "PROGRESS", agent_label=DIRECTOR_LABEL)

        pt_config = get_paper_type_config(paper_input.get("paper_type", "original_research"))

        prompt = f"""Review this manuscript outline and summarize it for the researcher who must approve it.

【Paper type】{pt_config['label']}
【Outline】
{outline}

Write your review now."""

        summary = await self.generate(
            prompt=prompt, session_id=session_id, temperature=0.5,
            agent_label=DIRECTOR_LABEL,
            system_prompt_override=DIRECTOR_SYSTEM_PROMPT + language_instruction(paper_input.get("language", "en")),
        )
        await self.log(session_id, "Phase 1 검토 완료 → HITL Gate 1 대기", "HITL", agent_label=DIRECTOR_LABEL)
        return summary

    async def design_outline(self, session_id: str, paper_input: dict) -> dict:
        await self.log(session_id, "연구 갭 분석 및 논문 구조 설계 시작...", "PROGRESS")

        paper_type = paper_input.get("paper_type", "original_research")
        pt_config = get_paper_type_config(paper_type)
        structure = pt_config["structure"]
        word_lo, word_hi = pt_config["target_word_count"]

        prompt = f"""Design the outline for the following manuscript.

【Paper type】{pt_config['label']}
【Writing purpose for this type】{pt_config['writing_purpose']}
【What to emphasize for this type】
{chr(10).join(f'- {e}' for e in pt_config['emphasis'])}
【Required section structure (in order)】{', '.join(structure)}
【Target length】{word_lo}-{word_hi} words total (body text, excluding references)

【Research field】{paper_input.get('field') or '(not specified)'}
【Working topic/title given by researcher】{paper_input.get('topic') or '(not specified)'}
【Research purpose / hypothesis (researcher's own words)】{paper_input.get('purpose') or '(not specified)'}
【Methods notes】{paper_input.get('methods_notes') or '(not specified)'}
【Results / data notes】{paper_input.get('results_notes') or '(not specified)'}
【Keywords given by researcher】{paper_input.get('keywords') or '(not specified)'}
【Extra instructions from researcher】{paper_input.get('extra_instructions') or '(none)'}

Return a single JSON object with exactly this schema:
{{
  "title": "<concise academic title>",
  "working_title_alternatives": ["<alt1>", "<alt2>"],
  "abstract_outline": ["<bullet point the abstract must cover>", ...],
  "logic_chain": {{
    "background": "<1-2 sentence background context>",
    "gap": "<what existing research has NOT addressed>",
    "purpose": "<this study's specific objective, directly closing the gap above>",
    "expected_conclusion": "<what the conclusion must answer - must directly resolve 'purpose'>"
  }},
  "sections": [
    {{
      "key": "<one of: {', '.join(structure)}>",
      "thesis": "<the one core point this section must establish>",
      "key_points": ["<point to cover>", ...],
      "gap_warning": "<empty string, or a note if the researcher's input is insufficient for this section>"
    }}
  ],
  "notes_for_writer": "<any caveats the Writer agent should know, e.g. missing data, tone requirements>"
}}

The "sections" array must contain exactly one entry per item in the required section structure, in the
same order."""

        result_text = await self.generate(
            prompt=prompt,
            session_id=session_id,
            use_thinking=True,  # 논리 구조 설계는 이 파이프라인에서 가장 추론이 중요한 단계
            temperature=0.4,
            json_mode=True,
            system_prompt_override=STRATEGIST_SYSTEM_PROMPT + language_instruction(paper_input.get("language", "en")),
        )

        outline = self._parse_json(result_text)

        if not outline.get("title") or not outline.get("sections"):
            await self.log(
                session_id,
                f"아웃라인 파싱 결과가 불완전합니다 (응답 앞부분: {result_text[:200]!r})",
                "ERROR",
            )
            raise RuntimeError(f"{self.name}: 아웃라인 생성에 실패했습니다 (제목 또는 섹션이 비어 있음). 다시 시도해주세요.")

        await self.log(
            session_id,
            f"아웃라인 설계 완료: 제목 '{outline.get('title', '?')}', "
            f"섹션 {len(outline.get('sections', []))}개",
            "SUCCESS",
        )
        return outline

    async def revise_outline(self, session_id: str, paper_input: dict, outline: dict, feedback: str) -> dict:
        """사용자 피드백만 반영해 아웃라인을 부분 수정 (전체 재생성 아님)"""
        await self.log(session_id, f"피드백 반영 아웃라인 수정 시작: {feedback[:50]}...", "PROGRESS")

        prompt = f"""Here is an existing manuscript outline and the researcher's feedback on it. Revise the
outline to address the feedback.

【Existing outline】
{json.dumps(outline, ensure_ascii=False, indent=2)}

【Researcher's feedback】
{feedback}

Revision rules:
1. Only change what the feedback asks for. Leave everything else exactly as it was.
2. Keep the same JSON schema and the same set of section "key" values.

Return the revised outline as a single JSON object with the same schema as the existing outline above."""

        result_text = await self.generate(
            prompt=prompt,
            session_id=session_id,
            use_thinking=True,
            temperature=0.3,
            json_mode=True,
            system_prompt_override=STRATEGIST_SYSTEM_PROMPT + language_instruction(paper_input.get("language", "en")),
        )

        revised = self._parse_json(result_text, fallback=outline)
        await self.log(session_id, "아웃라인 수정 완료", "SUCCESS")
        return revised

    @staticmethod
    def _parse_json(text: str, fallback: dict = None) -> dict:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(match.group()) if match else json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return fallback if fallback is not None else {}
