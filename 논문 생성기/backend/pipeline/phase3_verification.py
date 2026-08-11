"""
SCI 논문 생성기 — Phase 3: 1차 검증 파이프라인
팩트체커(근거/재현성/윤리) + 교정관(명료성/약어) → HITL Gate 2
"""
import json
from pathlib import Path
from typing import AsyncGenerator, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.reviewer import ReviewerAgent
from backend.agents.writer import WriterAgent
from backend.db.session import SessionManager, EventLogger, PhaseOutputManager


class Phase3Pipeline:
    def __init__(self):
        self.reviewer = ReviewerAgent()
        self.writer = WriterAgent()

    async def run(self, session_id: str, paper_input: dict) -> AsyncGenerator[str, None]:
        try:
            await SessionManager.update_status(session_id, "PHASE3_RUNNING", phase=3)

            draft = await PhaseOutputManager.get(session_id, 2, "draft")
            if not draft:
                raise RuntimeError("Phase 2 초안을 찾을 수 없습니다. Phase 2를 먼저 완료해주세요.")

            fact_check = await self.reviewer.check_draft(session_id, paper_input, draft)
            await PhaseOutputManager.save(session_id, 3, "fact_check", fact_check)

            language_check = await self.reviewer.check_language(session_id, draft)
            await PhaseOutputManager.save(session_id, 3, "language_check", language_check)

            hitl_data = {
                "draft_title": draft.get("title", ""),
                "fact_check": fact_check,
                "language_check": language_check,
            }
            await PhaseOutputManager.save(session_id, 3, "hitl_data", hitl_data)

            await SessionManager.update_status(session_id, "HITL_GATE2", phase=3)
            yield json.dumps({"type": "status_update", "status": "HITL_GATE2"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=3)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 3 실행 중 오류: {e}", event_type="ERROR", phase=3,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)

    async def run_revision(self, session_id: str, feedback: str) -> AsyncGenerator[str, None]:
        """Gate 2 수정 요청: 지적사항+피드백 반영해 초안 수정 → 재검증 → 다시 Gate 2"""
        try:
            await SessionManager.update_status(session_id, "PHASE3_RUNNING", phase=3)

            draft = await PhaseOutputManager.get(session_id, 2, "draft")
            fact_check = await PhaseOutputManager.get(session_id, 3, "fact_check")
            language_check = await PhaseOutputManager.get(session_id, 3, "language_check")
            if not draft:
                raise RuntimeError("Phase 2 초안을 찾을 수 없습니다.")

            revised_sections = await self.writer.revise_draft(
                session_id, draft.get("sections", {}), feedback, fact_check, language_check,
                language=draft.get("language", "en"),
            )
            draft["sections"] = revised_sections
            await PhaseOutputManager.save(session_id, 2, "draft", draft)

            # 수정된 초안을 다시 검증
            fact_check = await self.reviewer.check_draft(
                session_id, await self._get_paper_input(session_id), draft,
            )
            await PhaseOutputManager.save(session_id, 3, "fact_check", fact_check)

            language_check = await self.reviewer.check_language(session_id, draft)
            await PhaseOutputManager.save(session_id, 3, "language_check", language_check)

            hitl_data = {
                "draft_title": draft.get("title", ""),
                "fact_check": fact_check,
                "language_check": language_check,
            }
            await PhaseOutputManager.save(session_id, 3, "hitl_data", hitl_data)

            await SessionManager.update_status(session_id, "HITL_GATE2", phase=3)
            yield json.dumps({"type": "status_update", "status": "HITL_GATE2"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=3)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 3 수정 중 오류: {e}", event_type="ERROR", phase=3,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)

    @staticmethod
    async def _get_paper_input(session_id: str) -> dict:
        session = await SessionManager.get_session(session_id)
        return session or {}
