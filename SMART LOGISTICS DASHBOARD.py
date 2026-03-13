
# ═══════════════════════════════════════════════════════════════
# 🔒 보안 개선 사항 (v24.2)
# ═══════════════════════════════════════════════════════════════
# 
# ✅ 적용 완료:
# 1. Supabase users 테이블에서 사용자 로드 (평문 비밀번호 제거)
# 2. 마스터 비밀번호를 환경변수/Supabase로 이동
# 3. delete_all_rows에 Soft delete + 백업 추가
#
# ⚠️ 추가 작업 필요:
# 4. session_state 메모리 최적화 (페이징)
# 5. 엑셀 파싱 Validation 강화  
# 6. Supabase RLS 정책 설정
# 7. 캐시 무효화 개선
# 8. Google Drive → Supabase Storage 이전
#
# 📋 상세 내용: 보안_취약점_수정_가이드.md 참고
# ═══════════════════════════════════════════════════════════════


import re
import streamlit as st
import pandas as pd
import plotly.express as px
import hashlib
import calendar
import io
from datetime import datetime, timezone, timedelta, date
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# =================================================================
# 상수 정의
# =================================================================
# 성능 설정
AUTO_REFRESH_INTERVAL_MS = 30000  # 30초 자동 새로고침
MAX_FUNCTION_LINES = 200  # 함수 최대 라인 수 가이드

# UI 설정
PDF_VIEWER_HEIGHT_PX = 900
IFRAME_BORDER_RADIUS_PX = 10

# 데이터베이스
DEFAULT_PAGE_SIZE = 100
MAX_QUERY_RESULTS = 1000
MAX_AUDIT_LOG_ROWS = 200
MAX_PLAN_LOG_ROWS  = 500
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5분

# 파일 업로드
MAX_UPLOAD_SIZE_MB = 200
ALLOWED_FILE_EXTENSIONS = ['.xlsx', '.xls', '.csv']

# 색상 설정
COLOR_SUCCESS = "#28a745"
COLOR_ERROR = "#dc3545"
COLOR_WARNING = "#ffc107"
COLOR_INFO = "#17a2b8"


# =================================================================
# DataFrame 성능 최적화 예시
# =================================================================
# 
# ❌ 느린 방법 (iterrows 사용):
# 💡 성능 개선 예시: 위 DataFrame 성능 최적화 섹션 참고
# 💡 벡터화 예: df['result'] = df['col1'] + df['col2']  (현재 코드는 10-100배 느림)
# 💡 벡터화 예: df['result'] = df['col1'] + df['col2']  (현재 코드는 10-100배 느림)
# 💡 벡터화 예: df['result'] = df['col1'] + df['col2']  (현재 코드는 10-100배 느림)
# for idx, row in df.iterrows():
#     df.at[idx, 'result'] = row['a'] + row['b']
#
# ✅ 빠른 방법 (벡터화):
# df['result'] = df['a'] + df['b']
#
# ❌ 느린 방법 (반복문으로 필터링):
# result = []
# for idx, row in df.iterrows():
#     if row['status'] == 'active':
#         result.append(row)
#
# ✅ 빠른 방법 (boolean indexing):
# result = df[df['status'] == 'active']
#
# ❌ 느린 방법 (apply with iterrows):
# for idx, row in df.iterrows():
#     process_row(row)
#
# ✅ 빠른 방법 (apply 또는 map):
# df.apply(lambda row: process_row(row), axis=1)
# # 또는 단일 컬럼인 경우:
# df['column'].map(process_value)
#
# =================================================================

# =================================================================
# 1. 시스템 전역 설정 (v22.3 - 반응형)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v22.3",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
_refresh_count = st_autorefresh(interval=AUTO_REFRESH_INTERVAL_MS, key="pms_auto_refresh")
# autorefresh 카운터만 기록 - 팝업은 사용자가 직접 닫을 때까지 유지
if _refresh_count:
    st.session_state["_last_refresh_count"] = _refresh_count

PRODUCTION_GROUPS   = ["제조1반", "제조2반", "제조3반"]
CALENDAR_EDIT_ROLES = ["master", "admin", "control_tower", "schedule_manager"]

# ── 사용 설명서 PDF (외부 파일 로드) ────────────────────────────────
# PDF 파일을 소스 코드와 같은 폴더에 위치시키세요: PMS_v22.3_사용설명서.pdf
import os as _os, base64 as _b64_loader
_PDF_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "PMS_v22.3_사용설명서.pdf")
def _load_manual_pdf_b64() -> str:
    if _os.path.exists(_PDF_PATH):
        with open(_PDF_PATH, "rb") as _f:
            return _b64_loader.b64encode(_f.read()).decode("utf-8")
    return ""
_MANUAL_PDF_B64 = _load_manual_pdf_b64()

ROLES = {
    "master":           ["생산 지표 관리", "조립 라인", "검사 라인", "포장 라인", "OQC 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼"],
    "admin":            ["생산 지표 관리", "조립 라인", "검사 라인", "포장 라인", "OQC 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼"],
    "control_tower":    ["생산 지표 관리", "생산 현황 리포트", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼"],
    "assembly_team":    ["조립 라인", "작업자 매뉴얼"],
    "qc_team":          ["검사 라인", "불량 공정", "작업자 매뉴얼"],
    "packing_team":     ["포장 라인", "작업자 매뉴얼"],
    "schedule_manager": ["생산 지표 관리", "작업자 매뉴얼"],
    "oqc_team":         ["OQC 라인", "작업자 매뉴얼"],
}

ROLE_LABELS = {
    "master":        "👤 마스터 관리자",
    "admin":         "👤 관리자",
    "control_tower": "🗼 컨트롤 타워",
    "assembly_team": "🔧 조립 담당자",
    "qc_team":       "🔍 검사 담당자",
    "packing_team":  "📦 포장 담당자",
    "schedule_manager": "📅 일정 관리자",
    "oqc_team":       "🏅 OQC 품질팀",
}

SCHEDULE_COLORS = {
    "조립계획": "#7eb8e8",
    "포장계획": "#7ec8a0",
    "출하계획": "#f0c878",
    "특이사항": "#e8908a",
    "기타":     "#b49fd4",
}
# 일정 등록 폼에서 선택 가능한 계획 카테고리 (특이사항/기타 제외)
PLAN_CATEGORIES = ["조립계획", "포장계획", "출하계획"]
calendar.setfirstweekday(6)  # 일요일 시작

# ── 상태값 상수 ─────────────────────────────────────────────────
WIP_STATES    = ['조립중', '수리 완료(재투입)']
DONE_STATES   = ['검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중','완료']
ACTIVE_STATES = ['조립중','검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중','수리 완료(재투입)']

# ── 상태 스타일 (모듈 레벨 상수) ───────────────────────────────
STATUS_STYLE = {
    '검사대기': ('#fff3d4','#7a5c00','#f0c878','🔜'),
    '검사중':   ('#ddeeff','#1a4a7a','#7eb8e8','🔍'),
    '포장대기': ('#ede0f5','#4a1a7a','#b07ed8','🔜'),
    '포장중':   ('#fde8d4','#7a3c1a','#e8a87e','📦'),
    '완료':     ('#d4f0e2','#1f6640','#7ec8a0','✅'),
    'OQC대기':  ('#fef0d4','#7a5c00','#f0a868','🔜'),
    'OQC중':    ('#fde8d4','#7a3c1a','#f0a868','🔍'),
    '출하승인': ('#d4e8f0','#1a4a7a','#7eb8e8','✅'),
    '조립중':   ('#f0f0f0','#3d3530','#c8b89a','🔧'),
    '수리 완료(재투입)': ('#f0e8d4','#5a4020','#c8a87a','♻️'),
    '불량 처리 중': ('#fde8e7','#7a2e2a','#e87e7a','🚫'),
}

st.markdown("""
    <style>
    /* ════════════════════════════════════════
       파스텔 테마 (v22.3)
       배경: 따뜻한 크림/페이퍼 톤
       강조: 소프트 블루 · 세이지 그린 · 피치 · 라벤더
    ════════════════════════════════════════ */

    /* 전체 앱 배경 */
    .stApp {
        background-color: #faf6ef !important;
        overflow-x: hidden;
    }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background-color: #f0ebe0 !important;
        border-right: 1px solid #e0d8c8 !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span:not(.stButton span),
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stCaption {
        color: #3d3530 !important;
    }
    /* 사이드바 secondary 버튼 텍스트는 기본 색상 유지 */
    [data-testid="stSidebar"] .stButton button {
        color: inherit;
    }

    /* 메인 컨테이너 */
    .block-container {
        max-width: 1300px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        background-color: #faf6ef;
    }

    /* 입력 필드 */
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        background-color: #fffdf7 !important;
        border: 1px solid #ddd5c0 !important;
        border-radius: 8px !important;
        color: #3d3530 !important;
        max-width: 480px !important;
    }
    /* 검색 필드는 더 짧게 */
    .stTextInput input[placeholder*="검색"],
    .stTextInput input[placeholder*="S/N"],
    .stTextInput input[placeholder*="시리얼"] {
        max-width: 320px !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: #7eb8e8 !important;
        box-shadow: 0 0 0 2px rgba(126,184,232,0.25) !important;
    }
    /* selectbox, multiselect 너비 제한 */
    .stSelectbox > div > div,
    .stMultiSelect > div > div {
        max-width: 480px !important;
    }
    /* selectbox 드롭다운 팝업 글자 선명하게 */
    [data-baseweb="popover"],
    [data-baseweb="popover"] * {
        -webkit-font-smoothing: antialiased !important;
        -moz-osx-font-smoothing: grayscale !important;
        font-smoothing: antialiased !important;
        opacity: 1 !important;
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
    }
    [data-baseweb="menu"] {
        background: #ffffff !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15) !important;
        border: 1px solid #e0d8c8 !important;
        border-radius: 8px !important;
    }
    [data-baseweb="menu"] li,
    [data-baseweb="option"] {
        color: #2a2420 !important;
        font-weight: 500 !important;
        opacity: 1 !important;
        background: #ffffff !important;
    }
    [data-baseweb="menu"] li:hover,
    [data-baseweb="option"]:hover {
        background: #f5f0e8 !important;
        color: #2a2420 !important;
    }
    [aria-selected="true"][data-baseweb="option"] {
        background: #e8e0d0 !important;
        color: #2a2420 !important;
        font-weight: 700 !important;
    }
    /* number_input 짧게 */
    .stNumberInput {
        max-width: 200px !important;
    }
    /* 파일 업로더 너비 제한 */
    .stFileUploader {
        max-width: 520px !important;
    }

    /* ── 버튼 전체 공통 ── */
    .stButton > button,
    div[data-testid="stFormSubmitButton"] > button,
    button[kind="primary"],
    button[kind="secondary"] {
        display: inline-flex !important; justify-content: center !important; align-items: center !important;
        margin-top: 1px !important; padding: 6px 16px !important;
        min-width: 80px !important; max-width: 100% !important;
        border-radius: 8px !important; font-weight: 600 !important;
        white-space: nowrap !important; overflow: hidden !important;
        text-overflow: ellipsis !important; transition: all 0.2s ease !important;
    }
    /* Secondary (기본) → 아이보리 배경 */
    .stButton > button:not([kind="primary"]),
    div[data-testid="stFormSubmitButton"] > button:not([kind="primary"]) {
        background-color: #fffdf7 !important;
        border: 1px solid #c8b89a !important;
        color: #3d3530 !important;
    }
    .stButton > button:not([kind="primary"]):hover {
        background-color: #f0ebe0 !important;
        border-color: #7eb8e8 !important;
        color: #2a2420 !important;
    }
    /* Primary → 파스텔 블루 */
    .stButton > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
        background-color: #7eb8e8 !important;
        border: 1px solid #6aaad8 !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #6aaad8 !important;
    }
    /* ── 최신 Streamlit 버튼 선택자 강제 적용 ── */
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-secondaryFormSubmit"] {
        background-color: #fffdf7 !important;
        border: 1px solid #c8b89a !important;
        color: #3d3530 !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="baseButton-secondaryFormSubmit"]:hover {
        background-color: #f0ebe0 !important;
        border-color: #7eb8e8 !important;
        color: #2a2420 !important;
    }
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-primaryFormSubmit"] {
        background-color: #7eb8e8 !important;
        border: 1px solid #6aaad8 !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="baseButton-primaryFormSubmit"]:hover {
        background-color: #6aaad8 !important;
        color: #ffffff !important;
    }
    /* 모든 버튼 텍스트 색 강제 (최후 방어) */
    .stButton button p,
    .stButton button span,
    .stButton button div {
        color: inherit !important;
    }
    /* 다운로드 버튼 → 파스텔 아이보리 + 진한 글자 */
    [data-testid="stDownloadButton"] > button {
        background-color: #fffdf7 !important;
        border: 1px solid #c8b89a !important;
        color: #3d3530 !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        width: 100% !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #f0ebe0 !important;
        border-color: #7eb8e8 !important;
    }

    /* 컨테이너 border */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #fffdf7 !important;
        border: 1px solid #e0d8c8 !important;
        border-radius: 10px !important;
    }

    /* 탭 */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #f0ebe0;
        border-radius: 8px;
        padding: 2px;
    }
    .stTabs [data-baseweb="tab"] { color: #8a7f72 !important; }
    .stTabs [aria-selected="true"] {
        background-color: #fffdf7 !important;
        color: #3d3530 !important;
        border-bottom: 3px solid #7eb8e8 !important;
        border-radius: 6px 6px 0 0;
    }

    /* 타이틀 / 섹션 헤더 */
    .centered-title {
        text-align: center; font-weight: bold;
        margin: 20px 0; color: #2a2420 !important;
    }
    .section-title {
        background-color: #f5f0e8; color: #2a2420;
        padding: 14px 20px; border-radius: 10px;
        font-weight: bold; margin: 8px 0 20px 0;
        border-left: 10px solid #7eb8e8;
        box-shadow: 0 2px 6px rgba(180,160,120,0.15);
    }

    /* 본문 텍스트 기본 색상 */
    .stApp p, .stApp label, .stApp .stMarkdown p {
        color: #2a2420;
    }
    /* subheader / h3 / h2 / write 텍스트 */
    .stApp h1, .stApp h2, .stApp h3,
    .stApp h4, .stApp h5, .stApp h6 {
        color: #2a2420 !important;
    }
    /* st.write, st.caption 등 일반 텍스트 */
    .stApp .stMarkdown,
    .stApp .stMarkdown p,
    .stApp .stMarkdown span,
    .stApp .stMarkdown strong,
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] span {
        color: #2a2420 !important;
    }
    /* metric, caption */
    .stApp [data-testid="stMetricLabel"],
    .stApp [data-testid="stMetricValue"],
    .stApp [data-testid="stCaptionContainer"] {
        color: #5a5048 !important;
    }

    /* 통계 박스 */
    .stat-box {
        display: flex; flex-direction: column;
        justify-content: center; align-items: center;
        background-color: #fffdf7; border-radius: 12px;
        padding: 16px 8px; border: 1px solid #e0d8c8;
        margin-bottom: 8px;
        box-shadow: 0 4px 10px rgba(180,160,120,0.1);
        width: 100%; box-sizing: border-box; overflow: hidden;
    }
    .stat-label {
        font-size: clamp(0.65rem, 1vw, 0.88rem); color: #8a7f72;
        font-weight: bold; margin-bottom: 8px; white-space: nowrap;
    }
    .stat-value {
        font-size: clamp(1.4rem, 2vw, 2.4rem); color: #5a96c8;
        font-weight: bold; line-height: 1; white-space: nowrap;
    }

    .button-spacer { margin-top: 28px; }

    /* 캘린더 셀 */
    .cal-day-wrap {
        cursor: pointer;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .cal-day-wrap:hover {
        box-shadow: 0 4px 16px rgba(126,184,232,0.35);
        border-color: #7eb8e8 !important;
    }
    .cal-cell {
        background: #fffdf8;
        border: 1px solid #e0d8c8;
        border-radius: 8px;
        padding: 8px 6px;
        min-height: 120px;
        box-sizing: border-box;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        cursor: pointer;
    }
    .cal-cell:hover {
        transform: scale(1.05);
        box-shadow: 0 8px 24px rgba(126,184,232,0.3);
        border-color: #7eb8e8 !important;
        z-index: 999; position: relative;
    }
    .cal-cell.today {
        background: #e8f5ed;
        border: 2px solid #7ec8a0 !important;
    }
    .cal-day-num {
        font-weight: bold; color: #3d3530;
        margin-bottom: 4px; font-size: 0.92rem;
    }
    .cal-event {
        border-radius: 4px; padding: 2px 5px;
        margin-bottom: 3px; font-size: 0.63rem; line-height: 1.3;
    }

    /* ── 캘린더 날짜 버튼: 날짜 숫자처럼 보이는 깔끔한 버튼 ── */
    .cal-day-btn > div > button,
    .cal-day-btn button {
        background-color: transparent !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #3d3530 !important;
        font-weight: bold !important;
        font-size: 1.0rem !important;
        min-height: 28px !important;
        height: 28px !important;
        padding: 0 4px !important;
        margin: 0 !important;
        width: 100% !important;
        cursor: pointer !important;
        border-radius: 6px !important;
        transition: background 0.15s !important;
    }
    .cal-day-btn > div > button:hover,
    .cal-day-btn button:hover {
        background-color: #e4f0f8 !important;
        color: #2471a3 !important;
    }
    .cal-today-btn > div > button,
    .cal-today-btn button {
        color: #1e8449 !important;
    }

    /* ── Expander (펼치기) ── */
    .stExpander {
        border: 1px solid #e0d8c8 !important;
        border-radius: 10px !important;
        background-color: #fffdf7 !important;
        margin-bottom: 8px !important;
    }
    .stExpander summary,
    .stExpander [data-testid="stExpanderToggleIcon"],
    .stExpander details summary {
        background-color: #f5f0e8 !important;
        border-radius: 10px !important;
        color: #3d3530 !important;
        padding: 10px 16px !important;
    }
    .stExpander summary:hover {
        background-color: #ede8de !important;
    }
    .stExpander summary p,
    .stExpander summary span,
    .stExpander details summary p {
        color: #3d3530 !important;
        font-weight: 600 !important;
    }
    /* expander 내부 배경 */
    .stExpander details {
        background-color: #fffdf7 !important;
        border-radius: 0 0 10px 10px !important;
    }

    /* 좁은 화면 */
    @media (max-width: 900px) {
        .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        .stat-value { font-size: 1.3rem; }
        .cal-cell { min-height: 80px; padding: 5px 4px; }
        .cal-day-num { font-size: 0.78rem; }
        .cal-event { font-size: 0.52rem; }
    }
    </style>
""", unsafe_allow_html=True)

# =================================================================
# 2. 보안 유틸리티
# =================================================================

try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _BCRYPT_AVAILABLE = False

def hash_pw(password: str) -> str:
    """bcrypt 사용 가능 시 bcrypt, 아니면 SHA-256 (fallback)"""
    if _BCRYPT_AVAILABLE:
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_pw(plain: str, hashed: str) -> bool:
    """bcrypt 해시($2b$)와 SHA-256 해시(64자 hex) 모두 검증"""
    if _BCRYPT_AVAILABLE and hashed.startswith("$2"):
        try:
            return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    # SHA-256 fallback (기존 계정 호환)
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == hashed


# =================================================================
# 에러 핸들링 베스트 프랙티스
# =================================================================
# 1. 구체적인 예외 타입 사용 (Exception보다 ValueError, KeyError 등)
# 2. 에러 로깅 추가 (st.error()와 함께 로그 기록)
# 3. 사용자 친화적 메시지 제공
# 4. 복구 가능한 에러는 graceful degradation
# =================================================================

def get_master_pw_hash() -> str | None:
    """
    ✅ 보안 개선: 마스터 비밀번호 해시를 안전하게 로드
    우선순위:
    1. Supabase RLS 보호된 테이블에서 로드
    2. 환경변수 (secrets.toml이 아닌 Key Vault)
    3. 없으면 None (초기 설정 필요)
    """
    try:
        # 1순위: Supabase에서 로드 (RLS 보호)
        sb = get_supabase()
        result = sb.table("system_config").select("master_hash").eq("key", "master_password").execute()
        if result.data and len(result.data) > 0:
            return result.data[0].get("master_hash")
    except Exception as e:
        pass
    
    try:
        # 2순위: st.secrets에서 로드 (Streamlit Cloud / secrets.toml)
        # 최상위 키 체크
        secrets_hash = st.secrets.get("master_admin_pw_hash") or st.secrets.get("MASTER_PASSWORD_HASH")
        # connections.gsheets 하위 키도 체크 (구 구조 호환)
        if not secrets_hash:
            try:
                secrets_hash = st.secrets["connections"]["gsheets"].get("master_admin_pw_hash")
            except Exception:
                pass
        if secrets_hash:
            return secrets_hash
    except Exception:
        pass

    try:
        # 3순위: 환경변수
        env_hash = _os.getenv("MASTER_PASSWORD_HASH")
        if env_hash:
            return env_hash
    except Exception:
        pass

    # 4순위: 설정 없음 → None (호출 측에서 처리)
    # 보안: 하드코딩 해시 제거 - Supabase system_config 또는 secrets.toml에 master_admin_pw_hash 설정 필요
    return None

# =================================================================
# 3. Supabase 연결 및 DB 함수
# =================================================================

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def _clear_production_cache() -> None:
    """생산 데이터 캐시만 초기화"""
    load_realtime_ledger.clear()

def _clear_schedule_cache() -> None:
    """일정 캐시만 초기화"""
    load_schedule.clear()

def _clear_plan_cache() -> None:
    """계획 관련 캐시 초기화"""
    load_production_plan.clear()
    load_plan_change_log.clear()

def _clear_master_cache() -> None:
    """모델 마스터 캐시 초기화"""
    load_model_master.clear()

def _clear_audit_cache() -> None:
    """감사 로그 캐시 초기화"""
    load_audit_log.clear()

def keep_supabase_alive() -> None:
    try:
        get_supabase().table("production").select("id").limit(1).execute()
    except Exception as e:
        # 연결 실패 시 사이드바에 경고 (디버깅용)
        st.sidebar.warning(f"⚠️ Supabase 연결 확인 실패: {e}")

# 앱 최초 기동 시 1회만 실행 (30초 자동 새로고침마다 재실행 방지)
if "supabase_alive_checked" not in st.session_state:
    keep_supabase_alive()
    st.session_state["supabase_alive_checked"] = True

def get_now_kst_str() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

@st.cache_data(ttl=10)
def load_realtime_ledger(months: int = 3) -> pd.DataFrame:
    """최근 N개월 데이터만 로드 (기본 3개월, 성능 최적화)"""
    _EMPTY_COLS = ['시간','반','라인','모델','품목코드','시리얼','상태','증상','수리','작업자']
    try:
        sb = get_supabase()
        from datetime import date, timedelta
        cutoff = (date.today().replace(day=1) -
                  timedelta(days=(months-1)*28)).strftime('%Y-%m-%d')
        try:
            # deleted_at IS NULL 필터 적용 (Soft-delete된 행 제외)
            res = (sb.table("production")
                     .select("*")
                     .gte("시간", cutoff)
                     .is_("deleted_at", "null")
                     .order("시간", desc=False)
                     .execute())
        except Exception:
            # deleted_at 컬럼이 없는 경우 필터 없이 조회 (하위 호환)
            res = (sb.table("production")
                     .select("*")
                     .gte("시간", cutoff)
                     .order("시간", desc=False)
                     .execute())
        if res.data:
            df = pd.DataFrame(res.data)
            df = df.drop(columns=[c for c in ['id','created_at','deleted_at','deleted_by'] if c in df.columns])
            return df.fillna("")
        return pd.DataFrame(columns=_EMPTY_COLS)
    except Exception as e:
        # 로그인 후에만 오류 표시 (로그인 화면에서 노출 방지)
        if st.session_state.get('login_status', False):
            st.warning(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=_EMPTY_COLS)

def insert_row(row: dict) -> bool:
    try:
        get_supabase().table("production").insert(row).execute()
        return True
    except Exception as e:
        err_str = str(e)
        if "23505" in err_str or "duplicate key" in err_str or "already exists" in err_str:
            sn = row.get('시리얼', '')
            st.error(f"⚠️ 이미 등록된 시리얼입니다: **{sn}**\n\n동일한 S/N이 이미 생산 이력에 존재합니다. 시리얼을 확인해주세요.")
        else:
            st.error(f"등록 실패: {e}")
        return False

def update_row(시리얼: str, data: dict) -> bool:
    try:
        get_supabase().table("production").update(data).eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"업데이트 실패: {e}"); return False

def delete_all_rows() -> bool:
    """
    ✅ 보안 개선: Soft delete + 백업 자동 생성 + 2단계 확인 강화
    """
    # rerun 이후에도 메시지가 유지되도록 session_state에 수집
    msgs = []
    try:
        sb = get_supabase()
        
        # 1. 백업 생성 (삭제 전 필수)
        backup_time = get_now_kst_str()
        all_data = sb.table("production").select("*").execute()
        
        if all_data.data:
            backup_records = [{
                **record,
                'deleted_at': backup_time,
                'deleted_by': st.session_state.get('user_id', 'unknown')
            } for record in all_data.data]
            
            try:
                sb.table("production_backup").insert(backup_records).execute()
            except Exception as e:
                msgs.append(("warning", f"⚠️ 백업 실패 (데이터 복구 불가능): {e}"))
        
        # 2. Soft Delete (deleted_at 컬럼 사용)
        try:
            sb.table("production").update({
                'deleted_at': backup_time,
                'deleted_by': st.session_state.get('user_id', 'unknown')
            }).is_('deleted_at', 'null').execute()
        except Exception as e:
            msgs.append(("warning", f"⚠️ Soft delete 불가 — Hard delete 실행됨: {e}"))
            sb.table("production").delete().gte("id", 0).execute()
        
        st.session_state['_delete_msgs'] = msgs
        return True
    except Exception as e:
        st.session_state['_delete_msgs'] = [("error", f"삭제 실패: {e}")]
        return False

def delete_production_row_by_sn(시리얼: str) -> bool:
    try:
        get_supabase().table("production").delete().eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"삭제 실패: {e}"); return False

def load_app_setting(key: str):
    """app_settings 테이블에서 값 로드. 없으면 None 반환."""
    try:
        import json as _j
        res = get_supabase().table("app_settings").select("value").eq("key", key).execute()
        if res.data:
            return _j.loads(res.data[0]["value"])
    except Exception:
        pass
    return None

def save_app_setting(key: str, value):
    """app_settings 테이블에 upsert 저장. 성공 시 True, 실패 시 오류 메시지 문자열 반환."""
    try:
        import json as _j
        get_supabase().table("app_settings").upsert(
            {"key": key, "value": _j.dumps(value, ensure_ascii=False)},
            on_conflict="key"
        ).execute()
        return True
    except Exception as e:
        return str(e)

def delete_all_audit_log() -> bool:
    try:
        get_supabase().table("audit_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"감사로그 삭제 실패: {e}"); return False

def delete_audit_log_row(row_id) -> bool:
    try:
        get_supabase().table("audit_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"감사로그 행 삭제 실패: {e}"); return False

def delete_all_material_serial() -> bool:
    try:
        get_supabase().table("material_serial").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"자재시리얼 삭제 실패: {e}"); return False

def delete_material_serial_row(row_id) -> bool:
    try:
        get_supabase().table("material_serial").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"자재시리얼 행 삭제 실패: {e}"); return False

def delete_all_production_schedule() -> bool:
    try:
        get_supabase().table("production_schedule").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"생산일정 삭제 실패: {e}"); return False

def delete_all_plan_change_log() -> bool:
    try:
        get_supabase().table("plan_change_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"계획변경이력 삭제 실패: {e}"); return False

def delete_plan_change_log_row(row_id) -> bool:
    try:
        get_supabase().table("plan_change_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"계획변경이력 행 삭제 실패: {e}"); return False

def delete_all_schedule_change_log() -> bool:
    try:
        get_supabase().table("schedule_change_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"일정변경이력 삭제 실패: {e}"); return False

def delete_schedule_change_log_row(row_id) -> bool:
    try:
        get_supabase().table("schedule_change_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정변경이력 행 삭제 실패: {e}"); return False



@st.cache_data(ttl=60)
def load_schedule() -> pd.DataFrame:
    try:
        sb  = get_supabase()
        res = sb.table("production_schedule").select("*").order("날짜", desc=False).execute()
        if res.data:
            return pd.DataFrame(res.data).fillna("")
        return pd.DataFrame(columns=['id','날짜','반','카테고리','pn','모델명','조립수','출하계획','특이사항','작성자'])
    except Exception as e:
        st.warning(f"일정 로드 실패: {e}")
        return pd.DataFrame(columns=['id','날짜','반','카테고리','pn','모델명','조립수','출하계획','특이사항','작성자'])

# ── 모델 마스터 DB 함수 ──────────────────────────────────────────
@st.cache_data(ttl=300)
def load_model_master() -> pd.DataFrame:
    try:
        res = get_supabase().table("model_master").select("*").execute()
        if res.data:
            return pd.DataFrame(res.data)
        return pd.DataFrame(columns=['id','반','모델명','품목코드'])
    except Exception as e:
        return pd.DataFrame(columns=['id','반','모델명','품목코드'])

def upsert_model_master(반: str, 모델명: str, 품목코드: str) -> bool:
    """반+모델명+품목코드 조합이 없으면 insert, 있으면 스킵 (UNIQUE 제약)"""
    try:
        get_supabase().table("model_master").upsert(
            {"반": 반, "모델명": 모델명, "품목코드": 품목코드},
            on_conflict="반,모델명,품목코드"
        ).execute()
        return True
    except Exception:
        return False

def delete_model_from_master(반: str, 모델명: str) -> bool:
    """반+모델명 전체 삭제 (해당 모델의 모든 품목 포함)"""
    try:
        get_supabase().table("model_master").delete()\
            .eq("반", 반).eq("모델명", 모델명).execute()
        return True
    except Exception:
        return False

def delete_item_from_master(반: str, 모델명: str, 품목코드: str) -> bool:
    """특정 품목코드만 삭제"""
    try:
        get_supabase().table("model_master").delete()\
            .eq("반", 반).eq("모델명", 모델명).eq("품목코드", 품목코드).execute()
        return True
    except Exception:
        return False

def delete_all_master_by_group(반: str) -> bool:
    """특정 반의 모델/품목 전체 삭제"""
    try:
        get_supabase().table("model_master").delete().eq("반", 반).execute()
        return True
    except Exception:
        return False

def sync_master_to_session():
    """DB model_master → session_state group_master_models/items 동기화"""
    df = load_model_master()
    if df.empty:
        return
    models_map = {g: [] for g in PRODUCTION_GROUPS}
    items_map  = {g: {} for g in PRODUCTION_GROUPS}
    # 벡터화: iterrows 대신 groupby 사용
    valid_df = df[df['반'].isin(PRODUCTION_GROUPS)].copy()
    valid_df['반']      = valid_df['반'].astype(str)
    valid_df['모델명']   = valid_df['모델명'].astype(str)
    valid_df['품목코드'] = valid_df['품목코드'].astype(str)
    for g, gdf in valid_df.groupby('반'):
        for m, mdf in gdf.groupby('모델명'):
            models_map[g].append(m)
            items_map[g][m] = [pn for pn in mdf['품목코드'].unique() if pn and pn != 'nan']
    # 기존 session 값과 병합 (수동 등록분 유지)
    for g in PRODUCTION_GROUPS:
        for m in models_map[g]:
            if m not in st.session_state.group_master_models[g]:
                st.session_state.group_master_models[g].append(m)
            if m not in st.session_state.group_master_items[g]:
                st.session_state.group_master_items[g][m] = []
            for pn in items_map[g].get(m, []):
                if pn not in st.session_state.group_master_items[g][m]:
                    st.session_state.group_master_items[g][m].append(pn)

def insert_schedule(row: dict) -> bool:
    try:
        # Supabase에 넣을 컬럼만 추출 (id, created_at 등 자동생성 컬럼 제외)
        allowed = {'날짜', '반', '카테고리', 'pn', '모델명', '조립수', '출하계획', '특이사항', '작성자'}
        clean_row = {k: v for k, v in row.items() if k in allowed}
        # 날짜 문자열 보정
        if '날짜' in clean_row and hasattr(clean_row['날짜'], 'strftime'):
            clean_row['날짜'] = clean_row['날짜'].strftime('%Y-%m-%d')
        get_supabase().table("production_schedule").insert(clean_row).execute()
        # ── 일정 등록 시 해당 반 모델/품목 마스터 자동 등록 ──
        반   = str(clean_row.get('반', '')).strip()
        모델 = str(clean_row.get('모델명', '')).strip()
        pn   = str(clean_row.get('pn', '')).strip()
        if 반 in PRODUCTION_GROUPS and 모델:
            upsert_model_master(반, 모델, pn if pn else 모델)
            if 모델 not in st.session_state.group_master_models.get(반, []):
                st.session_state.group_master_models.setdefault(반, []).append(모델)
            if 모델 not in st.session_state.group_master_items.get(반, {}):
                st.session_state.group_master_items.setdefault(반, {})[모델] = []
            if pn and pn not in st.session_state.group_master_items[반][모델]:
                st.session_state.group_master_items[반][모델].append(pn)
        return True
    except Exception as e:
        st.error(f"일정 등록 실패: {e}")
        return False

def update_schedule(row_id: int, data: dict) -> bool:
    try:
        get_supabase().table("production_schedule").update(data).eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정 수정 실패: {e}"); return False

def delete_schedule(row_id: int) -> bool:
    try:
        get_supabase().table("production_schedule").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정 삭제 실패: {e}"); return False


# ── 감사 로그 ────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_audit_log(limit: int = MAX_AUDIT_LOG_ROWS) -> pd.DataFrame:
    try:
        sb  = get_supabase()
        res = sb.table("audit_log").select("*").order("시간", desc=True).limit(limit).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])
    except Exception:
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])

# ── 생산 계획 수량 (대시보드용) ──────────────────────────────────
@st.cache_data(ttl=300)
def load_production_plan() -> dict:
    """Supabase production_plan 테이블에서 {반_YYYY-MM: 계획수량} 로드"""
    try:
        sb  = get_supabase()
        res = sb.table("production_plan").select("*").execute()
        if res.data:
            return {f"{r['반']}_{r['월']}": int(r.get('계획수량', 0)) for r in res.data}
        return {}
    except Exception:
        return {}

def save_production_plan(반: str, 월: str, 계획수량: int) -> bool:
    """production_plan upsert (반+월 복합키)"""
    try:
        sb = get_supabase()
        sb.table("production_plan").upsert({
            "반": 반, "월": 월, "계획수량": 계획수량
        }, on_conflict="반,월").execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 저장 실패: {e}")
        return False

def delete_production_plan_row(반: str, 월: str) -> bool:
    """production_plan 특정 반+월 행 삭제"""
    try:
        get_supabase().table("production_plan").delete().eq("반", 반).eq("월", 월).execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 삭제 실패: {e}"); return False

def delete_all_production_plan() -> bool:
    """production_plan 전체 삭제"""
    try:
        get_supabase().table("production_plan").delete().neq("반", "").execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 전체 삭제 실패: {e}"); return False


# ── 감사 로그 (Audit Log) ────────────────────────────────────────
def insert_audit_log(시리얼: str, 모델: str, 반: str,
                     이전상태: str, 이후상태: str,
                     작업자: str, 비고: str = "") -> bool:
    """audit_log 테이블에 상태 변경 이력 기록"""
    try:
        sb = get_supabase()
        sb.table("audit_log").insert({
            "시간":    get_now_kst_str(),
            "시리얼":  시리얼,
            "모델":    모델,
            "반":      반,
            "이전상태": 이전상태,
            "이후상태": 이후상태,
            "작업자":  작업자,
            "비고":    비고,
        }).execute()
        return True
    except Exception:
        return False  # 로그 실패는 무시 (주요 흐름 방해 안 함)


