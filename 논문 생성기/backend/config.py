"""
SCI 논문 생성기 — 전역 설정
"""
import os
from pathlib import Path

# .env 파일 로드 (python-dotenv 없이 직접 파싱 — 다른 유틸리티 프로그램과 동일한 방식)
BASE_DIR = Path(__file__).parent.parent


def _load_env_file() -> None:
    """이 프로젝트 폴더의 .env 파일에서 GEMINI_API_KEY 등을 읽어 환경변수로 등록합니다.
    (이메일 분석기 등 다른 유틸리티 프로그램과 동일한 키를 재사용하기 위함)"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

# ===========================================
# API 설정
# ===========================================
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# "-latest" 별칭 사용: Google이 특정 버전을 단종해도 프로그램 수정 없이 최신 모델을 계속 사용
# 비용 절감을 위해 Phase 1~3(기획/초안/검증)도 Pro 대신 Flash를 기본값으로 사용 (2026-08-10 변경).
# 품질을 높이고 싶은 특정 단계만 다시 Pro로 올리고 싶으면 .env에 GEMINI_PRIMARY_MODEL=gemini-pro-latest로 재정의.
GEMINI_PRIMARY_MODEL: str = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-flash-latest")
GEMINI_FAST_MODEL: str = os.getenv("GEMINI_FAST_MODEL", "gemini-flash-latest")

# ===========================================
# 서버 설정
# ===========================================
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8010"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

# ===========================================
# 경로 설정
# ===========================================
DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/paper_generator.db")
OUTPUT_DIR: Path = BASE_DIR / os.getenv("OUTPUT_DIR", "output")
FRONTEND_DIR: Path = BASE_DIR / "frontend"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ===========================================
# 논문 유형별 목표 분량 (Phase 1 아웃라인 설계 + Phase 4 word limit 감사 기준)
# ===========================================
PAPER_TYPES = {
    "original_research": {
        "label": "Original Research Article",
        "structure": ["abstract", "introduction", "methods", "results", "discussion", "conclusion", "references"],
        "target_word_count": (4000, 7000),
        "target_pages": (15, 25),
        "description": "일반적인 SCI(E) 원저 논문 표준 형식 (IMRaD 전체 구성)",
        "writing_purpose": (
            "새로운 실험/조사 결과를 엄밀하고 재현 가능하게 보고하여, 해당 분야 지식에 검증된 "
            "기여를 추가하는 것이 목적이다."
        ),
        "emphasis": [
            "기존 연구 대비 참신성(novelty)과 차별점을 서론에서 명확히 제시",
            "재현 가능할 만큼 구체적인 방법론 서술 (표본 크기, 파라미터, 통계 기법)",
            "결과의 통계적/실증적 근거를 결과-논의 전반에서 일관되게 뒷받침",
            "Discussion에서 결과를 재서술하지 않고 '왜 이런 결과가 나왔는지', 기존 문헌과 어떻게 다른지 설명",
        ],
    },
    "short_communication": {
        "label": "Short Communication / Letter",
        "structure": ["abstract", "introduction", "methods", "results_and_discussion", "conclusion", "references"],
        "target_word_count": (1500, 3000),
        "target_pages": (4, 8),
        "description": "짧은 보고형 논문. Results와 Discussion을 통합해 압축적으로 서술",
        "writing_purpose": (
            "시급성 있는 단일 핵심 발견을 신속하고 임팩트 있게 학계에 알리는 것이 목적이다. "
            "포괄적인 이론 전개보다 '이 하나의 결과가 왜 중요한가'에 집중한다."
        ),
        "emphasis": [
            "배경 설명은 핵심 맥락 1~2문단으로 최소화하고 바로 연구 질문으로 진입",
            "여러 주장을 나열하지 말고 단 하나의 핵심 메시지에 논문 전체를 집중",
            "Results와 Discussion을 통합해 결과 제시 직후 바로 그 의미를 설명하는 압축적 구성",
            "후속 연구로 미룰 수 있는 부차적 분석은 과감히 생략 (분량 제약이 최우선 제약조건)",
        ],
    },
    "review_article": {
        "label": "Review Article",
        "structure": ["abstract", "introduction", "thematic_sections", "discussion", "conclusion", "references"],
        "target_word_count": (6000, 10000),
        "target_pages": (25, 40),
        "description": "특정 연구 주제의 문헌을 종합·비평하는 리뷰 논문. Methods/Results 대신 주제별 소단원으로 구성",
        "writing_purpose": (
            "해당 주제에 대한 기존 문헌을 폭넓게 종합하고 비판적으로 평가하여, 현재 지식의 상태와 "
            "쟁점, 향후 연구 방향을 독자에게 제시하는 것이 목적이다. 새로운 1차 데이터를 생산하지 않는다."
        ),
        "emphasis": [
            "단순 문헌 요약 나열이 아니라 주제/쟁점별로 문헌을 비교·종합하는 비판적 관점 유지",
            "각 소단원(thematic section)마다 명확한 조직 원리(연대순/방법론별/관점별 등)를 설정",
            "상충하는 연구 결과나 미해결 쟁점을 회피하지 않고 명시적으로 다룸",
            "결론에서 현재 지식의 한계와 향후 연구가 필요한 구체적 방향을 제시",
        ],
    },
}
DEFAULT_PAPER_TYPE = "original_research"


def get_paper_type_config(paper_type: str) -> dict:
    return PAPER_TYPES.get(paper_type, PAPER_TYPES[DEFAULT_PAPER_TYPE])


# ===========================================
# 에이전트 설정
# ===========================================
# Phase별 사용 모델 (복잡도에 따라 조절)
PHASE_MODELS = {
    "phase1": GEMINI_PRIMARY_MODEL,  # 기획: 논리 구조 설계 - 고품질 모델
    "phase2": GEMINI_PRIMARY_MODEL,  # 초안 작성: 고품질 모델
    "phase3": GEMINI_PRIMARY_MODEL,  # 검증: 정밀한 판단 필요 - 고품질 모델
    "phase4": GEMINI_FAST_MODEL,     # 최종 감사: 규칙 기반 위주 - 빠른 모델
}

# Thinking Mode 활성화 Phase (복잡한 추론이 필요한 단계)
THINKING_ENABLED_PHASES = {"phase1", "phase3"}

CITATION_STYLES = ["APA", "IEEE", "Vancouver"]
DEFAULT_CITATION_STYLE = "APA"

# 출력 언어: "en"(SCI(E) 국제 학술지용 영문, 기본값) / "ko"(KCI 등 국내 학술지용 국문)
LANGUAGE_OPTIONS = {
    "en": "English (SCI/SCIE 국제 학술지용)",
    "ko": "한국어 (KCI 등 국내 학술지용)",
}
DEFAULT_LANGUAGE = "en"

# 국문(ko) 작성 시 DOCX에 사용할 폰트. 한글이 없는 Times New Roman 대신 Word 기본 번들 폰트로 대체
KOREAN_DOCX_FONT = "맑은 고딕"


def validate_config() -> list[str]:
    """설정 유효성 검사. 오류 목록 반환."""
    errors = []
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    return errors
