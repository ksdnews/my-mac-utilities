"""
SCI 논문 생성기 — SQLite 세션/이벤트/토큰사용량 관리
(KIAST R&D Architect의 db/session.py 패턴을 논문 작성 도메인에 맞게 재구성)
"""
import json
import uuid
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.config import DB_PATH


async def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                field TEXT DEFAULT '',
                purpose TEXT DEFAULT '',
                methods_notes TEXT DEFAULT '',
                results_notes TEXT DEFAULT '',
                keywords TEXT DEFAULT '',
                references_raw TEXT DEFAULT '',
                ethics_statement TEXT DEFAULT '',
                extra_instructions TEXT DEFAULT '',
                paper_type TEXT DEFAULT 'original_research',
                citation_style TEXT DEFAULT 'APA',
                language TEXT DEFAULT 'en',
                status TEXT DEFAULT 'INPUT',
                current_phase INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS phase_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                phase INTEGER NOT NULL,
                output_type TEXT NOT NULL,
                content TEXT NOT NULL,
                approved INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                model_name TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                thinking_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
        """)
        await db.commit()


SESSION_FIELDS = [
    "topic", "field", "purpose", "methods_notes", "results_notes", "keywords",
    "references_raw", "ethics_statement", "extra_instructions", "paper_type", "citation_style", "language",
]


class SessionManager:
    """세션 CRUD 관리"""

    @staticmethod
    async def create_session(paper_input: dict) -> str:
        """새 세션 생성. session_id 반환."""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        values = [paper_input.get(f, "") for f in SESSION_FIELDS]

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"""INSERT INTO sessions
                   (id, {', '.join(SESSION_FIELDS)}, status, current_phase, created_at, updated_at)
                   VALUES (?, {', '.join(['?'] * len(SESSION_FIELDS))}, 'INPUT', 0, ?, ?)""",
                (session_id, *values, now, now),
            )
            await db.commit()

        return session_id

    @staticmethod
    async def get_session(session_id: str) -> Optional[dict]:
        """세션 정보 조회"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return None

    @staticmethod
    async def update_status(session_id: str, status: str, phase: int = None):
        """세션 상태 업데이트"""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            if phase is not None:
                await db.execute(
                    "UPDATE sessions SET status=?, current_phase=?, updated_at=? WHERE id=?",
                    (status, phase, now, session_id),
                )
            else:
                await db.execute(
                    "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
                    (status, now, session_id),
                )
            await db.commit()

    @staticmethod
    async def list_sessions() -> list[dict]:
        """모든 세션 목록 조회"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, topic, paper_type, status, current_phase, created_at, updated_at "
                "FROM sessions ORDER BY updated_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


class EventLogger:
    """실시간 이벤트 로그 관리 (SSE 스트리밍용 메모리 큐 + DB 영속 저장)"""

    _queues: dict[str, list] = {}

    @classmethod
    async def log(
        cls,
        session_id: str,
        agent_name: str,
        content: str,
        event_type: str = "LOG",
        phase: int = 0,
    ):
        now = datetime.now().isoformat()
        event = {
            "session_id": session_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "content": content,
            "phase": phase,
            "timestamp": now,
        }

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO events (session_id, agent_name, event_type, content, phase, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, agent_name, event_type, content, phase, now),
            )
            await db.commit()

        cls._queues.setdefault(session_id, []).append(event)

    @classmethod
    def push_event(cls, session_id: str, event: dict):
        """구조화된 이벤트(type 필드 포함)를 SSE 큐에 직접 추가 (DB 저장 없이 화면 전환 신호용)"""
        cls._queues.setdefault(session_id, []).append(event)

    @classmethod
    def get_pending_events(cls, session_id: str) -> list:
        events = cls._queues.get(session_id, []).copy()
        cls._queues[session_id] = []
        return events

    @staticmethod
    async def get_all_events(session_id: str) -> list[dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


class PhaseOutputManager:
    """Phase별 출력 결과 관리"""

    @staticmethod
    async def save(session_id: str, phase: int, output_type: str, content: Any):
        now = datetime.now().isoformat()
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO phase_outputs
                   (session_id, phase, output_type, content, approved, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (session_id, phase, output_type, content_str, now),
            )
            await db.commit()

    @staticmethod
    async def get(session_id: str, phase: int, output_type: str) -> Optional[Any]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT content FROM phase_outputs
                   WHERE session_id=? AND phase=? AND output_type=?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, phase, output_type),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        return json.loads(row["content"])
                    except json.JSONDecodeError:
                        return row["content"]
        return None

    @staticmethod
    async def approve(session_id: str, phase: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE phase_outputs SET approved=1 WHERE session_id=? AND phase=?",
                (session_id, phase),
            )
            await db.commit()


# ===========================================
# 모델별 토큰 단가 (USD per 1M tokens) — 참고용 추정치, 실제 청구서와 다를 수 있음
# ===========================================
MODEL_PRICING = {
    "gemini-pro-latest": {"input": 1.25, "output": 10.00, "thinking": 10.00},
    "gemini-flash-latest": {"input": 0.30, "output": 2.50, "thinking": 2.50},
    "gemini-flash-lite-latest": {"input": 0.10, "output": 0.40, "thinking": 0.40},
    "default": {"input": 1.25, "output": 10.00, "thinking": 10.00},
}


def _calc_cost(model_name: str, input_tokens: int, output_tokens: int, thinking_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model_name, MODEL_PRICING["default"])
    per_m = 1_000_000
    return (
        (input_tokens * pricing["input"] / per_m)
        + (output_tokens * pricing["output"] / per_m)
        + (thinking_tokens * pricing.get("thinking", 0) / per_m)
    )


class UsageTracker:
    """API 호출당 토큰 사용량 및 비용 추적"""

    @staticmethod
    async def record(
        session_id: str,
        agent_name: str,
        model_name: str,
        phase: int,
        input_tokens: int,
        output_tokens: int,
        thinking_tokens: int = 0,
    ):
        cost = _calc_cost(model_name, input_tokens, output_tokens, thinking_tokens)
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO token_usage
                   (session_id, agent_name, model_name, phase,
                    input_tokens, output_tokens, thinking_tokens, cost_usd, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, agent_name, model_name, phase,
                 input_tokens, output_tokens, thinking_tokens, cost, now),
            )
            await db.commit()

    @staticmethod
    async def get_session_usage(session_id: str) -> dict:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT
                       SUM(input_tokens) as total_input,
                       SUM(output_tokens) as total_output,
                       SUM(thinking_tokens) as total_thinking,
                       SUM(cost_usd) as total_cost,
                       COUNT(*) as call_count
                   FROM token_usage WHERE session_id = ?""",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "total_input_tokens": row["total_input"] or 0,
                        "total_output_tokens": row["total_output"] or 0,
                        "total_thinking_tokens": row["total_thinking"] or 0,
                        "total_tokens": (row["total_input"] or 0) + (row["total_output"] or 0) + (row["total_thinking"] or 0),
                        "total_cost_usd": round(row["total_cost"] or 0.0, 6),
                        "api_call_count": row["call_count"] or 0,
                    }
        return {"total_input_tokens": 0, "total_output_tokens": 0, "total_thinking_tokens": 0,
                "total_tokens": 0, "total_cost_usd": 0.0, "api_call_count": 0}