# ── 생산 계획 변경 로그 ──────────────────────────────────────────
def insert_plan_change_log(반: str, 월: str, 이전수량: int, 변경수량: int,
                            변경사유: str, 사유상세: str, 작업자: str) -> bool:
    """plan_change_log 테이블에 계획 변경 이력 기록"""
    try:
        sb = get_supabase()
        sb.table("plan_change_log").insert({
            "시간":     get_now_kst_str(),
            "반":       반,
            "월":       월,
            "이전수량": 이전수량,
            "변경수량": 변경수량,
            "증감":     변경수량 - 이전수량,
            "변경사유": 변경사유,
            "사유상세": 사유상세,
            "작업자":   작업자,
        }).execute()
        return True
    except Exception:
        return False

@st.cache_data(ttl=60)
def load_plan_change_log(limit: int = DEFAULT_PAGE_SIZE) -> pd.DataFrame:
    """plan_change_log 최근 N건 조회"""
    try:
        sb  = get_supabase()
        res = sb.table("plan_change_log").select("*").order("시간", desc=True).limit(limit).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])
    except Exception:
        return pd.DataFrame(columns=['시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])


# ── 자재 시리얼 관리 ─────────────────────────────────────────────
def insert_material_serials(메인시리얼: str, 모델: str, 반: str,
                             자재목록: list, 작업자: str) -> bool:
    """material_serial 테이블에 자재 S/N 등록 (메인 1 : 자재 N)"""
    try:
        sb = get_supabase()
        rows = [{
            "시간":     get_now_kst_str(),
            "메인시리얼": 메인시리얼,
            "모델":     모델,
            "반":       반,
            "자재명":   m.get("자재명",""),
            "자재시리얼": m.get("자재시리얼",""),
            "작업자":   작업자,
        } for m in 자재목록 if m.get("자재시리얼","").strip()]
        if rows:
            sb.table("material_serial").insert(rows).execute()
        return True
    except Exception as e:
        st.error(f"자재 시리얼 등록 실패: {e}")
        return False

@st.cache_data(ttl=60)
def load_material_serials(메인시리얼: str = "") -> pd.DataFrame:
    """material_serial 조회. 메인시리얼 지정 시 해당 건만 반환"""
    try:
        sb  = get_supabase()
        q   = sb.table("material_serial").select("*")
        if 메인시리얼:
            q = q.eq("메인시리얼", 메인시리얼)
        res = q.order("시간", desc=False).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
    except Exception:
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])

def search_material_by_sn(자재시리얼: str) -> pd.DataFrame:
    """자재 S/N으로 메인 S/N 역추적"""
    try:
        sb  = get_supabase()
        자재시리얼_cleaned = re.sub(r'[^\w가-힣-]', '', 자재시리얼) if 자재시리얼 else ""
        # SQL Injection 방지: 입력값 검증
        res = sb.table("material_serial").select("*").ilike("자재시리얼", f"%{자재시리얼_cleaned}%").execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def upload_img_to_drive(file_obj, serial_no: str) -> str:
    try:
        gcp_info  = st.secrets["connections"]["gsheets"]
        creds     = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = gcp_info.get("image_folder_id")
        meta      = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media     = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded  = drive_svc.files().create(body=meta, media_body=media, fields='id,webViewLink').execute()
        return uploaded.get('webViewLink', "")
    except Exception as e:
        return "⚠️ 이미지 업로드에 실패했습니다. 관리자에게 문의하세요."

# =================================================================
# 4. 캘린더 다이얼로그
# =================================================================


# ── 일정 변경 로그 ───────────────────────────────────────────────
SCH_CHANGE_REASONS = [
    "(선택 필수)",
    "영업 요구량 변경 (주문 취소)",
    "영업 요구량 변경 (물량 증가)",
    "긴급 주문 (Rush Order)",
    "자재 수급 문제 (입고 지연)",
    "자재 수급 문제 (불량 자재)",
    "설비 고장 / 유지보수",
    "인력 변동 (부족/결원)",
    "품질 문제 (불량 발생)",
    "계획 오입력 수정",
    "기타 (직접 입력)",
]

def insert_schedule_change_log(sch_id: int, 날짜: str, 반: str, 모델명: str,
                                이전내용: str, 변경내용: str,
                                변경사유: str, 사유상세: str, 작업자: str) -> bool:
    """schedule_change_log 테이블에 일정 변경 이력 기록"""
    try:
        sb = get_supabase()
        sb.table("schedule_change_log").insert({
            "시간":     get_now_kst_str(),
            "일정id":   sch_id,
            "날짜":     날짜,
            "반":       반,
            "모델명":   모델명,
            "이전내용": 이전내용,
            "변경내용": 변경내용,
            "변경사유": 변경사유,
            "사유상세": 사유상세,
            "작업자":   작업자,
        }).execute()
        return True
    except Exception:
        return False


# =================================================================
# st.rerun() 사용 가이드
# =================================================================
# ⚠️ st.rerun()은 전체 스크립트를 재실행하므로 성능에 영향을 줍니다.
# 권장 패턴:
#   1. st.session_state 업데이트 후 자연스러운 리렌더링 활용
#   2. 조건문으로 불필요한 rerun 방지
#   3. 연속된 rerun() 호출 금지
# =================================================================


# ╔════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  리팩토링 권장: 이 함수는 332 라인입니다!                      ║
# ║                                                                      ║
# ║  권장 분리 구조:                                                    ║
# ║  1. _day_panel_load_data() - 일일 데이터 로딩 (50 라인)            ║
# ║  2. _day_panel_render_header() - 헤더 렌더링 (40 라인)             ║
# ║  3. _day_panel_render_schedule() - 일정 표시 (100 라인)            ║
# ║  4. _day_panel_handle_actions() - 액션 버튼 처리 (80 라인)         ║
# ║  5. _day_panel_render_summary() - 요약 정보 (60 라인)              ║
# ╚════════════════════════════════════════════════════════════════════╝

def show_inline_day_panel():
    """캘린더 날짜 클릭 시 인라인으로 일정 표시 (dialog 대신)"""
    action      = st.session_state.get("cal_action")
    action_data = st.session_state.get("cal_action_data")
    if not action or not action_data:
        return

    can_edit = st.session_state.user_role in CALENDAR_EDIT_ROLES
    sch_df   = st.session_state.schedule_db

    # ── 패널 컨테이너 ─────────────────────────────────────────
    with st.container(border=True):

        # ── 수정 폼 모드 ──────────────────────────────────────
        if action == "edit":
            sch_id  = action_data
            matched = sch_df[sch_df['id'] == sch_id]
            if matched.empty:
                st.warning("일정을 찾을 수 없습니다.")
                if st.button("닫기", key="inline_edit_notfound_close"):
                    st.session_state.cal_action = None; st.rerun()
                return

            r = matched.iloc[0]
            saved_date = str(r.get('날짜', ''))

            ph1, ph2 = st.columns([8, 1])
            ph1.markdown(f"✏️ **일정 수정** — {saved_date}")
            if ph2.button("✖", key="inline_edit_close"):
                st.session_state.cal_action = None; st.rerun()

            if not can_edit:
                st.info(f"카테고리: {r.get('카테고리','')} / 모델명: {r.get('모델명','')} / 조립수: {r.get('조립수',0)}대")
                return

            save_done_key = f"edit_saved_{sch_id}"
            cur_cat = r.get('카테고리', '조립계획')
            cat_idx = PLAN_CATEGORIES.index(cur_cat) if cur_cat in PLAN_CATEGORIES else 0

            with st.form("edit_sch_form_inline"):
                cat   = st.selectbox("계획 유형 *", PLAN_CATEGORIES, index=cat_idx)
                fe1, fe2 = st.columns(2)
                model = fe1.text_input("모델명", value=str(r.get('모델명', '')))
                pn    = fe2.text_input("P/N",    value=str(r.get('pn', '')))
                ff1, ff2 = st.columns(2)
                qty   = ff1.number_input("조립수", min_value=0, step=1, value=int(r.get('조립수', 0) or 0))
                ship  = ff2.text_input("출하계획", value=str(r.get('출하계획', '')))
                note  = st.text_input("특이사항", value=str(r.get('특이사항', '')))
                etc   = st.text_input("기타")
                st.markdown("---")
                dr1, dr2 = st.columns(2)
                sch_reason = dr1.selectbox("변경 사유 *(필수)", SCH_CHANGE_REASONS, key=f"ie_reason_{sch_id}")
                sch_detail = dr2.text_input("상세 내용", placeholder="예: 고객사 요청", key=f"ie_detail_{sch_id}")
                c1, c2, c3 = st.columns(3)
                save_label = "✅ 저장 완료" if st.session_state.get(save_done_key) else "💾 저장"
                if c1.form_submit_button(save_label, use_container_width=True, type="primary"):
                    if not st.session_state.get(save_done_key):
                        if sch_reason == "(선택 필수)":
                            st.error("변경 사유를 반드시 선택해주세요.")
                        else:
                            note_combined = " / ".join(filter(None, [note.strip(), etc.strip()]))
                            _prev = f"유형:{r.get('카테고리','')} 모델:{r.get('모델명','')} 조립수:{r.get('조립수',0)}"
                            _next = f"유형:{cat} 모델:{model.strip()} 조립수:{int(qty)}"
                            _reason_final = sch_detail.strip() if sch_reason == "기타 (직접 입력)" and sch_detail.strip() else sch_reason
                            update_schedule(sch_id, {
                                '카테고리': cat, 'pn': pn.strip(), '모델명': model.strip(),
                                '조립수': int(qty), '출하계획': ship.strip(), '특이사항': note_combined
                            })
                            insert_schedule_change_log(
                                sch_id=sch_id, 날짜=saved_date,
                                반=str(r.get('반','')), 모델명=model.strip(),
                                이전내용=_prev, 변경내용=_next,
                                변경사유=_reason_final, 사유상세=sch_detail.strip(),
                                작업자=st.session_state.user_id
                            )
                            st.session_state.schedule_db    = load_schedule()
                            st.session_state[save_done_key] = True
                            st.rerun()
                if c2.form_submit_button("🔙 목록으로", use_container_width=True):
                    st.session_state.cal_action      = "view_day"
                    st.session_state.cal_action_data = saved_date
                    st.session_state[save_done_key]  = False
                    st.rerun()
                if c3.form_submit_button("🗑️ 삭제", use_container_width=True):
                    delete_schedule(sch_id)
                    st.session_state.schedule_db    = load_schedule()
                    st.session_state.cal_action     = None
                    st.session_state[save_done_key] = False
                    st.rerun()
            if st.session_state.get(save_done_key):
                st.success("저장되었습니다.")
            return

        # ── 일정 추가 폼 모드 ─────────────────────────────────
        if action == "add":
            selected_date = action_data
            ph1, ph2 = st.columns([8, 1])
            ph1.markdown(f"➕ **일정 추가** — {selected_date}")
            if ph2.button("✖", key="inline_add_close"):
                st.session_state.cal_action = None; st.rerun()

            if not can_edit:
                st.warning("일정 추가 권한이 없습니다.")
                return

            with st.form("add_sch_form_inline"):
                ban   = st.selectbox("반 *", PRODUCTION_GROUPS)
                cat   = st.selectbox("계획 유형 *", PLAN_CATEGORIES)
                fa1, fa2 = st.columns(2)
                model = fa1.text_input("모델명 *")
                pn    = fa2.text_input("P/N (품목코드)")
                fb1, fb2 = st.columns(2)
                qty   = fb1.number_input("조립수", min_value=0, step=1)
                ship  = fb2.text_input("출하계획")
                note  = st.text_input("특이사항")
                etc   = st.text_input("기타")
                if st.form_submit_button("✅ 등록", use_container_width=True, type="primary"):
                    if model.strip() or note.strip():
                        note_combined = " / ".join(filter(None, [note.strip(), etc.strip()]))
                        if insert_schedule({
                            '날짜': selected_date, '반': ban,
                            '카테고리': cat, 'pn': pn.strip(), '모델명': model.strip(),
                            '조립수': int(qty), '출하계획': ship.strip(),
                            '특이사항': note_combined, '작성자': st.session_state.user_id
                        }):
                            st.session_state.schedule_db = load_schedule()
                            st.session_state.cal_action  = "view_day"
                            st.session_state.cal_action_data = selected_date
                            st.rerun()
                    else:
                        st.warning("모델명 또는 특이사항을 입력해주세요.")
            return

        # ── 일정 목록 보기 (view_day) ─────────────────────────
        selected_date = action_data
        day_data = sch_df[sch_df['날짜'] == selected_date] if not sch_df.empty else pd.DataFrame()

        ph1, ph2 = st.columns([8, 1])
        ph1.markdown(
            f"### 📆 {selected_date} &nbsp;<span style='font-size:0.85rem;color:#8a7f72;font-weight:normal;'>총 {len(day_data)}건</span>",
            unsafe_allow_html=True
        )
        if ph2.button("✖ 닫기", key="inline_view_close"):
            st.session_state.cal_action = None; st.rerun()

        if not day_data.empty:
            BAN_COLORS = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}
            for ban in PRODUCTION_GROUPS:
                ban_rows = day_data[day_data['반'] == ban]
                if ban_rows.empty:
                    continue
                ban_color = BAN_COLORS.get(ban, "#7a6f65")
                st.markdown(
                    f"<div style='background:{ban_color}12; border-left:4px solid {ban_color}; "
                    f"padding:7px 14px; border-radius:5px; margin:12px 0 4px 0;'>"
                    f"<span style='color:{ban_color}; font-weight:bold; font-size:0.92rem;'>🏭 {ban}</span>"
                    f"<span style='color:#8a7f72; font-size:0.8rem; margin-left:8px;'>{len(ban_rows)}건</span>"
                    f"</div>", unsafe_allow_html=True
                )
                col_w = [1.8, 2.8, 1.5, 1.2, 1.8, 0.9] if can_edit else [1.8, 2.8, 1.5, 1.2, 2.2]
                hdrs  = ["카테고리", "모델명", "P/N", "조립수", "출하계획"] + (["관리"] if can_edit else [])
                hcols = st.columns(col_w)
                for hc, hl in zip(hcols, hdrs):
                    hc.markdown(
                        f"<p style='color:#8a7f72;font-size:0.72rem;font-weight:bold;margin:0 0 2px;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{hl}</p>",
                        unsafe_allow_html=True
                    )
                for _, r in ban_rows.sort_values('카테고리').iterrows():
                    row_id  = r.get('id', None)
                    cat_v   = str(r.get('카테고리', '기타'))
                    cat_color = SCHEDULE_COLORS.get(cat_v, "#888")
                    def _esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                    model_v = _esc(r.get('모델명', ''))
                    pn_v    = _esc(r.get('pn', ''))
                    ship_v  = _esc(r.get('출하계획', ''))
                    note_v  = _esc(r.get('특이사항', ''))
                    try: qty_v = int(float(r.get('조립수', 0))) if r.get('조립수') not in (None,'','nan') else 0
                    except: qty_v = 0
                    qty_str  = f"{qty_v}대" if qty_v else "-"
                    ship_str = ship_v if ship_v and ship_v != 'nan' else "-"
                    note_str = f" ⚠️ {note_v}" if note_v and note_v not in ('', 'nan') else ""

                    rcols = st.columns(col_w)
                    rcols[0].markdown(f"<span style='background:{cat_color}22;color:{cat_color};font-weight:bold;font-size:0.72rem;padding:1px 6px;border-radius:8px;'>{cat_v}</span>", unsafe_allow_html=True)
                    rcols[1].markdown(f"<p style='font-size:0.78rem;margin:2px 0;color:#2a2420;font-weight:bold;'>{model_v}{note_str}</p>", unsafe_allow_html=True)
                    rcols[2].markdown(f"<p style='font-size:0.75rem;margin:2px 0;color:#5a5048;'>{pn_v or '-'}</p>", unsafe_allow_html=True)
                    rcols[3].markdown(f"<p style='font-size:0.78rem;margin:2px 0;color:#2471a3;font-weight:bold;'>{qty_str}</p>", unsafe_allow_html=True)
                    rcols[4].markdown(f"<p style='font-size:0.75rem;margin:2px 0;color:#5a5048;'>{ship_str}</p>", unsafe_allow_html=True)

                    if can_edit and row_id:
                        confirm_key = f"del_confirm_{row_id}"
                        if not st.session_state.get(confirm_key, False):
                            bc1, bc2 = rcols[5].columns(2)
                            if bc1.button("✏️", key=f"mod_{row_id}", help="수정"):
                                st.session_state.cal_action      = "edit"
                                st.session_state.cal_action_data = int(row_id)
                                st.session_state.cal_action_sub  = None
                                st.rerun()
                            if bc2.button("🗑️", key=f"del_{row_id}", help="삭제"):
                                st.session_state[confirm_key] = True
                                st.rerun()
                        else:
                            st.warning(f"⚠️ [{model_v}] 일정을 삭제하시겠습니까?")
                            y1, y2 = st.columns(2)
                            if y1.button("✅ 예, 삭제", key=f"del_yes_{row_id}", type="primary", use_container_width=True):
                                delete_schedule(int(row_id))
                                st.session_state.schedule_db  = load_schedule()
                                st.session_state[confirm_key] = False
                                st.session_state.cal_action   = None
                                st.rerun()
                            if y2.button("취소", key=f"del_no_{row_id}", use_container_width=True):
                                st.session_state[confirm_key] = False
                                st.rerun()
        else:
            st.info("등록된 일정이 없습니다.")

        if can_edit:
            st.divider()
            if st.button("➕ 이 날짜에 일정 추가", key="inline_add_btn", use_container_width=True, type="primary"):
                st.session_state.cal_action      = "add"
                st.session_state.cal_action_data = selected_date
                st.rerun()

# =================================================================
# 5. 세션 상태 초기화
# =================================================================

if 'schedule_db'     not in st.session_state: st.session_state.schedule_db     = load_schedule()
if 'production_plan' not in st.session_state: st.session_state.production_plan = load_production_plan()
if 'production_db'   not in st.session_state: st.session_state.production_db   = pd.DataFrame()
if 'cal_year'         not in st.session_state: st.session_state.cal_year         = datetime.now(KST).year
if 'cal_month'        not in st.session_state: st.session_state.cal_month        = datetime.now(KST).month
if 'cal_month_year'   not in st.session_state: st.session_state.cal_month_year   = datetime.now(KST).year
if 'cal_month_month'  not in st.session_state: st.session_state.cal_month_month  = datetime.now(KST).month
if 'cal_view'        not in st.session_state: st.session_state.cal_view        = "주별"
if 'cal_week_idx'    not in st.session_state: st.session_state.cal_week_idx    = 0
# ── 드롭박스 옵션 기본값 ──────────────────────────────────────────
_DD_DEFAULTS = {
    "dropdown_oqc_defect": [
        "(선택)",
        "외관 불량 (스크래치/변형)", "기능 불량 (동작 이상)",
        "라벨 / 刻印 오류", "포장 불량", "치수 불량",
        "이물질 혼입", "수량 부족", "서류 오류",
        "기타 (직접 입력)",
    ],
    "dropdown_defect_cause": [
        "(선택)",
        "납땜 불량", "부품 미삽", "부품 오삽", "부품 불량",
        "기구 파손", "기구 간섭", "나사 체결 불량",
        "소프트웨어 오류", "펌웨어 오류", "설정 오류",
        "외관 불량 (스크래치)", "외관 불량 (변형)",
        "통신 불량", "전원 불량", "센서 불량",
        "기타 (직접 입력)",
    ],
    "dropdown_repair_action": [
        "(선택)",
        "재납땜", "부품 교체", "부품 재삽입",
        "기구 교체", "나사 재체결",
        "펌웨어 재설치", "소프트웨어 초기화", "설정 재조정",
        "외관 교체", "세척 후 재검사",
        "재검사 후 양품 확인", "폐기 처리",
        "기타 (직접 입력)",
    ],
    "dropdown_mat_name": [
        "PCB", "배터리", "메인보드", "디스플레이",
        "케이블", "모듈", "센서", "커넥터", "기타",
    ],
}
for _dd_key, _dd_default in _DD_DEFAULTS.items():
    if _dd_key not in st.session_state:
        _loaded = load_app_setting(_dd_key)
        st.session_state[_dd_key] = _loaded if _loaded is not None else _dd_default
if 'cal_action'      not in st.session_state: st.session_state.cal_action      = None
if 'cal_action_data' not in st.session_state: st.session_state.cal_action_data = None
if 'cal_action_sub'      not in st.session_state: st.session_state.cal_action_sub      = None
if 'cal_action_sub_data' not in st.session_state: st.session_state.cal_action_sub_data = None

if 'user_db' not in st.session_state:
    # ✅ 보안 개선: secrets.toml에서 비밀번호 해시 로드
    # .streamlit/secrets.toml에 다음 내용 추가 필요:
    # [default_users]
    # admin_hash = "your_bcrypt_hash_here"
    # master_hash = "your_bcrypt_hash_here"
    # control_tower_hash = "your_bcrypt_hash_here"
    
    try:
        # Supabase에서 사용자 정보 로드 시도
        sb = get_supabase()
        # users 테이블에서 로드
        result = sb.table("users").select("*").execute()
        if result.data:
            # DB에서 로드 성공
            import json as _json
            st.session_state.user_db = {
                user['username']: {
                    'pw_hash': user['password_hash'],
                    'role': user['role'],
                    **({'custom_permissions': _json.loads(user['custom_permissions'])}
                       if user.get('custom_permissions') else {})
                }
                for user in result.data
            }
        else:
            # DB에 데이터 없으면 기본값 (환경변수에서)
            st.session_state.user_db = {
                "admin": {"pw_hash": st.secrets.get("default_users", {}).get("admin_hash", hash_pw("CHANGE_ME_NOW")), "role": "admin"},
            }
    except Exception as e:
        # Supabase 연결 실패 시 임시 계정 (경고 표시)
        # 보안: 평문 비밀번호 하드코딩 제거 → secrets.toml 또는 환경변수에서 해시 로드
        st.sidebar.warning("⚠️ Supabase 연결 실패: 로컬 임시 계정으로 실행 중입니다.")
        _fb_users = {}
        try:
            _fb_cfg = st.secrets.get("fallback_users", {})
            if _fb_cfg.get("master_hash"):
                _fb_users["master"] = {"pw_hash": _fb_cfg["master_hash"], "role": "master"}
            if _fb_cfg.get("admin_hash"):
                _fb_users["admin"] = {"pw_hash": _fb_cfg["admin_hash"], "role": "admin"}
        except Exception:
            pass
        if not _fb_users:
            st.sidebar.error("❌ Supabase 미연결 & 임시 계정 미설정: secrets.toml에 [fallback_users] 섹션을 추가하세요.")
        st.session_state.user_db = _fb_users

if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {"제조1반": [], "제조2반": [], "제조3반": []}

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {"제조1반": {}, "제조2반": {}, "제조3반": {}}

# DB model_master → session 동기화 (앱 시작 시 1회)
if 'master_synced' not in st.session_state:
    sync_master_to_session()
    st.session_state.master_synced = True

if 'login_status'        not in st.session_state: st.session_state.login_status        = False
if 'user_role'           not in st.session_state: st.session_state.user_role           = None
if 'user_id'             not in st.session_state: st.session_state.user_id             = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'selected_group'      not in st.session_state: st.session_state.selected_group      = "제조2반"
if 'current_line'        not in st.session_state: st.session_state.current_line        = "현황판"
if 'confirm_target'      not in st.session_state: st.session_state.confirm_target      = None
if 'wait_checked'        not in st.session_state: st.session_state.wait_checked        = {}
if 'wait_scan_cnt'       not in st.session_state: st.session_state.wait_scan_cnt       = {}

# =================================================================
# 6. 로그인
# =================================================================

if not st.session_state.login_status:
    _, c_col, _ = st.columns([1, 1.2, 1])
    with c_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("gate_login"):
            in_id = st.text_input("아이디(ID)")
            in_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 시작", use_container_width=True):
                # ── 로그인 시도 제한 (Brute-force 방어) ──
                _now_ts = datetime.now(KST).timestamp()
                _attempt_key = f"login_attempts_{in_id}"
                _lockout_key = f"login_lockout_{in_id}"
                _lockout_until = st.session_state.get(_lockout_key, 0)
                if _now_ts < _lockout_until:
                    _remain = int(_lockout_until - _now_ts)
                    st.error(f"⛔ 로그인 잠금 중입니다. {_remain}초 후 다시 시도하세요.")
                    st.stop()
                user_info = st.session_state.user_db.get(in_id)
                if user_info and verify_pw(in_pw, user_info["pw_hash"]):
                    # 로그인 성공 → 시도 카운터 초기화
                    st.session_state[_attempt_key] = 0
                    # bcrypt 설치 후 최초 로그인 시 SHA-256 → bcrypt 자동 업그레이드
                    if _BCRYPT_AVAILABLE and not user_info["pw_hash"].startswith("$2"):
                        new_hash = hash_pw(in_pw)
                        st.session_state.user_db[in_id]["pw_hash"] = new_hash
                        try:
                            get_supabase().table("users").update(
                                {"password_hash": new_hash}
                            ).eq("username", in_id).execute()
                        except Exception:
                            pass  # 업그레이드 실패해도 로그인은 허용
                    # 역할 유효성 검사 (허용되지 않은 role이면 로그인 차단)
                    _role = user_info.get("role", "")
                    if _role not in ROLES:
                        st.error(f"❌ 허용되지 않은 계정 권한입니다. (role={_role})")
                        st.stop()
                    st.session_state.login_status  = True
                    st.session_state.user_id       = in_id
                    st.session_state.user_role     = _role
                    # ✨ 커스텀 권한 적용
                    st.session_state.user_custom_permissions = user_info.get("custom_permissions", None)
                    st.session_state.production_db = load_realtime_ledger()
                    st.session_state.schedule_db   = load_schedule()
                    st.rerun()
                else:
                    _attempts = st.session_state.get(_attempt_key, 0) + 1
                    st.session_state[_attempt_key] = _attempts
                    _remain_attempts = MAX_LOGIN_ATTEMPTS - _attempts
                    if _attempts >= MAX_LOGIN_ATTEMPTS:
                        st.session_state[_lockout_key] = _now_ts + LOGIN_LOCKOUT_SECONDS
                        st.error(f"⛔ 로그인 {MAX_LOGIN_ATTEMPTS}회 실패로 {LOGIN_LOCKOUT_SECONDS//60}분 동안 잠금됩니다.")
                    else:
                        st.error(f"로그인 정보가 올바르지 않습니다. (남은 시도: {_remain_attempts}회)")
    st.stop()

# =================================================================
# 7. 사이드바
# =================================================================

def clear_cal() -> None:
    st.session_state.cal_action      = None
    st.session_state.cal_action_data = None

st.sidebar.markdown("### 🏭 생산 관리 시스템 v22.3")
st.sidebar.markdown(f"**{ROLE_LABELS.get(st.session_state.user_role, '')}**")
st.sidebar.caption(f"ID: {st.session_state.user_id}")
st.sidebar.divider()

# ✨ 커스텀 권한이 있으면 우선 적용, 없으면 기본 역할 권한
allowed_nav = st.session_state.get("user_custom_permissions", None)
if allowed_nav is None:
    allowed_nav = ROLES.get(st.session_state.user_role, [])

if st.sidebar.button("🏠 메인 현황판", use_container_width=True,
    type="primary" if st.session_state.current_line == "현황판" else "secondary"):
    clear_cal()
    st.session_state.production_db = load_realtime_ledger()
    st.session_state.schedule_db   = load_schedule()
    st.session_state.current_line  = "현황판"
    st.rerun()

if "생산 지표 관리" in allowed_nav:
    if st.sidebar.button("📡 생산 지표 관리", use_container_width=True,
        type="primary" if st.session_state.current_line == "생산 지표 관리" else "secondary"):
        clear_cal()
        st.session_state.production_db = load_realtime_ledger()
        st.session_state.schedule_db   = load_schedule()
        st.session_state.current_line  = "생산 지표 관리"
        st.rerun()

st.sidebar.divider()

for group in PRODUCTION_GROUPS:
    exp = (st.session_state.selected_group == group
           and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=exp):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in allowed_nav:
                active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True,
                             type="primary" if active else "secondary"):
                    clear_cal()
                    st.session_state.selected_group = group
                    st.session_state.current_line   = p
                    st.session_state.production_db  = load_realtime_ledger()
                    st.rerun()
        if group == PRODUCTION_GROUPS[-1] and "불량 공정" in allowed_nav:
            if st.sidebar.button("🚫 불량 공정", key="nav_defect", use_container_width=True,
                type="primary" if st.session_state.current_line == "불량 공정" else "secondary"):
                clear_cal()
                st.session_state.current_line  = "불량 공정"
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
        if group == PRODUCTION_GROUPS[-1] and "OQC 라인" in allowed_nav:
            if st.sidebar.button("🏅 OQC 라인", key="nav_oqc", use_container_width=True,
                type="primary" if st.session_state.current_line == "OQC 라인" else "secondary"):
                clear_cal()
                st.session_state.current_line  = "OQC 라인"
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()

st.sidebar.divider()

for p in ["생산 현황 리포트", "수리 현황 리포트"]:
    if p in allowed_nav:
        if st.sidebar.button(p, key=f"fnav_{p}", use_container_width=True,
            type="primary" if st.session_state.current_line == p else "secondary"):
            clear_cal()
            st.session_state.current_line  = p
            st.session_state.production_db = load_realtime_ledger()
            st.rerun()

if "마스터 관리" in allowed_nav:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True,
        type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"):
        clear_cal()
        st.session_state.current_line = "마스터 관리"
        st.rerun()

if "작업자 매뉴얼" in allowed_nav or "관리자 매뉴얼" in allowed_nav:
    st.sidebar.divider()
if "작업자 매뉴얼" in allowed_nav:
    if st.sidebar.button("📖 작업자 매뉴얼", use_container_width=True,
        type="primary" if st.session_state.current_line == "작업자 매뉴얼" else "secondary"):
        clear_cal()
        st.session_state.current_line = "작업자 매뉴얼"
        st.rerun()
if "관리자 매뉴얼" in allowed_nav:
    if st.sidebar.button("🔐 관리자 매뉴얼", use_container_width=True,
        type="primary" if st.session_state.current_line == "관리자 매뉴얼" else "secondary"):
        clear_cal()
        st.session_state.current_line = "관리자 매뉴얼"
        st.rerun()

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for k in ['login_status','user_role','user_id','admin_authenticated']:
        st.session_state[k] = False if k == 'login_status' else None
    st.rerun()

# =================================================================
# 8. 입고 확인 다이얼로그
# =================================================================

# 입고 확인 → 인라인 처리 (show_inline_entry_confirm 에서 렌더링)
def _do_batch_entry(sn_list, curr_line):
    """sn_list의 시리얼들을 일괄 입고 처리"""
    _next_status = '검사중' if curr_line == '검사 라인' else '포장중'
    _prev_status = '검사대기' if curr_line == '검사 라인' else '출하승인'
    db = st.session_state.production_db
    for sn in sn_list:
        _row = db[db['시리얼'] == sn]
        _model = _row.iloc[0]['모델'] if not _row.empty else ''
        _ban   = _row.iloc[0]['반']   if not _row.empty else ''
        update_row(sn, {'시간': get_now_kst_str(), '라인': curr_line,
                        '상태': _next_status, '작업자': st.session_state.user_id})
        insert_audit_log(시리얼=sn, 모델=_model, 반=_ban,
            이전상태=_prev_status, 이후상태=_next_status, 작업자=st.session_state.user_id)
    st.session_state.production_db = load_realtime_ledger()

# 캘린더 인라인 패널 → 캘린더 렌더링 직후에 호출 (아래 메인 현황판 섹션 참조)

# =================================================================
# 9. 캘린더 렌더링
# =================================================================

# 공통 셀 렌더링 헬퍼
def _render_cal_cells(sch_df, cal_year, cal_month, weeks_to_show, today, can_edit, key_prefix):
    days_kr  = ["일","월","화","수","목","금","토"]
    hdr_cols = st.columns(7)
    for i, d in enumerate(days_kr):
        color = "#e8908a" if i == 0 else "#7eb8e8" if i == 6 else "#7a6f65"
        hdr_cols[i].markdown(
            f"<div style='text-align:center; font-weight:bold; color:{color}; "
            f"padding:8px; background:#ede8de; border-radius:6px;'>{d}</div>",
            unsafe_allow_html=True)

    for week in weeks_to_show:
        week_cols = st.columns(7)
        for i, day in enumerate(week):
            with week_cols[i]:
                if day == 0:
                    st.markdown("<div style='min-height:100px;'></div>", unsafe_allow_html=True)
                    continue

                day_str   = f"{cal_year}-{cal_month:02d}-{day:02d}"
                day_data  = sch_df[sch_df['날짜'] == day_str] if not sch_df.empty else pd.DataFrame()
                is_today  = (today == date(cal_year, cal_month, day))
                bg        = "#d8ede2" if is_today else "#fffdf8"
                border    = "2px solid #7ec8a0" if is_today else "1px solid #e0d8c8"
                today_cls = " today" if is_today else ""

                # 카테고리별 건수 집계 (벡터화)
                cat_counts = {}
                event_count = 0
                if not day_data.empty:
                    _cat_col = day_data['카테고리'].fillna('기타').astype(str).replace('', '기타')
                    cat_counts = _cat_col.value_counts().to_dict()
                    event_count = len(day_data)

                today_mark = " 🟢" if is_today else ""
                btn_label  = f"{day}{today_mark}"

                # ── 날짜 버튼
                day_cls = "cal-today-btn" if is_today else "cal-day-btn"
                st.markdown(f"<div class='{day_cls}'>", unsafe_allow_html=True)
                if st.button(btn_label, key=f"{key_prefix}_{day_str}", use_container_width=True):
                    st.session_state.cal_action      = "view_day"
                    st.session_state.cal_action_data = day_str
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

                # ── 카테고리별 뱃지 (건수만)
                if cat_counts:
                    badge_html = "<div style='margin-top:3px; display:flex; flex-direction:column; gap:2px;'>"
                    for cat, cnt in cat_counts.items():
                        color = SCHEDULE_COLORS.get(cat, "#888")
                        badge_html += (
                            f"<div style='background:{color}18; border-left:3px solid {color}; "
                            f"border-radius:3px; padding:2px 5px; font-size:0.65rem; line-height:1.4;'>"
                            f"<span style='color:{color}; font-weight:bold;'>{cat}</span> "
                            f"<span style='color:#5a5048; font-weight:bold;'>{cnt}건</span>"
                            f"</div>"
                        )
                    badge_html += "</div>"
                    st.markdown(badge_html, unsafe_allow_html=True)


# ── 범례 공통
def _render_legend():
    legend_html = "<div style='display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px;'>"
    for cat, color in SCHEDULE_COLORS.items():
        legend_html += f"<span style='background:{color}; color:#fff; padding:3px 10px; border-radius:12px; font-size:0.75rem; font-weight:bold;'>{cat}</span>"
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

