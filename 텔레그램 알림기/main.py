# ============================================================
# 텔레그램 알림 봇 — 통합 메인 실행 스크립트 (Integrated Alert Pipeline)
# ============================================================
import os, sys, json, re, time, requests, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(BASE_DIR, "config.json")
HISTORY_FILE = os.path.join(BASE_DIR, "sent_history.json")
WEEKDAYS_KO  = ["월", "화", "수", "목", "금", "토", "일"]

def load_config():
    """config.json 설정 로드"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ config.json 로드 오류: {e}")
    return {}

CONFIG = load_config()

# ==============================================================================
# 1. 환경변수 및 토큰 설정
# ==============================================================================
BOT_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN") or CONFIG.get("telegram", {}).get("bot_token", "").strip()
DEFAULT_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

channels_cfg = CONFIG.get("telegram", {}).get("channels", {})
CHAT_ID_AERO    = os.environ.get("CHAT_ID_AERO")    or channels_cfg.get("aero", {}).get("chat_id", "-1004303018302") or DEFAULT_CHAT_ID
CHAT_ID_MEDIA   = os.environ.get("CHAT_ID_MEDIA")   or channels_cfg.get("media", {}).get("chat_id", "-1003965956256") or DEFAULT_CHAT_ID
CHAT_ID_QT      = os.environ.get("CHAT_ID_QT")      or channels_cfg.get("qt", {}).get("chat_id", "-1004304461870") or DEFAULT_CHAT_ID
CHAT_ID_AI_NEWS = os.environ.get("CHAT_ID_AI_NEWS") or channels_cfg.get("ai_news", {}).get("chat_id", "-1003755390083") or DEFAULT_CHAT_ID
CHAT_ID_AI_YT   = os.environ.get("CHAT_ID_AI_YT")   or channels_cfg.get("ai_yt", {}).get("chat_id", "-1003849449000") or DEFAULT_CHAT_ID

DATA_GO_KR_KEY = os.environ.get("DATA_GO_KR_KEY") or CONFIG.get("telegram", {}).get("data_go_kr_key", "242f60fdc4a357127a300e1ba345bc083301293cdc89cf85146c1dbfaeec4627")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY") or CONFIG.get("telegram", {}).get("youtube_api_key", "").strip() or CONFIG.get("youtube_api_key", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ==============================================================================
# 2. 채널 및 대상 정의
# ==============================================================================
yt_cfg = CONFIG.get("youtube_channels", [])
if yt_cfg:
    YOUTUBE_MEDIA = [c for c in yt_cfg if c.get("enabled", True) and c.get("target") == "media"]
    YOUTUBE_AI    = [c for c in yt_cfg if c.get("enabled", True) and c.get("target") == "ai"]
else:
    YOUTUBE_MEDIA = [
        {"name": "선두교회", "channel_id": "UCij1EEaODLVz87fJfZYOLHg"},
        {"name": "새롭게하소서CBS", "channel_id": "UCqCqf21juyyL_8peGs2CWGg"},
        {"name": "이성미의못간다", "channel_id": "UC0m0-TblIhiyJmhe-KbNO2A"},
        {"name": "교회는 안 다니는데 궁금은 하네요", "channel_id": "UCzhoPJDYg_5ccq0PAYuMAxQ"},
    ]
    YOUTUBE_AI = [
        {"name": "조코딩 JoCoding", "channel_id": "UCQNE2JmbasNYbjGAcuBiRRg"},
        {"name": "테디노트 TeddyNote", "channel_id": "UCt2wAAXgm87ACiQnDHQEW6Q"},
        {"name": "노마드 코더", "channel_id": "UCUpJs89fSBXNolQGOYKn0YQ"},
        {"name": "레인 | AI 바이브코딩", "channel_id": "UCc3-QWjpSyx7D_x7kh3TdgQ"},
    ]

# 보도자료 부처
press_cfg = CONFIG.get("press_targets", [])
if press_cfg:
    PRESS_TARGETS = [p for p in press_cfg if p.get("enabled", True)]
else:
    PRESS_TARGETS = [
        {"name": "우주항공청", "rep_code": "B00026", "filter": "none", "enabled": True},
        {"name": "국토교통부", "rep_code": "A00006", "filter": "aviation", "enabled": True},
    ]

AVIATION_KEYWORDS = [
    # 1. 전국 공항 및 신공항
    "공항", "신공항", "국제공항", "가덕도", "가덕도신공항", "인천공항", "인천국제공항", "김포공항", "김포국제공항",
    "김해공항", "김해국제공항", "제주공항", "제주국제공항", "대구공항", "대구경북신공항", "TK신공항", "청주공항",
    "청주국제공항", "무안공항", "무안국제공항", "양양공항", "양양국제공항", "광주공항", "여수공항", "포항경주공항",
    "울산공항", "사천공항", "군산공항", "원주공항", "제주제2공항", "울릉공항", "흑산공항", "백령공항", "새만금신공항", "서산공항",
    # 2. 국내외 항공사
    "항공사", "대한항공", "아시아나", "아시아나항공", "진에어", "제주항공", "티웨이", "티웨이항공", "에어부산",
    "에어서울", "이스타항공", "이스타", "에어로케이", "에어프레미아", "파라타항공", "플라이강원", "FSC", "LCC",
    "저비용항공사", "저비용항공", "국적항공사", "외항사",
    # 3. 항공기 및 기체
    "항공기", "여객기", "화물기", "수송기", "비행기", "헬기", "헬리콥터", "보잉", "에어버스",
    "B737", "B747", "B777", "B787", "A320", "A321", "A330", "A350", "A380", "기체",
    # 4. 공항 인프라 및 운항
    "활주로", "유도로", "계류장", "탑승교", "탑승구", "탑승동", "여객터미널", "화물터미널", "지상조업", "슬롯", "운수권",
    "관제탑", "항공교통관제", "항공관제", "공역", "항행", "항행안전", "레이더", "MRO", "항공정비", "감항",
    # 5. UAM, 드론, 우주항공
    "UAM", "K-UAM", "도심항공교통", "AAM", "미래항공모빌리티", "eVTOL", "드론", "무인기",
    "항공안전", "항공보안", "우주항공", "우주항공청", "SAF", "조종사", "파일럿", "승무원"
]

# ==============================================================================
# 3. 공통 유틸리티
# ==============================================================================
def get_kst_now():
    """KST(UTC+9) 현재 시각 계산"""
    return datetime.now(timezone(timedelta(hours=9)))

def format_korean_time(dt: datetime, include_approx: bool = False) -> str:
    """오전/오후 HH:MM 포맷팅 (예: 오전 08:00, 오후 06:10)"""
    ampm = "오전" if dt.hour < 12 else "오후"
    hour_12 = dt.hour if dt.hour <= 12 else dt.hour - 12
    if hour_12 == 0:
        hour_12 = 12
    return f"{ampm} {hour_12:02d}:{dt.minute:02d}"

def get_formatted_datetime(dt: datetime = None, include_approx: bool = False) -> str:
    """YYYY-MM-DD(요일) 오전/오후 HH:MM 포맷팅 (예: 2026-09-22(화) 오후 06:10)"""
    if dt is None:
        dt = get_kst_now()
    weekday = WEEKDAYS_KO[dt.weekday()]
    time_str = format_korean_time(dt)
    return f"{dt.strftime('%Y-%m-%d')}({weekday}) {time_str}"

def load_history():
    """발송 장부 로드"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
                elif isinstance(data, dict):
                    return [str(x) for x in data.get("history", [])]
        except Exception as e:
            print(f"⚠️ 발송 장부 로드 오류: {e}")
    return []

