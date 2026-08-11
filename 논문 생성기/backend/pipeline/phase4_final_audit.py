"""
SCI 논문 생성기 — Phase 4: 최종 감사 + 출력 파이프라인
품질감사관(규칙 기반 최종 점검 + 종합 검토) → DOCX(원고 + 체크리스트 리포트) 생성
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.agents.auditor import AuditorAgent
from backend.config import OUTPUT_DIR
from backend.db.session import SessionManager, EventLogger, PhaseOutputManager
from backend.export.docx_generator import build_manuscript_docx, build_checklist_report_docx, build_reviewer_qa_docx
from backend.export.manuscript_export import build_manuscript_markdown, build_manuscript_pdf


class Phase4Pipeline:
    def __init__(self):
        self.auditor = AuditorAgent()

    async def run(self, session_id: str, paper_input: dict) -> AsyncGenerator[str, None]:
        try:
            await SessionManager.update_status(session_id, "PHASE4_RUNNING", phase=4)

            draft = await PhaseOutputManager.get(session_id, 2, "draft")
            if not draft:
                raise RuntimeError("Phase 2 초안을 찾을 수 없습니다.")
            fact_check = await PhaseOutputManager.get(session_id, 3, "fact_check") or {}
            language_check = await PhaseOutputManager.get(session_id, 3, "language_check") or {}

            static_checks = self.auditor.run_static_checks(draft, paper_input)
            await EventLogger.log(
                session_id=session_id, agent_name="품질 감사관",
                content=f"규칙 기반 최종 점검 완료: 분량 {static_checks['word_count_verdict']}, "
                        f"잔여 [NEEDS DATA] {static_checks['remaining_needs_data_count']}건",
                event_type="SUCCESS", phase=4,
            )

            final_verdict = await self.auditor.final_review(session_id, draft, paper_input, static_checks)

            review_qa = await self.auditor.generate_review_qa(
                session_id, paper_input, draft, fact_check, static_checks,
            )
            await PhaseOutputManager.save(session_id, 4, "review_qa", review_qa)

            hitl_data = {
                "static_checks": static_checks,
                "final_verdict": final_verdict,
                "review_qa": review_qa,
            }
            await PhaseOutputManager.save(session_id, 4, "static_checks", static_checks)
            await PhaseOutputManager.save(session_id, 4, "final_verdict", final_verdict)
            await PhaseOutputManager.save(session_id, 4, "hitl_data", hitl_data)

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c for c in (draft.get("title") or "manuscript") if c not in '\\/:*?"<>|').strip()
            safe_title = safe_title[:60] or "manuscript"

            manuscript_path = os.path.join(OUTPUT_DIR, f"{safe_title}_{timestamp}.docx")
            build_manuscript_docx(draft, manuscript_path)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"원고 DOCX 생성 완료: {os.path.basename(manuscript_path)}",
                event_type="SUCCESS", phase=4,
            )

            manuscript_md_path = os.path.join(OUTPUT_DIR, f"{safe_title}_{timestamp}.md")
            with open(manuscript_md_path, "w", encoding="utf-8") as f:
                f.write(build_manuscript_markdown(draft))
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"원고 Markdown 생성 완료: {os.path.basename(manuscript_md_path)}",
                event_type="SUCCESS", phase=4,
            )

            manuscript_pdf_path = os.path.join(OUTPUT_DIR, f"{safe_title}_{timestamp}.pdf")
            build_manuscript_pdf(draft, manuscript_pdf_path)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"원고 PDF 생성 완료: {os.path.basename(manuscript_pdf_path)}",
                event_type="SUCCESS", phase=4,
            )

            checklist_path = os.path.join(OUTPUT_DIR, f"{safe_title}_{timestamp}_checklist.docx")
            build_checklist_report_docx(
                draft.get("title", ""), fact_check, language_check, static_checks, final_verdict, checklist_path,
                language=draft.get("language", "en"),
            )
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"체크리스트 리포트 생성 완료: {os.path.basename(checklist_path)}",
                event_type="SUCCESS", phase=4,
            )

            reviewer_qa_path = os.path.join(OUTPUT_DIR, f"{safe_title}_{timestamp}_reviewer_qa.docx")
            build_reviewer_qa_docx(draft.get("title", ""), review_qa, reviewer_qa_path, language=draft.get("language", "en"))
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"예상 심사위원 Q&A 리포트 생성 완료: {os.path.basename(reviewer_qa_path)}",
                event_type="SUCCESS", phase=4,
            )

            await PhaseOutputManager.save(session_id, 4, "output_files", {
                "manuscript": manuscript_path,
                "manuscript_md": manuscript_md_path,
                "manuscript_pdf": manuscript_pdf_path,
                "checklist": checklist_path,
                "reviewer_qa": reviewer_qa_path,
            })

            await SessionManager.update_status(session_id, "COMPLETE", phase=4)
            yield json.dumps({"type": "status_update", "status": "COMPLETE"}, ensure_ascii=False)

        except Exception as e:
            await SessionManager.update_status(session_id, "ERROR", phase=4)
            await EventLogger.log(
                session_id=session_id, agent_name="시스템",
                content=f"Phase 4 실행 중 오류: {e}", event_type="ERROR", phase=4,
            )
            yield json.dumps({"type": "status_update", "status": "ERROR", "message": str(e)}, ensure_ascii=False)