# ── 주별 캘린더
def render_calendar_weekly():
    sch_df    = st.session_state.schedule_db
    cal_year  = st.session_state.cal_year
    cal_month = st.session_state.cal_month
    can_edit  = st.session_state.user_role in CALENDAR_EDIT_ROLES
    today     = date.today()
    cal_weeks = calendar.monthcalendar(cal_year, cal_month)

    # 현재 주 자동 탐색
    if cal_year == today.year and cal_month == today.month:
        for wi, week in enumerate(cal_weeks):
            if today.day in week:
                if st.session_state.get('cal_auto_week', True):
                    st.session_state.cal_week_idx  = wi
                    st.session_state.cal_auto_week = False
                break

    week_idx = min(st.session_state.cal_week_idx, len(cal_weeks)-1)
    exp_label = f"📅 주별 캘린더  —  {cal_year}년 {cal_month}월 {week_idx+1}주차"

    with st.expander(exp_label, expanded=True):
        # 월 네비게이션
        h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
        if h1.button("◀ 이전달", key="w_prev_month", use_container_width=True):
            clear_cal()
            if cal_month == 1: st.session_state.cal_year -= 1; st.session_state.cal_month = 12
            else: st.session_state.cal_month -= 1
            st.session_state.cal_week_idx = 0
            st.rerun()
        if h2.button("오늘", key="w_today", use_container_width=True):
            clear_cal()
            st.session_state.cal_year      = today.year
            st.session_state.cal_month     = today.month
            st.session_state.cal_auto_week = True
            st.rerun()
        h3.markdown(
            f"<p style='text-align:center; font-weight:bold; margin:8px 0; font-size:1rem;'>"
            f"{cal_year}년 {cal_month}월 {week_idx+1}주차</p>",
            unsafe_allow_html=True)
        if h4.button("다음달 ▶", key="w_next_month", use_container_width=True):
            clear_cal()
            if cal_month == 12: st.session_state.cal_year += 1; st.session_state.cal_month = 1
            else: st.session_state.cal_month += 1
            st.session_state.cal_week_idx = 0
            st.rerun()

        # 주 네비게이션
        w1, w2, w3 = st.columns([1, 4, 1])
        if w1.button("◀ 이전주", key="w_prev_week", use_container_width=True):
            clear_cal()
            if st.session_state.cal_week_idx > 0:
                st.session_state.cal_week_idx -= 1
            else:
                if cal_month == 1: st.session_state.cal_year -= 1; st.session_state.cal_month = 12
                else: st.session_state.cal_month -= 1
                prev_weeks = calendar.monthcalendar(st.session_state.cal_year, st.session_state.cal_month)
                st.session_state.cal_week_idx = len(prev_weeks) - 1
            st.rerun()
        w2.markdown(
            f"<p style='text-align:center; color:#8a7f72; margin:8px 0;'>"
            f"{cal_year}년 {cal_month}월 {week_idx+1}주차</p>",
            unsafe_allow_html=True)
        if w3.button("다음주 ▶", key="w_next_week", use_container_width=True):
            clear_cal()
            if st.session_state.cal_week_idx < len(cal_weeks) - 1:
                st.session_state.cal_week_idx += 1
            else:
                if cal_month == 12: st.session_state.cal_year += 1; st.session_state.cal_month = 1
                else: st.session_state.cal_month += 1
                st.session_state.cal_week_idx = 0
            st.rerun()

        _render_legend()
        _render_cal_cells(sch_df, cal_year, cal_month,
                          [cal_weeks[week_idx]], today, can_edit, "wk")

# ── 월별 캘린더

# ╔════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  리팩토링 필요: 이 함수는 864 라인입니다!                      ║
# ║                                                                      ║
# ║  권장 분리 구조:                                                    ║
# ║  1. _calendar_load_schedule() - 스케줄 데이터 로딩 (50 라인)       ║
# ║  2. _calendar_render_navigation() - 월/주 네비게이션 (80 라인)     ║
# ║  3. _calendar_render_legend() - 범례 표시 (30 라인)                ║
# ║  4. _calendar_render_grid() - 달력 그리드 렌더링 (200 라인)        ║
# ║  5. _calendar_handle_cell_click() - 셀 클릭 이벤트 (100 라인)      ║
# ║  6. _calendar_handle_edit() - 일정 편집 (150 라인)                 ║
# ║  7. _calendar_save_changes() - 변경사항 저장 (100 라인)            ║
# ╚════════════════════════════════════════════════════════════════════╝

def render_calendar_monthly(
    # ⚠️ 리팩토링 권장: 이 함수는 390+ 라인으로 다음과 같이 분리 권장:
    # - render_calendar_header(): 헤더 렌더링
    # - render_calendar_cells(): 셀 렌더링
    # - handle_calendar_events(): 이벤트 처리
    # - save_calendar_changes(): 변경사항 저장
    ):
    sch_df    = st.session_state.schedule_db
    cal_year  = st.session_state.cal_month_year  if 'cal_month_year'  in st.session_state else st.session_state.cal_year
    cal_month = st.session_state.cal_month_month if 'cal_month_month' in st.session_state else st.session_state.cal_month
    can_edit  = st.session_state.user_role in CALENDAR_EDIT_ROLES
    today     = date.today()
    cal_weeks = calendar.monthcalendar(cal_year, cal_month)

    exp_label = f"🗓️ 월별 캘린더  —  {cal_year}년 {cal_month}월 전체"

    with st.expander(exp_label, expanded=False):
        h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
        if h1.button("◀ 이전달", key="m_prev_month", use_container_width=True):
            clear_cal()
            if cal_month == 1: st.session_state.cal_month_year = cal_year - 1; st.session_state.cal_month_month = 12
            else: st.session_state.cal_month_year = cal_year; st.session_state.cal_month_month = cal_month - 1
            st.rerun()
        if h2.button("오늘", key="m_today", use_container_width=True):
            clear_cal()
            st.session_state.cal_month_year  = today.year
            st.session_state.cal_month_month = today.month
            st.rerun()
        h3.markdown(
            f"<p style='text-align:center; font-weight:bold; margin:8px 0; font-size:1rem;'>"
            f"{cal_year}년 {cal_month}월 전체</p>",
            unsafe_allow_html=True)
        if h4.button("다음달 ▶", key="m_next_month", use_container_width=True):
            clear_cal()
            if cal_month == 12: st.session_state.cal_month_year = cal_year + 1; st.session_state.cal_month_month = 1
            else: st.session_state.cal_month_year = cal_year; st.session_state.cal_month_month = cal_month + 1
            st.rerun()

        _render_legend()
        _render_cal_cells(sch_df, cal_year, cal_month,
                          cal_weeks, today, can_edit, "mo")

# =================================================================
# 10. 페이지 렌더링
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# ── 현황판 ──────────────────────────────────────────────────────
if curr_l == "현황판":
    st.markdown("<h2 class='centered-title'>🏭 생산 통합 현황판</h2>", unsafe_allow_html=True)
    st.caption(f"🕐 마지막 업데이트: {get_now_kst_str()}")

    db_all = st.session_state.production_db

    # 차트 (데이터 있을 때만)
    if not db_all.empty:
        st.markdown("<div class='section-title'>📈 실시간 차트</div>", unsafe_allow_html=True)
        ch1, ch2, ch3 = st.columns([2.5, 1.5, 1.2])
        with ch1:
            fig = px.bar(
                db_all.groupby(['반','라인']).size().reset_index(name='수량'),
                x='라인', y='수량', color='반', barmode='group',
                title="반별 공정 진행 현황", template="plotly_white"
            )
            fig.update_yaxes(dtick=1)
            fig.update_layout(
                margin=dict(t=50, b=50, l=20, r=20),
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                title=dict(font=dict(size=13), x=0, xanchor='left', pad=dict(t=4))
            )
            st.plotly_chart(fig, use_container_width=True, key="dashboard_bar")
        with ch2:
            fig2 = px.pie(
                db_all.groupby('상태').size().reset_index(name='수량'),
                values='수량', names='상태', hole=0.5, title="<b>전체 상태 비중</b>"
            )
            fig2.update_layout(margin=dict(t=40,b=20))
            st.plotly_chart(fig2, use_container_width=True, key="dashboard_pie")
        with ch3:
            fig3 = px.bar(
                db_all.groupby('반').size().reset_index(name='수량'),
                x='반', y='수량', color='반',
                title="<b>반별 총 투입</b>", template="plotly_white"
            )
            fig3.update_yaxes(dtick=1)
            fig3.update_layout(margin=dict(t=40,b=20), showlegend=False)
            st.plotly_chart(fig3, use_container_width=True, key="dashboard_bar2")

    st.divider()

    # 요약 카드 (6열로 넓게)
    st.markdown("<div class='section-title'>📊 전체 반 생산 요약</div>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    total      = len(db_all)
    completed  = len(db_all[(db_all['라인']=='포장 라인')&(db_all['상태']=='완료')])
    in_prog    = len(db_all[db_all['상태']=='진행 중'])
    defects    = len(db_all[db_all['상태'].str.contains('불량',na=False)])
    col1.markdown(f"<div class='stat-box'><div class='stat-label'>📦 총 투입</div><div class='stat-value'>{total}</div></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 최종 완료</div><div class='stat-value'>{completed}</div></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='stat-box'><div class='stat-label'>🏗️ 작업 중</div><div class='stat-value'>{in_prog}</div></div>", unsafe_allow_html=True)
    col4.markdown(f"<div class='stat-box'><div class='stat-label'>🚨 불량 이슈</div><div class='stat-value'>{defects}</div></div>", unsafe_allow_html=True)

    st.divider()

    # 반별 현황 카드
    st.markdown("<div class='section-title'>🏭 반별 생산 현황</div>", unsafe_allow_html=True)
    cards_html = "<div style='display:flex; gap:16px; width:100%; box-sizing:border-box;'>"
    for g in PRODUCTION_GROUPS:
        gdf  = db_all[db_all['반'] == g]
        완료 = len(gdf[(gdf['라인']=='포장 라인')&(gdf['상태']=='완료')])
        재공 = len(gdf[gdf['상태'].isin(['조립중','검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중'])])
        불량 = len(gdf[gdf['상태'].str.contains('불량',na=False)])
        투입 = len(gdf)
        cards_html += (
            f"<div style='flex:1; background:#fffdf8; border:1px solid #e0d8c8; border-radius:14px; padding:20px; box-sizing:border-box; min-width:0;'>"
            f"<div style='font-size:clamp(1rem,1.5vw,1.2rem); font-weight:bold; margin-bottom:14px; color:#3d3530;'>📍 {g}</div>"
            f"<div style='background:#f5f0e8; border-radius:10px; padding:14px; text-align:center; margin-bottom:12px;'>"
            f"<div style='font-size:clamp(0.65rem,1vw,0.85rem); color:#8a7f72; font-weight:bold; margin-bottom:6px;'>총 투입</div>"
            f"<div style='font-size:clamp(1.5rem,3vw,2.5rem); color:#5a96c8; font-weight:bold;'>{투입} EA</div></div>"
            f"<div style='display:flex; gap:8px;'>"
            f"<div style='flex:1; background:#f5f0e8; border-radius:10px; padding:12px 4px; text-align:center; min-width:0;'>"
            f"<div style='font-size:clamp(0.6rem,0.9vw,0.78rem); color:#8a7f72; font-weight:bold;'>✅ 완료</div>"
            f"<div style='font-size:clamp(1.2rem,2.5vw,2rem); color:#4da875; font-weight:bold;'>{완료}</div></div>"
            f"<div style='flex:1; background:#f5f0e8; border-radius:10px; padding:12px 4px; text-align:center; min-width:0;'>"
            f"<div style='font-size:clamp(0.6rem,0.9vw,0.78rem); color:#8a7f72; font-weight:bold;'>🏗️ 작업중</div>"
            f"<div style='font-size:clamp(1.2rem,2.5vw,2rem); color:#5a96c8; font-weight:bold;'>{재공}</div></div>"
            f"<div style='flex:1; background:#f5f0e8; border-radius:10px; padding:12px 4px; text-align:center; min-width:0;'>"
            f"<div style='font-size:clamp(0.6rem,0.9vw,0.78rem); color:#8a7f72; font-weight:bold;'>🚨 불량</div>"
            f"<div style='font-size:clamp(1.2rem,2.5vw,2rem); color:#c8605a; font-weight:bold;'>{불량}</div></div>"
            f"</div></div>"
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)

    if db_all.empty:
        st.info("등록된 생산 데이터가 없습니다.")

    st.divider()

    # 캘린더
    st.markdown("<div class='section-title'>📅 생산 일정 캘린더</div>", unsafe_allow_html=True)
    if st.session_state.user_role in CALENDAR_EDIT_ROLES:
        st.caption("✏️ 날짜 버튼 클릭 → 일정 상세/추가/수정/삭제")
    else:
        st.caption("👁️ 조회만 가능합니다.")
    render_calendar_weekly()
    render_calendar_monthly()

    # ── 일정 상세 인라인 패널 (날짜 클릭 시 캘린더 바로 아래 표시) ──
    if st.session_state.get("cal_action") in ("view_day", "add", "edit"):
        show_inline_day_panel()

# ── 조립 라인 ────────────────────────────────────────────────────
elif curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 신규 조립 현황</h2>", unsafe_allow_html=True)

    # ── 오늘 일정 알림 & 팝업 ─────────────────────────────────
    today_str   = datetime.now(KST).strftime('%Y-%m-%d')
    sch_all     = st.session_state.schedule_db
    # 조립 라인은 조립계획만, 포장 라인은 포장계획만 표시
    LINE_SCH_FILTER = {"조립 라인": "조립계획", "포장 라인": "포장계획"}
    sch_cat_filter  = LINE_SCH_FILTER.get(curr_l)
    if not sch_all.empty:
        _mask = (sch_all['날짜'] == today_str) & (sch_all['반'] == curr_g)
        if sch_cat_filter:
            _mask = _mask & (sch_all['카테고리'] == sch_cat_filter)
        today_sch = sch_all[_mask]
    else:
        today_sch = pd.DataFrame()

    # 변경 감지: 마지막 확인 이후 등록된 일정
    last_seen_key = f"sch_last_seen_{curr_g}"
    if last_seen_key not in st.session_state:
        st.session_state[last_seen_key] = ""
    sch_ids_now   = ",".join(sorted(str(i) for i in today_sch['id'].tolist())) if not today_sch.empty else ""
    has_new_sch   = (sch_ids_now != st.session_state[last_seen_key]) and not today_sch.empty

    # 변경 알림 팝업
    if has_new_sch and not st.session_state.get(f"sch_popup_dismissed_{curr_g}", False):
        with st.container():
            st.warning(f"🔔 오늘 생산 일정이 등록/변경되었습니다!\n\n{today_str} 기준 **{curr_g}** 일정 **{len(today_sch)}건**이 있습니다. 아래에서 확인하세요.")
            ack_c1, ack_c2 = st.columns([3, 1])
            if ack_c2.button("✅ 확인했습니다", key=f"sch_ack_{curr_g}", use_container_width=True, type="primary"):
                st.session_state[last_seen_key] = sch_ids_now
                st.session_state[f"sch_popup_dismissed_{curr_g}"] = True
                st.rerun()

    # 오늘 일정 카드
    _today_label = f"📋 오늘({today_str}) {curr_g} 작업 일정" + (f"  ·  {len(today_sch)}건" if not today_sch.empty else "  ·  없음")
    with st.expander(_today_label, expanded=True):
        if today_sch.empty:
            st.info("오늘 등록된 작업 일정이 없습니다.")
        else:
            th = st.columns([1.2, 2.8, 1.5, 0.8, 1.8, 2.5])
            for col, txt in zip(th, ["유형", "모델명", "P/N", "조립수", "출하계획", "특이사항"]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:2px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
            for _, sr in today_sch.iterrows():
                cat   = str(sr.get('카테고리', '기타'))
                color = SCHEDULE_COLORS.get(cat, "#888")
                model = str(sr.get('모델명', ''))
                pn    = str(sr.get('pn', ''))
                qty   = sr.get('조립수', 0)
                try:
                    qty = int(float(qty)) if qty not in (None, '', 'nan') else 0
                except (ValueError, TypeError):
                    qty = 0
                ship  = str(sr.get('출하계획', ''))
                note  = str(sr.get('특이사항', ''))
                rc = st.columns([1.2, 2.8, 1.5, 0.8, 1.8, 2.5])
                rc[0].markdown(f"<span style='background:{color}22;color:{color};border-left:3px solid {color};padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{cat}</span>", unsafe_allow_html=True)
                rc[1].write(model)
                rc[2].caption(pn if pn and pn != 'nan' else "-")
                rc[3].write(f"**{qty:,}**")
                rc[4].caption(ship if ship and ship != 'nan' else "-")
                rc[5].caption(f"⚠️ {note}" if note and note != 'nan' else "-")

    # 이번 달 전체 일정
    with st.expander(f"📅 {curr_g} 이번 달 전체 일정 보기", expanded=False):
        month_sch = sch_all[
            (sch_all['날짜'].str.startswith(today_str[:7])) &
            (sch_all['반'] == curr_g)
        ] if not sch_all.empty else pd.DataFrame()
        if not month_sch.empty:
            show_cols = ['날짜','카테고리','모델명','pn','조립수','출하계획','특이사항']
            show_cols = [c for c in show_cols if c in month_sch.columns]
            st.dataframe(month_sch[show_cols].sort_values('날짜'), use_container_width=True, hide_index=True)
        else:
            st.info("이번 달 등록된 일정이 없습니다.")

    st.divider()
    db_v = st.session_state.production_db
    f_df = db_v[(db_v['반'] == curr_g) & (db_v['라인'] == "조립 라인")]

    # ── 모델/품목별 수량 카운트 + 생산 이력 ─────────────────────────
    if not f_df.empty:
        with st.expander(f"📊 {curr_g} 조립 라인 수량 현황", expanded=True):
            grp = f_df.groupby(['모델','품목코드'])
            count_rows = []
            for (model, pn), gdf in grp:
                total  = len(gdf)
                done   = len(gdf[gdf['상태'].isin(['검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중','완료'])])
                wip    = len(gdf[gdf['상태'].isin(['조립중','수리 완료(재투입)'])])
                defect = len(gdf[gdf['상태'].str.contains('불량', na=False)])
                count_rows.append((model, pn, total, done, wip, defect))

            for (model, pn, total, done, wip, defect) in count_rows:
                pct = int(done / total * 100) if total > 0 else 0
                with st.container(border=True):
                    mc1, mc2 = st.columns([3, 1])
                    mc1.markdown(f"**{model}**" + (f" `{pn}`" if pn else ""))
                    mc2.markdown(f"완료율 **{pct}%**")
                    st.progress(min(pct, 100) / 100)
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    sc1.metric("전체", total)
                    sc2.metric("✅ 완료", done)
                    sc3.metric("🏗️ 작업중", wip)
                    sc4.metric("🚨 불량", defect, delta=None if defect == 0 else f"{defect}건", delta_color="inverse")

        with st.expander(f"📋 {curr_g} 생산 이력", expanded=True):
            _asm_chk_key = f"asm_checked_{curr_g}"
            if _asm_chk_key not in st.session_state:
                st.session_state[_asm_chk_key] = {}

            _asm_search_cnt = f"asm_search_cnt_{curr_g}"
            if _asm_search_cnt not in st.session_state:
                st.session_state[_asm_search_cnt] = 0
            _asm_search_key = f"sn_search_{curr_g}_{st.session_state[_asm_search_cnt]}"
            sc1, sc2 = st.columns([2, 2])
            sn_search = sc1.text_input("🔍 시리얼 검색", placeholder="S/N 스캔 또는 입력...", key=_asm_search_key)
            if sn_search.strip():
                f_df_view = f_df[f_df['시리얼'].str.contains(sn_search.strip(), case=False, na=False)]
                if f_df_view.empty:
                    st.warning(f"🔍 **'{sn_search.strip()}'** 에 해당하는 시리얼이 없습니다.")
                for _si, _sr in f_df_view.iterrows():
                    if _sr['상태'] in ["조립중", "수리 완료(재투입)"]:
                        st.session_state[_asm_chk_key][str(_si)] = True
                st.session_state[_asm_search_cnt] += 1
                st.rerun()
            else:
                f_df_view = f_df

            checked_idxs = [k for k,v in st.session_state[_asm_chk_key].items() if v]
            if checked_idxs:
                ba1, ba2, ba3 = st.columns([2, 1, 1])
                ba1.markdown(f"<span style='color:#2E75B6;font-weight:700;'>✓ {len(checked_idxs)}개 선택됨</span>", unsafe_allow_html=True)
                if ba2.button("✅ 일괄 완료", key=f"bulk_ok_{curr_g}", type="primary", use_container_width=True):
                    for ci in checked_idxs:
                        ci_int = int(ci)
                        if ci_int in f_df.index:
                            _r = f_df.loc[ci_int]
                            update_row(_r['시리얼'], {'상태':'검사대기','시간':get_now_kst_str()})
                            insert_audit_log(시리얼=_r['시리얼'], 모델=_r['모델'], 반=curr_g,
                                이전상태=_r['상태'], 이후상태='검사대기', 작업자=st.session_state.user_id)
                    st.session_state[_asm_chk_key] = {}
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                if ba3.button("🚫 일괄 불량", key=f"bulk_ng_{curr_g}", use_container_width=True):
                    for ci in checked_idxs:
                        ci_int = int(ci)
                        if ci_int in f_df.index:
                            _r = f_df.loc[ci_int]
                            update_row(_r['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str(),
                                '증상': f'불량입고출처: 조립 라인'})
                            insert_audit_log(시리얼=_r['시리얼'], 모델=_r['모델'], 반=curr_g,
                                이전상태=_r['상태'], 이후상태='불량 처리 중', 작업자=st.session_state.user_id)
                    st.session_state[_asm_chk_key] = {}
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()

            # STATUS_STYLE: 모듈 상수 사용 (상단 정의 참조)
            h = st.columns([0.4, 2.0, 1.8, 1.4, 1.6, 2.0])
            for col, txt in zip(h, ["☑","기록 시간","모델","품목","시리얼","현장 제어"]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;'>{txt}</p>", unsafe_allow_html=True)

            for idx, row in f_df_view.sort_values('시간', ascending=False).iterrows():
                is_actionable = row['상태'] in ["조립중", "수리 완료(재투입)"]
                r = st.columns([0.4, 2.0, 1.8, 1.4, 1.6, 2.0])
                _ck = r[0].checkbox("", key=f"asm_cb_{curr_g}_{idx}",
                    value=st.session_state[_asm_chk_key].get(str(idx), False),
                    disabled=not is_actionable, label_visibility="collapsed")
                st.session_state[_asm_chk_key][str(idx)] = _ck
                r[1].caption(str(row['시간'])[:16]); r[2].caption(row['모델'])
                r[3].caption(row['품목코드']); r[4].caption(f"`{row['시리얼']}`")
                with r[5]:
                    if is_actionable:
                        b1, b2 = st.columns(2)
                        if b1.button("✅", key=f"ok_{idx}", use_container_width=True, help="완료"):
                            update_row(row['시리얼'], {'상태':'검사대기','시간':get_now_kst_str()})
                            insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                                이전상태=row['상태'], 이후상태='검사대기', 작업자=st.session_state.user_id)
                            st.session_state[_asm_chk_key].pop(str(idx), None)
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
                        if b2.button("🚫", key=f"ng_{idx}", use_container_width=True, help="불량"):
                            update_row(row['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str(),
                                '증상': f'불량입고출처: 조립 라인'})
                            insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                                이전상태=row['상태'], 이후상태='불량 처리 중', 작업자=st.session_state.user_id)
                            st.session_state[_asm_chk_key].pop(str(idx), None)
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
                    else:
                        s = row['상태']
                        if "불량" in str(s):
                            st.markdown(f"<div style='background:#fde8e7;color:#7a2e2a;padding:2px 6px;border-radius:5px;text-align:center;font-weight:bold;font-size:0.75rem;'>🚫 {s}</div>", unsafe_allow_html=True)
                        else:
                            bg,tc,bc,ic = STATUS_STYLE.get(s, ('#f5f2ec','#5a5048','#c8b89a','•'))
                            st.markdown(f"<div style='background:{bg};color:{tc};padding:2px 6px;border-radius:5px;text-align:center;font-weight:bold;border:1px solid {bc};font-size:0.75rem;'>{ic} {s}</div>", unsafe_allow_html=True)
    else:
        st.info("등록된 생산 내역이 없습니다.")

    # 자재 목록 마스터
    MAT_NAME_OPTIONS = st.session_state.get("dropdown_mat_name") or ["PCB", "배터리", "메인보드", "디스플레이", "케이블", "모듈", "센서", "커넥터", "기타"]

    _mat_list_key  = f"mat_list_{curr_g}"
    _scan_sn_key   = f"scan_sn_{curr_g}"
    _mat_name_key  = f"mat_name_sel_{curr_g}"

    if _mat_list_key not in st.session_state:
        st.session_state[_mat_list_key] = []

    with st.container(border=True):
        st.markdown(f"#### ➕ {curr_g} 신규 생산 등록")

        g_models     = st.session_state.group_master_models.get(curr_g, [])
        target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + g_models, key=f"model_sel_{curr_g}")
        g_items      = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])

        ef1, ef2 = st.columns(2)
        target_item = ef1.selectbox("품목 코드",
            g_items if target_model != "선택하세요." else ["모델 선택 대기"],
            key=f"item_sel_{curr_g}")
        _msn_cnt_key = f"msn_cnt_{curr_g}"
        if _msn_cnt_key not in st.session_state:
            st.session_state[_msn_cnt_key] = 0
        _msn_field_key = f"sn_input_{curr_g}_{st.session_state[_msn_cnt_key]}"
        target_sn = ef2.text_input(
            "📦 메인 S/N",
            placeholder="S/N 입력 후 아래 버튼으로 등록",
            key=_msn_field_key)
        ef2.caption("💡 자재 시리얼 입력 완료 후 [생산 시작 등록] 버튼을 누르세요")

        st.divider()

        st.markdown("<p style='font-size:0.88rem;font-weight:700;color:#5a4f45;margin:0 0 6px 0;'>🔩 자재 시리얼</p>", unsafe_allow_html=True)

        sc1, sc2, sc3 = st.columns([2, 3, 1])
        sel_mat_name = sc1.selectbox("자재명 선택", MAT_NAME_OPTIONS, key=_mat_name_key)

        _scan_counter_key = f"scan_cnt_{curr_g}"
        if _scan_counter_key not in st.session_state:
            st.session_state[_scan_counter_key] = 0
        _scan_field_key = f"{_scan_sn_key}_{st.session_state[_scan_counter_key]}"

        scan_input = sc2.text_input(
            "자재 S/N 스캔",
            placeholder="바코드 스캔 → 자동 추가 (Enter)",
            key=_scan_field_key,
        )
        sc2.caption("💡 스캐너로 스캔하면 Enter가 자동 입력됩니다")

        if scan_input.strip():
            already = any(m["자재시리얼"] == scan_input.strip()
                         for m in st.session_state[_mat_list_key])
            if not already:
                st.session_state[_mat_list_key].append({
                    "자재명": sel_mat_name,
                    "자재시리얼": scan_input.strip()
                })
            else:
                st.toast(f"⚠️ 이미 추가된 자재 S/N: {scan_input.strip()}", icon="⚠️")
            st.session_state[_scan_counter_key] += 1
            st.rerun()

        if sc3.button("➕ 추가", key=f"mat_manual_add_{curr_g}", use_container_width=True):
            st.session_state[_mat_list_key].append({
                "자재명": sel_mat_name, "자재시리얼": ""
            })
            st.rerun()

        mat_list_now = st.session_state[_mat_list_key]
        if mat_list_now:
            st.markdown(f"<p style='font-size:0.78rem;color:#8a7f72;margin:6px 0 2px 0;'>등록 예정 자재: <b>{len(mat_list_now)}개</b></p>", unsafe_allow_html=True)
            lh1, lh2, lh3 = st.columns([2, 4, 1])
            lh1.markdown("<p style='font-size:0.7rem;font-weight:700;color:#aaa;margin:0;'>자재명</p>", unsafe_allow_html=True)
            lh2.markdown("<p style='font-size:0.7rem;font-weight:700;color:#aaa;margin:0;'>자재 S/N</p>", unsafe_allow_html=True)

            updated_list = []
            _should_rerun = False
            for mi, mat in enumerate(mat_list_now):
                lc1, lc2, lc3 = st.columns([2, 4, 1])
                new_name = lc1.selectbox("", MAT_NAME_OPTIONS,
                    index=MAT_NAME_OPTIONS.index(mat["자재명"]) if mat["자재명"] in MAT_NAME_OPTIONS else 0,
                    key=f"mat_nm_{curr_g}_{mi}", label_visibility="collapsed")
                new_sn = lc2.text_input("", value=mat["자재시리얼"],
                    key=f"mat_sv_{curr_g}_{mi}", label_visibility="collapsed",
                    placeholder="S/N 직접 입력 또는 스캔")
                if not lc3.button("🗑", key=f"mat_del_{curr_g}_{mi}", help="삭제"):
                    updated_list.append({"자재명": new_name, "자재시리얼": new_sn})
                else:
                    _should_rerun = True  # 삭제 버튼 클릭됨 — 해당 항목은 updated_list에 추가 안 됨

            st.session_state[_mat_list_key] = updated_list  # 먼저 저장
            if _should_rerun:
                st.rerun()  # 저장 후 rerun

            if st.button("🗑 전체 초기화", key=f"mat_clear_{curr_g}", type="secondary"):
                st.session_state[_mat_list_key] = []
                st.rerun()
        else:
            st.caption("자재 없음 — 스캔하거나 ➕ 추가 버튼을 누르세요")

        st.divider()

        def _do_register_sn(sn_val):
            if insert_row({
                '시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인",
                '모델': target_model, '품목코드': target_item,
                '시리얼': sn_val, '상태': '조립중',
                '증상': '', '수리': '', '작업자': st.session_state.user_id
            }):
                valid_mats = [m for m in st.session_state[_mat_list_key] if m["자재시리얼"].strip()]
                if valid_mats:
                    insert_material_serials(
                        메인시리얼=sn_val, 모델=target_model,
                        반=curr_g, 자재목록=valid_mats,
                        작업자=st.session_state.user_id
                    )
                st.session_state[_mat_list_key] = []
                st.session_state[f"scan_cnt_{curr_g}"] = 0
                st.session_state[_msn_cnt_key] += 1
                st.session_state.production_db = load_realtime_ledger()
                st.toast(f"✅ 등록 완료: {sn_val}", icon="✅")
                st.rerun()

        if st.button("▶️ 생산 시작 등록", use_container_width=True, type="primary", key=f"start_btn_{curr_g}"):
            if target_model != "선택하세요." and target_sn.strip():
                _do_register_sn(target_sn.strip())
            else:
                st.warning("모델과 메인 S/N을 모두 입력해주세요.")