def save_history(history_list):
    """최대 최근 1000개의 발송 기록 보존"""
    try:
        trimmed = history_list[-1000:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 발송 장부 저장 오류: {e}")

def send_telegram(text, chat_id, retry=2):
    """텔레그램 메시지 발송 API 호출"""
    if not chat_id:
        print("  → ⚠️ 전송 건너뜀: CHAT_ID가 없습니다.")
        return False
    if not BOT_TOKEN:
        print("  → ❌ 전송 불가: 텔레그램 봇 토큰(BOT_TOKEN)이 설정되지 않았습니다.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False
    }
    for attempt in range(retry + 1):
        try:
            r = requests.post(url, json=payload, timeout=12)
            res_json = r.json() if "application/json" in r.headers.get("content-type", "") else {}
            if r.status_code == 200 and res_json.get("ok"):
                print(f"  → 텔레그램 전송 성공 [채널: {chat_id}]")
                time.sleep(1.0)
                return True
            elif r.status_code == 429:
                retry_after = int(res_json.get("parameters", {}).get("retry_after", 5))
                print(f"  ⏳ 텔레그램 API Rate Limit 발생 (429). {retry_after}초 후 재시도...")
                time.sleep(retry_after + 1)
                continue
            else:
                print(f"  → ❌ 텔레그램 전송 실패 HTTP {r.status_code}: {res_json.get('description', r.text)}")
                return False
        except Exception as e:
            print(f"  → ❌ 텔레그램 전송 에러: {e}")
            if attempt < retry:
                time.sleep(2)
                continue
            return False
    return False

# ==============================================================================
# 4. 보도자료 수집 모듈 (국토교통부 / 우주항공청)
# ==============================================================================
def collect_press(history, ignore_history=False):
    now = get_kst_now()
    msgs = []
    seen = set()
    base = "https://www.korea.kr"

    print(f"\n[정부 정책브리핑] 실시간 보도자료 수집 시작...")
    for t in PRESS_TARGETS:
        if not t.get("enabled", True):
            continue
        rep_code = t.get("rep_code", "").strip()
        rep_type = rep_code[0] if rep_code else "A"
        url = f"{base}/briefing/pressReleaseList.do?repCodeType={rep_type}&repCode={rep_code}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            lt = soup.find(class_="list_type")
            if not lt:
                continue
            for li in lt.find_all("li"):
                a = li.find("a")
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"newsId=(\d+)", href)
                if not m:
                    continue
                nid = m.group(1)
                if nid in seen:
                    continue
                if not ignore_history and nid in history:
                    continue

                strong = a.find("strong")
                title = strong.get_text(" ", strip=True) if strong else a.get_text(" ", strip=True)
                title = " ".join(title.split())
                if " - " in title:
                    title = title.split(" - ")[0].strip()

                if t.get("filter") == "aviation":
                    if not any(k.lower() in title.lower() for k in AVIATION_KEYWORDS):
                        continue

                seen.add(nid)

                date_str = now.strftime("%Y-%m-%d")
                src_span = a.find("span", class_="source")
                if src_span:
                    spans = src_span.find_all("span")
                    if spans:
                        raw_d = spans[0].get_text(strip=True)
                        try:
                            d = datetime.strptime(raw_d, "%Y-%m-%d")
                            date_str = f"{raw_d}({WEEKDAYS_KO[d.weekday()]})"
                        except:
                            date_str = raw_d

                link = f"{base}/briefing/pressReleaseView.do?newsId={nid}"
                msg = (
                    f"🆕 {t['name']} 신규 보도자료 알림\n"
                    f"🗓 일시 : {date_str}\n"
                    f"📌 {title}\n"
                    f"🔗 원문 보기: {link}"
                )
                msgs.append((nid, msg))
                print(f"  ★ [보도자료] [{t['name']}] {title}")
        except Exception as e:
            print(f"  [보도자료 수집 오류/{t['name']}] {e}")

    return msgs

