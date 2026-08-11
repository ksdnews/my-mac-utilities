"""
SCI 논문 생성기 — Phase 1: 기획 파이프라인
전략분석가(입력 점검+아웃라인 설계+최종 검토) → HITL Gate 1
"""
import json
from pathlib import Path
from typing import AsyncGenerator, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.strategist import StrategistAgent, DIRECTOR_LABEL
from backend.db.session import SessionManager, EventLogger, PhaseOutputManager


class Phase1Pipeline:
    def __init__(self):
        self.strategist = StrategistAgent()

    async def run(self, session_id: str, paper_input: dict) -> AsyncGenerator[str, None]:
        try:
            await SessionManager.update_status(session_id, "PHASE1_RUNNING", phase=1)

            warnings = self.strategist.check_input_completeness(paper_input)
            for w in warnings:
                await EventLogger.log(
                    session_id=session_id, agent_name=DIRECTOR_LABEL,
                    content=w["message"], event_type=w["level"].upper(), phase=1,
                )
            await PhaseOutputManager.save(session_id, 1, "input_warnings", warnings)

            outline = await self.strategist.design_outline(session_id, paper_input)
            await PhaseOutputManager.save(session_id, 1, "outline", outline)

            summary = await self.strategist.review_and_summarize(session_id, paper_input, outline)
            await PhaseOutputManager.save(session_id, 1, "summary", summary)

            hitl_data = {"outline": outline, "summary": summary, "input_warnings": warnings}
            await PhaseOutputManager.save(session_id, 1, "hitl_data", hitl_data)

            await SessionManager.update_status(session_id, "HITL_GATE1", phase=1)
            yield json.dumps({"type": "status_update", "status": "HITL_GATE1"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=1)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 1 실행 중 오류: {e}", event_type="ERROR", phase=1,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)

    async def run_revision(
        self, session_id: str, paper_input: dict, feedback: str, edited_outline: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            await SessionManager.update_status(session_id, "PHASE1_RUNNING", phase=1)

            current_outline = edited_outline or await PhaseOutputManager.get(session_id, 1, "outline") or {}
            revised = await self.strategist.revise_outline(session_id, paper_input, current_outline, feedback)
            await PhaseOutputManager.save(session_id, 1, "outline", revised)

            summary = await self.strategist.review_and_summarize(session_id, paper_input, revised)
            await PhaseOutputManager.save(session_id, 1, "summary", summary)

            warnings = await PhaseOutputManager.get(session_id, 1, "input_warnings") or []
            hitl_data = {"outline": revised, "summary": summary, "input_warnings": warnings}
            await PhaseOutputManager.save(session_id, 1, "hitl_data", hitl_data)

            await SessionManager.update_status(session_id, "HITL_GATE1", phase=1)
            yield json.dumps({"type": "status_update", "status": "HITL_GATE1"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=1)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 1 수정 중 오류: {e}", event_type="ERROR", phase=1,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)
