#!/usr/bin/env python3
# ============================================================
# 카카오톡 친구 전달 — 최초 1회 설정 도우미
#   1) 내 카카오 계정으로 로그인(동의: 카카오톡 메시지 전송 + 친구 목록)
#   2) 받을 친구도 같은 주소로 로그인·동의 (친구 목록에 나타나기 위한 조건)
#   3) 친구 목록에서 받을 사람 선택
#   4) 토큰/수신자를 Google Cloud(Cloud Run→GCS)에 저장
# 실행:  python3 kakao_setup.py
# 토큰은 kakao_token.json(로컬, .gitignore 대상)과 GCS에만 저장되며 GitHub에 올라가지 않습니다.
# ============================================================
import json, os, secrets, sys, threading, webbrowser, getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, quote
import time
import requests

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOCAL_FILE = os.path.join(BASE_DIR, "kakao_token.json")
REDIRECT   = "http://localhost:5001/callback"
SCOPE      = "talk_message,friends"
CLOUD_URL  = "https://telegram-alert-bot-80500727934.asia-northeast3.run.app"


def load_local():
    if os.path.exists(LOCAL_FILE):
        try:
            return json.load(open(LOCAL_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def wait_for_code(auth_url):
    box = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            box["code"] = (q.get("code") or [None])[0]
            box["error"] = (q.get("error_description") or q.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "로그인 완료! 터미널로 돌아가세요." if box["code"] else f"실패: {box['error']}"
            self.wfile.write(f"<h2>{msg}</h2>".encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = HTTPServer(("localhost", 5001), H)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    print("\n브라우저가 열립니다. [내 카카오 계정]으로 로그인하고 모든 항목에 동의하세요.")
    webbrowser.open(auth_url)
    t.join(timeout=300)
    srv.server_close()
    return box.get("code"), box.get("error")


def main():
    saved = load_local()
    print("=== 카카오톡 친구 전달 설정 ===")
    api_key = (saved.get("rest_api_key") or input("카카오 REST API 키: ").strip())
    secret = saved.get("client_secret", "")
    if not saved:
        secret = getpass.getpass("Client Secret (사용 안 함이면 Enter): ").strip()

    auth_url = (f"https://kauth.kakao.com/oauth/authorize?client_id={api_key}"
                f"&redirect_uri={quote(REDIRECT, safe='')}&response_type=code&scope={quote(SCOPE, safe='')}")

    code, err = wait_for_code(auth_url)
    if not code:
        sys.exit(f"❌ 로그인 실패: {err or '시간 초과'}")

    data = {"grant_type": "authorization_code", "client_id": api_key, "redirect_uri": REDIRECT, "code": code}
    if secret:
        data["client_secret"] = secret
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=15)
    tok = r.json()
    if "access_token" not in tok:
        sys.exit(f"❌ 토큰 발급 실패: {tok}")
    print(f"✅ 로그인 성공 (허용 범위: {tok.get('scope')})")
    if "friends" not in (tok.get("scope") or ""):
        print("⚠️ 'friends' 동의가 빠져 있습니다. Kakao Developers > 카카오 로그인 > 동의항목에서 "
              "'카카오 서비스 내 친구목록'을 '이용 중'으로 설정한 뒤 다시 실행하세요.")

    print("\n[친구 안내] 받을 친구도 아래 주소를 자기 폰/PC에서 열어 카카오 로그인 후 모든 항목에 동의해야 합니다.")
    print("(동의 후 localhost 연결 오류 화면이 떠도 정상입니다. 동의는 이미 저장됩니다.)")
    print("친구는 Kakao Developers '팀 관리'에 팀원으로 초대돼 있어야 합니다.\n")
    print(auth_url)
    input("\n친구가 동의를 마쳤으면 Enter...")

    fr = requests.get("https://kapi.kakao.com/v1/api/talk/friends",
                      headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=15)
    if fr.status_code != 200:
        sys.exit(f"❌ 친구 목록 조회 실패 HTTP {fr.status_code}: {fr.text}")
    friends = fr.json().get("elements", [])
    if not friends:
        sys.exit("❌ 친구 목록이 비어 있습니다. 친구의 앱 동의/팀원 초대/카톡 친구 상태를 확인하세요.")
    print("\n친구 목록:")
    for i, f in enumerate(friends, 1):
        print(f"  {i}. {f.get('profile_nickname')}")
    pick = int(input("\n받을 친구 번호: ").strip())
    chosen = friends[pick - 1]

    state = {
        "enabled": True,
        "rest_api_key": api_key,
        "client_secret": secret,
        "access_token": tok["access_token"],
        "access_expires_at": time.time() + int(tok.get("expires_in", 21600)),
        "refresh_token": tok["refresh_token"],
        "receiver_uuids": [chosen["uuid"]],
        "receiver_name": chosen.get("profile_nickname"),
        "admin_key": saved.get("admin_key") or secrets.token_urlsafe(24),
    }
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.chmod(LOCAL_FILE, 0o600)

    resp = requests.post(f"{CLOUD_URL}?mode=UPDATE_KAKAO", json=state, timeout=60)
    print(f"\nCloud 저장: HTTP {resp.status_code} {resp.text}")
    if resp.status_code == 200:
        print(f"✅ 완료! 수신자: {chosen.get('profile_nickname')}")
        print("테스트 발송:  python3 main.py KAKAO_QT   (또는 Cloud Run ?mode=KAKAO_QT)")


if __name__ == "__main__":
    main()
