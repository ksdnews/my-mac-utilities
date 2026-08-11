"""
SCI 논문 생성기 — Gemini API 기반 에이전트 추상화 클래스 (google-genai SDK)
모든 전문 에이전트는 이 클래스를 상속합니다.
"""
import asyncio
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.config import GEMINI_API_KEY, GEMINI_PRIMARY_MODEL
from backend.db.session import EventLogger, UsageTracker

_client = genai.Client(api_key=GEMINI_API_KEY)

# 단일 Gemini 호출이 응답 없이 멈출 경우 대비 (예: 다른 병렬 호출까지 무한 대기하는 것을 방지)
_GENERATE_TIMEOUT_SEC = 150


class BaseAgent:
    """모든 논문 생성기 에이전트의 기반 클래스.

    하나의 파이썬 클래스가 여러 "역할"(예: 전략 분석가 + 총괄 디렉터)을 겸할 수 있도록,
    generate()/log() 호출마다 agent_label(로그 표시 이름)과 system_prompt_override(해당
    역할 고유의 시스템 프롬프트)를 지정할 수 있다. 지정하지 않으면 생성자에서 정한
    기본 이름/프롬프트를 사용한다. 역할별 프롬프트 내용은 이 파라미터들과 무관하게
    호출부에서 그대로 전달하므로, 클래스를 합쳐도 실제 생성 결과에는 영향이 없다.
    """

    def __init__(
        self,
        name: str,           # 에이전트 이름 (한국어, 로그/화면 표시용)
        name_en: str,        # 에이전트 이름 (영어, 내부 로그용)
        system_prompt: str,
        model_name: str = None,
        phase: int = 0,
    ):
        self.name = name
        self.name_en = name_en
        self.system_prompt = system_prompt
        self.model_name = model_name or GEMINI_PRIMARY_MODEL
        self.phase = phase

    def _build_config(
        self,
        use_thinking: bool = False,
        temperature: float = 0.4,
        json_mode: bool = False,
        system_prompt_override: Optional[str] = None,
    ) -> types.GenerateContentConfig:
        thinking_config = types.ThinkingConfig(thinking_budget=-1) if use_thinking else None
        return types.GenerateContentConfig(
            system_instruction=system_prompt_override or self.system_prompt,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=thinking_config,
        )

    async def generate(
        self,
        prompt: str,
        session_id: str,
        use_thinking: bool = False,
        temperature: float = 0.4,
        json_mode: bool = False,
        agent_label: Optional[str] = None,
        system_prompt_override: Optional[str] = None,
    ) -> str:
        """비스트리밍 생성"""
        label = agent_label or self.name

        await EventLogger.log(
            session_id=session_id, agent_name=label,
            content="작업 시작...", event_type="START", phase=self.phase,
        )

        config = self._build_config(use_thinking, temperature, json_mode, system_prompt_override)

        try:
            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config,
                    ),
                ),
                timeout=_GENERATE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            await EventLogger.log(
                session_id=session_id, agent_name=label,
                content=f"Gemini 응답 시간 초과({_GENERATE_TIMEOUT_SEC}초)",
                event_type="ERROR", phase=self.phase,
            )
            raise TimeoutError(f"{label}: Gemini 응답 시간 초과 ({_GENERATE_TIMEOUT_SEC}초)")

        result = response.text or ""

        if not result.strip():
            finish_reason = None
            try:
                finish_reason = response.candidates[0].finish_reason
            except Exception:
                pass
            await EventLogger.log(
                session_id=session_id, agent_name=label,
                content=f"Gemini로부터 빈 응답을 받았습니다 (finish_reason={finish_reason}). "
                        f"모델이 응답을 생성하지 못했을 수 있습니다.",
                event_type="ERROR", phase=self.phase,
            )
            raise RuntimeError(f"{label}: Gemini 빈 응답 (finish_reason={finish_reason})")

        try:
            usage = response.usage_metadata
            if usage:
                await UsageTracker.record(
                    session_id=session_id,
                    agent_name=label,
                    model_name=self.model_name,
                    phase=self.phase,
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    thinking_tokens=getattr(usage, "thoughts_token_count", 0) or 0,
                )
        except Exception:
            pass  # 토큰 추적 실패는 생성 결과에 영향을 주지 않도록 무시

        await EventLogger.log(
            session_id=session_id, agent_name=label,
            content=f"작업 완료 ({len(result)}자)", event_type="COMPLETE", phase=self.phase,
        )

        return result

    async def log(self, session_id: str, message: str, event_type: str = "LOG", agent_label: Optional[str] = None):
        await EventLogger.log(
            session_id=session_id, agent_name=agent_label or self.name,
            content=message, event_type=event_type, phase=self.phase,
        )