# ── 검사 / 포장 라인 ─────────────────────────────────────────────
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l} 현황</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "OQC 라인"

    db_s = st.session_state.production_db
    wait_status = "검사대기" if curr_l == "검사 라인" else "출하승인"
    wait_list = db_s[(db_s['반']==curr_g)&(db_s['상태']==wait_status)]
    _wait_cnt = len(wait_list)

    _wck_key     = f"wait_ck_{curr_g}_{curr_l}"
    _wscan_cnt   = f"wscan_cnt_{curr_g}_{curr_l}"
    if _wck_key   not in st.session_state: st.session_state[_wck_key]   = {}
    if _wscan_cnt not in st.session_state: st.session_state[_wscan_cnt] = 0

    with st.expander(f"📥 이전 공정({prev}) 완료 — 입고 대기" + (f"  ·  {_wait_cnt}건" if _wait_cnt else "  ·  없음"), expanded=True):
        if not wait_list.empty:
            _wscan_key = f"wscan_{curr_g}_{curr_l}_{st.session_state[_wscan_cnt]}"
            ws1, ws2 = st.columns([3, 3])
            w_scan = ws1.text_input("🔍 시리얼 스캔/검색", placeholder="스캔 또는 입력 → 자동 체크",
                                    key=_wscan_key)
            if w_scan.strip():
                matched_sn = wait_list[wait_list['시리얼'].str.contains(
                    w_scan.strip(), case=False, na=False)]
                if not matched_sn.empty:
                    for wi in matched_sn.index:
                        st.session_state[_wck_key][str(wi)] = True
                    st.session_state[_wscan_cnt] += 1
                    st.rerun()
                else:
                    ws1.warning(f"**'{w_scan.strip()}'** — 대기 목록에 없습니다.")

            w_checked = [k for k,v in st.session_state[_wck_key].items() if v]
            if w_checked:
                wba1, wba2, wba3 = st.columns([3, 1, 1])
                wba1.markdown(f"<span style='color:#2E75B6;font-weight:700;'>✓ {len(w_checked)}개 선택됨</span>",
                              unsafe_allow_html=True)
                if wba2.button("✅ 일괄 입고", key=f"wait_bulk_{curr_g}_{curr_l}",
                               type="primary", use_container_width=True):
                    _clear_production_cache()
                    _next_s = '검사중' if curr_l == '검사 라인' else '포장중'
                    _prev_s = '검사대기' if curr_l == '검사 라인' else '출하승인'
                    for wi in w_checked:
                        wi_int = int(wi)
                        if wi_int in wait_list.index:
                            _wr = wait_list.loc[wi_int]
                            update_row(_wr['시리얼'], {'시간': get_now_kst_str(),
                                '라인': curr_l, '상태': _next_s,
                                '작업자': st.session_state.user_id})
                            insert_audit_log(시리얼=_wr['시리얼'], 모델=_wr['모델'],
                                반=curr_g, 이전상태=_prev_s, 이후상태=_next_s,
                                작업자=st.session_state.user_id)
                    st.session_state[_wck_key] = {}
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                if wba3.button("☐ 선택 해제", key=f"wait_unck_{curr_g}_{curr_l}",
                               use_container_width=True):
                    st.session_state[_wck_key] = {}
                    st.rerun()

            st.markdown("<hr style='margin:8px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)

            grp_w = wait_list.groupby(['모델','품목코드'])
            for (w_model, w_pn), w_gdf in grp_w:
                with st.container(border=True):
                    wc1, wc2 = st.columns([4, 1])
                    wc1.markdown(f"**{w_model}**" + (f"  `{w_pn}`" if w_pn else ""))
                    wc2.caption(f"{len(w_gdf)}대")
                    for wi, (widx, wrow) in enumerate(w_gdf.iterrows()):
                        wr1, wr2, wr3 = st.columns([0.5, 3, 1.2])
                        _wck = wr1.checkbox("", key=f"wck_{curr_g}_{curr_l}_{widx}",
                            value=st.session_state[_wck_key].get(str(widx), False),
                            label_visibility="collapsed")
                        st.session_state[_wck_key][str(widx)] = _wck
                        wr2.markdown(f"`{wrow['시리얼']}`  <span style='color:#999;font-size:0.75rem;'>{str(wrow.get('시간',''))[:16]}</span>",
                                    unsafe_allow_html=True)
                        if wr3.button("📥 입고", key=f"in_{widx}", use_container_width=True):
                            _clear_production_cache()
                            _next_s = '검사중' if curr_l == '검사 라인' else '포장중'
                            _prev_s = '검사대기' if curr_l == '검사 라인' else '출하승인'
                            update_row(wrow['시리얼'], {'시간': get_now_kst_str(),
                                '라인': curr_l, '상태': _next_s,
                                '작업자': st.session_state.user_id})
                            insert_audit_log(시리얼=wrow['시리얼'], 모델=wrow['모델'],
                                반=curr_g, 이전상태=_prev_s, 이후상태=_next_s,
                                작업자=st.session_state.user_id)
                            st.session_state[_wck_key].pop(str(widx), None)
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
        else:
            st.info("입고 대기 물량 없음")

    st.divider()
    f_df = db_s[(db_s['반']==curr_g)&(db_s['라인']==curr_l)]
    _hist_cnt = len(f_df)

    _hck_key   = f"hist_ck_{curr_g}_{curr_l}"
    _hsrch_cnt = f"hsrch_cnt_{curr_g}_{curr_l}"
    if _hck_key   not in st.session_state: st.session_state[_hck_key]   = {}
    if _hsrch_cnt not in st.session_state: st.session_state[_hsrch_cnt] = 0

    with st.expander(f"📋 {curr_g} {curr_l} 이력" + (f"  ·  {_hist_cnt}건" if _hist_cnt else "  ·  없음"), expanded=True):
        if not f_df.empty:
            _hsrch_key = f"hsrch_{curr_g}_{curr_l}_{st.session_state[_hsrch_cnt]}"
            hs1, hs2 = st.columns([3, 3])
            _sn_search_qp = hs1.text_input("🔍 시리얼 스캔/검색",
                placeholder="스캔 또는 입력 → 자동 체크", key=_hsrch_key)

            if _sn_search_qp.strip():
                _actionable = f_df[f_df['상태'].isin(["검사중","포장중","수리 완료(재투입)"])]
                f_df_view = _actionable[_actionable['시리얼'].str.contains(
                    _sn_search_qp.strip(), case=False, na=False)]
                if f_df_view.empty:
                    hs1.warning(f"**'{_sn_search_qp.strip()}'** — 처리 가능한 시리얼이 없습니다.")
                else:
                    for _hi in f_df_view.index:
                        st.session_state[_hck_key][str(_hi)] = True
                    st.session_state[_hsrch_cnt] += 1
                    st.rerun()
                f_df_view = f_df
            else:
                f_df_view = f_df

            _h_checked = [k for k,v in st.session_state[_hck_key].items() if v]
            if _h_checked:
                btn_lbl = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                hba1, hba2, hba3, hba4 = st.columns([2, 1.2, 1.2, 0.8])
                hba1.markdown(f"<span style='color:#2E75B6;font-weight:700;'>✓ {len(_h_checked)}개 선택됨</span>",
                              unsafe_allow_html=True)
                if hba2.button(f"✅ 일괄 {btn_lbl}", key=f"hist_bulk_ok_{curr_g}_{curr_l}",
                               type="primary", use_container_width=True):
                    _clear_production_cache()
                    _ok_s  = 'OQC대기' if curr_l == '검사 라인' else '완료'
                    _prv_s = '검사중'  if curr_l == '검사 라인' else '포장중'
                    for ci in _h_checked:
                        ci_int = int(ci)
                        if ci_int in f_df.index:
                            _r = f_df.loc[ci_int]
                            if _r['상태'] in ["검사중","포장중","수리 완료(재투입)"]:
                                update_row(_r['시리얼'], {'상태':_ok_s,'시간':get_now_kst_str()})
                                insert_audit_log(시리얼=_r['시리얼'], 모델=_r['모델'], 반=curr_g,
                                    이전상태=_r['상태'], 이후상태=_ok_s, 작업자=st.session_state.user_id)
                    st.session_state[_hck_key] = {}
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                if hba3.button("🚫 일괄 불량", key=f"hist_bulk_ng_{curr_g}_{curr_l}",
                               use_container_width=True):
                    _clear_production_cache()
                    for ci in _h_checked:
                        ci_int = int(ci)
                        if ci_int in f_df.index:
                            _r = f_df.loc[ci_int]
                            if _r['상태'] in ["검사중","포장중","수리 완료(재투입)"]:
                                update_row(_r['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str(),
                                    '증상': f'불량입고출처: {curr_l}'})
                                insert_audit_log(시리얼=_r['시리얼'], 모델=_r['모델'], 반=curr_g,
                                    이전상태=_r['상태'], 이후상태='불량 처리 중', 작업자=st.session_state.user_id)
                    st.session_state[_hck_key] = {}
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                if hba4.button("☐", key=f"hist_unck_{curr_g}_{curr_l}",
                               use_container_width=True, help="선택 해제"):
                    st.session_state[_hck_key] = {}
                    st.rerun()

            STATUS_STYLE2 = {
                '검사대기': ('#fff3d4','#7a5c00','#f0c878','🔜'),
                '검사중':   ('#ddeeff','#1a4a7a','#7eb8e8','🔍'),
                '포장대기': ('#ede0f5','#4a1a7a','#b07ed8','🔜'),
                '포장중':   ('#fde8d4','#7a3c1a','#e8a87e','📦'),
                '완료':     ('#d4f0e2','#1f6640','#7ec8a0','✅'),
                'OQC대기':  ('#fff3d4','#7a5c00','#f0c878','⏳'),
                '출하승인': ('#d4f0e2','#1f6640','#7ec8a0','✅'),
            }

            h = st.columns([0.4, 1.8, 1.8, 1.3, 1.6, 2.2])
            for col, txt in zip(h, ["☑","기록 시간","모델","품목","시리얼","제어"]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;'>{txt}</p>",
                             unsafe_allow_html=True)

            for idx, row in f_df_view.sort_values('시간', ascending=False).iterrows():
                is_act = row['상태'] in ["검사중","포장중","수리 완료(재투입)"]
                r = st.columns([0.4, 1.8, 1.8, 1.3, 1.6, 2.2])
                _hck = r[0].checkbox("", key=f"hck_{curr_g}_{curr_l}_{idx}",
                    value=st.session_state[_hck_key].get(str(idx), False),
                    disabled=not is_act, label_visibility="collapsed")
                st.session_state[_hck_key][str(idx)] = _hck
                r[1].caption(str(row['시간'])[:16])
                r[2].caption(row['모델'])
                r[3].caption(row['품목코드'])
                r[4].caption(f"`{row['시리얼']}`")
                with r[5]:
                    if is_act:
                        btn_lbl = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                        c1, c2 = st.columns(2)
                        if c1.button("✅", key=f"ok_{idx}", use_container_width=True, help=btn_lbl):
                            _clear_production_cache()
                            _ok_s  = 'OQC대기' if curr_l == '검사 라인' else '완료'
                            _prv_s = '검사중'  if curr_l == '검사 라인' else '포장중'
                            update_row(row['시리얼'], {'상태':_ok_s,'시간':get_now_kst_str()})
                            insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                                이전상태=row['상태'], 이후상태=_ok_s, 작업자=st.session_state.user_id)
                            st.session_state[_hck_key].pop(str(idx), None)
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
                        if c2.button("🚫", key=f"ng_{idx}", use_container_width=True, help="불량"):
                            update_row(row['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str(),
                                '증상': f'불량입고출처: {curr_l}'})
                            insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                                이전상태=row['상태'], 이후상태='불량 처리 중', 작업자=st.session_state.user_id)
                            st.session_state[_hck_key].pop(str(idx), None)
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
                    else:
                        s2 = row['상태']
                        if "불량" in str(s2):
                            st.markdown(f"<div style='background:#fde8e7;color:#7a2e2a;padding:2px 6px;border-radius:5px;text-align:center;font-weight:bold;font-size:0.75rem;'>🚫 {s2}</div>", unsafe_allow_html=True)
                        else:
                            bg2,tc2,bc2,ic2 = STATUS_STYLE2.get(s2, ('#f5f2ec','#5a5048','#c8b89a','•'))
                            st.markdown(f"<div style='background:{bg2};color:{tc2};padding:2px 6px;border-radius:5px;text-align:center;font-weight:bold;border:1px solid {bc2};font-size:0.75rem;'>{ic2} {s2}</div>", unsafe_allow_html=True)
        else:
            st.info("해당 공정 내역이 없습니다.")

elif curr_l == "생산 현황 리포트":

    # ── 신규 제품 등록 ───────────────────────────────────────────────
    st.markdown("<div class='section-title'>➕ 신규 제품 등록</div>", unsafe_allow_html=True)
    models_for_group = st.session_state.group_master_models.get(curr_g, [])
    items_for_group  = st.session_state.group_master_items.get(curr_g, {})

    with st.form("asm_register_form", clear_on_submit=True):
        fc1, fc2, fc3 = st.columns([2, 2, 1.5])
        sn_input  = fc1.text_input("시리얼 번호 *", placeholder="예: SN20260301001")
        model_sel = fc2.selectbox("모델 *", ["(선택)"] + models_for_group)
        auto_pn   = items_for_group.get(model_sel, "") if model_sel != "(선택)" else ""
        pn_input  = fc3.text_input("품목코드", value=auto_pn)
        submitted  = st.form_submit_button("✅ 등록", use_container_width=True, type="primary")

    if submitted:
        sn_clean = sn_input.strip()
        if not sn_clean:
            st.error("시리얼 번호를 입력해주세요.")
        elif model_sel == "(선택)":
            st.error("모델을 선택해주세요.")
        else:
            new_row = {
                "시간": get_now_kst_str(), "반": curr_g, "라인": "조립 라인",
                "모델": model_sel,
                "품목코드": pn_input.strip(), "시리얼": sn_clean,
                "상태": "조립중", "증상": "", "수리": "",
                "작업자": st.session_state.user_id
            }
            if insert_row(new_row):
                insert_audit_log(시리얼=sn_clean, 모델=model_sel, 반=curr_g,
                    이전상태="", 이후상태="조립중", 작업자=st.session_state.user_id)
                st.success(f"✅ [{sn_clean}] 등록 완료")
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()

    st.divider()

    # ── 조립 중 목록 ─────────────────────────────────────────────────
    st.markdown("<div class='section-title'>🔧 조립 진행 중</div>", unsafe_allow_html=True)
    ing_df = db_g[db_g['상태'] == '조립중'].sort_values('시간', ascending=False)

    if not ing_df.empty:
        hh = st.columns([2, 2, 2, 1.5])
        for col, txt in zip(hh, ["등록 시간", "모델", "시리얼", "조립 완료"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
        for idx, row in ing_df.iterrows():
            rr = st.columns([2, 2, 2, 1.5])
            rr[0].caption(str(row.get('시간', ''))[:16])
            rr[1].write(row.get('모델', ''))
            rr[2].markdown(f"`{row.get('시리얼', '')}`")
            if rr[3].button("✔ 조립 완료", key=f"asm_done_{idx}", use_container_width=True, type="primary"):
                _clear_production_cache()
                update_row(row['시리얼'], {'상태': '검사대기', '시간': get_now_kst_str()})
                insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                    이전상태='조립중', 이후상태='검사대기', 작업자=st.session_state.user_id)
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
    else:
        st.info("조립 진행 중인 제품이 없습니다.")

    st.divider()

    with st.expander("📋 최근 등록 이력 (최근 20건)", expanded=False):
        hist = db_g[db_g['라인'] == '조립 라인'].sort_values('시간', ascending=False).head(20)
        if not hist.empty:
            st.dataframe(hist[['시간', '모델', '시리얼', '상태', '작업자']].reset_index(drop=True),
                         use_container_width=True, hide_index=True)
        else:
            st.info("이력이 없습니다.")

# ── 검사 라인 ────────────────────────────────────────────────────
elif curr_l == "검사 라인":
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} 검사 라인 현황</h2>", unsafe_allow_html=True)

    db_qc_all = st.session_state.production_db.copy()
    db_qc     = db_qc_all[db_qc_all['반'] == curr_g]
    DEFECT_CAUSES = st.session_state.get('dropdown_defect_cause', ['(선택)', '기타 (직접 입력)'])

    # ── KPI ─────────────────────────────────────────────────────────
    qc_wait = len(db_qc[db_qc['상태'] == '검사대기'])
    qc_ing  = len(db_qc[db_qc['상태'] == '검사중'])
    qc_pass = len(db_qc[db_qc['상태'] == 'OQC대기'])
    qc_ng   = len(db_qc[db_qc['상태'] == '불량 처리 중'])

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📥 검사 대기", f"{qc_wait}건")
    k2.metric("🔍 검사 중",   f"{qc_ing}건")
    k3.metric("✅ OQC 대기",  f"{qc_pass}건")
    k4.metric("🚫 불량",      f"{qc_ng}건")
    st.divider()

    # ── 검사 대기 목록 ───────────────────────────────────────────────
    st.markdown("<div class='section-title'>📥 검사 대기 (조립 완료 제품)</div>", unsafe_allow_html=True)
    wait_df = db_qc[db_qc['상태'] == '검사대기'].sort_values('시간', ascending=False)

    if not wait_df.empty:
        hh = st.columns([2, 2, 2, 1.5])
        for col, txt in zip(hh, ["시간", "모델", "시리얼", "검사 시작"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
        for idx, row in wait_df.iterrows():
            rr = st.columns([2, 2, 2, 1.5])
            rr[0].caption(str(row.get('시간', ''))[:16])
            rr[1].write(row.get('모델', ''))
            rr[2].markdown(f"`{row.get('시리얼', '')}`")
            if rr[3].button("▶ 검사 시작", key=f"qc_in_{idx}", use_container_width=True, type="primary"):
                _clear_production_cache()
                update_row(row['시리얼'], {'상태': '검사중', '시간': get_now_kst_str(),
                    '라인': '검사 라인', '작업자': st.session_state.user_id})
                insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                    이전상태='검사대기', 이후상태='검사중', 작업자=st.session_state.user_id)
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
    else:
        st.info("검사 대기 중인 제품이 없습니다.")

    st.divider()

    # ── 검사 중 → 판정 ───────────────────────────────────────────────
    st.markdown("<div class='section-title'>🔍 검사 진행 중</div>", unsafe_allow_html=True)
    qc_ing_df = db_qc[db_qc['상태'] == '검사중'].sort_values('시간', ascending=False)

    if not qc_ing_df.empty:
        for idx, row in qc_ing_df.iterrows():
            with st.container(border=True):
                ic1, ic2, ic3 = st.columns([2, 2, 1.5])
                ic1.markdown(f"**{row.get('모델', '')}**")
                ic2.markdown(f"`{row.get('시리얼', '')}`")
                ic3.markdown("<span style='background:#ddeeff;color:#1a4a7a;padding:2px 8px;"
                             "border-radius:6px;font-size:0.8rem;font-weight:bold;'>🔍 검사중</span>",
                             unsafe_allow_html=True)

                qc1, qc2 = st.columns([2, 1])
                with qc1:
                    cause_sel = st.selectbox("불량 원인 (불량 처리 시 선택)",
                        DEFECT_CAUSES, key=f"qc_cause_{idx}")
                    if cause_sel == "기타 (직접 입력)":
                        cause_txt = st.text_input("직접 입력", key=f"qc_cause_txt_{idx}", placeholder="불량 원인 입력")
                    elif cause_sel == "(선택)":
                        cause_txt = ""
                    else:
                        cause_txt = cause_sel
                with qc2:
                    btn_pass = st.button("✅ 합격 (OQC 대기)", key=f"qc_ok_{idx}", use_container_width=True, type="primary")
                    btn_ng   = st.button("🚫 불량 처리",       key=f"qc_ng_{idx}",  use_container_width=True)

                if btn_pass:
                    _clear_production_cache()
                    update_row(row['시리얼'], {'상태': 'OQC대기', '시간': get_now_kst_str()})
                    insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                        이전상태='검사중', 이후상태='OQC대기', 작업자=st.session_state.user_id)
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                if btn_ng:
                    if not cause_txt:
                        st.warning("⚠️ 불량 원인을 먼저 선택해주세요.")
                    else:
                        _clear_production_cache()
                        update_row(row['시리얼'], {'상태': '불량 처리 중', '시간': get_now_kst_str(), '증상': cause_txt})
                        insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                            이전상태='검사중', 이후상태='불량 처리 중',
                            작업자=st.session_state.user_id, 비고=f"원인:{cause_txt}")
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
    else:
        st.info("검사 진행 중인 제품이 없습니다.")

    st.divider()

    with st.expander("📋 최근 검사 이력 (최근 20건)", expanded=False):
        hist = db_qc[db_qc['라인'] == '검사 라인'].sort_values('시간', ascending=False).head(20)
        if not hist.empty:
            st.dataframe(hist[['시간', '모델', '시리얼', '상태', '증상', '작업자']].reset_index(drop=True),
                         use_container_width=True, hide_index=True)
        else:
            st.info("이력이 없습니다.")