# ==============================================================================
# 5. 유튜브 수집 모듈 (YouTube Data API v3 연동 & 쇼츠 완벽 필터링 & 영상 길이)
# ==============================================================================
def parse_iso8601_duration(duration_iso):
    """
    ISO 8601 duration (예: PT1H2M3S, PT42M26S, PT26S) 파싱
    반환: (total_seconds: int, duration_str: str)
    """
    if not duration_iso:
        return 0, ""
    match = re.match(r'P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_iso)
    if not match:
        return 0, ""
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0) + days * 24
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    if hours > 0:
        duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        duration_str = f"{minutes}:{seconds:02d}"
    return total_seconds, duration_str

def parse_youtube_published_kst(pub_text):
    if not pub_text:
        return get_formatted_datetime()
    try:
        if pub_text.endswith("Z"):
            pub_text = pub_text[:-1] + "+00:00"
        dt = datetime.fromisoformat(pub_text)
        kst_tz = timezone(timedelta(hours=9))
        dt_kst = dt.astimezone(kst_tz)
        return get_formatted_datetime(dt_kst)
    except Exception:
        return get_formatted_datetime()

def check_video_metadata(vid, title=""):
    """
    유튜브 영상의 쇼츠 여부, 재생 시간(Duration), 라이브 여부 정밀 판별
    (YouTube Data API v3 우선 사용, 미설정 시 웹 스크래핑 폴백)
    반환: (is_shorts, duration_str, is_live_now)
    """
    # 1. 제목에 #shorts 포함 시 원천 차단
    if "#shorts" in title.lower() or "#short" in title.lower():
        return True, "", False

    # 2. YouTube Data API v3 우선 사용 (100% 신뢰도)
    if YOUTUBE_API_KEY:
        try:
            api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,liveStreamingDetails&id={vid}&key={YOUTUBE_API_KEY}"
            res = requests.get(api_url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if items:
                    item = items[0]
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    
                    # 라이브 방송 여부
                    live_broadcast = snippet.get("liveBroadcastContent", "none")
                    is_live_now = (live_broadcast == "live")
                    
                    # 재생 시간 파싱
                    duration_iso = content_details.get("duration", "")
                    total_sec, duration_str = parse_iso8601_duration(duration_iso)
                    
                    # 60초 이하는 쇼츠로 판별하여 차단
                    if 0 < total_sec <= 60:
                        return True, duration_str, False
                    
                    return False, duration_str, is_live_now
        except Exception as e:
            print(f"  ⚠️ [YouTube API 호출 예외] {e} -> 스크래핑으로 전환")

    # 3. API 미설정 또는 호출 실패 시 웹 스크래핑 방식 (Fallback)
    try:
        shorts_url = f"https://www.youtube.com/shorts/{vid}"
        r_head = requests.head(shorts_url, headers=HEADERS, allow_redirects=False, timeout=4)
        if r_head.status_code == 200:
            return True, "", False
    except Exception:
        pass

    duration_str = ""
    is_live_now = False
    try:
        watch_url = f"https://www.youtube.com/watch?v={vid}"
        r = requests.get(watch_url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            if '"isLiveBroadcast":true' in r.text or '"isLive":true' in r.text or '"BADGE_STYLE_TYPE_LIVE_NOW"' in r.text:
                is_live_now = True

            sec_m = re.search(r'"lengthSeconds":"(\d+)"', r.text)
            if sec_m:
                sec = int(sec_m.group(1))
                if 0 < sec <= 60:
                    return True, "", False
                if sec > 0:
                    h = sec // 3600
                    m = (sec % 3600) // 60
                    s = sec % 60
                    if h > 0:
                        duration_str = f"{h}:{m:02d}:{s:02d}"
                    else:
                        duration_str = f"{m}:{s:02d}"
    except Exception:
        pass

    return False, duration_str, is_live_now

def collect_youtube(channels, history, ignore_history=False):
    """
    유튜브 채널의 최신 영상 수집 (쇼츠 제외, 영상 길이 및 라이브 스트림 정밀 표기)
    """
    msgs = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    now_kst = get_kst_now()

    for ch in channels:
        ch_name = ch.get("name", "")
        ch_id = ch.get("channel_id", "")
        if not ch_id:
            continue
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            root = ET.fromstring(res.content)
            entries = root.findall("atom:entry", ns)[:3]

            for e in entries:
                vid_t   = e.find("yt:videoId", ns)
                title_t = e.find("atom:title", ns)
                pub_t   = e.find("atom:published", ns)
                if vid_t is None or title_t is None or not vid_t.text or not title_t.text:
                    continue

                vid = vid_t.text.strip()
                title = title_t.text.strip()
                if not ignore_history and vid in history:
                    continue

                # 쇼츠 검사 및 재생 시간 조회
                is_shorts, duration, is_live_now = check_video_metadata(vid, title)
                if is_shorts:
                    if not ignore_history:
                        if isinstance(history, set):
                            history.add(vid)
                        elif isinstance(history, list) and vid not in history:
                            history.append(vid)
                    continue

                pub_str = parse_youtube_published_kst(pub_t.text.strip() if pub_t is not None and pub_t.text else None)
                video_link = f"https://youtu.be/{vid}"
                dur_line = f"\n⏱ 영상 길이 : {duration}" if duration else ""

                if is_live_now:
                    time_line = f"방송 상태 : 실시간 스트리밍 중 ({format_korean_time(now_kst)} 기준)"
                    msg = (
                        f"📺 YouTube 라이브 알림 [Live 🔴]\n"
                        f"🗓 {time_line}{dur_line}\n"
                        f"📌 [{ch_name}] {title}\n"
                        f"🔗 영상 바로보기: {video_link}"
                    )
                else:
                    msg = (
                        f"📺 YouTube 최신영상 알림 [New]\n"
                        f"🗓 업로드 일시 : {pub_str}{dur_line}\n"
                        f"📌 [{ch_name}] {title}\n"
                        f"🔗 영상 바로보기: {video_link}"
                    )

                msgs.append((vid, msg))
                print(f"  ★ [유튜브] [{ch_name}] {title} (길이: {duration or '확인불가'})")
        except Exception as e:
            print(f"  [유튜브 수집 오류/{ch_name}] {e}")

    return msgs

# ==============================================================================
# 6. AI 전문 소식지 수집 모듈 (AI타임스 & MIT Tech Review)
# ==============================================================================
ai_news_cfg = CONFIG.get("ai_newsletters", [])
AI_NEWSLETTERS = ai_news_cfg if ai_news_cfg else [
    {"name": "AI타임스", "url": "https://www.aitimes.com/news/articleList.html?sc_section_code=S1N1", "enabled": True},
    {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/topic/artificial-intelligence/", "enabled": True}
]

def collect_ai_newsletters(history, ignore_history=False):
    """
    국내외 주요 AI 전문 소식지 최신 기사 수집 -> AI 전용 채널 발송
    """
    formatted_now = get_formatted_datetime()
    messages = []
    seen = set()

    enabled_targets = {item["name"]: item.get("enabled", True) for item in AI_NEWSLETTERS}

    print(f"\n[AI 소식지] 최신 인공지능 테크 뉴스 수집 시작...")

    # 1) AI타임스 (AITimes)
    if enabled_targets.get("AI타임스", True):
        aitimes_url = "https://www.aitimes.com/news/articleList.html?sc_section_code=S1N1"
        try:
            res = requests.get(aitimes_url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"articleView\.html\?idxno=(\d+)"))
                for a in links:
                    href = a.get("href", "")
                    title = a.get_text(strip=True)
                    if not title or len(title) < 6 or "포토" in title:
                        continue
                    idx_m = re.search(r"idxno=(\d+)", href)
                    item_id = f"aitimes_{idx_m.group(1)}" if idx_m else href
                    if item_id in seen:
                        continue
                    if not ignore_history and item_id in history:
                        continue

                    seen.add(item_id)
                    full_url = href if href.startswith("http") else f"https://www.aitimes.com/news/{href}"
                    msg = (
                        f"📰 [AI타임스] 최신 테크 동향\n"
                        f"🗓 일시 : {formatted_now}\n"
                        f"📌 {title}\n"
                        f"🔗 기사 바로보기: {full_url}"
                    )
                    messages.append((item_id, msg))
                    print(f"  ★ [AI 소식지] [AI타임스] {title}")
                    if len(messages) >= 3:
                        break
        except Exception as e:
            print(f"  [AI타임스 수집 오류] {e}")

    # 2) MIT Technology Review (AI 섹션)
    if enabled_targets.get("MIT Technology Review", True):
        mit_url = "https://www.technologyreview.com/topic/artificial-intelligence/"
        try:
            res = requests.get(mit_url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"/20\d\d/\d\d/\d\d/"))
                for a in links:
                    href = a.get("href", "")
                    title = a.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue
                    item_id = f"mit_ai_{href.strip('/').split('/')[-1]}"
                    if item_id in seen:
                        continue
                    if not ignore_history and item_id in history:
                        continue

                    seen.add(item_id)
                    full_url = href if href.startswith("http") else f"https://www.technologyreview.com{href}"
                    msg = (
                        f"🌐 [MIT Tech Review] 글로벌 AI 소식\n"
                        f"🗓 일시 : {formatted_now}\n"
                        f"📌 {title}\n"
                        f"🔗 아티클 바로보기: {full_url}"
                    )
                    messages.append((item_id, msg))
                    print(f"  ★ [AI 소식지] [MIT Tech Review] {title}")
                    if len(messages) >= 5:
                        break
        except Exception as e:
            print(f"  [MIT Tech Review 수집 오류] {e}")

    return messages

# ==============================================================================
# 7. 성경 QT 모듈 (QTLand 수집)
# ==============================================================================
def collect_qt():
    now = get_kst_now()
    header_date = f"{now.strftime('%Y-%m-%d')}({WEEKDAYS_KO[now.weekday()]})"
    today_num   = now.strftime("%Y%m%d")
    qt_targets  = [
        {"cate": "A", "name": "어른용"},
        {"cate": "C", "name": "어린이용"},
        {"cate": "D", "name": "키즈용"}
    ]
    messages = []
    print(f"\n[성경 QT] 오늘의 큐티 수집 시작...")
    for item in qt_targets:
        cate = item["cate"]
        cat_name = item["name"]
        page_url = f"https://www.qtland.com/quiet/quiet.php?cate={cate}"
        img_url = ""
        try:
            res = requests.get(page_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if "meditation" in src:
                        if src.startswith("http"):
                            img_url = src
                        elif src.startswith("../"):
                            img_url = f"https://www.qtland.com/{src[3:]}"
                        elif src.startswith("/"):
                            img_url = f"https://www.qtland.com{src}"
                        else:
                            img_url = f"https://www.qtland.com/{src}"
                        break
        except Exception as e:
            print(f"  [QT 웹 수집 오류/{cat_name}] {e}")

        if not img_url:
            img_url = f"https://www.qtland.com/data/meditation/{cate}{today_num}.jpg"

        msg = (
            f"📖 오늘의 큐티\n"
            f"🗓 {header_date}\n"
            f"📌 [복있는 사람] {cat_name}\n"
            f"🔗 연결: {img_url}"
        )
        messages.append(msg)
        print(f"  ★ [QT] {cat_name} ({img_url})")

    return messages

# ==============================================================================
# 8. 텔레그램 연동 테스트 모듈
# ==============================================================================
def test_telegram_connection():
    """모든 채널에 봇 연동 테스트 메시지 발송"""
    print("\n" + "="*50)
    print("📡 [TEST 모드] 텔레그램 채널 연동 테스트 시작")
    print("="*50)

    if not BOT_TOKEN:
        print("❌ [오류] 텔레그램 봇 토큰(BOT_TOKEN)이 비어있습니다!")
        return

    targets = [
        ("항공 보도자료", CHAT_ID_AERO),
        ("유튜브 관심영상", CHAT_ID_MEDIA),
        ("매일 QT", CHAT_ID_QT),
        ("AI 유투브 영상", CHAT_ID_AI_YT),
        ("AI 관심자료(뉴스)", CHAT_ID_AI_NEWS),
    ]

    for name, cid in targets:
        print(f"\n[채널 테스트] '{name}' (Chat ID: {cid})")
        if not cid:
            print("  ⚠️ CHAT_ID가 설정되지 않았습니다.")
            continue
        test_msg = f"🔔 [테스트] 텔레그램 알림 봇 연동 테스트입니다.\n🗓 {get_formatted_datetime()}\n채널: {name}\n상태: 정상 작동 중 ✅"
        send_telegram(test_msg, cid)

def run_pipeline(mode="HOURLY"):
    print(f"=== 실행 모드: {mode} | {get_formatted_datetime()} ===")

    if not BOT_TOKEN:
        print("\n⚠️ [경고] TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.\n")

    history_list = load_history()
    history_set  = set(history_list)
    sent_count   = 0

    if mode == "TEST":
        test_telegram_connection()

    elif mode == "QT":
        for msg in collect_qt():
            if send_telegram(msg, CHAT_ID_QT):
                sent_count += 1

    elif mode == "FORCE":
        print("\n[FORCE 모드] 발송 이력을 무시하고 최신 항목을 1건씩 강제 발송합니다.")
        press_items = collect_press(history_set, ignore_history=True)
        if press_items:
            nid, msg = press_items[0]
            if send_telegram(msg, CHAT_ID_AERO):
                sent_count += 1

        media_items = collect_youtube(YOUTUBE_MEDIA, history_set, ignore_history=True)
        if media_items:
            vid, msg = media_items[0]
            if send_telegram(msg, CHAT_ID_MEDIA):
                sent_count += 1

        ai_yt_items = collect_youtube(YOUTUBE_AI, history_set, ignore_history=True)
        if ai_yt_items:
            vid, msg = ai_yt_items[0]
            if send_telegram(msg, CHAT_ID_AI_YT):
                sent_count += 1

        ai_news_items = collect_ai_newsletters(history_set, ignore_history=True)
        if ai_news_items:
            nid, msg = ai_news_items[0]
            if send_telegram(msg, CHAT_ID_AI_NEWS):
                sent_count += 1

    else: # HOURLY 모드 (정기 수집)
        # 1) 항공 보도자료 수집 및 전송
        press_items = collect_press(history_set)
        for nid, msg in press_items:
            if send_telegram(msg, CHAT_ID_AERO):
                sent_count += 1
                if nid not in history_set:
                    history_set.add(nid)
                    history_list.append(nid)
                    save_history(history_list)

        # 2) 관심 유튜브 영상 수집 및 전송 (일반 채널)
        yt_items = collect_youtube(YOUTUBE_MEDIA, history_set)
        for vid, msg in yt_items:
            if send_telegram(msg, CHAT_ID_MEDIA):
                sent_count += 1
                if vid not in history_set:
                    history_set.add(vid)
                    history_list.append(vid)
                    save_history(history_list)

        # 3) AI 유튜브 영상 수집 및 전송 (AI 유튜브 전용 채널)
        ai_yt_items = collect_youtube(YOUTUBE_AI, history_set)
        for vid, msg in ai_yt_items:
            if send_telegram(msg, CHAT_ID_AI_YT):
                sent_count += 1
                if vid not in history_set:
                    history_set.add(vid)
                    history_list.append(vid)
                    save_history(history_list)

        # 4) AI 전문 소식지 수집 및 전송 (AI 뉴스 전용 채널)
        ai_news_items = collect_ai_newsletters(history_set)
        for item_id, msg in ai_news_items:
            if send_telegram(msg, CHAT_ID_AI_NEWS):
                sent_count += 1
                if item_id not in history_set:
                    history_set.add(item_id)
                    history_list.append(item_id)
                    save_history(history_list)

    if mode != "TEST":
        if sent_count > 0:
            print(f"\n신규 발송 완료 ({sent_count}건) | 장부 총 {len(history_list)}건 저장됨")
        else:
            print("\n신규 발송 대상 없음 (정상 대기 모드)")

    return sent_count

# ==============================================================================
# 9. Google Cloud Functions / Cloud Run HTTP Handler
# ==============================================================================
def telegram_alert_bot(request=None):
    """Google Cloud Functions 엔트리포인트 (HTTP Trigger)"""
    mode = "HOURLY"
    if request is not None:
        try:
            if hasattr(request, "args") and request.args.get("mode"):
                mode = request.args.get("mode").upper()
            elif hasattr(request, "get_json") and request.get_json(silent=True) and request.get_json(silent=True).get("mode"):
                mode = request.get_json(silent=True).get("mode").upper()
        except Exception:
            pass
    elif len(sys.argv) > 1:
        mode = sys.argv[1].upper()

    count = run_pipeline(mode)
    res = {
        "status": "success",
        "mode": mode,
        "sent_count": count,
        "timestamp": get_formatted_datetime()
    }
    return (json.dumps(res, ensure_ascii=False), 200, {"Content-Type": "application/json; charset=utf-8"})

def main(request=None):
    return telegram_alert_bot(request)

# Cloud Run / Functions Framework 진입점 호환성 별칭
hello_http = telegram_alert_bot
run_bot = telegram_alert_bot

if __name__ == "__main__":
    raw_arg = sys.argv[1].upper() if len(sys.argv) > 1 else "HOURLY"
    run_pipeline(raw_arg)
