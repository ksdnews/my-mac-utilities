"""
SCI 논문 생성기 — Phase 2: 초안 작성 파이프라인
집필가(섹션별 본문 작성 + 참고문헌 포맷팅/인용 삽입)
"""
import json
from pathlib import Path
from typing import AsyncGenerator

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.writer import WriterAgent
from backend.db.session import SessionManager, EventLogger, PhaseOutputManager

NON_PROSE_SECTION_KEYS = {"references"}


class Phase2Pipeline:
    def __init__(self):
        self.writer = WriterAgent()

    async def run(self, session_id: str, paper_input: dict) -> AsyncGenerator[str, None]:
        try:
            await SessionManager.update_status(session_id, "PHASE2_RUNNING", phase=2)

            outline = await PhaseOutputManager.get(session_id, 1, "outline")
            if not outline:
                raise RuntimeError("Phase 1 아웃라인을 찾을 수 없습니다. Phase 1을 먼저 완료해주세요.")

            drafted: dict[str, list[str]] = {}
            for section in outline.get("sections", []):
                key = section.get("key", "")
                if key in NON_PROSE_SECTION_KEYS:
                    continue
                paragraphs = await self.writer.write_section(session_id, paper_input, outline, section, drafted)
                drafted[key] = paragraphs

            annotated_sections, reference_list = await self.writer.format_and_insert_citations(
                session_id, paper_input, drafted,
            )

            keywords_raw = (paper_input.get("keywords") or "").strip()
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

            draft = {
                "title": outline.get("title", ""),
                "keywords": keywords,
                "citation_style": paper_input.get("citation_style", "APA"),
                "paper_type": paper_input.get("paper_type", "original_research"),
                "language": paper_input.get("language", "en"),
                "sections": annotated_sections,
                "section_order": [s["key"] for s in outline.get("sections", []) if s["key"] not in NON_PROSE_SECTION_KEYS],
                "reference_list": reference_list,
            }
            await PhaseOutputManager.save(session_id, 2, "draft", draft)

            await SessionManager.update_status(session_id, "PHASE2_COMPLETE", phase=2)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 2 완료: {len(drafted)}개 섹션 작성, 참고문헌 {len(reference_list)}건",
                event_type="SUCCESS", phase=2,
            )
            yield json.dumps({"type": "status_update", "status": "PHASE2_COMPLETE"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=2)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 2 실행 중 오류: {e}", event_type="ERROR", phase=2,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)