# ── 포장 라인 ────────────────────────────────────────────────────
elif curr_l == "포장 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 포장 라인 현황</h2>", unsafe_allow_html=True)

    db_pk_all = st.session_state.production_db.copy()
    db_pk     = db_pk_all[db_pk_all['반'] == curr_g]

    # ── KPI ─────────────────────────────────────────────────────────
    pk_wait = len(db_pk[db_pk['상태'] == '출하승인'])
    pk_ing  = len(db_pk[db_pk['상태'] == '포장중'])
    pk_done = len(db_pk[db_pk['상태'] == '완료'])
    pk_ng   = len(db_pk[db_pk['상태'].str.contains('불량', na=False)])

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📥 포장 대기", f"{pk_wait}건")
    k2.metric("📦 포장 중",   f"{pk_ing}건")
    k3.metric("✅ 완료",      f"{pk_done}건")
    k4.metric("🚫 불량",      f"{pk_ng}건")
    st.divider()

    # ── 포장 대기 (OQC 합격 → 출하승인 상태) ────────────────────────
    st.markdown("<div class='section-title'>📥 포장 대기 (OQC 합격 제품)</div>", unsafe_allow_html=True)
    pk_wait_df = db_pk[db_pk['상태'] == '출하승인'].sort_values('시간', ascending=False)

    if not pk_wait_df.empty:
        hh = st.columns([2, 2, 2, 1.5])
        for col, txt in zip(hh, ["시간", "모델", "시리얼", "포장 시작"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
        for idx, row in pk_wait_df.iterrows():
            rr = st.columns([2, 2, 2, 1.5])
            rr[0].caption(str(row.get('시간', ''))[:16])
            rr[1].write(row.get('모델', ''))
            rr[2].markdown(f"`{row.get('시리얼', '')}`")
            if rr[3].button("▶ 포장 시작", key=f"pk_in_{idx}", use_container_width=True, type="primary"):
                _clear_production_cache()
                update_row(row['시리얼'], {'상태': '포장중', '시간': get_now_kst_str(),
                    '라인': '포장 라인', '작업자': st.session_state.user_id})
                insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                    이전상태='출하승인', 이후상태='포장중', 작업자=st.session_state.user_id)
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
    else:
        st.info("포장 대기 중인 제품이 없습니다.")

    st.divider()

    # ── 포장 중 → 완료 ───────────────────────────────────────────────
    st.markdown("<div class='section-title'>📦 포장 진행 중</div>", unsafe_allow_html=True)
    pk_ing_df = db_pk[db_pk['상태'] == '포장중'].sort_values('시간', ascending=False)

    if not pk_ing_df.empty:
        hh = st.columns([2, 2, 2, 1.5])
        for col, txt in zip(hh, ["시간", "모델", "시리얼", "포장 완료"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
        for idx, row in pk_ing_df.iterrows():
            rr = st.columns([2, 2, 2, 1.5])
            rr[0].caption(str(row.get('시간', ''))[:16])
            rr[1].write(row.get('모델', ''))
            rr[2].markdown(f"`{row.get('시리얼', '')}`")
            if rr[3].button("✔ 포장 완료", key=f"pk_done_{idx}", use_container_width=True, type="primary"):
                _clear_production_cache()
                update_row(row['시리얼'], {'상태': '완료', '시간': get_now_kst_str()})
                insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=curr_g,
                    이전상태='포장중', 이후상태='완료', 작업자=st.session_state.user_id)
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
    else:
        st.info("포장 진행 중인 제품이 없습니다.")

    st.divider()

    with st.expander("📋 최근 완료 이력 (최근 20건)", expanded=False):
        hist = db_pk[db_pk['상태'] == '완료'].sort_values('시간', ascending=False).head(20)
        if not hist.empty:
            st.dataframe(hist[['시간', '모델', '시리얼', '작업자']].reset_index(drop=True),
                         use_container_width=True, hide_index=True)
        else:
            st.info("완료된 제품이 없습니다.")

elif curr_l == "생산 현황 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    v_group = st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = st.session_state.production_db.copy()
    if v_group != "전체": df = df[df['반'] == v_group]

    if not df.empty:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("총 투입",      f"{len(df)} EA")
        c2.metric("최종 생산",    f"{len(df[(df['라인']=='포장 라인')&(df['상태']=='완료')])} EA")
        c3.metric("현재 작업 중", f"{len(df[df['상태'].isin(['조립중','검사중','포장중'])])} EA")
        c4.metric("품질 이슈",    f"{len(df[df['상태'].str.contains('불량',na=False)])} 건")
        st.divider()
        cl, cr = st.columns([1.8, 1.2])
        with cl:
            fig_b = px.bar(df.groupby('라인').size().reset_index(name='수량'),
                           x='라인', y='수량', color='라인',
                           title="<b>[공정 단계별 제품 분포]</b>", template="plotly_white")
            fig_b.update_yaxes(dtick=1)
            st.plotly_chart(fig_b, use_container_width=True)
        with cr:
            fig_p = px.pie(df.groupby('모델').size().reset_index(name='수량'),
                           values='수량', names='모델', hole=0.5, title="<b>[생산 모델별 비중]</b>")
            st.plotly_chart(fig_p, use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회 가능한 데이터가 없습니다.")

# ── 생산 지표 관리 ─────────────────────────────────────────────────
elif curr_l == "생산 지표 관리":

    # ── CSS: 전광판 스타일 ─────────────────────────────────────────
    st.markdown("""
<style>
.db-title   { font-size:1.35rem; font-weight:800; color:#2a2420; letter-spacing:-0.5px; margin:0 0 2px 0; }
.db-section { display:flex; align-items:center; gap:8px; font-size:0.78rem; font-weight:700;
              color:#fff; padding:5px 14px; border-radius:20px; margin:14px 0 8px 0;
              width:fit-content; letter-spacing:0.3px; }
.kpi-card   { background:#fff; border:1px solid #e8e2d8; border-radius:10px;
              padding:12px 16px 10px 16px; text-align:center; }
.kpi-lbl    { font-size:0.68rem; font-weight:600; color:#8a7f72;
              text-transform:uppercase; letter-spacing:0.6px; margin-bottom:2px; }
.kpi-val    { font-size:2.2rem; font-weight:800; line-height:1.1; color:#2a2420; }
.kpi-sub    { font-size:0.68rem; color:#aaa; margin-top:2px; }
.kpi-green  { color:#1e8449; }
.kpi-red    { color:#c0392b; }
.kpi-blue   { color:#2471a3; }
.kpi-amber  { color:#d68910; }
.ban-card   { border-radius:10px; padding:10px 14px 8px 14px; margin-bottom:2px; }
.ban-name   { font-size:0.72rem; font-weight:700; letter-spacing:0.4px; margin-bottom:4px; }
.ban-pct    { font-size:2.6rem; font-weight:900; line-height:1.05; }
.ban-sub    { font-size:0.65rem; color:#888; margin-top:1px; }
.ban-row    { display:flex; gap:6px; margin-top:8px; }
.ban-chip   { flex:1; border-radius:6px; padding:5px 0; text-align:center; }
.ban-chip-lbl { font-size:0.6rem; font-weight:600; color:#888; }
.ban-chip-val { font-size:1.3rem; font-weight:800; line-height:1.1; }
.proc-card  { border-radius:10px; padding:10px 14px 10px 14px; }
.proc-name  { font-size:0.75rem; font-weight:700; letter-spacing:0.3px; margin-bottom:6px; }
.proc-row   { display:flex; gap:6px; }
.proc-chip  { flex:1; background:#f5f2ec; border-radius:6px; padding:6px 4px; text-align:center; }
.proc-chip-lbl { font-size:0.58rem; font-weight:600; color:#888; }
.proc-chip-val { font-size:1.5rem; font-weight:800; line-height:1.1; color:#2a2420; }
.proc-arrow { display:flex; align-items:center; justify-content:center;
              font-size:1.6rem; color:#c8b89a; padding:0 2px; }
.ng-row     { display:flex; gap:8px; align-items:center; padding:6px 0;
              border-bottom:1px solid #f0ebe0; }
.ng-model   { flex:2; font-size:0.82rem; font-weight:600; color:#2a2420; }
.ng-bar-wrap{ flex:3; background:#f0ebe0; border-radius:99px; height:7px; overflow:hidden; }
.ng-bar     { height:100%; border-radius:99px; }
.ng-pct     { flex:1; font-size:0.82rem; font-weight:700; text-align:right; }
.ng-cnt     { flex:1; font-size:0.72rem; color:#888; text-align:right; }
.rt-row     { display:flex; gap:0; padding:5px 0; border-bottom:1px solid #f5f2ec;
              align-items:center; font-size:0.78rem; }
.rt-chip    { font-size:0.65rem; font-weight:600; border-radius:4px;
              padding:1px 6px; margin-right:6px; }
</style>""", unsafe_allow_html=True)

    db_all    = st.session_state.production_db.copy()
    sch_all   = st.session_state.schedule_db.copy()
    today_str = datetime.now(KST).strftime('%Y-%m-%d')

    # ── 상단 필터 (한 줄, 컴팩트) ─────────────────────────────────
    st.markdown("<div class='db-title'>📡 생산 지표 관리</div>", unsafe_allow_html=True)
    fc1, fc2, _sp = st.columns([2, 2.5, 3])
    period     = fc1.radio("기간", ["오늘","이번 주","이번 달"], horizontal=True, key="dash_period")
    ban_filter = fc2.radio("반", ["전체"] + PRODUCTION_GROUPS, horizontal=True, key="dash_ban")

    from datetime import date as _date, timedelta as _td
    _today = _date.today()
    if period == "오늘":
        date_from = date_to_d = today_str
    elif period == "이번 주":
        _mon = _today - _td(days=_today.weekday())
        date_from = _mon.strftime('%Y-%m-%d'); date_to_d = today_str
    else:
        date_from = today_str[:7] + "-01"; date_to_d = today_str

    if not db_all.empty:
        db_f = db_all[db_all['시간'].str[:10] >= date_from]
        db_f = db_f[db_f['시간'].str[:10] <= date_to_d]
        if ban_filter != "전체": db_f = db_f[db_f['반'] == ban_filter]
    else:
        db_f = db_all.copy()

    if not sch_all.empty:
        sch_f = sch_all[(sch_all['날짜'] >= date_from) & (sch_all['날짜'] <= date_to_d)]
        if ban_filter != "전체": sch_f = sch_f[sch_f['반'] == ban_filter]
    else:
        sch_f = sch_all.copy()

    def _qty(df, col='조립수'):
        if df.empty: return 0
        return int(df[col].apply(lambda x: int(float(x)) if str(x) not in ('','nan') else 0).sum())

    total_in   = len(db_f) if not db_f.empty else 0
    total_done = len(db_f[(db_f['라인']=='포장 라인') & (db_f['상태']=='완료')]) if not db_f.empty else 0
    WIP_ALL = ['조립중','검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중','수리 완료(재투입)']
    total_wip  = len(db_f[db_f['상태'].isin(WIP_ALL)]) if not db_f.empty else 0
    total_ng   = len(db_f[db_f['상태'].str.contains('불량', na=False)]) if not db_f.empty else 0
    plan_qty   = _qty(sch_f)
    achieve_pct = round(total_done / plan_qty * 100, 1) if plan_qty > 0 else 0
    defect_pct  = round(total_ng / total_in * 100, 1) if total_in > 0 else 0

    # ══════════════════════════════════════════════════════════════
    # [A] KPI 5개 — 한 줄
    # ══════════════════════════════════════════════════════════════
    st.markdown("<div class='db-section' style='background:#4a4540;'>▪ 핵심 지표</div>", unsafe_allow_html=True)
    k = st.columns(5)
    kpi_data = [
        ("계획", f"{plan_qty:,}", "대", "#2471a3"),
        ("생산 완료", f"{total_done:,}", "대", "#1e8449"),
        ("달성률", f"{achieve_pct}", "%", "#1e8449" if achieve_pct >= 100 else "#d68910" if achieve_pct >= 70 else "#c0392b"),
        ("진행 중", f"{total_wip:,}", "대", "#2471a3"),
        ("불량률", f"{defect_pct}", "%", "#c0392b" if defect_pct > 3 else "#d68910" if defect_pct > 0 else "#1e8449"),
    ]
    for col, (lbl, val, unit, color) in zip(k, kpi_data):
        col.markdown(f"""
<div class='kpi-card'>
  <div class='kpi-lbl'>{lbl}</div>
  <div class='kpi-val' style='color:{color};'>{val}<span style='font-size:1rem;font-weight:600;color:#aaa;margin-left:2px;'>{unit}</span></div>
  <div class='kpi-sub'>{date_from} ~ {date_to_d}</div>
</div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # [B+C] 반별 달성률 + 공정 병목 — 한 줄 (4+3 비율)
    # ══════════════════════════════════════════════════════════════
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    left_col, right_col = st.columns([4, 3])

    BAN_COLORS_D = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}

    with left_col:
        st.markdown("<div class='db-section' style='background:#2471a3;'>🏭 반별 달성률</div>", unsafe_allow_html=True)
        bc = st.columns(3)
        for bi, ban in enumerate(PRODUCTION_GROUPS):
            bdb  = db_f[db_f['반']==ban] if not db_f.empty else pd.DataFrame()
            bsch = sch_f[sch_f['반']==ban] if not sch_f.empty else pd.DataFrame()
            b_plan = _qty(bsch)
            b_done = len(bdb[(bdb['라인']=='포장 라인')&(bdb['상태']=='완료')]) if not bdb.empty else 0
            b_wip  = len(bdb[bdb['상태'].isin(WIP_ALL)]) if not bdb.empty else 0
            b_ng   = len(bdb[bdb['상태'].str.contains('불량',na=False)]) if not bdb.empty else 0
            b_pct  = round(b_done / b_plan * 100, 1) if b_plan > 0 else 0
            clr    = BAN_COLORS_D.get(ban, "#888")
            bar_w  = min(int(b_pct), 100)
            pct_clr = "#1e8449" if b_pct >= 100 else "#d68910" if b_pct >= 70 else "#c0392b"

            with bc[bi]:
                st.markdown(f"""
<div class='ban-card' style='background:{clr}0d; border:1.5px solid {clr}44;'>
  <div class='ban-name' style='color:{clr};'>{ban}</div>
  <div style='background:#e8e2d8;border-radius:99px;height:5px;margin-bottom:6px;overflow:hidden;'>
    <div style='background:{clr};width:{bar_w}%;height:100%;border-radius:99px;'></div>
  </div>
  <div class='ban-pct' style='color:{pct_clr};'>{b_pct}<span style='font-size:1.1rem;'>%</span></div>
  <div class='ban-sub'>계획 {b_plan}대 → 완료 {b_done}대</div>
  <div class='ban-row'>
    <div class='ban-chip' style='background:#ddeeff;'>
      <div class='ban-chip-lbl'>진행</div>
      <div class='ban-chip-val' style='color:#2471a3;'>{b_wip}</div>
    </div>
    <div class='ban-chip' style='background:#d4f0e2;'>
      <div class='ban-chip-lbl'>완료</div>
      <div class='ban-chip-val' style='color:#1e8449;'>{b_done}</div>
    </div>
    <div class='ban-chip' style='background:{"#fde8e7" if b_ng>0 else "#f5f5f5"};'>
      <div class='ban-chip-lbl'>불량</div>
      <div class='ban-chip-val' style='color:{"#c0392b" if b_ng>0 else "#aaa"};'>{b_ng}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    with right_col:
        st.markdown("<div class='db-section' style='background:#7a6f65;'>🔄 공정 흐름</div>", unsafe_allow_html=True)
        lines_info = [
            ("🔧", "조립", "#7eb8e8"),
            ("🔍", "검사", "#7ec8a0"),
            ("📦", "포장", "#c8a07e"),
        ]
        line_names_full = ["조립 라인", "검사 라인", "포장 라인"]
        proc_html = "<div style='display:flex;align-items:stretch;gap:0;'>"
        for pi, (emoji, name, clr) in enumerate(lines_info):
            ldf    = db_f[db_f['라인']==line_names_full[pi]] if not db_f.empty else pd.DataFrame()
            l_tot  = len(ldf)
            l_done = len(ldf[ldf['상태']=='완료']) if not ldf.empty else 0
            l_wip  = len(ldf[ldf['상태'].isin(['조립중','검사중','포장중','수리 완료(재투입)'])]) if not ldf.empty else 0
            l_ng   = len(ldf[ldf['상태'].str.contains('불량',na=False)]) if not ldf.empty else 0
            l_wait = len(db_f[(db_f['라인']==line_names_full[pi-1])&(db_f['상태']=='완료')]) if pi>0 and not db_f.empty else 0
            btl_flag = "⚠" if l_wip > 5 else ""
            wip_clr = "#c0392b" if l_wip > 5 else "#2471a3"

            proc_html += f"""
<div class='proc-card' style='flex:1;background:{clr}18;border:1.5px solid {clr}55;border-radius:10px;'>
  <div class='proc-name' style='color:{clr[:-2] if len(clr)>7 else clr};'>{emoji} {name} {btl_flag}</div>
  <div class='proc-row'>
    <div class='proc-chip'><div class='proc-chip-lbl'>투입</div><div class='proc-chip-val'>{l_tot}</div></div>
    <div class='proc-chip'><div class='proc-chip-lbl'>완료</div><div class='proc-chip-val' style='color:#1e8449;'>{l_done}</div></div>
  </div>
  <div class='proc-row' style='margin-top:4px;'>
    <div class='proc-chip'><div class='proc-chip-lbl'>진행</div><div class='proc-chip-val' style='color:{wip_clr};'>{l_wip}</div></div>
    <div class='proc-chip'><div class='proc-chip-lbl'>불량</div><div class='proc-chip-val' style='color:{"#c0392b" if l_ng>0 else "#aaa"};'>{l_ng}</div></div>
  </div>
  {"<div style='font-size:0.6rem;color:#888;margin-top:4px;'>📥 대기 "+str(l_wait)+"대</div>" if pi>0 else ""}
</div>"""
            if pi < 2:
                proc_html += "<div class='proc-arrow'>▶</div>"
        proc_html += "</div>"
        st.markdown(proc_html, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # [D+E] 불량 분석 + 실시간 — 한 줄 (3+4 비율)
    # ══════════════════════════════════════════════════════════════
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    ng_col, rt_col = st.columns([3, 4])

    with ng_col:
        st.markdown("<div class='db-section' style='background:#c0392b;'>📉 모델별 불량 분석</div>", unsafe_allow_html=True)
        if not db_f.empty:
            ng_df = db_f.groupby('모델').agg(
                투입=('시리얼','count'),
                불량=('상태', lambda x: x.str.contains('불량',na=False).sum())
            ).reset_index()
            ng_df['불량률'] = (ng_df['불량'] / ng_df['투입'] * 100).round(1)
            ng_df = ng_df[ng_df['불량'] > 0].sort_values('불량률', ascending=False)
            if not ng_df.empty:
                max_pct = ng_df['불량률'].max() or 1
                ng_html = ""
                for _, row in ng_df.iterrows():
                    bar_w = int(row['불량률'] / max_pct * 100)
                    bar_c = "#c0392b" if row['불량률'] > 10 else "#d68910" if row['불량률'] > 5 else "#e8c97a"
                    ng_html += f"""
<div class='ng-row'>
  <div class='ng-model'>{row['모델']}</div>
  <div class='ng-bar-wrap'><div class='ng-bar' style='width:{bar_w}%;background:{bar_c};'></div></div>
  <div class='ng-pct' style='color:{bar_c};'>{row['불량률']}%</div>
  <div class='ng-cnt'>{int(row['불량'])}건</div>
</div>"""
                st.markdown(ng_html, unsafe_allow_html=True)
            else:
                st.success("✅ 불량 없음")
        else:
            st.info("데이터 없음")

    with rt_col:
        st.markdown("<div class='db-section' style='background:#1e8449;'>⚡ 실시간 진행 중</div>", unsafe_allow_html=True)
        rt_df = st.session_state.production_db.copy()
        if ban_filter != "전체": rt_df = rt_df[rt_df['반'] == ban_filter]
        WIP_STATES = ['조립중','검사대기','검사중','OQC대기','OQC중','출하승인','포장대기','포장중','수리 완료(재투입)']
        rt_wip = rt_df[rt_df['상태'].isin(WIP_STATES)].sort_values('시간', ascending=False) if not rt_df.empty else pd.DataFrame()

        if not rt_wip.empty:
            BAN_BG = {"제조1반":"#ddeeff","제조2반":"#d4f0e2","제조3반":"#ede0f5"}
            BAN_CL = {"제조1반":"#2471a3","제조2반":"#1e8449","제조3반":"#6c3483"}
            LINE_BG = {"조립 라인":"#fff3d4","검사 라인":"#d4f0e2","포장 라인":"#fde8d4"}
            rt_html = "<div style='font-size:0.7rem;font-weight:600;color:#aaa;display:flex;gap:0;padding:0 0 4px 0;border-bottom:2px solid #e8e2d8;margin-bottom:2px;'><span style='flex:1.2;'>반</span><span style='flex:1.5;'>라인</span><span style='flex:2.5;'>모델</span><span style='flex:2;'>시리얼</span><span style='flex:1.8;'>시작</span></div>"
            for _, row in rt_wip.iterrows():
                ban_v  = row.get('반','')
                line_v = row.get('라인','')
                bbg = BAN_BG.get(ban_v, "#f0f0f0"); bcl = BAN_CL.get(ban_v, "#666")
                lbg = LINE_BG.get(line_v, "#f0f0f0")
                rt_html += f"""
<div class='rt-row'>
  <span style='flex:1.2;'><span class='rt-chip' style='background:{bbg};color:{bcl};'>{ban_v[:3]}</span></span>
  <span style='flex:1.5;'><span class='rt-chip' style='background:{lbg};color:#555;'>{line_v[:2]}</span></span>
  <span style='flex:2.5;font-weight:600;'>{row.get('모델','')}</span>
  <span style='flex:2;color:#5a5048;font-family:monospace;'>{row.get('시리얼','')}</span>
  <span style='flex:1.8;color:#aaa;'>{str(row.get('시간',''))[:16]}</span>
</div>"""
            st.markdown(rt_html, unsafe_allow_html=True)
        else:
            st.info("현재 진행 중인 작업 없음")

    # ══════════════════════════════════════════════════════════════
    # [F] 계획 수량 입력 + 월별 달성률 그래프
    # ══════════════════════════════════════════════════════════════
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='db-section' style='background:#5a4f8a;'>📅 월별 계획 수량 관리</div>", unsafe_allow_html=True)

    # 변경 사유 선택지
    PLAN_CHANGE_REASONS = [
        "신규 계획 등록",
        "영업 요구량 변경 (주문 취소)",
        "영업 요구량 변경 (물량 증가)",
        "긴급 주문 (Rush Order)",
        "자재 수급 문제 (입고 지연)",
        "자재 수급 문제 (불량 자재)",
        "설비 고장 / 유지보수",
        "인력 변동 (부족/결원)",
        "품질 문제 (불량 발생)",
        "기타 (직접 입력)",
    ]

    # 입력 폼 (관리자 전용)
    if st.session_state.user_role in CALENDAR_EDIT_ROLES:
        with st.expander("⚙️ 월 계획 수량 입력 / 변경", expanded=False):
            st.caption("반/월별 목표 수량을 입력합니다. 변경 시 사유를 선택하면 이력이 자동 기록됩니다.")
            pl1, pl2, pl3 = st.columns([1.5, 1.5, 1.2])
            p_ban  = pl1.selectbox("반", PRODUCTION_GROUPS, key="plan_ban")
            from datetime import date as _d2
            _months = []
            for i in range(6):
                _m = (_d2.today().replace(day=1) - __import__('datetime').timedelta(days=i*28)).strftime('%Y-%m')
                if _m not in _months: _months.append(_m)
            _months = sorted(set(_months), reverse=True)[:6]
            p_month = pl2.selectbox("월", _months, key="plan_month")
            p_qty   = pl3.number_input("계획 수량 (대)", min_value=0, step=10, key="plan_qty")

            # 현재 저장된 수량 표시
            _cur_qty = st.session_state.production_plan.get(f"{p_ban}_{p_month}", 0)
            if _cur_qty > 0:
                st.caption(f"📌 현재 저장된 수량: **{_cur_qty:,}대** → 변경 후: **{int(p_qty):,}대** "
                           f"({'▲' if int(p_qty) > _cur_qty else '▼'} {abs(int(p_qty)-_cur_qty):,}대)")

            pr1, pr2 = st.columns([2, 2])
            p_reason = pr1.selectbox("변경 사유 *", PLAN_CHANGE_REASONS, key="plan_reason")
            p_detail = pr2.text_input("상세 내용 (선택)", placeholder="예: 고객사 요청, 부품 수급 지연 등", key="plan_detail")

            if st.button("💾 저장", type="primary", key="plan_save_btn"):
                _reason_final = p_detail.strip() if p_reason == "기타 (직접 입력)" and p_detail.strip() else p_reason
                if save_production_plan(p_ban, p_month, int(p_qty)):
                    # 변경 로그 기록
                    insert_plan_change_log(
                        반=p_ban, 월=p_month,
                        이전수량=_cur_qty, 변경수량=int(p_qty),
                        변경사유=_reason_final, 사유상세=p_detail.strip(),
                        작업자=st.session_state.user_id
                    )
                    plan_key = f"{p_ban}_{p_month}"
                    st.session_state.production_plan[plan_key] = int(p_qty)
                    _clear_plan_cache()
                    st.success(f"✅ {p_ban} / {p_month} → {p_qty:,}대 저장 완료")
                    st.rerun()

    # ── 월별 달성률 그래프 ────────────────────────────────────────
    plan_map_now = st.session_state.production_plan  # {반_YYYY-MM: 계획수량}

    # 최근 6개월 목록
    from datetime import date as _d3
    months_list = []
    for i in range(5, -1, -1):
        _m = (_d3.today().replace(day=1) - __import__('datetime').timedelta(days=i*28))
        months_list.append(_m.strftime('%Y-%m'))
    months_list = sorted(set(months_list))[-6:]

    # 반별 월별 실적 집계
    db_raw = st.session_state.production_db.copy()
    chart_rows = []
    for ban in PRODUCTION_GROUPS:
        for mo in months_list:
            plan_v = plan_map_now.get(f"{ban}_{mo}", 0)
            # 해당 월 포장 완료 건수
            if not db_raw.empty:
                actual_v = len(db_raw[
                    (db_raw['반'] == ban) &
                    (db_raw['상태'] == '완료') &
                    (db_raw['라인'] == '포장 라인') &
                    (db_raw['시간'].str[:7] == mo)
                ])
            else:
                actual_v = 0
            pct = round(actual_v / plan_v * 100, 1) if plan_v > 0 else 0
            chart_rows.append({
                '월': mo, '반': ban,
                '계획': plan_v, '실적': actual_v, '달성률(%)': pct
            })

    chart_df = pd.DataFrame(chart_rows)

    if not chart_df.empty and chart_df['계획'].sum() > 0:
        import plotly.graph_objects as go

        BAN_CLR = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}
        BAN_CLR_LIGHT = {"제조1반": "#aad4f5", "제조2반": "#a8dfc4", "제조3반": "#caaee8"}

        gc1, gc2 = st.columns([3, 2])

        with gc1:
            # 그룹 막대 차트: 계획 vs 실적
            fig_plan = go.Figure()
            for ban in PRODUCTION_GROUPS:
                bdf = chart_df[chart_df['반'] == ban]
                fig_plan.add_trace(go.Bar(
                    name=f"{ban} 계획",
                    x=bdf['월'], y=bdf['계획'],
                    marker_color=BAN_CLR_LIGHT.get(ban, "#ccc"),
                    opacity=0.6, offsetgroup=ban,
                    text=bdf['계획'].apply(lambda v: f"{v:,}" if v > 0 else ""),
                    textposition='outside', textfont=dict(size=9)
                ))
                fig_plan.add_trace(go.Bar(
                    name=f"{ban} 실적",
                    x=bdf['월'], y=bdf['실적'],
                    marker_color=BAN_CLR.get(ban, "#888"),
                    offsetgroup=ban + "_실적",
                    text=bdf['실적'].apply(lambda v: f"{v:,}" if v > 0 else ""),
                    textposition='outside', textfont=dict(size=9)
                ))
            fig_plan.update_layout(
                title="월별 계획 vs 실적 (반별)",
                barmode='group',
                template='plotly_white',
                height=320,
                margin=dict(t=40, b=40, l=20, r=20),
                legend=dict(orientation='h', y=-0.2, font=dict(size=10)),
                yaxis_title="수량 (대)"
            )
            st.plotly_chart(fig_plan, use_container_width=True)

        with gc2:
            # 달성률 라인 차트
            fig_pct = go.Figure()
            for ban in PRODUCTION_GROUPS:
                bdf = chart_df[chart_df['반'] == ban]
                fig_pct.add_trace(go.Scatter(
                    name=ban, x=bdf['월'], y=bdf['달성률(%)'],
                    mode='lines+markers+text',
                    line=dict(color=BAN_CLR.get(ban, "#888"), width=2),
                    marker=dict(size=7),
                    text=bdf['달성률(%)'].apply(lambda v: f"{v}%" if v > 0 else ""),
                    textposition='top center', textfont=dict(size=9)
                ))
            # 100% 기준선
            fig_pct.add_hline(y=100, line_dash="dash", line_color="#e8908a",
                              annotation_text="목표 100%", annotation_font_size=10)
            fig_pct.update_layout(
                title="월별 달성률 추이 (%)",
                template='plotly_white',
                height=320,
                margin=dict(t=40, b=40, l=20, r=20),
                legend=dict(orientation='h', y=-0.2, font=dict(size=10)),
                yaxis=dict(title="달성률 (%)", range=[0, max(120, (chart_df['달성률(%)'].max() + 10) if not chart_df.empty else 0)])
            )
            st.plotly_chart(fig_pct, use_container_width=True)

        # 요약 테이블
        summary = chart_df.groupby('반').agg(
            총계획=('계획','sum'), 총실적=('실적','sum')
        ).reset_index()
        summary['전체달성률(%)'] = (summary['총실적'] / summary['총계획'] * 100).round(1).where(summary['총계획'] > 0, 0)
        st.dataframe(summary, use_container_width=True, hide_index=True)
    else:
        st.info("계획 수량을 입력하면 달성률 그래프가 표시됩니다.")

    # ── 변경 이력 로그 (탭 구분) ─────────────────────────────────
    st.divider()
    st.markdown("<div class='db-section' style='background:#5a4f8a;'>📋 변경 이력 로그</div>", unsafe_allow_html=True)

    REASON_COLOR = {
        "신규 계획 등록":              "#ddeeff",
        "영업 요구량 변경 (주문 취소)": "#fde8e7",
        "영업 요구량 변경 (물량 증가)": "#d4f0e2",
        "긴급 주문 (Rush Order)":      "#fff3d4",
        "자재 수급 문제 (입고 지연)":   "#fde8d4",
        "자재 수급 문제 (불량 자재)":   "#fde8d4",
        "설비 고장 / 유지보수":         "#fde8e7",
        "인력 변동 (부족/결원)":        "#ede0f5",
        "품질 문제 (불량 발생)":        "#fde8e7",
        "계획 오입력 수정":             "#f5f2ec",
    }

    log_tab1, log_tab2 = st.tabs(["📊 월별 계획 수량 변경", "📅 일정 수정 이력"])

    # ── 탭1: 월별 계획 수량 변경 이력 ───────────────────────────
    with log_tab1:
        lf1, lf2, lf3 = st.columns([1.5, 2, 1])
        log_ban    = lf1.selectbox("반 필터", ["전체"] + PRODUCTION_GROUPS, key="plog_ban")
        log_reason = lf2.selectbox("사유 필터", ["전체"] + PLAN_CHANGE_REASONS, key="plog_reason")
        if lf3.button("🔄 새로고침", key="plog_refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()

        plog_df = load_plan_change_log()
        if not plog_df.empty:
            if log_ban    != "전체": plog_df = plog_df[plog_df['반'] == log_ban]
            if log_reason != "전체": plog_df = plog_df[plog_df['변경사유'].str.contains(log_reason, na=False)]

            pk1, pk2, pk3, pk4 = st.columns(4)
            pk1.metric("전체 변경 건수", f"{len(plog_df)}건")
            inc = plog_df[plog_df['증감'] > 0]['증감'].sum()
            dec = plog_df[plog_df['증감'] < 0]['증감'].sum()
            pk2.metric("총 증가량", f"+{int(inc):,}대")
            pk3.metric("총 감소량", f"{int(dec):,}대")
            pk4.metric("순 변동량", f"{int(inc+dec):+,}대")

            th = st.columns([1.8, 1.0, 1.0, 1.0, 1.0, 0.9, 2.5, 2.0, 1.2])
            for col, txt in zip(th, ["시간","반","월","이전","변경","증감","변경 사유","상세 내용","작업자"]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
            for _, row in plog_df.iterrows():
                tr = st.columns([1.8, 1.0, 1.0, 1.0, 1.0, 0.9, 2.5, 2.0, 1.2])
                tr[0].caption(str(row.get('시간',''))[:16])
                tr[1].write(row.get('반',''))
                tr[2].write(row.get('월',''))
                tr[3].caption(f"{int(row.get('이전수량',0)):,}대")
                tr[4].write(f"**{int(row.get('변경수량',0)):,}대**")
                증감 = int(row.get('증감', 0))
                clr = "#1e8449" if 증감 > 0 else "#c0392b" if 증감 < 0 else "#888"
                tr[5].markdown(f"<span style='color:{clr};font-weight:bold;font-size:0.85rem;'>{증감:+,}</span>", unsafe_allow_html=True)
                reason_v = str(row.get('변경사유',''))
                rbg = REASON_COLOR.get(reason_v, "#f5f2ec")
                tr[6].markdown(f"<span style='background:{rbg};padding:1px 6px;border-radius:4px;font-size:0.72rem;'>{reason_v}</span>", unsafe_allow_html=True)
                tr[7].caption(row.get('사유상세',''))
                tr[8].caption(row.get('작업자',''))
        else:
            st.info("계획 변경 이력이 없습니다. 계획 수량 저장 시 자동 기록됩니다.")

    # ── 탭2: 일정 수정 이력 ──────────────────────────────────────
    with log_tab2:
        @st.cache_data(ttl=30)
        def load_schedule_change_log(limit: int = 200) -> pd.DataFrame:
            try:
                sb  = get_supabase()
                res = sb.table("schedule_change_log").select("*").order("시간", desc=True).limit(limit).execute()
                if res.data:
                    return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
                return pd.DataFrame(columns=['시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])
            except Exception:
                return pd.DataFrame(columns=['시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])

        sf1, sf2, sf3 = st.columns([1.5, 2, 1])
        s_ban    = sf1.selectbox("반 필터", ["전체"] + PRODUCTION_GROUPS, key="slog_ban")
        s_reason = sf2.selectbox("사유 필터", ["전체"] + SCH_CHANGE_REASONS[1:], key="slog_reason")
        if sf3.button("🔄 새로고침", key="slog_refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()

        slog_df = load_schedule_change_log()
        if not slog_df.empty:
            if s_ban    != "전체": slog_df = slog_df[slog_df['반'] == s_ban]
            if s_reason != "전체": slog_df = slog_df[slog_df['변경사유'].str.contains(s_reason, na=False)]

            sk1, sk2, sk3 = st.columns(3)
            sk1.metric("전체 수정 건수", f"{len(slog_df)}건")
            sk2.metric("수정 관여 작업자", f"{slog_df['작업자'].nunique()}명")
            sk3.metric("수정된 날짜 수", f"{slog_df['날짜'].nunique()}일")

            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            th2 = st.columns([1.6, 1.0, 1.0, 1.2, 2.0, 2.0, 2.2, 1.8, 1.2])
            for col, txt in zip(th2, ["수정 시간","날짜","반","모델","이전 내용","변경 내용","변경 사유","상세","작업자"]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
            for _, row in slog_df.iterrows():
                tr2 = st.columns([1.6, 1.0, 1.0, 1.2, 2.0, 2.0, 2.2, 1.8, 1.2])
                tr2[0].caption(str(row.get('시간',''))[:16])
                tr2[1].caption(str(row.get('날짜',''))[:10])
                tr2[2].write(row.get('반',''))
                tr2[3].write(row.get('모델명',''))
                tr2[4].caption(row.get('이전내용',''))
                tr2[5].caption(row.get('변경내용',''))
                reason_v2 = str(row.get('변경사유',''))
                rbg2 = REASON_COLOR.get(reason_v2, "#f5f2ec")
                tr2[6].markdown(f"<span style='background:{rbg2};padding:1px 6px;border-radius:4px;font-size:0.72rem;'>{reason_v2}</span>", unsafe_allow_html=True)
                tr2[7].caption(row.get('사유상세',''))
                tr2[8].caption(row.get('작업자',''))
        else:
            st.info("일정 수정 이력이 없습니다. 캘린더에서 일정 수정 시 자동 기록됩니다.")

    # ══════════════════════════════════════════════════════════════
    # [G] 생산 일정 관리
    # ══════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("<div class='section-title'>📅 생산 일정 관리</div>", unsafe_allow_html=True)
    sch_tab1, sch_tab2, sch_tab3 = st.tabs(["➕ 직접 입력", "📂 엑셀 일괄 업로드", "📋 등록된 일정 관리"])

    with sch_tab2:
        st.markdown("<p style='color:#2a2420;'>생산계획 엑셀 파일을 업로드하면 일정에 자동 등록됩니다.</p>", unsafe_allow_html=True)

        # 양식 다운로드
        dl1, dl2 = st.columns([1, 2])
        with dl1:
            try:
                import openpyxl as _xl
                import io as _tmpio
                from openpyxl.styles import Font as _Font, PatternFill as _Fill, Alignment as _Align, Border as _Border, Side as _Side
                from openpyxl.worksheet.datavalidation import DataValidation as _DV

                def _make_template():
                    _GROUP_COLORS = {
                        "제조1반": ("2471A3", "D4ECF7"),
                        "제조2반": ("1E8449", "D5F5E3"),
                        "제조3반": ("6C3483", "E8DAEF"),
                    }
                    _TAB_COLORS = {"제조1반":"2471A3","제조2반":"1E8449","제조3반":"6C3483"}
                    _EXAMPLES = {
                        "제조1반": ["2026-03-05","조립계획","TMP1115TI405","AM-1115 BLACK","32","3/15 32" ,"정상",""],
                        "제조2반": ["2026-03-05","조립계획","","모델명 예시","0","" ,"",""],
                        "제조3반": ["2026-03-05","포장계획","TMS9150008","T20i (i3-12세대) DUAL","20","3/20 20" ,"정상",""],
                    }

                    def _hf(color="FFFFFF", sz=10):
                        return _Font(name="맑은 고딕", bold=True, size=sz, color=color)
                    def _bf():
                        return _Font(name="맑은 고딕", size=10, color="2A2420")
                    def _fl(c): return _Fill("solid", fgColor=c)
                    def _bd(c="C8B89A"):
                        s = _Side(style="thin", color=c)
                        return _Border(left=s, right=s, top=s, bottom=s)
                    def _ca(): return _Align(horizontal="center", vertical="center", wrap_text=True)
                    def _la(): return _Align(horizontal="left",   vertical="center", wrap_text=True)

                    _wb = _xl.Workbook()
                    _wb.remove(_wb.active)

                    for _g in ["제조1반","제조2반","제조3반"]:
                        _hdr_col, _inp_bg = _GROUP_COLORS[_g]
                        _ws = _wb.create_sheet(_g)
                        _ws.sheet_properties.tabColor = _TAB_COLORS[_g]

                        # 1행 타이틀
                        _ws.merge_cells("A1:H1")
                        _ws["A1"].value = f"📋  {_g}  생산 일정 업로드 양식  |  시트명 = 반 이름 (자동 인식)"
                        _ws["A1"].font  = _Font(name="맑은 고딕", bold=True, size=12, color="FFFFFF")
                        _ws["A1"].fill  = _fl(_hdr_col)
                        _ws["A1"].alignment = _ca()
                        _ws.row_dimensions[1].height = 30

                        # 2행 안내
                        _ws.merge_cells("A2:H2")
                        _ws["A2"].value = "⚠  날짜: YYYY-MM-DD  |  카테고리: 드롭다운 선택  |  조립수: 숫자만  |  5행부터 입력 (4행 예시는 자동 스킵)"
                        _ws["A2"].font  = _Font(name="맑은 고딕", size=9, color="2A2420")
                        _ws["A2"].fill  = _fl("FFF3CD")
                        _ws["A2"].alignment = _la()
                        _ws.row_dimensions[2].height = 18

                        # 3행 헤더 (반 컬럼 없음 - 시트명이 곧 반)
                        _headers = ["날짜 *", "카테고리 *", "P/N", "모델명 *", "조립수", "출하계획", "특이사항", "비고"]
                        for _ci, _h in enumerate(_headers, 1):
                            _c = _ws.cell(3, _ci)
                            _c.value = _h
                            _c.font  = _hf(color="FFFFFF")
                            _c.fill  = _fl(_hdr_col)
                            _c.alignment = _ca()
                            _c.border = _bd(_hdr_col)
                        _ws.row_dimensions[3].height = 26

                        # 4행 예시
                        for _ci, _v in enumerate(_EXAMPLES[_g], 1):
                            _c = _ws.cell(4, _ci)
                            _c.value = _v
                            _c.font  = _Font(name="맑은 고딕", size=9, color="8A7F72", italic=True)
                            _c.fill  = _fl("EEEBE4")
                            _c.alignment = _ca()
                            _c.border = _bd()
                        _ws.row_dimensions[4].height = 20

                        # 5~204행 입력 영역
                        for _r in range(5, 205):
                            for _c in range(1, 9):
                                _cell = _ws.cell(_r, _c)
                                _cell.fill      = _fl(_inp_bg if _c <= 7 else "FFFDF7")
                                _cell.border    = _bd()
                                _cell.alignment = _ca() if _c in [1,2,5] else _la()
                                _cell.font      = _bf()

                        # 카테고리 드롭다운 (직접 입력도 허용 - 유효성 검사 없음)
                        _dv = _DV(type="list", formula1='"조립계획,포장계획,출하계획"',
                                  showDropDown=False, showErrorMessage=False)
                        _dv.sqref = "B5:B204"
                        _ws.add_data_validation(_dv)

                        # 조립수 숫자 유효성
                        _dv2 = _DV(type="whole", operator="greaterThanOrEqual", formula1="0",
                                   showErrorMessage=True, errorTitle="입력 오류", error="0 이상의 숫자만 입력하세요.")
                        _dv2.sqref = "E5:E204"
                        _ws.add_data_validation(_dv2)

                        # 컬럼 너비
                        for _col, _w in zip("ABCDEFGH", [14,13,18,34,10,18,22,18]):
                            _ws.column_dimensions[_col].width = _w
                        _ws.freeze_panes = "A5"

                    # 가이드 시트
                    _wg = _wb.create_sheet("📋 작성 가이드")
                    _wg.sheet_properties.tabColor = "8A7F72"
                    _guide = [
                        ["항목","설명"],
                        ["시트명","제조1반 / 제조2반 / 제조3반 → 시트명이 곧 반 (자동 인식)"],
                        ["날짜","YYYY-MM-DD 형식 (예: 2026-03-05)"],
                        ["카테고리","드롭다운: 조립계획 / 포장계획 / 출하계획 / 특이사항 / 기타"],
                        ["P/N","품목코드 (예: TMP6133002) — 선택"],
                        ["모델명","필수 — 조립 라인 모델 목록에 자동 등록됨"],
                        ["조립수","숫자만. 0 또는 빈칸이면 해당 행 스킵"],
                        ["출하계획","자유 텍스트 입력 — 예: 3/15 30 / 3월15일 30대 / 3/15 등 형식 무관, 선택 입력"],
                        ["특이사항","메모 자유 입력 — 선택"],
                        [],
                        ["⚠ 주의사항"],
                        ["1. 각 시트에 해당 반 데이터만 입력 (반 혼용 불가)"],
                        ["2. 4행 예시 행은 업로드 시 자동 스킵"],
                        ["3. 조립수 0 또는 빈칸 → 해당 행 스킵"],
                        ["4. 모델명 등록 시 해당 반 조립 라인에 자동 반영"],
                        ["5. 여러 반을 한 번에 → 각 시트 채워서 업로드"],
                    ]
                    for _ri, _row in enumerate(_guide, 1):
                        for _ci, _v in enumerate(_row, 1):
                            _c = _wg.cell(_ri, _ci, _v)
                            _c.font = _bf(); _c.alignment = _la()
                    for _ci in range(1, 3):
                        _c = _wg.cell(1, _ci)
                        _c.font = _hf(); _c.fill = _fl("7EB8E8")
                        _c.alignment = _ca(); _c.border = _bd()
                    _wg.cell(11, 1).font = _Font(name="맑은 고딕", bold=True, size=10, color="C8605A")
                    _wg.column_dimensions["A"].width = 14
                    _wg.column_dimensions["B"].width = 62

                    _buf = _tmpio.BytesIO()
                    _wb.save(_buf)
                    return _buf.getvalue()

                st.download_button(
                    "📥 업로드 양식 다운로드 (반별 시트)",
                    _make_template(),
                    "PMS_반별_업로드양식.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as _e:
                st.warning(f"양식 생성 오류: {_e}")
        with dl2:
            st.markdown("""<p style='color:#5a96c8; font-size:0.88rem; margin:8px 0;'>
            ✅ <b>반별 시트 양식</b> (추천): 제조1반·2반·3반 시트 분리 — 시트명이 곧 반, 별도 선택 불필요<br>
            </p>""", unsafe_allow_html=True)

        # 지원 형식 안내
        with st.expander("📌 지원 엑셀 형식 안내"):
            st.markdown("""
    <p style='color:#2a2420;'>
    <b>① PMS 반별 시트 양식</b> (위 버튼으로 다운로드) ⭐추천<br>
    &nbsp;&nbsp;• 시트명: <b>제조1반 / 제조2반 / 제조3반</b> — 시트명이 곧 반 정보<br>
    &nbsp;&nbsp;• 컬럼: 날짜 / 카테고리 / P/N / 모델명 / 조립수 / 출하계획 / 특이사항<br>
    &nbsp;&nbsp;• 여러 반을 한 파일에 각 시트별로 입력 후 한 번에 업로드 가능<br><br>
    <b>② PMS 단일 시트 양식</b><br>
    &nbsp;&nbsp;• 시트명: <b>생산계획_업로드</b> / 컬럼에 반 포함<br><br>
    """, unsafe_allow_html=True)

        uploaded_file = st.file_uploader("📎 엑셀 파일 선택 (.xlsx)", type=["xlsx"], key="sch_upload")

        if uploaded_file:
            try:
                import openpyxl, io as _io, re as _re
                from datetime import datetime as _dt

                raw = uploaded_file.read()
                wb  = openpyxl.load_workbook(_io.BytesIO(raw), data_only=True)
                sheet_names = wb.sheetnames

                # ── 양식 자동 감지 ──
                group_sheets = [s for s in sheet_names if s in PRODUCTION_GROUPS]
                if group_sheets:
                    detected_mode = "PMS 반별 시트 양식"
                elif "생산계획_업로드" in sheet_names:
                    detected_mode = "PMS 단일 시트 양식"
                else:
                    detected_mode = "지원하지 않는 양식"

                st.info(f"🔍 감지된 양식: **{detected_mode}**")

                parsed = []

                # ══════════════════════════════════════════
                # ① PMS 반별 시트 양식 파싱
                # ══════════════════════════════════════════
                if detected_mode == "PMS 반별 시트 양식":
                    st.markdown(
                        f"<p style='color:#2a2420;'>감지된 반 시트: "
                        + " ".join([f"<b style='color:#5a96c8;'>[{s}]</b>" for s in group_sheets])
                        + " — 전체 파싱합니다.</p>",
                        unsafe_allow_html=True)

                    for g_sheet in group_sheets:
                        ws = wb[g_sheet]
                        for row in ws.iter_rows(min_row=5, values_only=True):
                            date_val, cat, pn, model, qty, ship, note = (list(row) + [None]*7)[:7]
                            # 완전히 빈 행 스킵
                            if not any([date_val, cat, pn, model, qty, ship, note]):
                                continue
                            # 모델명 없으면 스킵
                            if not model:
                                continue
                            # 날짜 처리 (datetime / 문자열 / 숫자 모두 대응)
                            date_str = None
                            if isinstance(date_val, _dt):
                                date_str = date_val.strftime('%Y-%m-%d')
                            elif hasattr(date_val, 'strftime'):  # date 객체
                                date_str = date_val.strftime('%Y-%m-%d')
                            elif isinstance(date_val, str):
                                dv = date_val.strip()
                                # YYYY-MM-DD 또는 YYYY/MM/DD 형식
                                m = _re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', dv)
                                if m:
                                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                            elif isinstance(date_val, (int, float)):
                                # 엑셀 시리얼 날짜 변환
                                try:
                                    from datetime import date as _date
                                    date_str = (_date(1899, 12, 30) + __import__('datetime').timedelta(days=int(date_val))).strftime('%Y-%m-%d')
                                except Exception:
                                    pass
                            if not date_str:
                                continue
                            # 수량 처리 (비어있어도 0으로 등록 허용)
                            qty_int = 0
                            if isinstance(qty, (int, float)):
                                qty_int = max(0, int(qty))
                            elif isinstance(qty, str) and qty.strip():
                                nums = _re.findall(r'\d+', qty)
                                qty_int = int(nums[0]) if nums else 0
                            parsed.append({
                                '날짜':     date_str,
                                '반':       g_sheet,
                                '카테고리': str(cat  or "조립계획").strip(),
                                'pn':       str(pn   or "").strip(),
                                '모델명':   str(model or "").strip(),
                                '조립수':   qty_int,
                                '출하계획': str(ship or "").strip(),
                                '특이사항': str(note or "").strip(),
                                '작성자':   st.session_state.user_id,
                            })

                # ══════════════════════════════════════════
                # ② PMS 단일 시트 양식 파싱
                # ══════════════════════════════════════════
                elif detected_mode == "PMS 단일 시트 양식":
                    ws = wb["생산계획_업로드"]
                    for row in ws.iter_rows(min_row=5, values_only=True):
                        ban, date_val, cat, pn, model, qty, ship, note = (list(row) + [None]*8)[:8]

                        if not ban and not model and not date_val: continue
                        if not model and not note: continue
                        if isinstance(date_val, _dt):
                            date_str = date_val.strftime('%Y-%m-%d')
                        elif isinstance(date_val, str) and len(date_val) == 10:
                            date_str = date_val
                        else:
                            continue
                        qty_int = 0
                        if isinstance(qty, (int, float)) and qty > 0:
                            qty_int = int(qty)
                        elif isinstance(qty, str):
                            nums = _re.findall(r'\d+', qty)
                            qty_int = int(nums[0]) if nums else 0
                        if qty_int <= 0: continue
                        parsed.append({
                            '날짜':     date_str,
                            '반':       str(ban or "").strip(),
                            '카테고리': str(cat or "기타").strip(),
                            'pn':       str(pn  or "").strip(),
                            '모델명':   str(model or "").strip(),
                            '조립수':   qty_int,
                            '출하계획': str(ship or "").strip(),
                            '특이사항': str(note or "").strip(),
                            '작성자':   st.session_state.user_id,
                        })

                # 지원하지 않는 양식
                else:
                    st.error("⛔ 지원하지 않는 파일 형식입니다. 위 [업로드 양식 다운로드] 버튼으로 PMS 반별 시트 양식을 사용해주세요.")

                if parsed:
                    # 미리보기
                    import pandas as _pd
                    preview_df = _pd.DataFrame(parsed)[['날짜','카테고리','pn','모델명','조립수','출하계획']]
                    st.markdown(f"<p style='color:#2a2420;'>✅ <b>{len(parsed)}건</b> 파싱 완료 — 미리보기:</p>", unsafe_allow_html=True)
                    st.dataframe(preview_df, use_container_width=True, hide_index=True, height=300)

                    st.divider()

                    # ── 반 선택 (PMS 양식은 이미 반 포함, MNT는 여기서 지정) ──
                    has_ban = all(r.get('반','') in PRODUCTION_GROUPS for r in parsed)
                    if has_ban:
                        st.info(f"📍 반 정보가 파일에 포함되어 있습니다.")
                        upload_ban = None  # 파일 내 반 사용
                    else:
                        upload_ban = st.selectbox(
                            "📍 해당 엑셀의 반 선택 ✱필수",
                            PRODUCTION_GROUPS,
                            key="bulk_ban_sel",
                        
                        )

                    # 날짜 범위 필터
                    all_dates = sorted(set(r['날짜'] for r in parsed))
                    fc1, fc2 = st.columns(2)
                    date_from = fc1.selectbox("등록 시작일", all_dates, key="bulk_from")
                    date_to   = fc2.selectbox("등록 종료일", all_dates,
                        index=len(all_dates)-1, key="bulk_to")
                    filtered = [r for r in parsed if date_from <= r['날짜'] <= date_to]

                    # 실제 등록될 반 표시
                    actual_ban = upload_ban if upload_ban else "파일 내 반 정보 사용"
                    st.markdown(
                        f"<p style='color:#5a96c8; font-weight:bold;'>"
                        f"→ 선택 범위 {date_from} ~ {date_to} : <b>{len(filtered)}건</b>"
                        f" | 등록 반: <b>{actual_ban}</b></p>",
                        unsafe_allow_html=True)

                    # 중복 처리 옵션
                    dup_mode = st.radio("기존 일정 처리",
                        ["건너뜀 (중복 날짜+모델 제외)", "모두 등록 (중복 허용)"],
                        horizontal=True, key="bulk_dup_mode")

                    col_reg, _ = st.columns([2,1])
                    if col_reg.button(f"📥 {len(filtered)}건 일정 등록", type="primary", use_container_width=True, key="bulk_register"):
                        # 반 미선택 방어
                        if not has_ban and not upload_ban:
                            st.error("반을 선택해주세요.")
                        else:
                            existing = st.session_state.schedule_db
                            success_cnt = skip_cnt = fail_cnt = 0
                            fail_rows = []
                            
                            # ✨ 진행률 표시 추가
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            total = len(filtered)
                            
                            for idx, row in enumerate(filtered, 1):
                                # 진행률 업데이트
                                progress = idx / total
                                progress_bar.progress(progress)
                                status_text.text(f"📤 등록 중... {idx}/{total} ({int(progress*100)}%)")
                                
                                # 반 강제 지정
                                if upload_ban:
                                    row['반'] = upload_ban
                                # 반 최종 확인
                                if row.get('반','') not in PRODUCTION_GROUPS:
                                    skip_cnt += 1
                                    continue
                                # 중복 체크
                                if "건너뜀" in dup_mode and not existing.empty:
                                    dup = existing[
                                        (existing['날짜']   == row['날짜']) &
                                        (existing['모델명'] == row['모델명']) &
                                        (existing['카테고리'] == row['카테고리']) &
                                        (existing['반']     == row['반'])
                                    ]
                                    if not dup.empty:
                                        skip_cnt += 1
                                        continue
                                if insert_schedule(row):
                                    success_cnt += 1
                                else:
                                    fail_cnt += 1
                                    fail_rows.append(f"{row.get('날짜','')} / {row.get('모델명','')}")
                            
                            # 완료 표시
                            progress_bar.progress(1.0)
                            status_text.text(f"✅ 등록 완료!")
                            
                            st.session_state.schedule_db = load_schedule()
                            if success_cnt > 0:
                                st.success(f"✅ 등록 완료: {success_cnt}건  |  건너뜀(중복): {skip_cnt}건" + (f"  |  실패: {fail_cnt}건" if fail_cnt else ""))
                            if fail_rows:
                                st.error("등록 실패 행:\n" + "\n".join(fail_rows))
                            st.rerun()
                else:
                    st.warning("파싱된 일정이 없습니다. 파일 형식을 확인해주세요.")

            except Exception as e:
                st.error(f"파일 파싱 오류: {e}")

    with sch_tab1:
        with st.form("schedule_form"):
            sb1, sb2 = st.columns(2)
            sch_ban  = sb1.selectbox("반 *", PRODUCTION_GROUPS)
            sc1, sc2, sc3 = st.columns(3)
            sch_date  = sc1.date_input("날짜")
            sch_cat   = sc2.selectbox("계획 유형 *", PLAN_CATEGORIES)
            sch_model = sc3.text_input("모델명")
            sc4, sc5, sc6 = st.columns(3)
            sch_pn    = sc4.text_input("P/N (품목코드)")
            sch_qty   = sc5.number_input("조립수", min_value=0, step=1)
            sch_ship  = sc6.text_input("출하계획")
            sch_note  = st.text_input("특이사항")
            if st.form_submit_button("📅 일정 등록", use_container_width=True, type="primary"):
                if sch_model.strip() or sch_note.strip():
                    if insert_schedule({
                        '날짜': str(sch_date), '반': sch_ban,
                        '카테고리': sch_cat,
                        'pn': sch_pn.strip(), '모델명': sch_model.strip(),
                        '조립수': int(sch_qty), '출하계획': sch_ship.strip(),
                        '특이사항': sch_note.strip(), '작성자': st.session_state.user_id
                    }):
                        st.session_state.schedule_db = load_schedule()
                        st.success("일정 등록 완료!"); st.rerun()
                else:
                    st.warning("모델명 또는 특이사항을 입력해주세요.")

    with sch_tab3:
        sch_list = st.session_state.schedule_db
        if not sch_list.empty:
            # ── 전체 삭제 버튼 ──
            all_del_key = "sch_all_del_confirm"
            if not st.session_state.get(all_del_key, False):
                if st.button("🗑️ 전체 일정 삭제", type="secondary", key="sch_all_del"):
                    st.session_state[all_del_key] = True
                    st.rerun()
            else:
                st.error("⛔ 등록된 일정 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                ac1, ac2, ac3 = st.columns([2, 1, 1])
                ac1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if ac2.button("✅ 예, 전체 삭제", type="primary", use_container_width=True, key="sch_all_del_yes"):
                    for _, row in sch_list.iterrows():
                        delete_schedule(int(row['id']))
                    _clear_schedule_cache()                        # ← 캐시 초기화
                    st.session_state.schedule_db = load_schedule()
                    st.session_state[all_del_key] = False
                    st.rerun()
                if ac3.button("취소", use_container_width=True, key="sch_all_del_no"):
                    st.session_state[all_del_key] = False
                    st.rerun()
            st.divider()

            # ── 헤더 행 ──
            hh = st.columns([1.0, 0.8, 1.2, 1.5, 2.2, 0.8, 1.8, 0.5])
            for col, txt in zip(hh, ["유형","반","날짜","P/N","모델명","수량","특이사항",""]):
                col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)

            for _, row in sch_list.sort_values('날짜').iterrows():
                cat    = row.get('카테고리', '기타')
                color  = SCHEDULE_COLORS.get(cat, "#888")
                row_id = row['id']
                del_ck = f"sch_del_ck_{row_id}"

                # ── 데이터 행 ──
                c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([1.0, 0.8, 1.2, 1.5, 2.2, 0.8, 1.8, 0.5])
                c1.markdown(f"<span style='background:{color}22;border-left:3px solid {color};padding:2px 5px;border-radius:4px;font-size:0.78rem;'>{cat}</span>", unsafe_allow_html=True)
                c2.caption(row.get('반',''))
                c3.caption(row.get('날짜',''))
                c4.caption(row.get('pn',''))
                c5.caption(row.get('모델명',''))
                c6.caption(f"{row.get('조립수',0)}대")
                c7.caption(row.get('특이사항',''))
                if c8.button("🗑️", key=f"del_sch_{row_id}", help="삭제"):
                    st.session_state[del_ck] = True
                    st.rerun()

                # ── 확인 팝업: 행 아래에 별도 표시 ──
                if st.session_state.get(del_ck, False):
                    with st.container():
                        cf1, cf2, cf3 = st.columns([3, 1, 1])
                        cf1.warning(f"**[{row.get('날짜','')} / {row.get('모델명','')}]** 일정을 삭제하시겠습니까?")
                        if cf2.button("✅ 삭제", key=f"del_sch_yes_{row_id}", type="primary", use_container_width=True):
                            delete_schedule(int(row_id))
                            _clear_schedule_cache()                # ← 캐시 초기화
                            st.session_state.schedule_db = load_schedule()
                            st.session_state[del_ck] = False
                            st.rerun()
                        if cf3.button("취소", key=f"del_sch_no_{row_id}", use_container_width=True):
                            st.session_state[del_ck] = False
                            st.rerun()
        else:
            st.info("등록된 일정이 없습니다.")

    st.divider()



# ── OQC 라인 ─────────────────────────────────────────────────────
elif curr_l == "OQC 라인":
    st.markdown("<h2 class='centered-title'>🏅 OQC 출하 품질 검사</h2>", unsafe_allow_html=True)

    # 부적합 사유 선택지
    OQC_DEFECT_REASONS = st.session_state.get('dropdown_oqc_defect', ['(선택)', '기타 (직접 입력)'])

    db_oqc_all = st.session_state.production_db.copy()

    # ── 반 선택 ──────────────────────────────────────────────────
    BAN_CLR  = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}
    BAN_BG   = {"제조1반": "#ddeeff", "제조2반": "#d4f0e2", "제조3반": "#ede0f5"}
    oqc_ban  = st.radio("반 선택", ["전체"] + PRODUCTION_GROUPS, horizontal=True, key="oqc_ban_radio")
    db_oqc   = db_oqc_all[db_oqc_all['반'] == oqc_ban] if oqc_ban != "전체" else db_oqc_all.copy()

    # ── 요약 KPI (선택 반 기준) ───────────────────────────────────
    oqc_wait  = len(db_oqc[db_oqc['상태'] == 'OQC대기'])
    oqc_ing   = len(db_oqc[db_oqc['상태'] == 'OQC중'])
    oqc_pass  = len(db_oqc[db_oqc['상태'] == '출하승인'])
    oqc_fail  = len(db_oqc[db_oqc['상태'] == '부적합(OQC)'])

    # 반 색상 배지
    if oqc_ban != "전체":
        bc = BAN_CLR.get(oqc_ban, "#888"); bb = BAN_BG.get(oqc_ban, "#f0f0f0")
        st.markdown(f"<span style='background:{bb};color:{bc};padding:3px 12px;border-radius:8px;font-weight:bold;font-size:0.9rem;'>📍 {oqc_ban}</span>", unsafe_allow_html=True)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    ok1,ok2,ok3,ok4 = st.columns(4)
    ok1.metric("📥 OQC 대기", f"{oqc_wait}건")
    ok2.metric("🔍 검사 중",  f"{oqc_ing}건")
    ok3.metric("✅ 출하 승인", f"{oqc_pass}건")
    ok4.metric("🚫 부적합",   f"{oqc_fail}건")
    st.divider()

    # ── 입고 대기 목록 (포장 완료 → OQC 대기 전환) ───────────────
    st.markdown("<div class='section-title'>📥 입고 대기 (검사 합격 제품)</div>", unsafe_allow_html=True)
    packing_done = db_oqc[
        db_oqc['상태'] == 'OQC대기'
    ].sort_values('시간', ascending=False)

    if not packing_done.empty:
        hh = st.columns([2, 2, 1.5, 2, 1.5])
        for col, txt in zip(hh, ["시간", "모델", "반", "시리얼", "OQC 시작"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
        for idx, row in packing_done.iterrows():
            rr = st.columns([2, 2, 1.5, 2, 1.5])
            rr[0].caption(str(row.get('시간',''))[:16])
            rr[1].write(row.get('모델',''))
            rr[2].write(row.get('반',''))
            rr[3].markdown(f"`{row.get('시리얼','')}`")
            if rr[4].button("▶ OQC 시작", key=f"oqc_in_{idx}", use_container_width=True, type="primary"):
                _clear_production_cache()
                update_row(row['시리얼'], {'상태': 'OQC중', '시간': get_now_kst_str(), '라인': 'OQC 라인'})
                insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=row['반'],
                    이전상태='OQC대기', 이후상태='OQC중', 작업자=st.session_state.user_id)
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()
    else:
        st.info("OQC 대기 중인 제품이 없습니다.")

    st.divider()

    # ── OQC 대기 → 검사 시작 ─────────────────────────────────────
    st.markdown("<div class='section-title'>🔍 OQC 검사 진행</div>", unsafe_allow_html=True)
    oqc_wait_list = db_oqc[db_oqc['상태'] == 'OQC중'].sort_values('시간', ascending=False)

    if not oqc_wait_list.empty:
        for idx, row in oqc_wait_list.iterrows():
            with st.container(border=True):
                ic1, ic2, ic3, ic4 = st.columns([2, 1.5, 1.5, 1.5])
                ic1.markdown(f"**{row.get('모델','')}**")
                ic2.markdown(f"`{row.get('시리얼','')}`")
                ic3.write(row.get('반',''))
                # 상태 배지
                s_now = row.get('상태','')
                s_clr = '#fff3d4' if s_now == 'OQC대기' else '#ddeeff'
                s_txt = '#7a5c00' if s_now == 'OQC대기' else '#1a4a7a'
                ic4.markdown(f"<span style='background:{s_clr};color:{s_txt};padding:2px 8px;border-radius:6px;font-size:0.8rem;font-weight:bold;'>{'⏳ OQC대기' if s_now=='OQC대기' else '🔍 검사중'}</span>", unsafe_allow_html=True)

                # OQC 중 → 판정
                if s_now == 'OQC중':
                    oq1, oq2 = st.columns([2, 1])
                    with oq1:
                        defect_sel = st.selectbox("부적합 사유 (부적합 처리 시 선택)",
                            st.session_state.get("dropdown_oqc_defect", OQC_DEFECT_REASONS),
                            key=f"oqc_reason_{idx}")
                        if defect_sel == "기타 (직접 입력)":
                            defect_txt = st.text_input("직접 입력", key=f"oqc_reason_txt_{idx}",
                                placeholder="부적합 사유 입력")
                        elif defect_sel == "(선택)":
                            defect_txt = ""
                        else:
                            defect_txt = defect_sel
                    with oq2:
                        btn1 = st.button("✅ 합격 (출하 승인)", key=f"oqc_ok_{idx}",
                                         use_container_width=True, type="primary")
                        btn2 = st.button("🚫 부적합", key=f"oqc_ng_{idx}",
                                         use_container_width=True)
                    if btn1:
                        _clear_production_cache()
                        update_row(row['시리얼'], {
                            '상태': '출하승인', '시간': get_now_kst_str(),
                            '증상': 'OQC합격', '수리': 'OQC합격'
                        })
                        insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=row['반'],
                            이전상태='OQC중', 이후상태='출하승인',
                            작업자=st.session_state.user_id)
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                    if btn2:
                        if not defect_txt:
                            st.warning("⚠️ 부적합 사유를 먼저 선택해주세요.")
                        else:
                            _clear_production_cache()
                            update_row(row['시리얼'], {
                                '상태': '부적합(OQC)', '시간': get_now_kst_str(),
                                '증상': defect_txt, '수리': f"사유:{defect_txt}"
                            })
                            insert_audit_log(시리얼=row['시리얼'], 모델=row['모델'], 반=row['반'],
                                이전상태='OQC중', 이후상태='부적합(OQC)',
                                작업자=st.session_state.user_id, 비고=f"사유:{defect_txt}")
                            st.session_state.production_db = load_realtime_ledger()
                            st.rerun()
    else:
        st.info("OQC 검사 대기 중인 제품이 없습니다.")

    st.divider()

    # ── OQC 결과 이력 ─────────────────────────────────────────────
    st.markdown("<div class='section-title'>📋 OQC 결과 이력</div>", unsafe_allow_html=True)
    oqc_done = db_oqc[db_oqc['상태'].isin(['출하승인','부적합(OQC)'])].sort_values('시간', ascending=False)

    if not oqc_done.empty:
        oqc_sn_filter = st.text_input("🔍 S/N 검색", key="oqc_sn_filter", placeholder="시리얼 일부 입력")
        if oqc_sn_filter.strip():
            oqc_done = oqc_done[oqc_done['시리얼'].str.contains(oqc_sn_filter.strip(), case=False, na=False)]

        STATE_CLR2 = {
            '조립중':'#fff3d4','검사대기':'#fff3d4','검사중':'#ddeeff',
            '포장대기':'#ede0f5','포장중':'#fde8d4','완료':'#d4f0e2',
            '불량 처리 중':'#fde8e7','수리 완료(재투입)':'#e8f4fd',
            'OQC대기':'#fff3d4','OQC중':'#ddeeff',
            '출하승인':'#d4f0e2','부적합(OQC)':'#fde8e7',
        }

        rh = st.columns([1.8, 2, 1.5, 2.2, 1.5, 2.5, 1])
        for col, txt in zip(rh, ["시간", "모델", "반", "시리얼", "결과", "비고", "이력"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)

        for idx2, row in oqc_done.iterrows():
            rr2 = st.columns([1.8, 2, 1.5, 2.2, 1.5, 2.5, 1])
            rr2[0].caption(str(row.get('시간',''))[:16])
            rr2[1].write(row.get('모델',''))
            rr2[2].write(row.get('반',''))
            rr2[3].markdown(f"`{row.get('시리얼','')}`")
            결과 = row.get('상태','')
            if 결과 == '출하승인':
                rr2[4].markdown("<span style='background:#d4f0e2;color:#1f6640;padding:2px 8px;border-radius:5px;font-size:0.8rem;font-weight:bold;'>✅ 출하승인</span>", unsafe_allow_html=True)
            else:
                rr2[4].markdown("<span style='background:#fde8e7;color:#7a2e2a;padding:2px 8px;border-radius:5px;font-size:0.8rem;font-weight:bold;'>🚫 부적합</span>", unsafe_allow_html=True)
            rr2[5].caption(row.get('수리',''))

            # 이력 버튼 → 해당 행 아래 인라인 expander로 표시
            _hist_key = f"oqc_hist_open_{idx2}"
            if rr2[6].button("📋", key=f"oqc_hist_{idx2}", help="이력 조회"):
                st.session_state[_hist_key] = not st.session_state.get(_hist_key, False)

            if st.session_state.get(_hist_key, False):
                sn = row.get('시리얼','')
                with st.container(border=True):
                    hc1, hc2 = st.columns([8, 1])
                    hc1.markdown(f"📋 **제품 전체 이력** — `{sn}`")
                    if hc2.button("✖ 닫기", key=f"oqc_hist_close_{idx2}"):
                        st.session_state[_hist_key] = False
                        st.rerun()

                    db_all_h = st.session_state.production_db
                    sn_rows = db_all_h[db_all_h['시리얼'] == sn]
                    if not sn_rows.empty:
                        r0 = sn_rows.iloc[0]
                        st.caption(f"반: {r0.get('반','')}　|　모델: {r0.get('모델','')}　|　품목코드: {r0.get('품목코드','')}")
                    st.markdown("---")

                    # 상태 변경 이력
                    st.markdown("**🔄 상태 변경 이력**")
                    try:
                        res = get_supabase().table("audit_log").select("*").eq("시리얼", sn).order("시간").execute()
                        if res.data:
                            aud_df = pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
                            ah = st.columns([1.8, 1.5, 1.5, 1.2, 3])
                            for col, txt in zip(ah, ["시간","이전상태","이후상태","작업자","비고"]):
                                col.markdown(f"<p style='font-size:0.7rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
                            for _, ar in aud_df.iterrows():
                                ac = st.columns([1.8, 1.5, 1.5, 1.2, 3])
                                ac[0].caption(str(ar.get('시간',''))[:16])
                                prev_c = STATE_CLR2.get(ar.get('이전상태',''), '#f5f2ec')
                                next_c = STATE_CLR2.get(ar.get('이후상태',''), '#f5f2ec')
                                ac[1].markdown(f"<span style='background:{prev_c};padding:1px 6px;border-radius:4px;font-size:0.75rem;'>{ar.get('이전상태','')}</span>", unsafe_allow_html=True)
                                ac[2].markdown(f"<span style='background:{next_c};padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{ar.get('이후상태','')}</span>", unsafe_allow_html=True)
                                ac[3].caption(ar.get('작업자',''))
                                ac[4].caption(ar.get('비고',''))
                        else:
                            st.info("상태 변경 이력 없음")
                    except Exception as e:
                        st.warning(f"이력 조회 실패: {e}")

                    # 자재 시리얼
                    st.markdown("---")
                    st.markdown("**🔩 연결된 자재 시리얼**")
                    mat_df = load_material_serials(sn)
                    if not mat_df.empty:
                        for _, mr in mat_df.iterrows():
                            st.markdown(f"- **{mr.get('자재명','')}** : `{mr.get('자재시리얼','')}`　<span style='color:#aaa;font-size:0.75rem;'>{mr.get('작업자','')}</span>", unsafe_allow_html=True)
                    else:
                        st.info("등록된 자재 시리얼 없음")
    else:
        st.info("OQC 결과 이력이 없습니다.")


    st.divider()

    # ── OQC 전용 차트 ─────────────────────────────────────────────
    st.markdown("<div class='section-title'>📊 OQC 분석 차트</div>", unsafe_allow_html=True)

    db_oqc_chart = db_oqc_all.copy()  # 전체 반 기준
    oqc_chart_df = db_oqc_chart[db_oqc_chart['상태'].isin(['OQC대기','OQC중','출하승인','부적합(OQC)'])]

    if not oqc_chart_df.empty:
        import plotly.graph_objects as go

        cc1, cc2, cc3 = st.columns(3)

        # ① 반별 OQC 결과 현황 (누적 막대)
        with cc1:
            rows = []
            for ban in PRODUCTION_GROUPS:
                bdf = oqc_chart_df[oqc_chart_df['반'] == ban]
                rows.append({
                    '반': ban,
                    '출하승인': len(bdf[bdf['상태']=='출하승인']),
                    '부적합':   len(bdf[bdf['상태']=='부적합(OQC)']),
                    'OQC중':    len(bdf[bdf['상태']=='OQC중']),
                    'OQC대기':  len(bdf[bdf['상태']=='OQC대기']),
                })
            import pandas as _pd2
            ban_df = _pd2.DataFrame(rows)
            fig1 = go.Figure()
            CLR_MAP = {'출하승인':'#4da875','부적합':'#e8706a','OQC중':'#7eb8e8','OQC대기':'#f0c878'}
            for col in ['출하승인','부적합','OQC중','OQC대기']:
                fig1.add_trace(go.Bar(name=col, x=ban_df['반'], y=ban_df[col],
                    marker_color=CLR_MAP[col]))
            fig1.update_layout(
                title="반별 OQC 결과", barmode='stack',
                template='plotly_white', height=280,
                margin=dict(t=40,b=20,l=10,r=10),
                legend=dict(orientation='h', y=-0.25, font=dict(size=10))
            )
            st.plotly_chart(fig1, use_container_width=True)

        # ② 부적합 사유별 건수 (증상 컬럼 기준)
        with cc2:
            fail_df = oqc_chart_df[oqc_chart_df['상태']=='부적합(OQC)'].copy()
            if not fail_df.empty:
                reason_cnt = (fail_df['증상'].fillna('미기재')
                               .value_counts().reset_index())
                reason_cnt.columns = ['사유','건수']
                fig2 = go.Figure(go.Bar(
                    x=reason_cnt['건수'], y=reason_cnt['사유'],
                    orientation='h',
                    marker_color='#e8706a',
                    text=reason_cnt['건수'], textposition='outside'
                ))
                fig2.update_layout(
                    title="부적합 사유별 건수",
                    template='plotly_white', height=280,
                    margin=dict(t=40,b=20,l=10,r=10),
                    yaxis=dict(autorange='reversed')
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("부적합 데이터 없음")

        # ③ 합격률 추이 (월별)
        with cc3:
            oqc_done_chart = oqc_chart_df[oqc_chart_df['상태'].isin(['출하승인','부적합(OQC)'])].copy()
            if not oqc_done_chart.empty and '시간' in oqc_done_chart.columns:
                oqc_done_chart['월'] = oqc_done_chart['시간'].str[:7]
                monthly = oqc_done_chart.groupby('월').apply(
                    lambda x: round(len(x[x['상태']=='출하승인']) / len(x) * 100, 1)
                    if len(x) > 0 else 0
                ).reset_index()
                monthly.columns = ['월','합격률(%)']
                fig3 = go.Figure(go.Scatter(
                    x=monthly['월'], y=monthly['합격률(%)'],
                    mode='lines+markers+text',
                    line=dict(color='#4da875', width=2),
                    marker=dict(size=8),
                    text=monthly['합격률(%)'].apply(lambda v: f"{v}%"),
                    textposition='top center', textfont=dict(size=10)
                ))
                fig3.add_hline(y=100, line_dash="dash", line_color="#e8908a",
                               annotation_text="목표 100%", annotation_font_size=9)
                fig3.update_layout(
                    title="월별 합격률 추이",
                    template='plotly_white', height=280,
                    margin=dict(t=40,b=20,l=10,r=10),
                    yaxis=dict(range=[0,110], title="%")
                )
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("이력 데이터 없음")

        # ④ 모델별 부적합률 테이블
        if not oqc_done_chart.empty:
            model_grp = oqc_done_chart.groupby('모델').apply(
                lambda x: _pd2.Series({
                    '전체': len(x),
                    '출하승인': len(x[x['상태']=='출하승인']),
                    '부적합':   len(x[x['상태']=='부적합(OQC)']),
                    '부적합률(%)': round(len(x[x['상태']=='부적합(OQC)'])/len(x)*100,1) if len(x)>0 else 0
                })
            ).reset_index().sort_values('부적합률(%)', ascending=False)
            st.dataframe(model_grp, use_container_width=True, hide_index=True)
    else:
        st.info("OQC 데이터가 쌓이면 차트가 표시됩니다.")

    st.divider()
    st.divider()
    st.markdown("<div class='db-section' style='background:#7a5c3a;'>🔩 자재 시리얼 관리</div>", unsafe_allow_html=True)

    mat_tab1, mat_tab2, mat_tab3 = st.tabs(["🔍 자재 S/N 검색 (역추적)", "➕ 자재 S/N 등록", "📂 엑셀 업로드"])

    with mat_tab1:
        st.caption("메인 S/N 또는 자재 S/N으로 검색합니다.")
        
        # ✨ 개선: 검색 타입 선택 추가
        search_col1, search_col2 = st.columns(2)
        
        with search_col1:
            st.markdown("#### 📦 메인 S/N → 자재 조회")
            main_search = st.text_input("메인 S/N 입력", placeholder="메인 시리얼 입력", key="main_sn_search_mat")
            
            if main_search.strip():
                # 메인 시리얼로 자재 목록 조회
                mat_list = load_material_serials(main_search.strip())
                
                if not mat_list.empty:
                    st.success(f"✅ {len(mat_list)}건 발견")
                    st.markdown(f"**메인 S/N: `{main_search.strip()}`에 사용된 자재 목록**")
                    mh1 = st.columns([2, 2.5, 2.5, 1.5])
                    for col, txt in zip(mh1, ["등록시간", "자재명", "자재 S/N", "작업자"]):
                        col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
                    
                    for _, mr in mat_list.iterrows():
                        mc1 = st.columns([2, 2.5, 2.5, 1.5])
                        mc1[0].caption(str(mr.get('시간',''))[:16])
                        mc1[1].write(mr.get('자재명',''))
                        mc1[2].markdown(f"`{mr.get('자재시리얼','')}`")
                        mc1[3].caption(mr.get('작업자',''))
                else:
                    st.info("해당 메인 S/N의 자재 기록이 없습니다.")
        
        with search_col2:
            st.markdown("#### 🔩 자재 S/N → 메인 역추적")
            mat_search = st.text_input("자재 S/N 입력", placeholder="자재 시리얼 입력", key="mat_sn_search_reverse")
            
            if mat_search.strip():
                # 자재 시리얼로 역추적
                found = search_material_by_sn(mat_search.strip())
                
                if not found.empty:
                    st.success(f"✅ {len(found)}건 발견")
                    st.markdown(f"**자재 S/N: `{mat_search.strip()}`이 사용된 제품**")
                    mh2 = st.columns([1.8, 2, 1.5, 2, 1.5])
                    for col, txt in zip(mh2, ["등록시간","메인 S/N","반","모델","작업자"]):
                        col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)
                    
                    for _, mr in found.iterrows():
                        mc2 = st.columns([1.8, 2, 1.5, 2, 1.5])
                        mc2[0].caption(str(mr.get('시간',''))[:16])
                        mc2[1].markdown(f"**`{mr.get('메인시리얼','')}`**")
                        mc2[2].write(mr.get('반',''))
                        mc2[3].write(mr.get('모델',''))
                        mc2[4].caption(mr.get('작업자',''))
                else:
                    st.info("검색 결과 없음")

    with mat_tab2:
        st.caption("메인 S/N에 자재 S/N을 수동으로 추가 등록합니다.")
        db_now = st.session_state.production_db
        sn_list = db_now['시리얼'].dropna().unique().tolist() if not db_now.empty else []
        mt1, mt2 = st.columns(2)
        main_sn_sel = mt1.selectbox("메인 S/N 선택", ["직접 입력"] + sn_list, key="mat_reg_sn_sel")
        if main_sn_sel == "직접 입력":
            main_sn_val = mt2.text_input("메인 S/N 직접 입력", key="mat_reg_sn_txt")
        else:
            main_sn_val = main_sn_sel
            # 모델/반 자동 표시
            row_info = db_now[db_now['시리얼']==main_sn_sel]
            if not row_info.empty:
                ri = row_info.iloc[0]
                mt2.caption(f"모델: {ri.get('모델','')} / 반: {ri.get('반','')}")

        mat_add_count = st.number_input("추가할 자재 수", min_value=1, max_value=20, step=1, value=1, key="mat_add_count")
        mat_add_list = []
        for mi in range(int(mat_add_count)):
            ac1, ac2 = st.columns(2)
            an = ac1.text_input(f"자재명 #{mi+1}", key=f"mat_add_name_{mi}", placeholder="예: PCB")
            as_ = ac2.text_input(f"자재 S/N #{mi+1}", key=f"mat_add_sn_{mi}", placeholder="자재 시리얼")
            mat_add_list.append({"자재명": an, "자재시리얼": as_})

        if st.button("💾 자재 S/N 저장", type="primary", key="mat_save_btn"):
            sn_final = main_sn_val.strip() if main_sn_sel == "직접 입력" else main_sn_sel
            valid = [m for m in mat_add_list if m["자재시리얼"].strip()]
            if sn_final and valid:
                row_m = db_now[db_now['시리얼']==sn_final]
                m_model = row_m.iloc[0]['모델'] if not row_m.empty else ""
                m_ban   = row_m.iloc[0]['반']   if not row_m.empty else ""
                if insert_material_serials(sn_final, m_model, m_ban, valid, st.session_state.user_id):
                    load_material_serials.clear()
                    st.success(f"✅ {sn_final} → {len(valid)}개 자재 S/N 저장 완료")
            else:
                st.warning("메인 S/N과 자재 S/N을 입력해주세요.")

    with mat_tab3:
        st.caption("엑셀 파일로 자재 시리얼을 일괄 등록합니다.")
        # 양식 다운로드
        try:
            import openpyxl as _xl2; import io as _io2
            def _mat_template():
                wb = _xl2.Workbook(); ws = wb.active; ws.title = "자재시리얼"
                headers = ["메인시리얼","모델","반","자재명","자재시리얼"]
                for ci, h in enumerate(headers, 1):
                    ws.cell(1, ci, h)
                ws.append(["MAIN-001","G3014 KBD","제조1반","PCB","PCB-2024-001"])
                ws.append(["MAIN-001","G3014 KBD","제조1반","배터리","BAT-2024-001"])
                buf = _io2.BytesIO(); wb.save(buf); buf.seek(0); return buf
            st.download_button("📥 양식 다운로드", data=_mat_template(),
                               file_name="자재시리얼_양식.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="mat_tmpl_dl")
        except: st.caption("양식 다운로드 기능 준비 중")

        mat_file = st.file_uploader("자재 시리얼 엑셀 업로드", type=["xlsx","xls"], key="mat_xl_upload")
        if mat_file:
            try:
                import openpyxl as _xl3
                wb2 = _xl3.load_workbook(mat_file)
                ws2 = wb2.active
                rows2 = list(ws2.iter_rows(min_row=2, values_only=True))
                ok_cnt = 0; err_cnt = 0
                for r2 in rows2:
                    if len(r2) >= 5 and r2[0] and r2[4]:
                        res2 = insert_material_serials(
                            메인시리얼=str(r2[0]).strip(),
                            모델=str(r2[1] or "").strip(),
                            반=str(r2[2] or "").strip(),
                            자재목록=[{"자재명": str(r2[3] or "").strip(), "자재시리얼": str(r2[4]).strip()}],
                            작업자=st.session_state.user_id
                        )
                        if res2: ok_cnt += 1
                        else:    err_cnt += 1
                st.cache_data.clear()
                st.success(f"✅ 업로드 완료: {ok_cnt}건 성공 / {err_cnt}건 실패")
            except Exception as e:
                st.error(f"파일 처리 오류: {e}")



# ── 불량 공정 ────────────────────────────────────────────────────
elif curr_l == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db

    # 반 선택
    sel_group = st.radio("조회 반 선택", ["전체"] + PRODUCTION_GROUPS, horizontal=True,
                         key="defect_group_radio")
    if sel_group == "전체":
        target_groups = PRODUCTION_GROUPS
    else:
        target_groups = [sel_group]

    # 요약 카드 (선택된 반별)
    card_cols = st.columns(len(target_groups))
    for ci, g in enumerate(target_groups):
        w = len(db[(db['반']==g)&(db['상태']=="불량 처리 중")])
        d = len(db[(db['반']==g)&(db['상태']=='수리 완료(재투입)')])
        with card_cols[ci]:
            st.markdown(
                f"<div style='background:#fffdf8; border:1px solid #e0d8c8; border-radius:12px; padding:14px; margin-bottom:8px;'>"
                f"<div style='font-weight:bold; color:#3d3530; margin-bottom:10px; font-size:1rem;'>📍 {g}</div>"
                f"<div style='display:flex; gap:8px;'>"
                f"<div style='flex:1; background:#fde8e7; border-radius:8px; padding:10px 4px; text-align:center;'>"
                f"<div style='font-size:0.72rem; color:#7a2e2a; font-weight:bold;'>🛠️ 분석 대기</div>"
                f"<div style='font-size:1.8rem; color:#c8605a; font-weight:bold;'>{w}</div></div>"
                f"<div style='flex:1; background:#d4f0e2; border-radius:8px; padding:10px 4px; text-align:center;'>"
                f"<div style='font-size:0.72rem; color:#1f6640; font-weight:bold;'>✅ 조치 완료</div>"
                f"<div style='font-size:1.8rem; color:#4da875; font-weight:bold;'>{d}</div></div>"
                f"</div></div>",
                unsafe_allow_html=True
            )

    st.divider()

    # 불량 원인 / 수리 조치 선택지
    DEFECT_CAUSES = st.session_state.get('dropdown_defect_cause', ['(선택)', '기타 (직접 입력)'])
    REPAIR_ACTIONS = st.session_state.get('dropdown_repair_action', ['(선택)', '기타 (직접 입력)'])

    # 처리 대기 목록
    has_any = False
    for g in target_groups:
        wait = db[(db['반']==g)&(db['상태']=="불량 처리 중")]
        if wait.empty: continue
        has_any = True
        st.markdown(f"#### 📍 {g} 불량 처리 대기")
        for idx, row in wait.iterrows():
            with st.container(border=True):
                # 발생 정보
                # 불량 입고 출처 파싱
                _증상_raw = str(row.get('증상', ''))
                _from_line = ''
                if '불량입고출처:' in _증상_raw:
                    _from_line = _증상_raw.split('불량입고출처:')[-1].strip().split()[0]

                ic1, ic2, ic3, ic4, ic5 = st.columns([2, 1.3, 1.5, 1.5, 1.2])
                ic1.markdown(f"**{row['모델']}**")
                ic2.markdown(f"`{row['품목코드']}`")
                ic3.markdown(f"`{row['시리얼']}`")
                ic4.caption(f"🕐 {str(row.get('시간',''))[:16]}")
                if _from_line:
                    ic5.markdown(
                        f"<div style='background:#fff3d4;color:#7a5c00;padding:2px 6px;"
                        f"border-radius:5px;font-size:0.72rem;font-weight:700;text-align:center;"
                        f"border:1px solid #f0c878;'>📍 {_from_line}</div>",
                        unsafe_allow_html=True)
                else:
                    ic5.caption("출처 미기록")

                r1, r2 = st.columns(2)
                # 불량 원인 드롭다운 + 직접입력
                cause_sel = r1.selectbox("불량 원인", DEFECT_CAUSES, key=f"cs_{idx}")
                if cause_sel == "기타 (직접 입력)":
                    v_c = r1.text_input("직접 입력", key=f"c_{idx}", placeholder="원인 직접 입력")
                elif cause_sel == "(선택)":
                    v_c = ""
                else:
                    v_c = cause_sel

                # 수리 조치 드롭다운 + 직접입력
                action_sel = r2.selectbox("수리 조치", REPAIR_ACTIONS, key=f"as_{idx}")
                if action_sel == "기타 (직접 입력)":
                    v_a = r2.text_input("직접 입력", key=f"a_{idx}", placeholder="조치 직접 입력")
                elif action_sel == "(선택)":
                    v_a = ""
                else:
                    v_a = action_sel

                c_f, c_b = st.columns([3, 1])
                img = c_f.file_uploader("사진 첨부", type=['jpg','png'], key=f"i_{idx}")
                c_b.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if c_b.button("✅ 확정", key=f"b_{idx}", type="primary", use_container_width=True):
                    if v_c and v_a:
                        _clear_production_cache()
                        img_link = f" [사진: {upload_img_to_drive(img, row['시리얼'])}]" if img else ""
                        update_row(row['시리얼'], {
                            '상태': "수리 완료(재투입)", '시간': get_now_kst_str(),
                            '증상': v_c, '수리': v_a + img_link
                        })
                        # 감사 로그 기록
                        insert_audit_log(
                            시리얼=row['시리얼'], 모델=row['모델'], 반=row['반'],
                            이전상태="불량 처리 중", 이후상태="수리 완료(재투입)",
                            작업자=st.session_state.user_id,
                            비고=f"원인:{v_c} / 조치:{v_a}"
                        )
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                    else:
                        st.warning("불량 원인과 수리 조치를 모두 선택해주세요.")
    if not has_any:
        st.success("현재 처리 대기 중인 불량 이슈가 없습니다.")

# ── 수리 현황 리포트 ─────────────────────────────────────────────
elif curr_l == "수리 현황 리포트":
    st.markdown("<h2 class='centered-title'>📈 품질 분석 및 수리 이력 리포트</h2>", unsafe_allow_html=True)
    hist_df = st.session_state.production_db
    hist_df = hist_df[hist_df['수리'].astype(str).str.strip() != ""]

    if not hist_df.empty:
        c_l, c_r = st.columns([1.8, 1.2])
        with c_l:
            st.plotly_chart(px.bar(hist_df.groupby('라인').size().reset_index(name='수량'),
                x='라인', y='수량', title="공정별 이슈 빈도"), use_container_width=True)
        with c_r:
            st.plotly_chart(px.pie(hist_df.groupby('모델').size().reset_index(name='수량'),
                values='수량', names='모델', hole=0.4, title="모델별 불량 비중"), use_container_width=True)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else:
        st.info("기록된 이슈 내역이 없습니다.")

    # ── 감사 로그 조회 ────────────────────────────────────────────
    st.divider()
    st.markdown("<div class='section-title'>🔍 감사 로그 (상태 변경 이력)</div>", unsafe_allow_html=True)

    # 필터
    af1, af2, af3, af4 = st.columns([1.5, 1.5, 2, 1])
    a_ban    = af1.selectbox("반 필터", ["전체"] + PRODUCTION_GROUPS, key="audit_ban")
    a_state  = af2.selectbox("이후 상태", ["전체", "검사대기", "검사중", "포장대기", "포장중",
                                           "완료", "불량 처리 중", "수리 완료(재투입)"], key="audit_state")
    a_sn     = af3.text_input("S/N 검색", placeholder="시리얼 일부 입력", key="audit_sn")
    if af4.button("🔄 새로고침", key="audit_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    audit_df = load_audit_log()

    if not audit_df.empty:
        if a_ban   != "전체":  audit_df = audit_df[audit_df['반'] == a_ban]
        if a_state != "전체":  audit_df = audit_df[audit_df['이후상태'] == a_state]
        if a_sn.strip():       audit_df = audit_df[audit_df['시리얼'].str.contains(a_sn.strip(), case=False, na=False)]

        # 요약 KPI
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("전체 기록",   f"{len(audit_df):,} 건")
        k2.metric("완료 처리",   f"{len(audit_df[audit_df['이후상태']=='완료']):,} 건")
        k3.metric("불량 발생",   f"{len(audit_df[audit_df['이후상태']=='불량 처리 중']):,} 건")
        k4.metric("수리 완료",   f"{len(audit_df[audit_df['이후상태']=='수리 완료(재투입)']):,} 건")

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # 상태별 색상
        STATE_CLR = {
            '검사대기':        '#fff3d4',
            '검사중':          '#ddeeff',
            '포장대기':        '#ede0f5',
            '포장중':          '#fde8d4',
            '완료':            '#d4f0e2',
            '불량 처리 중':    '#fde8e7',
            '수리 완료(재투입)':'#e8f4fd',
        }

        # 테이블 헤더
        th = st.columns([1.8, 1.5, 2.2, 1.2, 1.5, 1.5, 1.2, 2.5])
        for col, txt in zip(th, ["시간", "시리얼", "모델", "반", "이전 상태", "이후 상태", "작업자", "비고"]):
            col.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;padding-bottom:3px;border-bottom:1px solid #e0d8c8;'>{txt}</p>", unsafe_allow_html=True)

        for _, row in audit_df.iterrows():
            tr = st.columns([1.8, 1.5, 2.2, 1.2, 1.5, 1.5, 1.2, 2.5])
            tr[0].caption(str(row.get('시간',''))[:16])
            tr[1].markdown(f"`{row.get('시리얼','')}`")
            tr[2].write(row.get('모델',''))
            tr[3].write(row.get('반',''))
            # 이전 상태
            prev_clr = STATE_CLR.get(row.get('이전상태',''), '#f5f2ec')
            tr[4].markdown(f"<span style='background:{prev_clr};padding:1px 6px;border-radius:4px;font-size:0.75rem;'>{row.get('이전상태','')}</span>", unsafe_allow_html=True)
            # 이후 상태
            next_clr = STATE_CLR.get(row.get('이후상태',''), '#f5f2ec')
            tr[5].markdown(f"<span style='background:{next_clr};padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{row.get('이후상태','')}</span>", unsafe_allow_html=True)
            tr[6].caption(row.get('작업자',''))
            tr[7].caption(row.get('비고',''))
    else:
        st.info("감사 로그가 없습니다. 상태 변경 시 자동으로 기록됩니다.")

# ── 마스터 관리 ──────────────────────────────────────────────────
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            with st.form("admin_verify"):
                pw = st.text_input("마스터 비밀번호", type="password")
                if st.form_submit_button("인증", use_container_width=True):
                    master_hash = get_master_pw_hash()
                    if master_hash is None:
                        st.error("마스터 비밀번호가 설정되지 않았습니다.")
                    elif verify_pw(pw, master_hash):
                        st.session_state.admin_authenticated = True; st.rerun()
                    else:
                        st.error("비밀번호가 올바르지 않습니다.")
    else:


        st.markdown("<div class='section-title'>📋 반별 독립 모델/품목 설정</div>", unsafe_allow_html=True)
        tabs = st.tabs([f"{g} 설정" for g in PRODUCTION_GROUPS])
        for i, g_name in enumerate(PRODUCTION_GROUPS):
            with tabs[i]:
                # ── 등록 ─────────────────────────────
                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin-bottom:6px;'>신규 모델 등록</h4>", unsafe_allow_html=True)
                        st.caption("여러 모델은 줄바꿈으로 구분")
                        nm_bulk = st.text_area(f"{g_name} 모델명", key=f"nm_{g_name}", height=120, placeholder="EPS7150\nEPS7133\nT20i")
                        if st.button(f"{g_name} 모델 저장", key=f"nb_{g_name}", use_container_width=True):
                            if nm_bulk.strip():
                                added, skipped = [], []
                                for nm in [x.strip() for x in nm_bulk.strip().splitlines() if x.strip()]:
                                    if nm not in st.session_state.group_master_models.get(g_name, []):
                                        st.session_state.group_master_models[g_name].append(nm)
                                        st.session_state.group_master_items[g_name][nm] = []
                                        upsert_model_master(g_name, nm, nm)
                                        added.append(nm)
                                    else: skipped.append(nm)
                                if added:   st.success(f"등록 완료: {', '.join(added)}")
                                if skipped: st.warning(f"이미 존재: {', '.join(skipped)}")
                                st.rerun()
                            else: st.warning("모델명을 입력해주세요.")
                with c2:
                    with st.container(border=True):
                        st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin-bottom:6px;'>세부 품목 등록</h4>", unsafe_allow_html=True)
                        g_mods = st.session_state.group_master_models.get(g_name, [])
                        if g_mods:
                            sm = st.selectbox(f"{g_name} 모델 선택", g_mods, key=f"sm_{g_name}")
                            st.caption("여러 품목은 줄바꿈으로 구분")
                            ni_bulk = st.text_area(f"[{sm}] 품목코드", key=f"ni_{g_name}", height=120, placeholder="7150-A\n7150-B")
                            if st.button(f"{g_name} 품목 저장", key=f"ib_{g_name}", use_container_width=True):
                                if ni_bulk.strip():
                                    current = st.session_state.group_master_items[g_name].get(sm, [])
                                    added, skipped = [], []
                                    for ni in [x.strip() for x in ni_bulk.strip().splitlines() if x.strip()]:
                                        if ni not in current:
                                            st.session_state.group_master_items[g_name][sm].append(ni)
                                            upsert_model_master(g_name, sm, ni)
                                            added.append(ni)
                                        else: skipped.append(ni)
                                    if added:   st.success(f"등록 완료: {', '.join(added)}")
                                    if skipped: st.warning(f"이미 존재: {', '.join(skipped)}")
                                    st.rerun()
                                else: st.warning("품목코드를 입력해주세요.")
                        else:
                            st.warning("모델을 먼저 등록하세요.")

                # ── 삭제 ─────────────────────────────
                st.divider()
                st.markdown("<h4 style='color:#c8605a; font-weight:bold; margin-bottom:6px;'>🗑️ 모델 / 품목 삭제</h4>", unsafe_allow_html=True)

                # ── 전체 삭제 버튼
                all_master_ck = f"del_all_master_ck_{g_name}"
                if not st.session_state.get(all_master_ck, False):
                    if st.button(f"⛔ {g_name} 모델/품목 전체 삭제", key=f"del_all_m_{g_name}",
                                 use_container_width=True, type="secondary"):
                        st.session_state[all_master_ck] = True
                        st.rerun()
                else:
                    st.error(f"⛔ [{g_name}]의 모든 모델과 품목코드를 삭제합니다. 되돌릴 수 없습니다.")
                    am1, am2, am3 = st.columns([2, 1, 1])
                    am1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                    if am2.button("✅ 예, 전체 삭제", key=f"del_all_m_yes_{g_name}",
                                  type="primary", use_container_width=True):
                        st.session_state.group_master_models[g_name] = []
                        st.session_state.group_master_items[g_name]  = {}
                        delete_all_master_by_group(g_name)
                        st.session_state[all_master_ck] = False
                        st.success(f"{g_name} 모델/품목 전체 삭제 완료")
                        st.rerun()
                    if am3.button("취소", key=f"del_all_m_no_{g_name}", use_container_width=True):
                        st.session_state[all_master_ck] = False
                        st.rerun()

                st.divider()
                del_c1, del_c2 = st.columns(2)

                with del_c1:
                    with st.container(border=True):
                        st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:4px;'>모델 삭제</p>", unsafe_allow_html=True)
                        st.caption("삭제 시 해당 모델의 모든 품목코드도 함께 삭제됩니다")
                        g_mods_del = st.session_state.group_master_models.get(g_name, [])
                        if g_mods_del:
                            del_model = st.selectbox("삭제할 모델", g_mods_del, key=f"del_m_{g_name}")
                            del_m_ck  = f"del_model_ck_{g_name}_{del_model}"
                            if not st.session_state.get(del_m_ck, False):
                                if st.button(f"🗑️ [{del_model}] 삭제", key=f"del_mb_{g_name}", use_container_width=True):
                                    st.session_state[del_m_ck] = True
                                    st.rerun()
                            else:
                                st.warning(f"⚠️ [{del_model}] 모델과 품목 전체를 삭제하시겠습니까?")
                                dm1, dm2 = st.columns(2)
                                if dm1.button("✅ 삭제", key=f"del_m_yes_{g_name}", type="primary", use_container_width=True):
                                    # session_state 제거
                                    if del_model in st.session_state.group_master_models.get(g_name, []):
                                        st.session_state.group_master_models[g_name].remove(del_model)
                                    st.session_state.group_master_items[g_name].pop(del_model, None)
                                    # DB 제거
                                    delete_model_from_master(g_name, del_model)
                                    st.session_state[del_m_ck] = False
                                    st.success(f"[{del_model}] 삭제 완료")
                                    st.rerun()
                                if dm2.button("취소", key=f"del_m_no_{g_name}", use_container_width=True):
                                    st.session_state[del_m_ck] = False
                                    st.rerun()
                        else:
                            st.info("등록된 모델이 없습니다.")

                with del_c2:
                    with st.container(border=True):
                        st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:4px;'>품목 삭제</p>", unsafe_allow_html=True)
                        st.caption("선택한 모델에서 특정 품목코드만 삭제합니다")
                        g_mods_di = st.session_state.group_master_models.get(g_name, [])
                        if g_mods_di:
                            di_model = st.selectbox("모델 선택", g_mods_di, key=f"di_m_{g_name}")
                            items_di = st.session_state.group_master_items.get(g_name, {}).get(di_model, [])
                            if items_di:
                                del_item = st.selectbox("삭제할 품목코드", items_di, key=f"del_i_{g_name}")
                                del_i_ck = f"del_item_ck_{g_name}_{di_model}_{del_item}"
                                if not st.session_state.get(del_i_ck, False):
                                    if st.button(f"🗑️ [{del_item}] 삭제", key=f"del_ib_{g_name}", use_container_width=True):
                                        st.session_state[del_i_ck] = True
                                        st.rerun()
                                else:
                                    st.warning(f"⚠️ [{di_model}] 의 [{del_item}] 품목을 삭제하시겠습니까?")
                                    di1, di2 = st.columns(2)
                                    if di1.button("✅ 삭제", key=f"del_i_yes_{g_name}", type="primary", use_container_width=True):
                                        st.session_state.group_master_items[g_name][di_model].remove(del_item)
                                        delete_item_from_master(g_name, di_model, del_item)
                                        st.session_state[del_i_ck] = False
                                        st.success(f"[{del_item}] 삭제 완료")
                                        st.rerun()
                                    if di2.button("취소", key=f"del_i_no_{g_name}", use_container_width=True):
                                        st.session_state[del_i_ck] = False
                                        st.rerun()
                            else:
                                st.info("등록된 품목이 없습니다.")
                        else:
                            st.info("등록된 모델이 없습니다.")

        st.divider()
        st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin:16px 0 10px 0;'>계정 및 데이터 관리</h4>", unsafe_allow_html=True)
        ac1, ac2 = st.columns(2)

        with ac1:
            # ✨ 개선: 탭으로 기본 생성과 개별 권한 관리 분리
            user_tab1, user_tab2, user_tab3 = st.tabs(["➕ 계정 생성", "🔑 개별 권한 관리", "🗑️ 계정 삭제"])
            
            with user_tab1:
                with st.form("user_mgmt"):
                    st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'>👤 사용자 계정 생성/업데이트</p>", unsafe_allow_html=True)
                    nu  = st.text_input("ID")
                    np_ = st.text_input("PW", type="password")
                    nr  = st.selectbox("Role", ["admin","master","control_tower","assembly_team","qc_team","packing_team","schedule_manager","oqc_team"])
                    if st.form_submit_button("사용자 저장"):
                        if nu and np_:
                            pw_hash = hash_pw(np_)
                            st.session_state.user_db[nu] = {"pw_hash": pw_hash, "role": nr}
                            # Supabase users 테이블에도 저장 (재시작 시 유지)
                            try:
                                get_supabase().table("users").upsert(
                                    {"username": nu, "password_hash": pw_hash, "role": nr},
                                    on_conflict="username"
                                ).execute()
                                st.success(f"계정 [{nu}] 저장 완료 (DB 반영됨)")
                            except Exception as _e:
                                st.warning(f"계정 [{nu}] 메모리 저장됨, DB 저장 실패: {_e}")
                        else: st.warning("ID와 PW를 모두 입력해주세요.")
            
            with user_tab2:
                st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'>🔑 사용자별 개별 권한 부여</p>", unsafe_allow_html=True)
                
                # 등록된 사용자 목록
                user_list = list(st.session_state.user_db.keys())
                if user_list:
                    selected_user = st.selectbox("사용자 선택", user_list, key="perm_user_select")
                    current_role = st.session_state.user_db[selected_user].get("role", "assembly_team")
                    
                    st.caption(f"현재 역할: **{current_role}**")
                    st.caption("체크된 메뉴에만 접근 가능합니다.")
                    
                    # 현재 사용자의 커스텀 권한 가져오기 (없으면 기본 역할 권한)
                    current_perms = st.session_state.user_db[selected_user].get("custom_permissions", None)
                    if current_perms is None:
                        current_perms = ROLES.get(current_role, [])
                    
                    # 모든 가능한 메뉴 목록
                    all_menus = ["생산 지표 관리", "조립 라인", "검사 라인", "포장 라인", "OQC 라인",
                                "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리",
                                "작업자 매뉴얼", "관리자 매뉴얼"]

                    st.markdown("**접근 가능 메뉴:**")

                    # 체크박스로 권한 선택
                    selected_perms = []
                    cols = st.columns(2)
                    for idx, menu in enumerate(all_menus):
                        col = cols[idx % 2]
                        if col.checkbox(menu, value=(menu in current_perms), key=f"perm_{selected_user}_{menu}"):
                            selected_perms.append(menu)

                    perm_col1, perm_col2 = st.columns(2)
                    if perm_col1.button("💾 권한 저장", key="save_custom_perm", use_container_width=True, type="primary"):
                        st.session_state.user_db[selected_user]["custom_permissions"] = selected_perms
                        try:
                            import json
                            get_supabase().table("users").update(
                                {"custom_permissions": json.dumps(selected_perms, ensure_ascii=False)}
                            ).eq("username", selected_user).execute()
                            st.success(f"✅ [{selected_user}] 권한 저장 완료 ({len(selected_perms)}개 메뉴) — DB 반영됨")
                        except Exception as _e:
                            st.success(f"✅ [{selected_user}] 권한 저장 완료 ({len(selected_perms)}개 메뉴)")
                            st.caption(f"DB 저장 실패 (세션에만 적용): {_e}")

                    if perm_col2.button("↩️ 기본 권한 복원", key="reset_custom_perm", use_container_width=True):
                        if "custom_permissions" in st.session_state.user_db[selected_user]:
                            del st.session_state.user_db[selected_user]["custom_permissions"]
                        try:
                            get_supabase().table("users").update(
                                {"custom_permissions": None}
                            ).eq("username", selected_user).execute()
                            st.success(f"✅ [{selected_user}] 기본 권한으로 복원됨 — DB 반영됨")
                        except Exception:
                            st.success(f"✅ [{selected_user}] 기본 권한으로 복원됨")
                else:
                    st.info("등록된 사용자가 없습니다. 먼저 계정을 생성해주세요.")

            with user_tab3:
                st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'>🗑️ 계정 삭제</p>", unsafe_allow_html=True)
                del_user_list = [u for u in st.session_state.user_db.keys()
                                 if u != st.session_state.user_id]
                if del_user_list:
                    del_target = st.selectbox("삭제할 계정 선택", del_user_list, key="del_user_select")
                    del_role = st.session_state.user_db[del_target].get("role", "")
                    st.caption(f"역할: **{del_role}**")
                    if not st.session_state.get("del_user_confirm", False):
                        if st.button(f"🗑️ [{del_target}] 삭제", key="del_user_btn",
                                     use_container_width=True, type="primary"):
                            st.session_state["del_user_confirm"] = True
                            st.session_state["del_user_target"] = del_target
                            st.rerun()
                    else:
                        confirm_target = st.session_state.get("del_user_target", "")
                        st.warning(f"⚠️ [{confirm_target}] 계정을 삭제하시겠습니까? 복구할 수 없습니다.")
                        dc1, dc2 = st.columns(2)
                        if dc1.button("✅ 삭제 확인", key="del_user_yes",
                                      use_container_width=True, type="primary"):
                            if confirm_target in st.session_state.user_db:
                                del st.session_state.user_db[confirm_target]
                            try:
                                get_supabase().table("users").delete().eq(
                                    "username", confirm_target).execute()
                                st.success(f"✅ [{confirm_target}] 계정 삭제 완료")
                            except Exception as _e:
                                st.warning(f"메모리 삭제 완료, DB 삭제 실패: {_e}")
                            st.session_state["del_user_confirm"] = False
                            st.session_state["del_user_target"] = ""
                            st.rerun()
                        if dc2.button("취소", key="del_user_no", use_container_width=True):
                            st.session_state["del_user_confirm"] = False
                            st.session_state["del_user_target"] = ""
                            st.rerun()
                else:
                    st.info("삭제 가능한 계정이 없습니다. (본인 계정은 삭제 불가)")

        with ac2:
            st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'>🗄️ 시스템 데이터 관리</p>", unsafe_allow_html=True)
            db_export    = st.session_state.production_db.copy()
            export_group = st.selectbox("반 선택", ["전체"] + PRODUCTION_GROUPS, key="export_group")
            ex_c1, ex_c2 = st.columns(2)
            start_date   = ex_c1.date_input("시작 날짜", key="export_start")
            end_date     = ex_c2.date_input("종료 날짜", key="export_end")
            if export_group != "전체":
                db_export = db_export[db_export['반'] == export_group]
            if '시간' in db_export.columns and not db_export.empty:
                try:
                    db_export['시간_dt'] = pd.to_datetime(db_export['시간'])
                    db_export = db_export[(db_export['시간_dt'].dt.date >= start_date) & (db_export['시간_dt'].dt.date <= end_date)]
                    db_export = db_export.drop(columns=['시간_dt'])
                except: pass
            st.caption(f"📋 조회 결과: **{len(db_export)}건**")
            st.download_button("📥 CSV 다운로드",
                db_export.to_csv(index=False).encode('utf-8-sig'),
                f"PMS_{export_group}_{start_date}~{end_date}.csv",
                use_container_width=True)
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                db_export.to_excel(writer, index=False, sheet_name='생산데이터')
            st.download_button("📊 Excel 다운로드", excel_buf.getvalue(),
                f"PMS_{export_group}_{start_date}~{end_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)

        st.divider()

        # ── 데이터 삭제 관리 ──────────────────────────────────────
        # ── 드롭박스 편집 ──────────────────────────────────────────
        st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin:16px 0 10px 0;'>📝 드롭박스 옵션 편집</h4>", unsafe_allow_html=True)
        st.caption("각 항목을 한 줄에 하나씩 입력하세요. '(선택)'과 '기타 (직접 입력)'은 자동 유지됩니다.")

        dd_tab1, dd_tab2, dd_tab3, dd_tab4 = st.tabs([
            "🔍 OQC 부적합 사유", "⚠️ 불량 원인", "🔧 수리 조치", "🔩 자재명"])

        def _render_dropdown_editor(ss_key: str, label: str, tab_key: str):
            """드롭박스 편집 공통 렌더러"""
            current = st.session_state.get(ss_key, [])
            # (선택), 기타(직접 입력) 제외한 편집 가능 항목
            editable = [x for x in current if x not in ["(선택)", "기타 (직접 입력)"]]
            current_text = "\n".join(editable)
            new_text = st.text_area(
                f"{label} 목록 (한 줄에 하나씩)",
                value=current_text, height=200,
                key=f"dd_edit_{tab_key}",
                placeholder="항목1\n항목2\n항목3"
            )
            ec1, ec2 = st.columns([1, 1])
            if ec1.button(f"💾 저장", key=f"dd_save_{tab_key}", use_container_width=True, type="primary"):
                new_items = [x.strip() for x in new_text.strip().splitlines() if x.strip()]
                seen = set()
                deduped = []
                for item in new_items:
                    if item not in seen and item not in ["(선택)", "기타 (직접 입력)"]:
                        seen.add(item); deduped.append(item)
                final = ["(선택)"] + deduped + ["기타 (직접 입력)"]
                st.session_state[ss_key] = final
                if save_app_setting(ss_key, final):
                    st.success(f"✅ {label} 저장 완료 ({len(deduped)}개 항목) — DB 반영됨")
                else:
                    st.success(f"✅ {label} 저장 완료 ({len(deduped)}개 항목)")
                    st.caption("DB 저장 실패 — 앱 재시작 시 초기화될 수 있습니다.")
                st.rerun()
            if ec2.button(f"↩️ 기본값 복원", key=f"dd_reset_{tab_key}", use_container_width=True):
                default_val = _DD_DEFAULTS.get(ss_key, [])
                st.session_state[ss_key] = default_val
                save_app_setting(ss_key, default_val)
                st.success("기본값으로 복원됩니다.")
                st.rerun()
            st.caption(f"현재 {len(editable)}개 항목 등록됨 (선택·직접입력 제외)")

        def _render_mat_name_editor():
            """자재명 목록 — 항목별 삭제 + 추가 + 전체삭제"""
            _SS = "dropdown_mat_name"

            # ── session_state 직접 참조 (or 폴백 없음 — 빈 목록도 유지)
            # 초기화 루프에서 이미 None이면 기본값 세팅됨
            current = list(st.session_state.get(_SS, []))

            # ── 항목별 행 렌더 ────────────────────────────────────────
            if current:
                st.markdown("<p style='font-size:0.8rem;font-weight:700;color:#5a4f45;margin:0 0 6px 0;'>등록된 자재명</p>", unsafe_allow_html=True)
                _del_idx = None
                for i, item in enumerate(current):
                    r1, r2 = st.columns([5, 1])
                    r1.markdown(f"<div style='padding:5px 8px;background:#f5f2ec;border-radius:6px;font-size:0.85rem;'>{item}</div>", unsafe_allow_html=True)
                    if r2.button("🗑", key=f"mat_del_item_{i}", help=f"{item} 삭제", use_container_width=True):
                        _del_idx = i
                if _del_idx is not None:
                    current.pop(_del_idx)
                    st.session_state[_SS] = current
                    ok = save_app_setting(_SS, current)
                    if ok:
                        st.toast("✅ 삭제 완료", icon="✅")
                    else:
                        st.toast("⚠️ DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다", icon="⚠️")
                    st.rerun()
            else:
                st.info("등록된 자재명이 없습니다. 아래에서 추가하거나 기본값을 복원하세요.")

            st.divider()

            # ── 신규 추가 ─────────────────────────────────────────────
            st.markdown("<p style='font-size:0.8rem;font-weight:700;color:#5a4f45;margin:0 0 4px 0;'>자재명 추가</p>", unsafe_allow_html=True)
            na1, na2 = st.columns([4, 1])
            new_item = na1.text_input("", placeholder="추가할 자재명 입력", key="mat_new_input", label_visibility="collapsed")
            if na2.button("➕ 추가", key="mat_add_btn", use_container_width=True, type="primary"):
                val = new_item.strip()
                if val and val not in current:
                    current.append(val)
                    st.session_state[_SS] = current
                    ok = save_app_setting(_SS, current)
                    if ok:
                        st.toast(f"✅ '{val}' 추가 완료", icon="✅")
                    else:
                        st.toast("⚠️ DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다", icon="⚠️")
                    st.rerun()
                elif val in current:
                    st.warning(f"'{val}'은 이미 등록된 자재명입니다.")
                else:
                    st.warning("자재명을 입력해주세요.")

            st.divider()

            # ── 전체 삭제 / 기본값 복원 ───────────────────────────────
            bc1, bc2 = st.columns([1, 1])
            if bc1.button("🗑 전체 삭제", key="mat_clear_all", use_container_width=True):
                st.session_state["_mat_clear_confirm"] = True; st.rerun()
            if bc2.button("↩️ 기본값 복원", key="dd_reset_mat", use_container_width=True):
                default_val = _DD_DEFAULTS.get(_SS, [])
                st.session_state[_SS] = default_val
                ok = save_app_setting(_SS, default_val)
                if not ok:
                    st.toast("⚠️ DB 저장 실패", icon="⚠️")
                st.rerun()

            if st.session_state.get("_mat_clear_confirm"):
                st.error("⛔ 자재명 목록을 전체 삭제합니다. 계속하시겠습니까?")
                cc1, cc2 = st.columns([1, 1])
                if cc1.button("✅ 예, 전체 삭제", key="mat_clear_yes", type="primary", use_container_width=True):
                    st.session_state[_SS] = []
                    ok = save_app_setting(_SS, [])
                    st.session_state["_mat_clear_confirm"] = False
                    if not ok:
                        st.toast("⚠️ DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다", icon="⚠️")
                    st.rerun()
                if cc2.button("취소", key="mat_clear_no", use_container_width=True):
                    st.session_state["_mat_clear_confirm"] = False; st.rerun()

            st.caption(f"현재 {len(current)}개 항목 등록됨")



        with dd_tab1:
            _render_dropdown_editor("dropdown_oqc_defect", "OQC 부적합 사유", "oqc")
        with dd_tab2:
            _render_dropdown_editor("dropdown_defect_cause", "불량 원인", "defect")
        with dd_tab3:
            _render_dropdown_editor("dropdown_repair_action", "수리 조치", "repair")
        with dd_tab4:
            _render_mat_name_editor()

        st.divider()

        st.markdown("<h4 style='color:#c8605a; font-weight:bold; margin:16px 0 10px 0;'>🗑️ 데이터 삭제 관리</h4>", unsafe_allow_html=True)
        st.caption("생산 이력, 감사 로그, 자재 시리얼, 생산 일정을 개별 또는 전체 삭제합니다.")

        del_tab1, del_tab2, del_tab3, del_tab4, del_tab5, del_tab6, del_tab7 = st.tabs([
            "📦 생산 이력", "🔍 감사 로그", "🔩 자재 시리얼",
            "📅 생산 일정", "📊 계획 변경 이력", "🗓️ 일정 변경 이력",
            "📈 월별 계획 수량"])

        # ─── 탭1: 생산 이력 ───────────────────────────────────────
        with del_tab1:
            prod_df = st.session_state.production_db.copy()
            st.caption(f"현재 **{len(prod_df)}건** 등록됨")

            # 필터
            dt1, dt2, dt3 = st.columns([1.5, 1.5, 2])
            _d_grp  = dt1.selectbox("반",    ["전체"] + PRODUCTION_GROUPS, key="d_prod_grp")
            _d_line = dt2.selectbox("라인",  ["전체","조립 라인","검사 라인","OQC 라인","포장 라인","불량 공정"], key="d_prod_line")
            _d_sn   = dt3.text_input("S/N 검색", key="d_prod_sn", placeholder="시리얼 일부 입력")
            if _d_grp  != "전체": prod_df = prod_df[prod_df['반']  == _d_grp]
            if _d_line != "전체": prod_df = prod_df[prod_df['라인'] == _d_line]
            if _d_sn.strip():    prod_df = prod_df[prod_df['시리얼'].str.contains(_d_sn.strip(), case=False, na=False)]

            if not prod_df.empty:
                # 개별 삭제
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                ph = st.columns([1.8, 1.5, 1.5, 1.8, 1.5, 1.0])
                for c, t in zip(ph, ["시간","반","라인","시리얼","상태","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for i, (idx, row) in enumerate(prod_df.sort_values('시간', ascending=False).head(200).iterrows()):
                    pr = st.columns([1.8, 1.5, 1.5, 1.8, 1.5, 1.0])
                    pr[0].caption(str(row.get('시간',''))[:16])
                    pr[1].caption(row.get('반',''))
                    pr[2].caption(row.get('라인',''))
                    pr[3].caption(f"`{row.get('시리얼','')}`")
                    pr[4].caption(row.get('상태',''))
                    if pr[5].button("🗑️", key=f"del_prod_{idx}", help="이 행 삭제"):
                        if delete_production_row_by_sn(row['시리얼']):
                            _clear_production_cache()
                            st.session_state.production_db = load_realtime_ledger()
                            st.success(f"삭제 완료: {row['시리얼']}")
                            st.rerun()
                if len(prod_df) > 200:
                    st.caption(f"※ 최대 200건만 표시. 필터로 범위를 좁혀주세요.")
            else:
                st.info("조건에 맞는 데이터가 없습니다.")

            # 전체 삭제
            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_prod_all = "del_prod_all_ck"
            if not st.session_state.get(_ck_prod_all):
                if st.button("⛔ 생산 이력 전체 삭제", key="del_prod_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_prod_all] = True; st.rerun()
            else:
                st.error("⛔ 생산 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _pa1, _pa2, _pa3 = st.columns([2,1,1])
                _pa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _pa2.button("✅ 예, 전체 삭제", key="del_prod_all_yes", type="primary", use_container_width=True):
                    if delete_all_rows():
                        _clear_production_cache()
                        st.session_state.production_db = load_realtime_ledger()
                        st.session_state[_ck_prod_all] = False
                        st.session_state["_delete_result"] = "success"
                        st.rerun()
                    else:
                        st.session_state["_delete_result"] = "fail"
                        st.rerun()
                if _pa3.button("취소", key="del_prod_all_no", use_container_width=True):
                    st.session_state[_ck_prod_all] = False; st.rerun()
                # rerun 후 메시지 표시
                _del_result = st.session_state.pop("_delete_result", None)
                if _del_result == "success":
                    st.success("✅ 생산 이력 전체 삭제 완료")
                elif _del_result == "fail":
                    st.error("❌ 삭제 실패")
                for _lvl, _msg in st.session_state.pop("_delete_msgs", []):
                    if _lvl == "warning": st.warning(_msg)
                    elif _lvl == "error": st.error(_msg)

        # ─── 탭2: 감사 로그 ───────────────────────────────────────
        with del_tab2:
            @st.cache_data(ttl=15)
            def _load_audit_all():
                try:
                    res = get_supabase().table("audit_log").select("*").order("시간", desc=True).limit(500).execute()
                    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                        columns=['id','시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])
                except: return pd.DataFrame(columns=['id','시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])

            audit_df = _load_audit_all()
            st.caption(f"현재 **{len(audit_df)}건** (최대 500건 표시)")
            if st.button("🔄 새로고침", key="audit_del_refresh"):
                st.cache_data.clear(); st.rerun()

            # 필터
            al1, al2 = st.columns([1.5, 2])
            _a_grp = al1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_audit_grp")
            _a_sn  = al2.text_input("S/N 검색", key="d_audit_sn", placeholder="시리얼 일부 입력")
            adf = audit_df.copy()
            if _a_grp != "전체": adf = adf[adf['반'] == _a_grp]
            if _a_sn.strip():   adf = adf[adf['시리얼'].str.contains(_a_sn.strip(), case=False, na=False)]

            if not adf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                ah = st.columns([1.8, 1.5, 1.8, 1.3, 1.5, 1.5, 1.0])
                for c, t in zip(ah, ["시간","반","시리얼","모델","이전상태","이후상태","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for idx, row in adf.iterrows():
                    ar = st.columns([1.8, 1.5, 1.8, 1.3, 1.5, 1.5, 1.0])
                    ar[0].caption(str(row.get('시간',''))[:16])
                    ar[1].caption(row.get('반',''))
                    ar[2].caption(f"`{row.get('시리얼','')}`")
                    ar[3].caption(row.get('모델',''))
                    ar[4].caption(row.get('이전상태',''))
                    ar[5].caption(row.get('이후상태',''))
                    _row_id = row.get('id')
                    if _row_id and ar[6].button("🗑️", key=f"del_audit_{_row_id}", help="이 행 삭제"):
                        if delete_audit_log_row(_row_id):
                            st.cache_data.clear()
                            st.success("삭제 완료"); st.rerun()
            else:
                st.info("조건에 맞는 감사 로그가 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_audit_all = "del_audit_all_ck"
            if not st.session_state.get(_ck_audit_all):
                if st.button("⛔ 감사 로그 전체 삭제", key="del_audit_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_audit_all] = True; st.rerun()
            else:
                st.error("⛔ 감사 로그 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _aa1, _aa2, _aa3 = st.columns([2,1,1])
                _aa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _aa2.button("✅ 예, 전체 삭제", key="del_audit_all_yes", type="primary", use_container_width=True):
                    if delete_all_audit_log():
                        _clear_audit_cache()
                        st.session_state[_ck_audit_all] = False
                        st.success("감사 로그 전체 삭제 완료"); st.rerun()
                if _aa3.button("취소", key="del_audit_all_no", use_container_width=True):
                    st.session_state[_ck_audit_all] = False; st.rerun()

        # ─── 탭3: 자재 시리얼 ────────────────────────────────────
        with del_tab3:
            @st.cache_data(ttl=15)
            def _load_mat_all():
                try:
                    res = get_supabase().table("material_serial").select("*").order("시간", desc=True).limit(500).execute()
                    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                        columns=['id','시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
                except: return pd.DataFrame(columns=['id','시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])

            mat_df = _load_mat_all()
            st.caption(f"현재 **{len(mat_df)}건** (최대 500건 표시)")
            if st.button("🔄 새로고침", key="mat_del_refresh"):
                st.cache_data.clear(); st.rerun()

            ml1, ml2 = st.columns([1.5, 2])
            _m_grp = ml1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_mat_grp")
            _m_sn  = ml2.text_input("S/N 검색", key="d_mat_sn", placeholder="메인 또는 자재 S/N")
            mdf = mat_df.copy()
            if _m_grp != "전체": mdf = mdf[mdf['반'] == _m_grp]
            if _m_sn.strip():
                mdf = mdf[
                    mdf['메인시리얼'].str.contains(_m_sn.strip(), case=False, na=False) |
                    mdf['자재시리얼'].str.contains(_m_sn.strip(), case=False, na=False)
                ]

            if not mdf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                mh = st.columns([1.8, 1.8, 1.5, 1.5, 1.8, 1.0])
                for c, t in zip(mh, ["시간","메인S/N","모델","자재명","자재S/N","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for idx, row in mdf.iterrows():
                    mr = st.columns([1.8, 1.8, 1.5, 1.5, 1.8, 1.0])
                    mr[0].caption(str(row.get('시간',''))[:16])
                    mr[1].caption(f"`{row.get('메인시리얼','')}`")
                    mr[2].caption(row.get('모델',''))
                    mr[3].caption(row.get('자재명',''))
                    mr[4].caption(f"`{row.get('자재시리얼','')}`")
                    _mid = row.get('id')
                    if _mid and mr[5].button("🗑️", key=f"del_mat_{_mid}", help="이 행 삭제"):
                        if delete_material_serial_row(_mid):
                            st.cache_data.clear()
                            st.success("삭제 완료"); st.rerun()
            else:
                st.info("조건에 맞는 자재 시리얼이 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_mat_all = "del_mat_all_ck"
            if not st.session_state.get(_ck_mat_all):
                if st.button("⛔ 자재 시리얼 전체 삭제", key="del_mat_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_mat_all] = True; st.rerun()
            else:
                st.error("⛔ 자재 시리얼 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _ma1, _ma2, _ma3 = st.columns([2,1,1])
                _ma1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _ma2.button("✅ 예, 전체 삭제", key="del_mat_all_yes", type="primary", use_container_width=True):
                    if delete_all_material_serial():
                        load_material_serials.clear()
                        st.session_state[_ck_mat_all] = False
                        st.success("자재 시리얼 전체 삭제 완료"); st.rerun()
                if _ma3.button("취소", key="del_mat_all_no", use_container_width=True):
                    st.session_state[_ck_mat_all] = False; st.rerun()

        # ─── 탭4: 생산 일정 ───────────────────────────────────────
        with del_tab4:
            sch_del_df = st.session_state.schedule_db.copy() if not st.session_state.schedule_db.empty else pd.DataFrame()
            st.caption(f"현재 **{len(sch_del_df)}건** 등록됨")

            sd1, sd2 = st.columns([1.5, 2])
            _s_grp = sd1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_sch_grp")
            _s_kw  = sd2.text_input("모델명/비고 검색", key="d_sch_kw", placeholder="검색어 입력")
            sdf = sch_del_df.copy()
            if _s_grp != "전체": sdf = sdf[sdf['반'] == _s_grp]
            if _s_kw.strip():
                sdf = sdf[
                    sdf.get('모델명', pd.Series(dtype=str)).str.contains(_s_kw.strip(), case=False, na=False) |
                    sdf.get('특이사항', pd.Series(dtype=str)).str.contains(_s_kw.strip(), case=False, na=False)
                ]

            if not sdf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                sh = st.columns([1.5, 1.2, 1.5, 2.0, 1.2, 1.2, 1.0])
                for c, t in zip(sh, ["날짜","반","카테고리","모델명","조립수","출하계획","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for idx, row in sdf.sort_values('날짜', ascending=False).iterrows():
                    sr = st.columns([1.5, 1.2, 1.5, 2.0, 1.2, 1.2, 1.0])
                    sr[0].caption(str(row.get('날짜',''))[:10])
                    sr[1].caption(row.get('반',''))
                    sr[2].caption(row.get('카테고리',''))
                    sr[3].caption(row.get('모델명',''))
                    sr[4].caption(str(row.get('조립수','')))
                    sr[5].caption(str(row.get('출하계획','')))
                    _sid = row.get('id')
                    if _sid and sr[6].button("🗑️", key=f"del_sch_{_sid}", help="이 행 삭제"):
                        if delete_schedule(int(_sid)):
                            _clear_schedule_cache()
                            st.session_state.schedule_db = load_schedule()
                            st.success("삭제 완료"); st.rerun()
            else:
                st.info("조건에 맞는 일정이 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_sch_all = "del_sch_all_ck"
            if not st.session_state.get(_ck_sch_all):
                if st.button("⛔ 생산 일정 전체 삭제", key="del_sch_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_sch_all] = True; st.rerun()
            else:
                st.error("⛔ 생산 일정 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _sa1, _sa2, _sa3 = st.columns([2,1,1])
                _sa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _sa2.button("✅ 예, 전체 삭제", key="del_sch_all_yes", type="primary", use_container_width=True):
                    if delete_all_production_schedule():
                        _clear_schedule_cache()
                        st.session_state.schedule_db = load_schedule()
                        st.session_state[_ck_sch_all] = False
                        st.success("생산 일정 전체 삭제 완료"); st.rerun()
                if _sa3.button("취소", key="del_sch_all_no", use_container_width=True):
                    st.session_state[_ck_sch_all] = False; st.rerun()

        # ─── 탭5: 계획 변경 이력 ─────────────────────────────────
        with del_tab5:
            @st.cache_data(ttl=15)
            def _load_plan_log_all():
                try:
                    res = get_supabase().table("plan_change_log").select("*").order("시간", desc=True).limit(500).execute()
                    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                        columns=['id','시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])
                except Exception:
                    return pd.DataFrame(columns=['id','시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])

            plog = _load_plan_log_all()
            st.caption(f"현재 **{len(plog)}건** (최대 500건 표시)")
            if st.button("🔄 새로고침", key="plog_del_refresh"):
                st.cache_data.clear(); st.rerun()

            pl1, pl2 = st.columns([1.5, 2])
            _pl_grp = pl1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_plog_grp")
            _pl_kw  = pl2.text_input("월 검색", key="d_plog_kw", placeholder="예: 2026-03")
            pldf = plog.copy()
            if _pl_grp != "전체": pldf = pldf[pldf['반'] == _pl_grp]
            if _pl_kw.strip():   pldf = pldf[pldf['월'].astype(str).str.contains(_pl_kw.strip(), na=False)]

            if not pldf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                plh = st.columns([1.8, 1.2, 1.3, 1.2, 1.2, 1.0, 1.8, 1.0])
                for c, t in zip(plh, ["시간","반","월","이전수량","변경수량","증감","변경사유","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for idx, row in pldf.iterrows():
                    plr = st.columns([1.8, 1.2, 1.3, 1.2, 1.2, 1.0, 1.8, 1.0])
                    plr[0].caption(str(row.get('시간',''))[:16])
                    plr[1].caption(row.get('반',''))
                    plr[2].caption(str(row.get('월','')))
                    plr[3].caption(str(row.get('이전수량','')))
                    plr[4].caption(str(row.get('변경수량','')))
                    _inc = row.get('증감', 0)
                    _inc_color = "#1f6640" if _inc >= 0 else "#c8605a"
                    plr[5].markdown(f"<span style='color:{_inc_color};font-weight:bold;font-size:0.8rem;'>{'+' if _inc>0 else ''}{_inc}</span>", unsafe_allow_html=True)
                    plr[6].caption(row.get('변경사유',''))
                    _plid = row.get('id')
                    if _plid and plr[7].button("🗑️", key=f"del_plog_{_plid}", help="이 행 삭제"):
                        if delete_plan_change_log_row(_plid):
                            st.cache_data.clear()
                            st.success("삭제 완료"); st.rerun()
            else:
                st.info("조건에 맞는 계획 변경 이력이 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_plog_all = "del_plog_all_ck"
            if not st.session_state.get(_ck_plog_all):
                if st.button("⛔ 계획 변경 이력 전체 삭제", key="del_plog_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_plog_all] = True; st.rerun()
            else:
                st.error("⛔ 계획 변경 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _pla1, _pla2, _pla3 = st.columns([2,1,1])
                _pla1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _pla2.button("✅ 예, 전체 삭제", key="del_plog_all_yes", type="primary", use_container_width=True):
                    if delete_all_plan_change_log():
                        _clear_plan_cache()
                        st.session_state[_ck_plog_all] = False
                        st.success("계획 변경 이력 전체 삭제 완료"); st.rerun()
                if _pla3.button("취소", key="del_plog_all_no", use_container_width=True):
                    st.session_state[_ck_plog_all] = False; st.rerun()

        # ─── 탭6: 일정 변경 이력 ─────────────────────────────────
        with del_tab6:
            @st.cache_data(ttl=15)
            def _load_sch_log_all():
                try:
                    res = get_supabase().table("schedule_change_log").select("*").order("시간", desc=True).limit(500).execute()
                    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                        columns=['id','시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])
                except Exception:
                    return pd.DataFrame(columns=['id','시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])

            slog = _load_sch_log_all()
            st.caption(f"현재 **{len(slog)}건** (최대 500건 표시)")
            if st.button("🔄 새로고침", key="slog_del_refresh"):
                st.cache_data.clear(); st.rerun()

            sl1, sl2 = st.columns([1.5, 2])
            _sl_grp = sl1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_slog_grp")
            _sl_kw  = sl2.text_input("모델명 검색", key="d_slog_kw", placeholder="모델명 일부 입력")
            sldf = slog.copy()
            if _sl_grp != "전체": sldf = sldf[sldf['반'] == _sl_grp]
            if _sl_kw.strip():   sldf = sldf[sldf['모델명'].astype(str).str.contains(_sl_kw.strip(), case=False, na=False)]

            if not sldf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                slh = st.columns([1.8, 1.2, 1.3, 1.8, 1.8, 1.5, 1.0])
                for c, t in zip(slh, ["시간","반","날짜","모델명","변경사유","작업자","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for idx, row in sldf.iterrows():
                    slr = st.columns([1.8, 1.2, 1.3, 1.8, 1.8, 1.5, 1.0])
                    slr[0].caption(str(row.get('시간',''))[:16])
                    slr[1].caption(row.get('반',''))
                    slr[2].caption(str(row.get('날짜',''))[:10])
                    slr[3].caption(row.get('모델명',''))
                    slr[4].caption(row.get('변경사유',''))
                    slr[5].caption(row.get('작업자',''))
                    _slid = row.get('id')
                    if _slid and slr[6].button("🗑️", key=f"del_slog_{_slid}", help="이 행 삭제"):
                        if delete_schedule_change_log_row(_slid):
                            st.cache_data.clear()
                            st.success("삭제 완료"); st.rerun()
            else:
                st.info("조건에 맞는 일정 변경 이력이 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_slog_all = "del_slog_all_ck"
            if not st.session_state.get(_ck_slog_all):
                if st.button("⛔ 일정 변경 이력 전체 삭제", key="del_slog_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_slog_all] = True; st.rerun()
            else:
                st.error("⛔ 일정 변경 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _sla1, _sla2, _sla3 = st.columns([2,1,1])
                _sla1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if _sla2.button("✅ 예, 전체 삭제", key="del_slog_all_yes", type="primary", use_container_width=True):
                    if delete_all_schedule_change_log():
                        st.cache_data.clear()
                        st.session_state[_ck_slog_all] = False
                        st.success("일정 변경 이력 전체 삭제 완료"); st.rerun()
                if _sla3.button("취소", key="del_slog_all_no", use_container_width=True):
                    st.session_state[_ck_slog_all] = False; st.rerun()

        # ─── 탭7: 월별 계획 수량 ──────────────────────────────────
        with del_tab7:
            @st.cache_data(ttl=15)
            def _load_plan_all():
                try:
                    res = get_supabase().table("production_plan").select("*").order("월", desc=True).execute()
                    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                        columns=['id','반','월','계획수량'])
                except Exception:
                    return pd.DataFrame(columns=['id','반','월','계획수량'])

            plan_df = _load_plan_all()
            st.caption(f"현재 **{len(plan_df)}건** 등록됨")
            if st.button("🔄 새로고침", key="plan_del_refresh"):
                st.cache_data.clear(); st.rerun()

            # 필터
            pp1, pp2 = st.columns([1.5, 2])
            _pp_grp = pp1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_plan_grp")
            _pp_kw  = pp2.text_input("월 검색", key="d_plan_kw", placeholder="예: 2026-03")
            ppdf = plan_df.copy()
            if _pp_grp != "전체": ppdf = ppdf[ppdf['반'] == _pp_grp]
            if _pp_kw.strip():   ppdf = ppdf[ppdf['월'].astype(str).str.contains(_pp_kw.strip(), na=False)]
            ppdf = ppdf.sort_values('월', ascending=False) if not ppdf.empty else ppdf

            if not ppdf.empty:
                st.markdown("<p style='font-weight:bold;margin:8px 0 4px 0;'>개별 삭제</p>", unsafe_allow_html=True)
                pph = st.columns([2, 2, 2, 1])
                for c, t in zip(pph, ["반", "월", "계획 수량", "삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>",
                               unsafe_allow_html=True)
                for idx, row in ppdf.iterrows():
                    ppr = st.columns([2, 2, 2, 1])
                    ppr[0].write(row.get('반', ''))
                    ppr[1].write(str(row.get('월', '')))
                    ppr[2].write(f"{int(row.get('계획수량', 0)):,} EA")
                    _p_ban = row.get('반', '')
                    _p_wol = row.get('월', '')
                    if ppr[3].button("🗑️", key=f"del_plan_{idx}", help="이 행 삭제"):
                        if delete_production_plan_row(_p_ban, _p_wol):
                            _clear_plan_cache()
                            st.session_state.production_plan = load_production_plan()
                            st.success(f"삭제 완료: {_p_ban} {_p_wol}")
                            st.rerun()
            else:
                st.info("조건에 맞는 계획 수량이 없습니다.")

            st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
            _ck_plan_all = "del_plan_all_ck"
            if not st.session_state.get(_ck_plan_all):
                if st.button("⛔ 월별 계획 수량 전체 삭제", key="del_plan_all_btn",
                             type="secondary", use_container_width=False):
                    st.session_state[_ck_plan_all] = True; st.rerun()
            else:
                st.error("⛔ 월별 계획 수량 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
                _ppa1, _ppa2, _ppa3 = st.columns([2, 1, 1])
                _ppa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>",
                               unsafe_allow_html=True)
                if _ppa2.button("✅ 예, 전체 삭제", key="del_plan_all_yes",
                                type="primary", use_container_width=True):
                    if delete_all_production_plan():
                        _clear_plan_cache()
                        st.session_state.production_plan = load_production_plan()
                        st.session_state[_ck_plan_all] = False
                        st.success("월별 계획 수량 전체 삭제 완료"); st.rerun()
                if _ppa3.button("취소", key="del_plan_all_no", use_container_width=True):
                    st.session_state[_ck_plan_all] = False; st.rerun()

        st.divider()

        # 기존 전체 초기화 버튼 (하위 호환)
        st.markdown("<p style='color:#8a7f72;font-size:0.85rem;'>⚠️ 아래는 생산 이력만 초기화하는 기존 버튼입니다. 위 탭을 이용하세요.</p>", unsafe_allow_html=True)
        # 초기화 버튼 - 2단계 확인
        if 'confirm_reset' not in st.session_state:
            st.session_state.confirm_reset = False

        if not st.session_state.confirm_reset:
            if st.button("⚠️ 전체 데이터 초기화", type="secondary", use_container_width=False):
                st.session_state.confirm_reset = True
                st.rerun()
        else:
            st.error("⛔ 정말로 전체 생산 데이터를 삭제하시겠습니까? **되돌릴 수 없습니다.**")
            cc1, cc2, cc3 = st.columns([2, 1, 1])
            cc1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가 — 신중히 결정하세요.</p>", unsafe_allow_html=True)
            if cc2.button("🗑️ 예, 삭제합니다", type="primary", use_container_width=True):
                if delete_all_rows():
                    st.session_state.production_db = load_realtime_ledger()
                    st.session_state.confirm_reset = False
                    st.success("전체 데이터가 초기화되었습니다.")
                    st.rerun()
            if cc3.button("취소", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()

# =================================================================
# [ PMS v22.3 종료 ]
# =================================================================

# ── 사용 설명서 ──────────────────────────────────────────────────
elif curr_l == "작업자 매뉴얼":
    # ══════════════════════════════════════════════════════════
    # 📖 작업자 매뉴얼
    # ══════════════════════════════════════════════════════════
    st.markdown("<h2 class='centered-title'>📖 작업자 매뉴얼</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#8a7f72;font-size:0.9rem;'>스마트 물류 대시보드 &nbsp;·&nbsp; 현장 작업자용</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    def _man_section(icon, title, color="#1B3A5C"):
        st.markdown(f"""
        <div style='background:{color};color:#fff;padding:8px 16px;border-radius:8px 8px 0 0;
                    font-weight:700;font-size:1.0rem;margin-top:16px;'>
            {icon} {title}
        </div>""", unsafe_allow_html=True)

    def _man_box(html_content, bg="#f8f6f2"):
        st.markdown(f"""
        <div style='background:{bg};border:1px solid #ddd5c0;border-radius:0 0 8px 8px;
                    padding:14px 18px;font-size:0.92rem;line-height:1.75;margin-bottom:4px;'>
            {html_content}
        </div>""", unsafe_allow_html=True)

    # ── 1. 시스템 소개 & 로그인 ──────────────────────────────
    with st.expander("🔑 1. 로그인 방법", expanded=True):
        _man_section("🔑", "로그인 절차")
        _man_box("""
        <ol style='margin:0;padding-left:1.4em;'>
          <li>브라우저(Chrome 권장)에서 시스템 URL 접속</li>
          <li><b>아이디(ID)</b>와 <b>비밀번호(PW)</b> 입력 후 <b>인증 시작</b> 클릭</li>
          <li>로그인 성공 → 내 권한에 맞는 화면으로 자동 이동</li>
          <li>실패 시 '로그인 정보가 올바르지 않습니다.' 메시지 → 관리자 문의</li>
        </ol>
        <p style='margin:8px 0 0;color:#7a5c00;background:#fff3d4;padding:6px 10px;border-radius:5px;'>
          ⚠ 비밀번호는 대소문자를 구분합니다. 초기 비밀번호는 관리자에게 문의하세요.
        </p>""")

    # ── 2. 생산 상태 흐름도 ──────────────────────────────────
    with st.expander("🔄 2. 생산 상태 흐름도"):
        _man_section("🔄", "제품이 거치는 상태 변화", "#2B7CB5")
        _man_box("""
        <div style='display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:4px 0;'>
          <span style='background:#2B7CB5;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>조립중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#0D9488;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>검사대기</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#0D9488;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>검사중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#16A34A;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>OQC대기</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#16A34A;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>OQC중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#F4892A;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>출하승인</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#7C3AED;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>포장중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#1B3A5C;color:#fff;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>✅ 완료</span>
        </div>
        <hr style='border:none;border-top:1px solid #e0d8c8;margin:10px 0;'>
        <p style='margin:0;'><b>🔴 불량 발생 시:</b>
          <span style='background:#DC2626;color:#fff;padding:3px 8px;border-radius:4px;font-size:0.82rem;'>불량 처리 중</span>
          → 불량 공정에서 원인 분석 →
          <span style='background:#F4892A;color:#fff;padding:3px 8px;border-radius:4px;font-size:0.82rem;'>수리 완료(재투입)</span>
          → 검사대기 복귀
        </p>""")

    # ── 3. 조립 라인 ────────────────────────────────────────
    with st.expander("🔧 3. 조립 라인 사용법"):
        _man_section("🔧", "조립 라인", "#16A34A")
        _man_box("""
        <b>① 오늘 일정 확인</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>화면 상단에 당일 생산 일정이 자동 표시됩니다.</li>
          <li>새 일정 등록 시 알림 팝업 → <b>확인</b> 버튼으로 닫기</li>
        </ul>
        <b>② 신규 제품 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모델명·품목코드·시리얼 번호 입력</li>
          <li>바코드 스캐너 연동 가능 — 스캔 후 자동 입력됩니다.</li>
          <li>자재 시리얼(부품 S/N)은 별도 항목에 추가 등록 가능</li>
        </ul>
        <b>③ 조립 완료 처리</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>이력 목록에서 완료된 항목 체크박스 선택</li>
          <li><b>조립 완료</b> 버튼 클릭 → 상태가 <b>검사대기</b>로 자동 전환</li>
          <li>불량 발생 시 <b>불량 처리</b> 버튼 클릭</li>
        </ul>
        <p style='margin:6px 0 0;background:#e8f5e9;padding:6px 10px;border-radius:5px;color:#1B5E20;'>
          💡 사이드바에서 반(제조1반·2반·3반)을 선택하면 해당 반의 일정과 이력만 표시됩니다.
        </p>""")

    # ── 4. 검사 라인 ────────────────────────────────────────
    with st.expander("🔍 4. 검사 라인 사용법"):
        _man_section("🔍", "검사 라인", "#0D9488")
        _man_box("""
        <b>① 입고 대기 처리 (검사대기 → 검사중)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>조립 완료된 제품 목록이 <b>검사대기</b> 섹션에 표시됩니다.</li>
          <li>시리얼 번호 스캔/검색으로 빠른 조회</li>
          <li>체크박스 선택 후 <b>일괄 입고</b> 버튼 → <b>검사중</b>으로 전환</li>
        </ul>
        <b>② 검사 판정</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b>✅ 합격</b> 버튼 → 상태가 <b>OQC대기</b>로 자동 전환</li>
          <li><b>🚫 불합격</b> 버튼 → 증상 메모 입력 후 확인 → <b>불량 처리 중</b>으로 전환</li>
        </ul>""")

    # ── 5. 포장 라인 ────────────────────────────────────────
    with st.expander("📦 5. 포장 라인 사용법"):
        _man_section("📦", "포장 라인", "#7C3AED")
        _man_box("""
        <b>① 입고 대기 처리 (출하승인 → 포장중)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>OQC 합격(출하승인) 제품이 목록에 표시됩니다.</li>
          <li>체크박스 선택 후 <b>일괄 입고</b> 버튼 → <b>포장중</b>으로 전환</li>
        </ul>
        <b>② 포장 완료 처리</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>포장중 목록에서 <b>포장 완료</b> 버튼 클릭 → <b>완료</b> 상태로 최종 처리</li>
          <li>완료된 수량은 KPI 대시보드에 자동 반영됩니다.</li>
        </ul>""")

    # ── 6. OQC 라인 ─────────────────────────────────────────
    with st.expander("🏅 6. OQC 라인 사용법"):
        _man_section("🏅", "OQC 라인 (최종 출하 품질 검사)", "#16A34A")
        _man_box("""
        <b>① OQC 시작</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>검사 완료(OQC대기) 제품 목록에서 <b>OQC 시작</b> 버튼 클릭 → <b>OQC중</b> 전환</li>
        </ul>
        <b>② 최종 판정</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b>✅ 합격</b> → <b>출하승인</b> (포장 라인으로 이동)</li>
          <li><b>🚫 부적합</b> → 부적합 사유 입력 후 <b>불량 처리 중</b>으로 전환</li>
        </ul>""")

    # ── 7. 불량 공정 ─────────────────────────────────────────
    with st.expander("🛠 7. 불량 공정 처리"):
        _man_section("🛠", "불량 공정", "#DC2626")
        _man_box("""
        <ol style='margin:0;padding-left:1.4em;'>
          <li>불량 처리 중 목록에서 해당 제품 확인</li>
          <li><b>불량 원인</b> 드롭다운에서 원인 선택 (또는 직접 입력)</li>
          <li><b>조치 방법</b> 선택 (재작업·폐기·반품 등)</li>
          <li><b>조치 완료</b> 버튼 클릭 → <b>수리 완료(재투입)</b> 상태로 전환</li>
          <li>재투입된 제품은 <b>검사대기</b> 상태로 복귀하여 재검사 진행</li>
        </ol>""")

    # ── 8. FAQ ───────────────────────────────────────────────
    with st.expander("❓ 8. 자주 묻는 질문 (FAQ)"):
        _man_section("❓", "FAQ", "#64748B")
        _man_box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.91rem;'>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;width:42%;border-bottom:1px solid #ddd;'>Q. 로그인이 안 됩니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 아이디/비밀번호 재확인 후 관리자에게 계정 재설정 요청하세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 데이터가 표시되지 않습니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 사이드바의 Supabase 경고 확인 후 페이지를 새로 고침하세요.</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 버튼을 눌렀는데 반응이 없습니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 처리 후 자동 새로고침됩니다. 잠시 기다려 주세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 불량 처리 후 제품이 안 보입니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 불량 공정 화면에서 해당 시리얼을 검색하세요.</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;'>Q. 내 반이 아닌 데이터가 보입니다.</td>
            <td style='padding:8px 12px;'>A. 사이드바에서 본인 반(제조1반·2반·3반)을 선택하세요.</td>
          </tr>
        </table>""")

elif curr_l == "관리자 매뉴얼":
    # ══════════════════════════════════════════════════════════
    # 🔐 관리자 매뉴얼
    # ══════════════════════════════════════════════════════════
    st.markdown("<h2 class='centered-title'>🔐 관리자 매뉴얼</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#8a7f72;font-size:0.9rem;'>스마트 물류 대시보드 &nbsp;·&nbsp; 관리자·마스터 전용</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    def _adm_section(icon, title, color="#1B3A5C"):
        st.markdown(f"""
        <div style='background:{color};color:#fff;padding:8px 16px;border-radius:8px 8px 0 0;
                    font-weight:700;font-size:1.0rem;margin-top:16px;'>
            {icon} {title}
        </div>""", unsafe_allow_html=True)

    def _adm_box(html_content, bg="#f8f6f2"):
        st.markdown(f"""
        <div style='background:{bg};border:1px solid #ddd5c0;border-radius:0 0 8px 8px;
                    padding:14px 18px;font-size:0.92rem;line-height:1.75;margin-bottom:4px;'>
            {html_content}
        </div>""", unsafe_allow_html=True)

    # ── 1. 사용자 권한 안내 ──────────────────────────────────
    with st.expander("👥 1. 사용자 권한(Role) 안내", expanded=True):
        _adm_section("👥", "역할별 접근 메뉴")
        _adm_box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.89rem;'>
          <tr style='background:#1B3A5C;color:#fff;'>
            <th style='padding:7px 10px;text-align:left;'>역할</th>
            <th style='padding:7px 10px;text-align:left;'>Role ID</th>
            <th style='padding:7px 10px;text-align:left;'>접근 가능 화면</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>👤 마스터 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>master</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>전체 메뉴</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>🛡 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>admin</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>전체 메뉴</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>🗼 컨트롤 타워</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>control_tower</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>KPI·리포트·마스터관리·매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>🔧 조립 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>assembly_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>조립 라인·작업자 매뉴얼</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>🔍 검사 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>qc_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>검사 라인·불량공정·작업자 매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>📦 포장 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>packing_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>포장 라인·작업자 매뉴얼</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>📅 일정 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>schedule_manager</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 지표 관리·작업자 매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;'>🏅 OQC 품질팀</td>
            <td style='padding:6px 10px;font-family:monospace;'>oqc_team</td>
            <td style='padding:6px 10px;'>OQC 라인·작업자 매뉴얼</td>
          </tr>
        </table>
        <p style='margin:10px 0 0;color:#1B5E20;background:#e8f5e9;padding:6px 10px;border-radius:5px;'>
          💡 계정 등록·수정·삭제는 Supabase Table Editor → <code>users</code> 테이블에서 직접 관리합니다.
        </p>""")

    # ── 2. 마스터 데이터 관리 ────────────────────────────────
    with st.expander("⚙ 2. 마스터 데이터 관리"):
        _adm_section("⚙", "모델·품목코드 기준 정보 등록", "#2B7CB5")
        _adm_box("""
        <p style='margin:0 0 8px;background:#fef2f2;padding:6px 10px;border-radius:5px;color:#7F1D1D;font-weight:700;'>
          🔐 마스터 비밀번호 인증 필요 — 관리자·마스터 권한만 접근 가능
        </p>
        <b>모델 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>반별(제조1·2·3반) 탭 선택 후 모델명 입력 (줄바꿈으로 여러 개 한 번에 등록)</li>
          <li>등록된 모델은 조립 라인 등록 화면의 드롭다운에 즉시 반영</li>
        </ul>
        <b>품목코드(P/N) 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모델 선택 후 품목코드 입력 (줄바꿈으로 일괄 등록 가능)</li>
          <li>모델-품목 연결 관계가 설정되어 조립 화면에서 선택 가능</li>
        </ul>
        <b>삭제</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>개별 삭제: 목록에서 삭제 버튼 클릭 (확인 팝업)</li>
          <li>전체 삭제: 해당 반의 모든 모델/품목 일괄 삭제</li>
          <li>⚠ 삭제는 되돌릴 수 없으므로 신중하게 진행</li>
        </ul>""")

    # ── 3. 생산 일정 관리 ────────────────────────────────────
    with st.expander("📅 3. 생산 일정 관리"):
        _adm_section("📅", "생산 계획 등록 및 편집", "#D97706")
        _adm_box("""
        <b>일정 등록 방법</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>메인 현황판 하단 달력에서 <b>날짜 클릭</b> → 일정 입력 팝업</li>
          <li>입력 항목: 날짜·유형·모델명·P/N·조립수량·출하계획·특이사항</li>
          <li>유형별 색상: 🔵 조립계획 / 🟢 포장계획 / 🟡 출하계획</li>
        </ul>
        <b>엑셀 일괄 업로드</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>생산 지표 관리 → <b>일정 관리</b> 탭 → 엑셀 업로드</li>
          <li>지원 형식: .xlsx (헤더: 날짜·유형·모델·P/N·조립수·출하·특이사항)</li>
        </ul>
        <b>편집·삭제 권한</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>마스터·관리자·컨트롤 타워·일정 관리자만 추가/수정/삭제 가능</li>
        </ul>""")

    # ── 4. 생산 지표(KPI) 관리 ───────────────────────────────
    with st.expander("📊 4. 생산 지표(KPI) 분석"):
        _adm_section("📊", "KPI 대시보드 활용", "#1B3A5C")
        _adm_box("""
        <b>필터 옵션</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>기간: 오늘 / 이번 주 / 이번 달</li>
          <li>반: 전체 / 제조1반 / 제조2반 / 제조3반</li>
        </ul>
        <b>주요 확인 지표</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>투입·완료·진행·불량</b> 수량 카드</li>
          <li><b>공정 흐름 표</b>: 각 단계별 적체 수량 → 병목 지점 파악</li>
          <li><b>불량 분석 차트</b>: 라인별·모델별 불량 분포</li>
          <li><b>FPY(First Pass Yield)</b>: 전체 품질 수준 지표</li>
          <li><b>월별 달성률 추이</b>: 계획 대비 실적 그래프</li>
        </ul>
        <p style='margin:0;background:#e0f2fe;padding:6px 10px;border-radius:5px;color:#0C4A6E;'>
          💡 공정 흐름 표에서 특정 단계 수량이 급증하면 해당 공정에 병목이 발생한 것입니다.
        </p>""")

    # ── 5. 수리 현황 리포트 ──────────────────────────────────
    with st.expander("📋 5. 수리 현황 리포트 & 감사 로그"):
        _adm_section("📋", "품질 추적 및 이력 관리", "#DC2626")
        _adm_box("""
        <b>수리 현황 리포트</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>라인별 불량 건수 막대 차트</li>
          <li>모델별 불량 분포 파이 차트</li>
          <li>전체 수리 이력 테이블 (시리얼·모델·원인·조치)</li>
        </ul>
        <b>감사 로그 (Audit Log)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모든 상태 변화 이력 기록 (누가·언제·어떤 제품을·어떤 상태로 변경)</li>
          <li>필터: 반 / 이후 상태 / 시리얼 번호 검색</li>
          <li>컬럼: 시간·시리얼·모델·반·이전상태·이후상태·작업자·비고</li>
        </ul>
        <p style='margin:0;background:#fef2f2;padding:6px 10px;border-radius:5px;color:#7F1D1D;'>
          ⚠ 감사 로그는 완전한 추적 이력(Traceability)을 제공합니다. 품질 이슈 발생 시 반드시 확인하세요.
        </p>""")

    # ── 6. 시스템 설정 안내 ──────────────────────────────────
    with st.expander("🛠 6. 시스템 설정 안내 (Streamlit Secrets)"):
        _adm_section("🛠", "운영 환경 설정", "#64748B")
        _adm_box("""
        <b>Streamlit Cloud Secrets 주요 항목</b>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:6px;'>
          <tr style='background:#1B3A5C;color:#fff;'>
            <th style='padding:6px 10px;text-align:left;'>키</th>
            <th style='padding:6px 10px;text-align:left;'>설명</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>master_admin_pw_hash</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>마스터 데이터 관리 비밀번호 SHA-256 해시 (최상위 키)</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>[supabase] url / key</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>Supabase 프로젝트 URL 및 anon 키</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>[connections.gsheets]</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>Google Sheets 서비스 계정 인증 정보</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;font-family:monospace;'>[fallback_users]</td>
            <td style='padding:6px 10px;'>Supabase 연결 실패 시 임시 계정 해시 (선택)</td>
          </tr>
        </table>
        <p style='margin:10px 0 0;background:#fff3d4;padding:6px 10px;border-radius:5px;color:#7a5c00;'>
          ⚠ <code>master_admin_pw_hash</code>는 반드시 <b>최상위 키</b>(어떤 [섹션] 밖)에 위치해야 합니다.
        </p>""")

    # ── 7. Supabase 테이블 구조 ──────────────────────────────
    with st.expander("🗄 7. Supabase 테이블 구조"):
        _adm_section("🗄", "DB 테이블 목록 및 주요 컬럼", "#2B7CB5")
        _adm_box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#1B3A5C;color:#fff;'>
            <th style='padding:6px 10px;text-align:left;'>테이블</th>
            <th style='padding:6px 10px;text-align:left;'>주요 컬럼</th>
            <th style='padding:6px 10px;text-align:left;'>용도</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>production</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시간·반·라인·모델·품목코드·시리얼·상태·deleted_at</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 이력 메인 테이블</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>users</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>username·password_hash·role</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>사용자 계정 관리</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>model_master</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>반·모델명·품목코드</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>모델/품목 기준 정보</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>production_schedule</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>날짜·유형·모델·수량·출하계획</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 일정</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>audit_log</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시간·시리얼·이전상태·이후상태·작업자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>상태 변화 이력</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;font-family:monospace;'>system_config</td>
            <td style='padding:6px 10px;'>key·master_hash</td>
            <td style='padding:6px 10px;'>마스터 비밀번호 등 시스템 설정</td>
          </tr>
        </table>""")

    st.markdown("<br>", unsafe_allow_html=True)
    st.info("📌 Supabase 테이블 편집은 [supabase.com](https://supabase.com) → 프로젝트 → Table Editor에서 진행합니다.")



# =================================================================
# 코드 품질 체크리스트 (Pull Request 전 확인)
# =================================================================
# 
# 새 코드 작성 시 확인사항:
# □ 함수가 100라인 이하인가?
# □ 타입 힌팅을 추가했는가?
# □ Docstring을 작성했는가?
# □ 에러 처리가 구체적인가? (Exception 대신 ValueError 등)
# □ SQL 쿼리에 사용자 입력이 직접 들어가지 않는가?
# □ iterrows() 대신 벡터화 연산을 사용했는가?
# □ st.rerun() 사용이 꼭 필요한가?
# □ 매직 넘버를 상수로 정의했는가?
# □ 단위 테스트를 작성했는가?
# □ 주석이 코드의 '왜'를 설명하는가? (무엇이 아닌)
#
# 코드 리뷰 시 확인사항:
# □ 비즈니스 로직이 명확한가?
# □ 엣지 케이스를 고려했는가?
# □ 성능 병목이 없는가?
# □ 보안 이슈가 없는가?
# □ 일관된 네이밍 규칙을 따르는가?
#
# =================================================================



# =================================================================
# 빠른 참조 가이드
# =================================================================
#
# 🔧 주요 상수:
#   AUTO_REFRESH_INTERVAL_MS = 30000  # 자동 새로고침 간격
#   PDF_VIEWER_HEIGHT_PX = 900         # PDF 뷰어 높이
#   MAX_FUNCTION_LINES = 200           # 함수 최대 권장 라인
#
# 🎨 색상 상수:
#   COLOR_SUCCESS = "#28a745"
#   COLOR_ERROR = "#dc3545"
#   COLOR_WARNING = "#ffc107"
#   COLOR_INFO = "#17a2b8"
#
# 📊 데이터베이스:
#   DEFAULT_PAGE_SIZE = 100
#   MAX_QUERY_RESULTS = 1000
#
# 🔐 보안:
#   - SQL 쿼리 시 re.sub()로 입력 검증
#   - 비밀번호는 hash_pw()로 해싱
#   - 역할 확인: CALENDAR_EDIT_ROLES
#
# ⚡ 성능:
#   - iterrows() → 벡터화 연산 사용
#   - st.cache_data / st.cache_resource 활용
#   - st.rerun() 최소화
#
# 🧪 테스트:
#   pytest tests/ --cov=. --cov-report=html
#
# =================================================================
