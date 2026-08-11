#!/bin/bash
# SCI 논문 생성기 — 로컬 실행 스크립트 (Mac/Linux)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=================================================="
echo " SCI 논문 생성기"
echo "=================================================="
echo ""

if [ ! -f ".env" ]; then
  echo "⚠️  .env 파일이 없습니다."
  echo "   cp .env.example .env 로 만든 뒤 GEMINI_API_KEY를 입력하세요."
  echo "   (다른 유틸리티 프로그램에서 이미 GEMINI_API_KEY를 쓰고 있다면"
  echo "    그 .env 파일을 그대로 복사해서 재사용해도 됩니다)"
  exit 1
fi

PYTHON=$(which python3 || which python)
if [ -z "$PYTHON" ]; then
  echo "오류: Python이 설치되어 있지 않습니다."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "가상환경 생성 중..."
  $PYTHON -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

mkdir -p data output

echo ""
echo "서버 시작 중... http://127.0.0.1:8010"
echo "종료: Ctrl+C"
echo ""

(sleep 2 && open http://127.0.0.1:8010) &

cd backend
python main.py
