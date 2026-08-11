"""
SCI 논문 생성기 — FastAPI 메인 서버
Step 0: 세션 관리 + 헬스체크만 우선 구현. Phase 1~4 API는 이후 단계에서 추가.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import HOST, PORT, DEBUG, FRONTEND_DIR, GEMINI_API_KEY, GEMINI_PRIMARY_MODEL, \
    PAPER_TYPES, DEFAULT_PAPER_TYPE, CITATION_STYLES, DEFAULT_CITATION_STYLE, \
    LANGUAGE_OPTIONS, DEFAULT_LANGUAGE, validate_config
from backend.db.session import init_db, SessionManager, EventLogger, PhaseOutputManager, UsageTracker
from backend.pipeline.phase1_planning import Phase1Pipeline
from backend.pipeline.phase2_drafting import Phase2Pipeline
from backend.pipeline.phase3_verification import Phase3Pipeline
from backend.pipeline.phase4_final_audit import Phase4Pipeline

app = FastAPI(
    title="SCI 논문 생성기 API",
    description="AI 기반 SCI(E) 논문 초안 생성 시스템",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    await init_db()
    errors = validate_config()
    if errors:
        print("설정 경고:")
        for err in errors:
            print(f"   - {err}")
    else:
        print("SCI 논문 생성기 서버 시작")
        print(f"   주소: http://{HOST}:{PORT}")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "SCI 논문 생성기 API", "docs": "/docs"}


# =============================================
# Pydantic 모델
# =============================================
class PaperInput(BaseModel):
    topic: str
    field: str = ""
    purpose: str = ""
    methods_notes: str = ""
    results_notes: str = ""
    keywords: str = ""
    references_raw: str = ""
    ethics_statement: str = ""
    extra_instructions: str = ""
    paper_type: str = DEFAULT_PAPER_TYPE
    citation_style: str = DEFAULT_CITATION_STYLE
    language: str = DEFAULT_LANGUAGE


# =============================================
# 메타데이터 API (프론트엔드 입력 폼 구성용)
# =============================================
@app.get("/api/meta")
async def get_meta():
    """논문 유형, 인용 스타일 등 프론트엔드가 필요로 하는 선택지 목록"""
    return {
        "paper_types": {k: {"label": v["label"], "description": v["description"]} for k, v in PAPER_TYPES.items()},
        "default_paper_type": DEFAULT_PAPER_TYPE,
        "citation_styles": CITATION_STYLES,
        "default_citation_style": DEFAULT_CITATION_STYLE,
        "languages": LANGUAGE_OPTIONS,
        "default_language": DEFAULT_LANGUAGE,
    }


# =============================================
# 세션 관리 API
# =============================================
@app.post("/api/session/new")
async def create_session(paper_input: PaperInput):
    """새 논문 작성 세션 생성"""
    if paper_input.paper_type not in PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 paper_type: {paper_input.paper_type}")
    if paper_input.citation_style not in CITATION_STYLES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 citation_style: {paper_input.citation_style}")
    if paper_input.language not in LANGUAGE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"알 수 없는 language: {paper_input.language}")

    session_id = await SessionManager.create_session(paper_input.model_dump())
    return {
        "session_id": session_id,
        "status": "INPUT",
        "message": "세션이 생성되었습니다.",
    }


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    session = await SessionManager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return session


@app.get("/api/sessions")
async def list_sessions():
    return await SessionManager.list_sessions()


@app.get("/api/usage/{session_id}")
async def get_usage(session_id: str):
    return {"session_id": session_id, "summary": await UsageTracker.get_session_usage(session_id)}


# =============================================
# SSE 스트리밍 API
# =============================================
def _forward_sse_event(session_id: str, event_json: str):
    try:
        EventLogger.push_event(session_id, json.loads(event_json))
    except (TypeError, ValueError):
        pass


@app.get("/api/stream/{session_id}")
async def stream_events(session_id: str):
    """Server-Sent Events — 실시간 에이전트 로그 스트리밍"""

    async def event_generator():
        yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"

        max_wait = 600
        waited = 0
        poll_interval = 0.5
        last_announced_status = None

        while waited < max_wait:
            events = EventLogger.get_pending_events(session_id)
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            session = await SessionManager.get_session(session_id)
            if session:
                current_status = session.get("status")
                if current_status != last_announced_status:
                    # 모든 상태 변화를 알려 배지가 항상 실제 진행 상황과 일치하도록 함
                    # (HITL/COMPLETE/ERROR 외의 상태는 프론트에서 배지 텍스트만 갱신하고 별도 화면 전환은 하지 않음)
                    yield f"data: {json.dumps({'type': 'status_update', 'status': current_status})}\n\n"
                    last_announced_status = current_status
                if current_status in ("COMPLETE", "ERROR"):
                    break

            await asyncio.sleep(poll_interval)
            waited += poll_interval

        yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================
# Phase 1: 기획 API
# =============================================
class Phase1StartRequest(BaseModel):
    session_id: str


class Phase1ApproveRequest(BaseModel):
    session_id: str
    action: str  # "approve" | "revise" | "regenerate"
    feedback: Optional[str] = None
    edited_outline: Optional[dict] = None


@app.post("/api/phase1/start")
async def start_phase1(request: Phase1StartRequest, background_tasks: BackgroundTasks):
    """Phase 1 시작 (기존에 생성된 세션 기준)"""
    session = await SessionManager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    background_tasks.add_task(_run_phase1_background, request.session_id, session)

    return {
        "session_id": request.session_id,
        "status": "PHASE1_STARTING",
        "stream_url": f"/api/stream/{request.session_id}",
        "message": "Phase 1 시작. /api/stream/{session_id}에서 실시간 로그를 확인하세요.",
    }


async def _run_phase1_background(session_id: str, paper_input: dict):
    pipeline = Phase1Pipeline()
    async for event_json in pipeline.run(session_id, paper_input):
        _forward_sse_event(session_id, event_json)


async def _run_phase1_revision_background(session_id: str, paper_input: dict, feedback: str, edited_outline):
    pipeline = Phase1Pipeline()
    async for event_json in pipeline.run_revision(session_id, paper_input, feedback, edited_outline):
        _forward_sse_event(session_id, event_json)


@app.get("/api/phase1/hitl-data/{session_id}")
async def get_phase1_hitl_data(session_id: str):
    """Phase 1 HITL Gate 1 데이터 조회 (아웃라인 + 디렉터 검토 요약)"""
    hitl_data = await PhaseOutputManager.get(session_id, 1, "hitl_data")
    if not hitl_data:
        raise HTTPException(status_code=404, detail="Phase 1 데이터가 없습니다.")
    return {"session_id": session_id, **hitl_data}


@app.post("/api/phase1/approve")
async def approve_phase1(request: Phase1ApproveRequest, background_tasks: BackgroundTasks):
    """Phase 1 HITL Gate 1 처리 (승인/수정/재생성)"""
    session = await SessionManager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    if request.action == "approve":
        if request.edited_outline is not None:
            await PhaseOutputManager.save(request.session_id, 1, "outline", request.edited_outline)
        await PhaseOutputManager.approve(request.session_id, 1)
        await SessionManager.update_status(request.session_id, "PHASE1_APPROVED", phase=1)
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content="Phase 1 승인 완료 → Phase 2(초안 작성) 시작", event_type="USER_APPROVE", phase=1,
        )
        background_tasks.add_task(_run_phase2_background, request.session_id, session)
        return {"status": "approved", "message": "Phase 1 승인 완료. Phase 2(초안 작성)를 시작합니다."}

    elif request.action == "revise":
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content=f"수정 요청: {request.feedback}", event_type="USER_REVISE", phase=1,
        )
        background_tasks.add_task(
            _run_phase1_revision_background, request.session_id, session, request.feedback or "", request.edited_outline,
        )
        return {"status": "revision_queued", "message": "피드백을 반영해 아웃라인을 다시 작성합니다."}

    elif request.action == "regenerate":
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content="Phase 1 전체 재생성 요청", event_type="USER_REGENERATE", phase=1,
        )
        background_tasks.add_task(_run_phase1_background, request.session_id, session)
        return {"status": "regenerating", "message": "Phase 1 재생성 시작."}

    else:
        raise HTTPException(status_code=400, detail="action은 approve/revise/regenerate 중 하나여야 합니다.")


# =============================================
# Phase 2: 초안 작성 API
# =============================================
class Phase2StartRequest(BaseModel):
    session_id: str


async def _run_phase2_background(session_id: str, paper_input: dict):
    """Phase 2(초안 작성) 실행 후, Gate 없이 곧바로 Phase 3(1차 검증)까지 이어서 실행한다."""
    pipeline = Phase2Pipeline()
    async for event_json in pipeline.run(session_id, paper_input):
        _forward_sse_event(session_id, event_json)

    session = await SessionManager.get_session(session_id)
    if session and session.get("status") == "PHASE2_COMPLETE":
        await _run_phase3_background(session_id, paper_input)


@app.post("/api/phase2/start")
async def start_phase2(request: Phase2StartRequest, background_tasks: BackgroundTasks):
    """Phase 2 수동 시작 (Phase 1 승인된 세션 기준). 보통은 Phase 1 승인 시 자동으로 시작됨."""
    session = await SessionManager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    background_tasks.add_task(_run_phase2_background, request.session_id, session)
    return {
        "session_id": request.session_id,
        "status": "PHASE2_STARTING",
        "stream_url": f"/api/stream/{request.session_id}",
        "message": "Phase 2 시작. /api/stream/{session_id}에서 실시간 로그를 확인하세요.",
    }


@app.get("/api/phase2/draft/{session_id}")
async def get_phase2_draft(session_id: str):
    """Phase 2 결과(초안 전체) 조회"""
    draft = await PhaseOutputManager.get(session_id, 2, "draft")
    if not draft:
        raise HTTPException(status_code=404, detail="Phase 2 초안이 없습니다.")
    return {"session_id": session_id, **draft}


# =============================================
# Phase 3: 1차 검증 API
# =============================================
class Phase3ApproveRequest(BaseModel):
    session_id: str
    action: str  # "approve" | "revise" | "regenerate"
    feedback: Optional[str] = None


async def _run_phase3_background(session_id: str, paper_input: dict):
    pipeline = Phase3Pipeline()
    async for event_json in pipeline.run(session_id, paper_input):
        _forward_sse_event(session_id, event_json)


async def _run_phase3_revision_background(session_id: str, feedback: str):
    pipeline = Phase3Pipeline()
    async for event_json in pipeline.run_revision(session_id, feedback):
        _forward_sse_event(session_id, event_json)


@app.get("/api/phase3/hitl-data/{session_id}")
async def get_phase3_hitl_data(session_id: str):
    """Phase 3 HITL Gate 2 데이터 조회 (팩트체크 + 언어 검토 결과)"""
    hitl_data = await PhaseOutputManager.get(session_id, 3, "hitl_data")
    if not hitl_data:
        raise HTTPException(status_code=404, detail="Phase 3 데이터가 없습니다.")
    return {"session_id": session_id, **hitl_data}


@app.post("/api/phase3/approve")
async def approve_phase3(request: Phase3ApproveRequest, background_tasks: BackgroundTasks):
    """Phase 3 HITL Gate 2 처리 (승인/수정/재생성)"""
    session = await SessionManager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    if request.action == "approve":
        await PhaseOutputManager.approve(request.session_id, 3)
        await SessionManager.update_status(request.session_id, "PHASE3_APPROVED", phase=3)
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content="Phase 3 승인 완료 → Phase 4(최종 감사) 시작", event_type="USER_APPROVE", phase=3,
        )
        background_tasks.add_task(_run_phase4_background, request.session_id, session)
        return {"status": "approved", "message": "Phase 3 승인 완료. Phase 4(최종 감사)를 시작합니다."}

    elif request.action == "revise":
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content=f"수정 요청: {request.feedback}", event_type="USER_REVISE", phase=3,
        )
        background_tasks.add_task(_run_phase3_revision_background, request.session_id, request.feedback or "")
        return {"status": "revision_queued", "message": "지적사항과 피드백을 반영해 초안을 다시 작성하고 재검증합니다."}

    elif request.action == "regenerate":
        await EventLogger.log(
            session_id=request.session_id, agent_name="사용자",
            content="Phase 3 재검증 요청", event_type="USER_REGENERATE", phase=3,
        )
        background_tasks.add_task(_run_phase3_background, request.session_id, session)
        return {"status": "regenerating", "message": "Phase 3 재검증 시작."}

    else:
        raise HTTPException(status_code=400, detail="action은 approve/revise/regenerate 중 하나여야 합니다.")


# =============================================
# Phase 4: 최종 감사 + 출력 API
# =============================================
async def _run_phase4_background(session_id: str, paper_input: dict):
    pipeline = Phase4Pipeline()
    async for event_json in pipeline.run(session_id, paper_input):
        _forward_sse_event(session_id, event_json)


class Phase4StartRequest(BaseModel):
    session_id: str


@app.post("/api/phase4/start")
async def start_phase4(request: Phase4StartRequest, background_tasks: BackgroundTasks):
    """Phase 4 수동 시작 (Phase 3 승인된 세션 기준). 보통은 Phase 3 승인 시 자동으로 시작됨."""
    session = await SessionManager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    background_tasks.add_task(_run_phase4_background, request.session_id, session)
    return {
        "session_id": request.session_id,
        "status": "PHASE4_STARTING",
        "stream_url": f"/api/stream/{request.session_id}",
        "message": "Phase 4 시작. /api/stream/{session_id}에서 실시간 로그를 확인하세요.",
    }


@app.get("/api/phase4/hitl-data/{session_id}")
async def get_phase4_hitl_data(session_id: str):
    """Phase 4 최종 감사 결과 조회"""
    hitl_data = await PhaseOutputManager.get(session_id, 4, "hitl_data")
    if not hitl_data:
        raise HTTPException(status_code=404, detail="Phase 4 데이터가 없습니다.")
    return {"session_id": session_id, **hitl_data}


async def _export_file(session_id: str, key: str, media_type: str, not_found_label: str) -> FileResponse:
    files = await PhaseOutputManager.get(session_id, 4, "output_files")
    if not files or not files.get(key):
        raise HTTPException(status_code=404, detail=f"아직 생성된 {not_found_label} 파일이 없습니다.")
    path = files[key]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다 (삭제되었을 수 있습니다).")
    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@app.get("/api/export/{session_id}/manuscript")
async def export_manuscript(session_id: str):
    """완성된 원고 DOCX 다운로드"""
    return await _export_file(session_id, "manuscript", DOCX_MEDIA_TYPE, "원고")


@app.get("/api/export/{session_id}/manuscript-md")
async def export_manuscript_md(session_id: str):
    """완성된 원고 Markdown 다운로드"""
    return await _export_file(session_id, "manuscript_md", "text/markdown; charset=utf-8", "원고 Markdown")


@app.get("/api/export/{session_id}/manuscript-pdf")
async def export_manuscript_pdf(session_id: str):
    """완성된 원고 PDF 다운로드"""
    return await _export_file(session_id, "manuscript_pdf", "application/pdf", "원고 PDF")


@app.get("/api/export/{session_id}/checklist")
async def export_checklist(session_id: str):
    """체크리스트 리포트 DOCX 다운로드"""
    return await _export_file(session_id, "checklist", DOCX_MEDIA_TYPE, "체크리스트")


@app.get("/api/export/{session_id}/reviewer-qa")
async def export_reviewer_qa(session_id: str):
    """예상 심사위원 Q&A 리포트 DOCX 다운로드"""
    return await _export_file(session_id, "reviewer_qa", DOCX_MEDIA_TYPE, "리뷰어 Q&A")


# =============================================
# 헬스체크
# =============================================
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "api_key_set": bool(GEMINI_API_KEY),
        "model": GEMINI_PRIMARY_MODEL,
        "version": "0.1.0",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="info" if DEBUG else "warning",
    )
