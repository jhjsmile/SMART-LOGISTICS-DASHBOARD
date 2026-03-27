import io
import json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import pandas as pd

from modules.database import (
    get_supabase, keep_supabase_alive,
    _clear_production_cache, _clear_schedule_cache, _clear_plan_cache,
    _clear_audit_cache,
    _clear_access_request_cache,
    load_realtime_ledger, load_schedule,
    update_row, delete_all_rows, delete_production_row_by_sn,
    load_app_setting, save_app_setting,
    load_access_requests, review_access_request,
    insert_audit_log,
    delete_all_audit_log, delete_audit_log_row,
    load_material_serials,
    delete_all_material_serial, delete_material_serial_row,
    delete_schedule, delete_all_production_schedule,
    delete_all_schedule_change_log, delete_schedule_change_log_row,
    upsert_model_master,
    delete_model_from_master, delete_item_from_master,
    delete_all_master_by_group, sync_master_to_session,
    load_production_plan,
    delete_production_plan_row, delete_all_production_plan,
    delete_all_plan_change_log, delete_plan_change_log_row,
)
from modules.auth import (
    hash_pw, verify_pw, get_master_pw_hash,
    _parse_custom_perms,
)
from modules.utils import get_now_kst_str

# ─── 페이지 설정 ────────────────────────────────────────────────────
st.set_page_config(
    page_title="마스터 관리 - PMS v1.0.0",
    layout="wide",
    initial_sidebar_state="collapsed",
)

KST = timezone(timedelta(hours=9))

st.markdown("""
    <style>
    /* ════════════════════════════════════════
       산업/공장 테마 (v2.0.0)
       배경: 콘크리트 회색
       강조: 산업용 오렌지 · 스틸 사이드바
    ════════════════════════════════════════ */

    /* 전체 앱 배경 */
    .stApp {
        background-color: #e9ebed !important;
        overflow-x: hidden;
    }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background-color: #cfd8dc !important;
        border-right: 2px solid #90a4ae !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span:not(.stButton span),
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stCaption {
        color: #1a242c !important;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1a242c !important;
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
        background-color: #e9ebed;
    }

    /* 입력 필드 */
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        background-color: #ffffff !important;
        border: 1px solid #78909c !important;
        border-radius: 4px !important;
        color: #1a242c !important;
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
        border-color: #f4922a !important;
        box-shadow: 0 0 0 2px rgba(230,92,0,0.20) !important;
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
        box-shadow: 0 4px 20px rgba(0,0,0,0.25) !important;
        border: 1px solid #78909c !important;
        border-radius: 4px !important;
    }
    [data-baseweb="menu"] li,
    [data-baseweb="option"] {
        color: #1a242c !important;
        font-weight: 500 !important;
        opacity: 1 !important;
        background: #ffffff !important;
    }
    [data-baseweb="menu"] li:hover,
    [data-baseweb="option"]:hover {
        background: #eceff1 !important;
        color: #1a242c !important;
    }
    [aria-selected="true"][data-baseweb="option"] {
        background: #fff3e0 !important;
        color: #1a242c !important;
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
        border-radius: 4px !important; font-weight: 700 !important;
        white-space: nowrap !important; overflow: hidden !important;
        text-overflow: ellipsis !important; transition: all 0.15s ease !important;
        letter-spacing: 0.03em !important;
    }
    /* Secondary (기본) → 밝은 회색 */
    .stButton > button:not([kind="primary"]),
    div[data-testid="stFormSubmitButton"] > button:not([kind="primary"]) {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
    }
    .stButton > button:not([kind="primary"]):hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }
    /* Primary → 산업 오렌지 */
    .stButton > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
        background-color: #f4922a !important;
        border: 1px solid #e07a18 !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #e07a18 !important;
    }
    /* ── Streamlit 버튼 선택자 (구버전 baseButton-* + 신버전 stBaseButton-* 동시 지원) ── */
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-secondaryFormSubmit"],
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-secondaryFormSubmit"] {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
    }
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="baseButton-secondaryFormSubmit"]:hover,
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-primaryFormSubmit"],
    button[data-testid="stBaseButton-primary"],
    button[data-testid="stBaseButton-primaryFormSubmit"] {
        background-color: #f4922a !important;
        border: 1px solid #e07a18 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
    }
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="baseButton-primaryFormSubmit"]:hover,
    button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background-color: #e07a18 !important;
        color: #ffffff !important;
    }
    /* disabled 버튼 — 흐리게 표시, 텍스트 색은 유지 */
    button:disabled, button[disabled] {
        opacity: 0.45 !important;
        cursor: not-allowed !important;
    }
    /* 모든 버튼 텍스트 색 강제 (최후 방어) */
    .stButton button p,
    .stButton button span,
    .stButton button div {
        color: inherit !important;
    }
    /* 다운로드 버튼 */
    [data-testid="stDownloadButton"] > button {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
        width: 100% !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }

    /* 컨테이너 border */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #f5f6f7 !important;
        border: 1px solid #90a4ae !important;
        border-radius: 4px !important;
    }

    /* 탭 */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #cfd8dc;
        border-radius: 4px;
        padding: 2px;
    }
    .stTabs [data-baseweb="tab"] { color: #546e7a !important; font-weight: 600 !important; }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important;
        color: #1a242c !important;
        border-bottom: 3px solid #f4922a !important;
        border-radius: 4px 4px 0 0;
    }

    /* 타이틀 / 섹션 헤더 */
    .centered-title {
        text-align: center; font-weight: bold;
        margin: 20px 0; color: #1a242c !important;
        letter-spacing: 0.05em;
    }
    .section-title {
        background-color: #cfd8dc; color: #1a242c;
        padding: 14px 20px; border-radius: 4px;
        font-weight: 800; margin: 8px 0 20px 0;
        border-left: 6px solid #f4922a;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        box-shadow: 0 2px 4px rgba(0,0,0,0.12);
    }

    /* 본문 텍스트 기본 색상 */
    .stApp p, .stApp label, .stApp .stMarkdown p {
        color: #1a242c;
    }
    /* subheader / h3 / h2 / write 텍스트 */
    .stApp h1, .stApp h2, .stApp h3,
    .stApp h4, .stApp h5, .stApp h6 {
        color: #1a242c !important;
    }
    /* st.write, st.caption 등 일반 텍스트 */
    .stApp .stMarkdown,
    .stApp .stMarkdown p,
    .stApp .stMarkdown span,
    .stApp .stMarkdown strong,
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] span {
        color: #1a242c !important;
    }
    /* metric, caption */
    .stApp [data-testid="stMetricLabel"],
    .stApp [data-testid="stMetricValue"],
    .stApp [data-testid="stCaptionContainer"] {
        color: #546e7a !important;
    }

    /* 통계 박스 */
    .stat-box {
        display: flex; flex-direction: column;
        justify-content: center; align-items: center;
        background-color: #f5f6f7; border-radius: 4px;
        padding: 16px 8px; border: 1px solid #90a4ae;
        margin-bottom: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.10);
        width: 100%; box-sizing: border-box; overflow: hidden;
    }
    .stat-label {
        font-size: clamp(0.65rem, 1vw, 0.88rem); color: #546e7a;
        font-weight: 700; margin-bottom: 8px; white-space: nowrap;
        text-transform: uppercase; letter-spacing: 0.06em;
    }
    .stat-value {
        font-size: clamp(1.4rem, 2vw, 2.4rem); color: #f4922a;
        font-weight: 800; line-height: 1; white-space: nowrap;
    }

    .button-spacer { margin-top: 28px; }

    /* 캘린더 셀 */
    .cal-day-wrap {
        cursor: pointer;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .cal-day-wrap:hover {
        box-shadow: 0 4px 12px rgba(230,92,0,0.25);
        border-color: #f4922a !important;
    }
    .cal-cell {
        background: #f5f6f7;
        border: 1px solid #90a4ae;
        border-radius: 4px;
        padding: 8px 6px;
        min-height: 120px;
        box-sizing: border-box;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        cursor: pointer;
    }
    .cal-cell:hover {
        transform: scale(1.04);
        box-shadow: 0 6px 18px rgba(230,92,0,0.20);
        border-color: #f4922a !important;
        z-index: 999; position: relative;
    }
    .cal-cell.today {
        background: #fff3e0;
        border: 2px solid #f4922a !important;
    }
    .cal-day-num {
        font-weight: bold; color: #1a242c;
        margin-bottom: 4px; font-size: 0.92rem;
    }
    .cal-event {
        border-radius: 3px; padding: 2px 5px;
        margin-bottom: 3px; font-size: 0.63rem; line-height: 1.3;
    }

    /* ── 캘린더 날짜 버튼 ── */
    .cal-day-btn > div > button,
    .cal-day-btn button {
        background-color: transparent !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #1a242c !important;
        font-weight: bold !important;
        font-size: 1.0rem !important;
        min-height: 28px !important;
        height: 28px !important;
        padding: 0 4px !important;
        margin: 0 !important;
        width: 100% !important;
        cursor: pointer !important;
        border-radius: 3px !important;
        transition: background 0.15s !important;
    }
    .cal-day-btn > div > button:hover,
    .cal-day-btn button:hover {
        background-color: #fff3e0 !important;
        color: #f4922a !important;
    }
    .cal-today-btn > div > button,
    .cal-today-btn button {
        color: #f4922a !important;
        font-weight: 900 !important;
    }

    /* ── Expander ── */
    .stExpander {
        border: 1px solid #90a4ae !important;
        border-radius: 4px !important;
        background-color: #f5f6f7 !important;
        margin-bottom: 8px !important;
    }
    .stExpander summary,
    .stExpander [data-testid="stExpanderToggleIcon"],
    .stExpander details summary {
        background-color: #cfd8dc !important;
        border-radius: 4px !important;
        color: #1a242c !important;
        padding: 10px 16px !important;
    }
    .stExpander summary:hover {
        background-color: #b0bec5 !important;
    }
    .stExpander summary p,
    .stExpander summary span,
    .stExpander details summary p {
        color: #1a242c !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }
    /* expander 내부 배경 */
    .stExpander details {
        background-color: #f5f6f7 !important;
        border-radius: 0 0 4px 4px !important;
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

# ─── 상수 ─────────────────────────────────────────────────────────
PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]
PERM_ACTIONS       = ["read", "write", "edit"]
ROLES = {
    "master":           ["생산 지표 관리", "조립 라인", "검사 라인", "포장 라인", "OQC 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼", "플로우차트"],
    "admin":            ["생산 지표 관리", "조립 라인", "검사 라인", "포장 라인", "OQC 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼", "플로우차트"],
    "control_tower":    ["생산 지표 관리", "생산 현황 리포트", "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼", "플로우차트"],
    "assembly_team":    ["조립 라인", "작업자 매뉴얼", "플로우차트"],
    "qc_team":          ["검사 라인", "불량 공정", "작업자 매뉴얼", "플로우차트"],
    "packing_team":     ["포장 라인", "작업자 매뉴얼", "플로우차트"],
    "schedule_manager": ["생산 지표 관리", "작업자 매뉴얼", "플로우차트"],
    "oqc_team":         ["OQC 라인", "작업자 매뉴얼", "플로우차트"],
}
_DD_DEFAULTS = {
    "dropdown_oqc_defect": [
        "(선택)", "외관 불량 (스크래치/변형)", "기능 불량 (동작 이상)", "라벨 / 刻印 오류",
        "포장 불량", "치수 불량", "이물질 혼입", "수량 부족", "서류 오류", "기타 (직접 입력)",
    ],
    "dropdown_defect_cause": [
        "(선택)", "납땜 불량", "부품 미삽", "부품 오삽", "부품 불량", "기구 파손", "기구 간섭",
        "나사 체결 불량", "소프트웨어 오류", "펌웨어 오류", "설정 오류",
        "외관 불량 (스크래치)", "외관 불량 (변형)", "통신 불량", "전원 불량", "센서 불량", "기타 (직접 입력)",
    ],
    "dropdown_repair_action": [
        "(선택)", "재납땜", "부품 교체", "부품 재삽입", "기구 교체", "나사 재체결",
        "펌웨어 재설치", "소프트웨어 초기화", "설정 재조정", "외관 교체", "세척 후 재검사",
        "재검사 후 양품 확인", "폐기 처리", "기타 (직접 입력)",
    ],
    "dropdown_mat_name": [],
}


# ─── Supabase 연결 유지 ─────────────────────────────────────────────
if "supabase_alive_checked" not in st.session_state:
    keep_supabase_alive()
    st.session_state["supabase_alive_checked"] = True

# ─── 세션 상태 초기화 ───────────────────────────────────────────────
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "user_db" not in st.session_state:
    try:
        _res = get_supabase().table("users").select("username,password_hash,role,custom_permissions").execute()
        st.session_state.user_db = {
            row["username"]: {
                "pw_hash": row.get("password_hash", ""),
                "role": row.get("role", "assembly_team"),
                **({"custom_permissions": json.loads(row["custom_permissions"])} if row.get("custom_permissions") else {})
            }
            for row in (_res.data or [])
        }
    except Exception:
        st.session_state.user_db = {}

if "group_master_models" not in st.session_state:
    st.session_state.group_master_models = {"제조1반": [], "제조2반": [], "제조3반": []}
if "group_master_items" not in st.session_state:
    st.session_state.group_master_items = {"제조1반": {}, "제조2반": {}, "제조3반": {}}
if "master_synced" not in st.session_state:
    sync_master_to_session()
    st.session_state.master_synced = True

if "production_db" not in st.session_state:
    st.session_state.production_db = load_realtime_ledger()
if "schedule_db" not in st.session_state:
    st.session_state.schedule_db = load_schedule()
if "production_plan" not in st.session_state:
    st.session_state.production_plan = load_production_plan()

for _dd_key, _dd_default in _DD_DEFAULTS.items():
    if _dd_key not in st.session_state:
        _loaded = load_app_setting(_dd_key)
        st.session_state[_dd_key] = _loaded if _loaded is not None else _dd_default

# ─── 옵티미스틱 업데이트 헬퍼 ────────────────────────────────────────
def _prod_update(sn: str, data: dict) -> None:
    _db = st.session_state.get("production_db", pd.DataFrame())
    if _db.empty or "시리얼" not in _db.columns:
        _clear_production_cache()
        st.session_state.production_db = load_realtime_ledger()
        return
    _mask = _db["시리얼"] == sn
    if not _mask.any():
        _clear_production_cache()
        st.session_state.production_db = load_realtime_ledger()
        return
    for col, val in data.items():
        if col in _db.columns:
            st.session_state.production_db.loc[_mask, col] = val

# ─── 사이드바 ───────────────────────────────────────────────────────
with st.sidebar:
    _main_url = st.secrets.get("main_app_url", "")
    if _main_url:
        st.link_button("← 메인 대시보드", _main_url, use_container_width=True)
    st.caption("마스터 관리 전용 앱")
    if st.session_state.admin_authenticated:
        st.divider()
        if st.button("로그아웃", key="master_logout", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.session_state.user_id = None
            st.rerun()

# ─── 마스터 관리 UI ─────────────────────────────────────────────────
st.markdown("<h2 class='centered-title'> 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)

if not st.session_state.admin_authenticated:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("admin_verify"):
            pw = st.text_input("마스터 비밀번호", type="password")
            if st.form_submit_button("인증", use_container_width=True):
                master_hash = get_master_pw_hash()
                if master_hash is None:
                    # get_master_pw_hash() 실패 시 secrets 직접 접근
                    try:
                        master_hash = st.secrets["master_admin_pw_hash"]
                    except Exception:
                        pass
                if master_hash is None:
                    st.error("마스터 비밀번호가 설정되지 않았습니다.")
                elif verify_pw(pw, master_hash):
                    st.session_state.admin_authenticated = True
                    st.session_state.user_id = "master_admin"
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
else:
    st.markdown("<div class='section-title'> 반별 독립 모델/품목 설정</div>", unsafe_allow_html=True)
    _master_grp = st.radio("반 선택", PRODUCTION_GROUPS, horizontal=True,
                           key="master_group_radio", label_visibility="hidden")
    st.divider()
    for i, g_name in enumerate(PRODUCTION_GROUPS):
        if g_name != _master_grp:
            continue
        with st.container():
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
                            if added:
                                st.success(f" 등록 완료: {', '.join(added)}")
                            elif skipped:
                                st.warning(f" 이미 존재: {', '.join(skipped)}")
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
                                if added:
                                    st.success(f" 등록 완료: {', '.join(added)}")
                                elif skipped:
                                    st.warning(f" 이미 존재: {', '.join(skipped)}")
                            else: st.warning("품목코드를 입력해주세요.")
                    else:
                        st.warning("모델을 먼저 등록하세요.")

            # ── 삭제 ─────────────────────────────
            st.divider()
            st.markdown("<h4 style='color:#c8605a; font-weight:bold; margin-bottom:6px;'> 모델 / 품목 삭제</h4>", unsafe_allow_html=True)

            # ── 전체 삭제 버튼
            all_master_ck = f"del_all_master_ck_{g_name}"
            if not st.session_state.get(all_master_ck, False):
                if st.button(f" {g_name} 모델/품목 전체 삭제", key=f"del_all_m_{g_name}",
                             use_container_width=True, type="secondary"):
                    st.session_state[all_master_ck] = True
                    st.rerun()
            else:
                st.error(f" [{g_name}]의 모든 모델과 품목코드를 삭제합니다. 되돌릴 수 없습니다.")
                am1, am2, am3 = st.columns([2, 1, 1])
                am1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                if am2.button(" 예, 전체 삭제", key=f"del_all_m_yes_{g_name}",
                              type="primary", use_container_width=True):
                    st.session_state.group_master_models[g_name] = []
                    st.session_state.group_master_items[g_name]  = {}
                    delete_all_master_by_group(g_name)
                    st.session_state[all_master_ck] = False
                    st.toast(f"{g_name} 모델/품목 전체 삭제 완료")
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
                            if st.button(f" [{del_model}] 삭제", key=f"del_mb_{g_name}", use_container_width=True):
                                st.session_state[del_m_ck] = True
                                st.rerun()
                        else:
                            st.warning(f" [{del_model}] 모델과 품목 전체를 삭제하시겠습니까?")
                            dm1, dm2 = st.columns(2)
                            if dm1.button(" 삭제", key=f"del_m_yes_{g_name}", type="primary", use_container_width=True):
                                # session_state 제거
                                if del_model in st.session_state.group_master_models.get(g_name, []):
                                    st.session_state.group_master_models[g_name].remove(del_model)
                                st.session_state.group_master_items[g_name].pop(del_model, None)
                                # DB 제거
                                delete_model_from_master(g_name, del_model)
                                st.session_state[del_m_ck] = False
                                st.toast(f"[{del_model}] 삭제 완료")
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
                                if st.button(f" [{del_item}] 삭제", key=f"del_ib_{g_name}", use_container_width=True):
                                    st.session_state[del_i_ck] = True
                                    st.rerun()
                            else:
                                st.warning(f" [{di_model}] 의 [{del_item}] 품목을 삭제하시겠습니까?")
                                di1, di2 = st.columns(2)
                                if di1.button(" 삭제", key=f"del_i_yes_{g_name}", type="primary", use_container_width=True):
                                    st.session_state.group_master_items[g_name][di_model].remove(del_item)
                                    delete_item_from_master(g_name, di_model, del_item)
                                    st.session_state[del_i_ck] = False
                                    st.toast(f"[{del_item}] 삭제 완료")
                                    st.rerun()
                                if di2.button("취소", key=f"del_i_no_{g_name}", use_container_width=True):
                                    st.session_state[del_i_ck] = False
                                    st.rerun()
                        else:
                            st.info("등록된 품목이 없습니다.")
                    else:
                        st.info("등록된 모델이 없습니다.")

    st.divider()

    # ── 계정 신청 관리 ─────────────────────────────────────────
    _pending_reqs = load_access_requests(status="pending")
    _pending_cnt  = len(_pending_reqs)
    _req_label    = f" 계정 신청 관리 ({_pending_cnt}건 대기 중)" if _pending_cnt > 0 else " 계정 신청 관리"
    with st.expander(_req_label, expanded=(_pending_cnt > 0), key="master_req_expander"):
        _req_tabs = st.tabs(["⏳ 대기 중", " 승인됨", " 반려됨"], key="master_req_tabs")

        def _render_requests(req_df: pd.DataFrame, tab_status: str):
            if req_df.empty:
                st.info("해당 내역이 없습니다.")
                return
            _REQ_ROLE_LBL = {
                "assembly_team": " 조립 담당자", "qc_team": " 검사 담당자",
                "oqc_team": " OQC 품질팀",    "packing_team": " 포장 담당자",
                "schedule_manager": " 일정 관리자", "control_tower": " 컨트롤 타워",
                "admin": " 관리자",             "master": " 마스터 관리자",
            }
            for rq in req_df.to_dict('records'):
                with st.container():
                    rc1, rc2, rc3 = st.columns([3, 2, 2])
                    rc1.markdown(
                        f"**{rq.get('name','')}** (`{rq.get('username','')}`)"
                        f"  \n소속: {rq.get('department','')} · "
                        f"요청 권한: {_REQ_ROLE_LBL.get(rq.get('requested_role',''), rq.get('requested_role',''))}"
                    )
                    rc2.caption(f"신청일: {str(rq.get('created_at',''))[:16]}")
                    rc2.caption(f"사유: {rq.get('reason','')}")
                    if tab_status == "pending":
                        _rq_id = rq.get('id') or rq.get('ID')
                        with rc3:
                            ap_col, rj_col = st.columns(2)
                            if ap_col.button(" 승인", key=f"req_approve_{_rq_id}",
                                             use_container_width=True, type="primary"):
                                # 사용자 계정 생성
                                _nu = rq.get('username','')
                                _nh = rq.get('password_hash','')
                                _nr = rq.get('requested_role','assembly_team')
                                st.session_state.user_db[_nu] = {"pw_hash": _nh, "role": _nr}
                                try:
                                    get_supabase().table("users").upsert(
                                        {"username": _nu, "password_hash": _nh, "role": _nr},
                                        on_conflict="username"
                                    ).execute()
                                except Exception:
                                    pass
                                review_access_request(
                                    int(_rq_id), "approved",
                                    st.session_state.user_id
                                )
                                _clear_access_request_cache()
                                st.toast(f" [{_nu}] 계정 승인 완료")
                                st.rerun()
                            _rj_reason_key = f"rj_reason_{_rq_id}"
                            if rj_col.button(" 반려", key=f"req_reject_{_rq_id}",
                                             use_container_width=True):
                                st.session_state[_rj_reason_key] = True
                                st.rerun()
                            if st.session_state.get(_rj_reason_key):
                                _rj_txt = st.text_input("반려 사유", key=f"rj_txt_{_rq_id}")
                                if st.button("반려 확인", key=f"rj_confirm_{_rq_id}",
                                             use_container_width=True):
                                    review_access_request(
                                        int(_rq_id), "rejected",
                                        st.session_state.user_id, _rj_txt
                                    )
                                    st.session_state[_rj_reason_key] = False
                                    _clear_access_request_cache()
                                    st.toast(f"반려 처리됐습니다.")
                                    st.rerun()
                    elif tab_status == "approved":
                        rc3.success(f"승인자: {rq.get('reviewed_by','')}")
                        rc3.caption(str(rq.get('reviewed_at',''))[:16])
                    else:
                        rc3.error(f"반려자: {rq.get('reviewed_by','')}")
                        rc3.caption(f"사유: {rq.get('reject_reason','')}")
                    st.markdown("<hr style='margin:4px 0; border-color:#e8e2d8;'>", unsafe_allow_html=True)

        with _req_tabs[0]:
            _render_requests(_pending_reqs, "pending")
            if st.button(" 새로고침", key="req_refresh_pending"):
                _clear_access_request_cache(); st.rerun()
        with _req_tabs[1]:
            _render_requests(load_access_requests(status="approved"), "approved")
        with _req_tabs[2]:
            _render_requests(load_access_requests(status="rejected"), "rejected")

    st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin:16px 0 10px 0;'>계정 및 데이터 관리</h4>", unsafe_allow_html=True)
    ac1, ac2 = st.columns(2)

    with ac1:
        #  개선: 탭으로 기본 생성과 개별 권한 관리 분리
        user_tab1, user_tab2, user_tab3 = st.tabs([" 계정 생성", " 개별 권한 관리", " 계정 삭제"], key="master_user_tabs")
        
        with user_tab1:
            with st.form("user_mgmt"):
                st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'> 사용자 계정 생성/업데이트</p>", unsafe_allow_html=True)
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
            st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'> 사용자별 개별 권한 부여</p>", unsafe_allow_html=True)

            # 등록된 사용자 목록
            user_list = list(st.session_state.user_db.keys())
            if user_list:
                selected_user = st.selectbox("사용자 선택", user_list, key="perm_user_select")
                current_role  = st.session_state.user_db[selected_user].get("role", "assembly_team")

                st.caption(f"현재 역할: **{current_role}**")
                st.caption(" 읽기 — 페이지 열람  /   쓰기 — 신규 등록·처리  /   수정 — 기존 데이터 변경·삭제")

                # ── 현재 커스텀 권한 파싱 (없으면 역할 기본값) ───────────
                _raw = st.session_state.user_db[selected_user].get("custom_permissions", None)
                _cur_pages, _cur_levels = _parse_custom_perms(_raw)
                if _cur_pages is None:
                    _cur_pages  = ROLES.get(current_role, [])
                    _cur_levels = {p: set(PERM_ACTIONS) for p in _cur_pages}

                selected_pages  = []   # 최종 접근 가능 페이지 목록
                selected_levels = {}   # {page_key: [action, ...]}

                # ── 일반 메뉴 권한 (읽기/쓰기/수정 각각 체크) ───────────
                st.markdown("**일반 메뉴 권한:**")
                _general_menus = ["생산 지표 관리", "OQC 라인", "생산 현황 리포트", "불량 공정",
                                  "수리 현황 리포트", "마스터 관리", "작업자 매뉴얼", "관리자 매뉴얼", "플로우차트"]

                _gh = st.columns([2.2, 0.7, 0.7, 0.7])
                _gh[0].markdown("**메뉴**")
                for _ai, _al in enumerate(["읽기", "쓰기", "수정"]):
                    _gh[_ai + 1].markdown(f"**{_al}**")

                for _menu in _general_menus:
                    _gr = st.columns([2.2, 0.7, 0.7, 0.7])
                    _gr[0].write(_menu)
                    _menu_levels = _cur_levels.get(_menu, set())
                    _has_access  = _menu in _cur_pages
                    _checked = {}
                    for _ai, _act in enumerate(PERM_ACTIONS):
                        _checked[_act] = _gr[_ai + 1].checkbox(
                            "", value=(_has_access and _act in _menu_levels),
                            key=f"perm_{selected_user}_{_menu}_{_act}",
                            label_visibility="collapsed"
                        )
                    # 읽기 체크 = 페이지 접근 허용
                    if _checked["read"]:
                        selected_pages.append(_menu)
                        selected_levels[_menu] = [a for a, v in _checked.items() if v]

                # ── 제조 라인 — 반별 접근 체크 (기존 그리드 유지) ────────
                st.markdown("** 제조 라인 접근 (반별 선택):**")
                st.caption("각 반(班)별로 접근 가능한 라인을 선택합니다.")
                _line_types = ["조립 라인", "검사 라인", "포장 라인"]
                _lh = st.columns([1.5, 1, 1, 1])
                _lh[0].markdown("**반**")
                for _li, _lt in enumerate(_line_types):
                    _lh[_li + 1].markdown(f"**{_lt}**")
                for _group in PRODUCTION_GROUPS:
                    _rc = st.columns([1.5, 1, 1, 1])
                    _rc[0].write(_group)
                    for _li, _lt in enumerate(_line_types):
                        _pk = f"{_lt}::{_group}"
                        _chk = (_pk in _cur_pages) or (_lt in _cur_pages)
                        if _rc[_li + 1].checkbox("", value=_chk,
                                                  key=f"perm_{selected_user}_{_group}_{_lt}",
                                                  label_visibility="collapsed"):
                            selected_pages.append(_pk)

                # ── 제조 라인 동작 권한 (라인 유형별 읽기/쓰기/수정) ─────
                st.markdown("** 제조 라인 동작 권한:**")
                st.caption("위에서 접근을 허용한 라인에서 수행 가능한 동작을 설정합니다.")

                _ldh = st.columns([1.5, 0.7, 0.7, 0.7])
                _ldh[0].markdown("**라인**")
                for _ai, _al in enumerate(["읽기", "쓰기", "수정"]):
                    _ldh[_ai + 1].markdown(f"**{_al}**")

                for _lt in _line_types:
                    _ldr = st.columns([1.5, 0.7, 0.7, 0.7])
                    _ldr[0].write(_lt)
                    # 이 라인 유형에 접근 권한이 있는지 확인
                    _lt_has_access = any(
                        f"{_lt}::{g}" in selected_pages for g in PRODUCTION_GROUPS
                    )
                    # 현재 레벨: 부모키(_lt) 우선, 없으면 서브키에서 검색
                    _lt_cur_levels = _cur_levels.get(_lt, None)
                    if _lt_cur_levels is None:
                        for _k, _v in _cur_levels.items():
                            if _k.startswith(_lt + "::"):
                                _lt_cur_levels = _v
                                break
                    if _lt_cur_levels is None:
                        _lt_cur_levels = set(PERM_ACTIONS) if _lt_has_access else set()

                    _lt_checked = {}
                    for _ai, _act in enumerate(PERM_ACTIONS):
                        _lt_checked[_act] = _ldr[_ai + 1].checkbox(
                            "", value=(_lt_has_access and _act in _lt_cur_levels),
                            key=f"perm_{selected_user}_{_lt}_lvl_{_act}",
                            label_visibility="collapsed",
                            disabled=not _lt_has_access
                        )
                    _lt_result = [a for a, v in _lt_checked.items() if v]
                    if _lt_result:
                        selected_levels[_lt] = _lt_result

                # ── 저장 / 복원 ───────────────────────────────────────────
                perm_col1, perm_col2 = st.columns(2)
                if perm_col1.button(" 권한 저장", key="save_custom_perm",
                                    use_container_width=True, type="primary"):
                    _new_perm = {"pages": selected_pages, "levels": selected_levels}
                    st.session_state.user_db[selected_user]["custom_permissions"] = _new_perm
                    try:
                        import json
                        get_supabase().table("users").update(
                            {"custom_permissions": json.dumps(_new_perm, ensure_ascii=False)}
                        ).eq("username", selected_user).execute()
                        st.success(f" [{selected_user}] 권한 저장 완료 ({len(selected_pages)}개 메뉴) — DB 반영됨")
                    except Exception as _e:
                        st.success(f" [{selected_user}] 권한 저장 완료 ({len(selected_pages)}개 메뉴)")
                        st.caption(f"DB 저장 실패 (세션에만 적용): {_e}")

                if perm_col2.button("↩ 기본 권한 복원", key="reset_custom_perm", use_container_width=True):
                    if "custom_permissions" in st.session_state.user_db[selected_user]:
                        del st.session_state.user_db[selected_user]["custom_permissions"]
                    try:
                        get_supabase().table("users").update(
                            {"custom_permissions": None}
                        ).eq("username", selected_user).execute()
                        st.success(f" [{selected_user}] 기본 권한으로 복원됨 — DB 반영됨")
                    except Exception:
                        st.success(f" [{selected_user}] 기본 권한으로 복원됨")
            else:
                st.info("등록된 사용자가 없습니다. 먼저 계정을 생성해주세요.")

        with user_tab3:
            st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'> 계정 삭제</p>", unsafe_allow_html=True)
            del_user_list = [u for u in st.session_state.user_db.keys()
                             if u != st.session_state.user_id]
            if del_user_list:
                del_target = st.selectbox("삭제할 계정 선택", del_user_list, key="del_user_select")
                del_role = st.session_state.user_db[del_target].get("role", "")
                st.caption(f"역할: **{del_role}**")
                if not st.session_state.get("del_user_confirm", False):
                    if st.button(f" [{del_target}] 삭제", key="del_user_btn",
                                 use_container_width=True, type="primary"):
                        st.session_state["del_user_confirm"] = True
                        st.session_state["del_user_target"] = del_target
                        st.rerun()
                else:
                    confirm_target = st.session_state.get("del_user_target", "")
                    st.warning(f" [{confirm_target}] 계정을 삭제하시겠습니까? 복구할 수 없습니다.")
                    dc1, dc2 = st.columns(2)
                    if dc1.button(" 삭제 확인", key="del_user_yes",
                                  use_container_width=True, type="primary"):
                        if confirm_target in st.session_state.user_db:
                            del st.session_state.user_db[confirm_target]
                        try:
                            get_supabase().table("users").delete().eq(
                                "username", confirm_target).execute()
                            st.toast(f" [{confirm_target}] 계정 삭제 완료")
                        except Exception as _e:
                            st.toast(f"메모리 삭제 완료, DB 삭제 실패: {_e}")
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
        st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'> 시스템 데이터 관리</p>", unsafe_allow_html=True)
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
            except (TypeError, KeyError): pass
        st.caption(f" 조회 결과: **{len(db_export)}건**")
        st.download_button(" CSV 다운로드",
            db_export.to_csv(index=False).encode('utf-8-sig'),
            f"PMS_{export_group}_{start_date}~{end_date}.csv",
            use_container_width=True)
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
            db_export.to_excel(writer, index=False, sheet_name='생산데이터')
        st.download_button(" Excel 다운로드", excel_buf.getvalue(),
            f"PMS_{export_group}_{start_date}~{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)

    st.divider()

    # ── 데이터 삭제 관리 ──────────────────────────────────────
    # ── 드롭박스 편집 ──────────────────────────────────────────
    st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin:16px 0 10px 0;'> 드롭박스 옵션 편집</h4>", unsafe_allow_html=True)
    st.caption("각 항목을 한 줄에 하나씩 입력하세요. '(선택)'과 '기타 (직접 입력)'은 자동 유지됩니다.")

    dd_tab1, dd_tab2, dd_tab3, dd_tab4 = st.tabs([
        " OQC 부적합 사유", " 불량 원인", " 수리 조치", " 자재명"], key="master_dd_tabs")

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
        if ec1.button(f" 저장", key=f"dd_save_{tab_key}", use_container_width=True, type="primary"):
            new_items = [x.strip() for x in new_text.strip().splitlines() if x.strip()]
            seen = set()
            deduped = []
            for item in new_items:
                if item not in seen and item not in ["(선택)", "기타 (직접 입력)"]:
                    seen.add(item); deduped.append(item)
            final = ["(선택)"] + deduped + ["기타 (직접 입력)"]
            st.session_state[ss_key] = final
            if save_app_setting(ss_key, final):
                st.toast(f" {label} 저장 완료 ({len(deduped)}개 항목) — DB 반영됨")
            else:
                st.toast(f" {label} 저장 완료 ({len(deduped)}개 항목) — DB 저장 실패, 앱 재시작 시 초기화될 수 있습니다.")
            st.rerun()
        if ec2.button(f"↩ 기본값 복원", key=f"dd_reset_{tab_key}", use_container_width=True):
            default_val = _DD_DEFAULTS.get(ss_key, [])
            st.session_state[ss_key] = default_val
            save_app_setting(ss_key, default_val)
            st.toast("기본값으로 복원됩니다.")
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
                if r2.button("삭제", key=f"mat_del_item_{i}", help=f"{item} 삭제", use_container_width=True):
                    _del_idx = i
            if _del_idx is not None:
                current.pop(_del_idx)
                st.session_state[_SS] = current
                ok = save_app_setting(_SS, current)
                if ok:
                    st.toast(" 삭제 완료")
                else:
                    st.toast(" DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다")
                st.rerun()
        else:
            st.info("등록된 자재명이 없습니다. 아래에서 추가하세요.")

        st.divider()

        # ── 신규 추가 ─────────────────────────────────────────────
        st.markdown("<p style='font-size:0.8rem;font-weight:700;color:#5a4f45;margin:0 0 4px 0;'>자재명 추가</p>", unsafe_allow_html=True)
        na1, na2 = st.columns([4, 1])
        new_item = na1.text_input("", placeholder="추가할 자재명 입력", key="mat_new_input", label_visibility="collapsed")
        if na2.button(" 추가", key="mat_add_btn", use_container_width=True, type="primary"):
            val = new_item.strip()
            if val and val not in current:
                current.append(val)
                st.session_state[_SS] = current
                ok = save_app_setting(_SS, current)
                if ok:
                    st.toast(f" '{val}' 추가 완료")
                else:
                    st.toast(" DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다")
                st.rerun()
            elif val in current:
                st.warning(f"'{val}'은 이미 등록된 자재명입니다.")
            else:
                st.warning("자재명을 입력해주세요.")

        st.divider()

        # ── 전체 삭제 ─────────────────────────────────────────────
        if st.button(" 전체 삭제", key="mat_clear_all", use_container_width=True):
            st.session_state["_mat_clear_confirm"] = True; st.rerun()

        if st.session_state.get("_mat_clear_confirm"):
            st.error(" 자재명 목록을 전체 삭제합니다. 계속하시겠습니까?")
            cc1, cc2 = st.columns([1, 1])
            if cc1.button(" 예, 전체 삭제", key="mat_clear_yes", type="primary", use_container_width=True):
                st.session_state[_SS] = []
                ok = save_app_setting(_SS, [])
                st.session_state["_mat_clear_confirm"] = False
                if not ok:
                    st.toast(" DB 저장 실패 — 앱 재시작 시 복원될 수 있습니다")
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

    # ── 상태 되돌리기 ────────────────────────────────────────
    st.markdown("<h4 style='color:#2a2420; font-weight:bold; margin:16px 0 10px 0;'>↩ 제품 상태 수동 변경 (관리자 전용)</h4>", unsafe_allow_html=True)
    with st.container(border=True):
        st.caption("실수로 잘못 처리된 제품의 상태를 되돌리거나 직접 변경합니다.")
        _all_states = ['조립중', '검사대기', '검사중', 'OQC대기', 'OQC중', '출하승인', '포장대기', '포장중', '완료', '불량 처리 중', '수리 완료(재투입)']
        _STATE_TO_LINE = {
            '조립중':           '조립 라인',
            '검사대기':         '조립 라인',
            '검사중':           '검사 라인',
            'OQC대기':          '검사 라인',
            'OQC중':            'OQC 라인',
            '출하승인':         'OQC 라인',
            '포장대기':         'OQC 라인',
            '포장중':           '포장 라인',
            '완료':             '포장 라인',
            '불량 처리 중':     '불량 공정',
            '수리 완료(재투입)':'불량 공정',
        }
        with st.form("rollback_search_form"):
            _rb_fcol1, _rb_fcol2 = st.columns([3, 1])
            _rb_sn_input = _rb_fcol1.text_input(
                "시리얼 번호 입력", placeholder="예) SN-20240101-001",
                value=st.session_state.get("_rb_sn_cache", ""))
            _rb_search = _rb_fcol2.form_submit_button(" 조회", use_container_width=True)

        if _rb_search:
            st.session_state["_rb_sn_cache"] = _rb_sn_input.strip()

        _cached_sn = st.session_state.get("_rb_sn_cache", "")
        if _cached_sn:
            _rb_df = st.session_state.production_db
            _rb_match = _rb_df[_rb_df['시리얼'] == _cached_sn] if not _rb_df.empty else pd.DataFrame()
            _rb_from_history = False
            # production_db 캐시 미포함(어제 이전 완료 등) → DB 직접 조회
            if _rb_match.empty:
                try:
                    _rb_direct = get_supabase().table("production").select("*").eq("시리얼", _cached_sn).is_("deleted_at", "null").execute()
                    if _rb_direct.data:
                        _rb_match = pd.DataFrame(_rb_direct.data).drop(columns=['id','deleted_at','deleted_by'], errors='ignore').fillna("")
                    else:
                        # production_history 아카이브 테이블도 조회
                        try:
                            _rb_hist = get_supabase().table("production_history").select("*").eq("시리얼", _cached_sn).execute()
                            if _rb_hist.data:
                                _rb_match = pd.DataFrame(_rb_hist.data).drop(columns=['id','deleted_at','deleted_by'], errors='ignore').fillna("")
                                _rb_from_history = True
                        except Exception:
                            pass
                except Exception:
                    pass
            if not _rb_match.empty:
                _rb_row = _rb_match.iloc[0]
                _rb_cur_line = _rb_row.get('라인', '')
                _rb_info_suffix = "  ⚠️ *아카이브 이력 데이터*" if _rb_from_history else ""
                st.info(f"현재 상태: **{_rb_row['상태']}** | 현재 라인: **{_rb_cur_line}** | 모델: {_rb_row.get('모델','')} | 반: {_rb_row.get('반','')}{_rb_info_suffix}")
                if _rb_from_history:
                    st.warning("아카이브된 이력 데이터는 상태 변경이 불가합니다. production 테이블에 해당 시리얼이 존재하지 않습니다.")
                _rb_col1, _rb_col2 = st.columns([2, 1])
                _rb_target = _rb_col1.selectbox("변경할 상태", _all_states, key="rollback_target")
                _rb_new_line = _STATE_TO_LINE.get(_rb_target, _rb_cur_line)
                _rb_col1.caption(f"라인 자동 변경: **{_rb_cur_line}** → **{_rb_new_line}**" if _rb_new_line != _rb_cur_line else f"라인 유지: {_rb_cur_line}")
                if _rb_col2.button(" 상태 변경 실행", key="rollback_exec", type="primary",
                                   use_container_width=True, disabled=_rb_from_history):
                    _prev_s = _rb_row['상태']
                    _upd = {'상태': _rb_target, '라인': _rb_new_line, '시간': get_now_kst_str()}
                    # update_row + insert_audit_log 병렬 실행으로 DB 대기 시간 단축
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=2) as _ex:
                        _f_upd = _ex.submit(update_row, _cached_sn, _upd)
                        _ex.submit(insert_audit_log,
                            시리얼=_cached_sn, 모델=_rb_row.get('모델',''), 반=_rb_row.get('반',''),
                            이전상태=_prev_s, 이후상태=_rb_target,
                            작업자=st.session_state.user_id,
                            비고=f"관리자 수동 상태 변경 (라인: {_rb_cur_line}→{_rb_new_line})"
                        )
                        _ok = _f_upd.result()
                    if _ok:
                        _prod_update(_cached_sn, _upd)
                        # 검색 결과 유지 → rerun 후 변경된 상태 즉시 확인 가능
                        st.toast(f" [{_cached_sn}] {_prev_s} → {_rb_target} / 라인: {_rb_cur_line} → {_rb_new_line}")
                        st.rerun()
                    else:
                        st.error("변경 실패. 시리얼 번호를 확인해주세요.")
            else:
                st.warning(f"'{_cached_sn}' 시리얼 번호를 찾을 수 없습니다.")

    st.divider()

    st.markdown("<h4 style='color:#c8605a; font-weight:bold; margin:16px 0 10px 0;'> 데이터 삭제 관리</h4>", unsafe_allow_html=True)
    st.caption("생산 이력, 감사 로그, 자재 시리얼, 생산 일정을 개별 또는 전체 삭제합니다.")
    # ── 삭제 결과 toast (rerun 후 표시) ──────────────────────────
    _del_mgr_toast = st.session_state.pop("_del_mgr_toast", None)
    if _del_mgr_toast:
        st.success(_del_mgr_toast)

    del_tab1, del_tab2, del_tab3, del_tab4, del_tab5, del_tab6, del_tab7 = st.tabs([
        " 생산 이력", " 감사 로그", " 자재 시리얼",
        " 생산 일정", " 계획 변경 이력", " 일정 변경 이력",
        " 월별 계획 수량"])

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
            with st.expander(f" 개별 삭제 목록 ({len(prod_df)}건)", expanded=False):
                ph = st.columns([1.8, 1.5, 1.5, 1.8, 1.5, 1.0])
                for c, t in zip(ph, ["시간","반","라인","시리얼","상태","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for i, row in enumerate(prod_df.sort_values('시간', ascending=False).head(200).to_dict('records')):
                    pr = st.columns([1.8, 1.5, 1.5, 1.8, 1.5, 1.0])
                    pr[0].caption(str(row.get('시간',''))[:16])
                    pr[1].caption(row.get('반',''))
                    pr[2].caption(row.get('라인',''))
                    pr[3].caption(f"`{row.get('시리얼','')}`")
                    pr[4].caption(row.get('상태',''))
                    if pr[5].button("삭제", key=f"del_prod_{i}", help="이 행 삭제"):
                        if delete_production_row_by_sn(row['시리얼']):
                            _clear_production_cache()
                            st.session_state.production_db = load_realtime_ledger()
                            st.toast(f"삭제 완료: {row['시리얼']}")
                            st.rerun()
                if len(prod_df) > 200:
                    st.caption(f"※ 최대 200건만 표시. 필터로 범위를 좁혀주세요.")
        else:
            st.info("조건에 맞는 데이터가 없습니다.")

        # 전체 삭제
        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_prod_all = "del_prod_all_ck"
        # rerun 후 결과 메시지 표시 (if/else 블록 바깥에서 항상 실행)
        _del_result = st.session_state.pop("_delete_result", None)
        if _del_result == "success":
            st.success(" 생산 이력 전체 삭제 완료")
        elif _del_result == "fail":
            st.error(" 삭제 실패")
        for _lvl, _msg in st.session_state.pop("_delete_msgs", []):
            if _lvl == "warning": st.warning(_msg)
            elif _lvl == "error": st.error(_msg)

        if not st.session_state.get(_ck_prod_all):
            if st.button(" 생산 이력 전체 삭제", key="del_prod_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_prod_all] = True; st.rerun()
        else:
            st.error(" 생산 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _pa1, _pa2, _pa3 = st.columns([2,1,1])
            _pa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _pa2.button(" 예, 전체 삭제", key="del_prod_all_yes", type="primary", use_container_width=True):
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

    # ─── 탭2: 감사 로그 ───────────────────────────────────────
    with del_tab2:
        @st.cache_data(ttl=60)
        def _load_audit_all():
            try:
                res = get_supabase().table("audit_log").select("*").order("시간", desc=True).limit(500).execute()
                return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                    columns=['id','시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])
            except Exception: return pd.DataFrame(columns=['id','시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])

        audit_df = _load_audit_all()
        st.caption(f"현재 **{len(audit_df)}건** (최대 500건 표시)")
        if st.button(" 새로고침", key="audit_del_refresh"):
            _clear_audit_cache(); st.rerun()

        # 필터
        al1, al2 = st.columns([1.5, 2])
        _a_grp = al1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_audit_grp")
        _a_sn  = al2.text_input("S/N 검색", key="d_audit_sn", placeholder="시리얼 일부 입력")
        adf = audit_df.copy()
        if _a_grp != "전체": adf = adf[adf['반'] == _a_grp]
        if _a_sn.strip():   adf = adf[adf['시리얼'].str.contains(_a_sn.strip(), case=False, na=False)]

        if not adf.empty:
            with st.expander(f" 개별 삭제 목록 ({len(adf)}건)", expanded=False):
                ah = st.columns([1.8, 1.5, 1.8, 1.3, 1.5, 1.5, 1.0])
                for c, t in zip(ah, ["시간","반","시리얼","모델","이전상태","이후상태","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for row in adf.to_dict('records'):
                    ar = st.columns([1.8, 1.5, 1.8, 1.3, 1.5, 1.5, 1.0])
                    ar[0].caption(str(row.get('시간',''))[:16])
                    ar[1].caption(row.get('반',''))
                    ar[2].caption(f"`{row.get('시리얼','')}`")
                    ar[3].caption(row.get('모델',''))
                    ar[4].caption(row.get('이전상태',''))
                    ar[5].caption(row.get('이후상태',''))
                    _row_id = row.get('id')
                    if _row_id and ar[6].button("삭제", key=f"del_audit_{_row_id}", help="이 행 삭제"):
                        if delete_audit_log_row(_row_id):
                            _clear_audit_cache()
                            st.session_state["_del_mgr_toast"] = " 감사 로그 삭제 완료"; st.rerun()
        else:
            st.info("조건에 맞는 감사 로그가 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_audit_all = "del_audit_all_ck"
        if not st.session_state.get(_ck_audit_all):
            if st.button(" 감사 로그 전체 삭제", key="del_audit_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_audit_all] = True; st.rerun()
        else:
            st.error(" 감사 로그 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _aa1, _aa2, _aa3 = st.columns([2,1,1])
            _aa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _aa2.button(" 예, 전체 삭제", key="del_audit_all_yes", type="primary", use_container_width=True):
                if delete_all_audit_log():
                    _clear_audit_cache()
                    st.session_state[_ck_audit_all] = False
                    st.session_state["_del_mgr_toast"] = " 감사 로그 전체 삭제 완료"; st.rerun()
            if _aa3.button("취소", key="del_audit_all_no", use_container_width=True):
                st.session_state[_ck_audit_all] = False; st.rerun()

    # ─── 탭3: 자재 시리얼 ────────────────────────────────────
    with del_tab3:
        @st.cache_data(ttl=60)
        def _load_mat_all():
            try:
                res = get_supabase().table("material_serial").select("*").order("시간", desc=True).limit(500).execute()
                return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                    columns=['id','시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
            except Exception: return pd.DataFrame(columns=['id','시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])

        mat_df = _load_mat_all()
        st.caption(f"현재 **{len(mat_df)}건** (최대 500건 표시)")
        if st.button(" 새로고침", key="mat_del_refresh"):
            load_material_serials.clear(); st.rerun()

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
            with st.expander(f" 개별 삭제 목록 ({len(mdf)}건)", expanded=False):
                mh = st.columns([1.8, 1.8, 1.5, 1.5, 1.8, 1.0])
                for c, t in zip(mh, ["시간","메인S/N","모델","자재명","자재S/N","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for row in mdf.to_dict('records'):
                    mr = st.columns([1.8, 1.8, 1.5, 1.5, 1.8, 1.0])
                    mr[0].caption(str(row.get('시간',''))[:16])
                    mr[1].caption(f"`{row.get('메인시리얼','')}`")
                    mr[2].caption(row.get('모델',''))
                    mr[3].caption(row.get('자재명',''))
                    mr[4].caption(f"`{row.get('자재시리얼','')}`")
                    _mid = row.get('id')
                    if _mid and mr[5].button("삭제", key=f"del_mat_{_mid}", help="이 행 삭제"):
                        if delete_material_serial_row(_mid):
                            load_material_serials.clear()
                            st.session_state["_del_mgr_toast"] = " 자재 시리얼 삭제 완료"; st.rerun()
        else:
            st.info("조건에 맞는 자재 시리얼이 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_mat_all = "del_mat_all_ck"
        if not st.session_state.get(_ck_mat_all):
            if st.button(" 자재 시리얼 전체 삭제", key="del_mat_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_mat_all] = True; st.rerun()
        else:
            st.error(" 자재 시리얼 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _ma1, _ma2, _ma3 = st.columns([2,1,1])
            _ma1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _ma2.button(" 예, 전체 삭제", key="del_mat_all_yes", type="primary", use_container_width=True):
                if delete_all_material_serial():
                    load_material_serials.clear()
                    st.session_state[_ck_mat_all] = False
                    st.session_state["_del_mgr_toast"] = " 자재 시리얼 전체 삭제 완료"; st.rerun()
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
            with st.expander(f" 개별 삭제 목록 ({len(sdf)}건)", expanded=False):
                sh = st.columns([1.5, 1.2, 1.5, 2.0, 1.2, 1.2, 1.0])
                for c, t in zip(sh, ["날짜","반","카테고리","모델명","처리수","출하계획","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for row in sdf.sort_values('날짜', ascending=False).to_dict('records'):
                    sr = st.columns([1.5, 1.2, 1.5, 2.0, 1.2, 1.2, 1.0])
                    sr[0].caption(str(row.get('날짜',''))[:10])
                    sr[1].caption(row.get('반',''))
                    sr[2].caption(row.get('카테고리',''))
                    sr[3].caption(row.get('모델명',''))
                    sr[4].caption(str(row.get('조립수','')))
                    sr[5].caption(str(row.get('출하계획','')))
                    _sid = row.get('id')
                    if _sid and sr[6].button("삭제", key=f"del_sch_{_sid}", help="이 행 삭제"):
                        if delete_schedule(int(_sid)):
                            _clear_schedule_cache()
                            st.session_state.schedule_db = load_schedule()
                            st.session_state["_del_mgr_toast"] = " 생산 일정 삭제 완료"; st.rerun()
        else:
            st.info("조건에 맞는 일정이 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_sch_all = "del_sch_all_ck"
        if not st.session_state.get(_ck_sch_all):
            if st.button(" 생산 일정 전체 삭제", key="del_sch_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_sch_all] = True; st.rerun()
        else:
            st.error(" 생산 일정 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _sa1, _sa2, _sa3 = st.columns([2,1,1])
            _sa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _sa2.button(" 예, 전체 삭제", key="del_sch_all_yes", type="primary", use_container_width=True):
                if delete_all_production_schedule():
                    _clear_schedule_cache()
                    st.session_state.schedule_db = load_schedule()
                    st.session_state[_ck_sch_all] = False
                    st.session_state["_del_mgr_toast"] = " 생산 일정 전체 삭제 완료"; st.rerun()
            if _sa3.button("취소", key="del_sch_all_no", use_container_width=True):
                st.session_state[_ck_sch_all] = False; st.rerun()

    # ─── 탭5: 계획 변경 이력 ─────────────────────────────────
    with del_tab5:
        @st.cache_data(ttl=60)
        def _load_plan_log_all():
            try:
                res = get_supabase().table("plan_change_log").select("*").order("시간", desc=True).limit(500).execute()
                return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                    columns=['id','시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])
            except Exception:
                return pd.DataFrame(columns=['id','시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])

        plog = _load_plan_log_all()
        st.caption(f"현재 **{len(plog)}건** (최대 500건 표시)")
        if st.button(" 새로고침", key="plog_del_refresh"):
            _clear_plan_cache(); st.rerun()

        pl1, pl2 = st.columns([1.5, 2])
        _pl_grp = pl1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_plog_grp")
        _pl_kw  = pl2.text_input("월 검색", key="d_plog_kw", placeholder="예: 2026-03")
        pldf = plog.copy()
        if _pl_grp != "전체": pldf = pldf[pldf['반'] == _pl_grp]
        if _pl_kw.strip():   pldf = pldf[pldf['월'].astype(str).str.contains(_pl_kw.strip(), na=False)]

        if not pldf.empty:
            with st.expander(f" 개별 삭제 목록 ({len(pldf)}건)", expanded=False):
                plh = st.columns([1.8, 1.2, 1.3, 1.2, 1.2, 1.0, 1.8, 1.0])
                for c, t in zip(plh, ["시간","반","월","이전수량","변경수량","증감","변경사유","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for row in pldf.to_dict('records'):
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
                    if _plid and plr[7].button("삭제", key=f"del_plog_{_plid}", help="이 행 삭제"):
                        if delete_plan_change_log_row(_plid):
                            _clear_plan_cache()
                            st.session_state["_del_mgr_toast"] = " 계획 변경 이력 삭제 완료"; st.rerun()
        else:
            st.info("조건에 맞는 계획 변경 이력이 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_plog_all = "del_plog_all_ck"
        if not st.session_state.get(_ck_plog_all):
            if st.button(" 계획 변경 이력 전체 삭제", key="del_plog_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_plog_all] = True; st.rerun()
        else:
            st.error(" 계획 변경 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _pla1, _pla2, _pla3 = st.columns([2,1,1])
            _pla1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _pla2.button(" 예, 전체 삭제", key="del_plog_all_yes", type="primary", use_container_width=True):
                if delete_all_plan_change_log():
                    _clear_plan_cache()
                    st.session_state[_ck_plog_all] = False
                    st.session_state["_del_mgr_toast"] = " 계획 변경 이력 전체 삭제 완료"; st.rerun()
            if _pla3.button("취소", key="del_plog_all_no", use_container_width=True):
                st.session_state[_ck_plog_all] = False; st.rerun()

    # ─── 탭6: 일정 변경 이력 ─────────────────────────────────
    with del_tab6:
        @st.cache_data(ttl=60)
        def _load_sch_log_all():
            try:
                res = get_supabase().table("schedule_change_log").select("*").order("시간", desc=True).limit(500).execute()
                return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                    columns=['id','시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])
            except Exception:
                return pd.DataFrame(columns=['id','시간','일정id','날짜','반','모델명','이전내용','변경내용','변경사유','사유상세','작업자'])

        slog = _load_sch_log_all()
        st.caption(f"현재 **{len(slog)}건** (최대 500건 표시)")
        if st.button(" 새로고침", key="slog_del_refresh"):
            _clear_schedule_cache(); st.rerun()

        sl1, sl2 = st.columns([1.5, 2])
        _sl_grp = sl1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_slog_grp")
        _sl_kw  = sl2.text_input("모델명 검색", key="d_slog_kw", placeholder="모델명 일부 입력")
        sldf = slog.copy()
        if _sl_grp != "전체": sldf = sldf[sldf['반'] == _sl_grp]
        if _sl_kw.strip():   sldf = sldf[sldf['모델명'].astype(str).str.contains(_sl_kw.strip(), case=False, na=False)]

        if not sldf.empty:
            with st.expander(f" 개별 삭제 목록 ({len(sldf)}건)", expanded=False):
                slh = st.columns([1.8, 1.2, 1.3, 1.8, 1.8, 1.5, 1.0])
                for c, t in zip(slh, ["시간","반","날짜","모델명","변경사유","작업자","삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>", unsafe_allow_html=True)
                for row in sldf.to_dict('records'):
                    slr = st.columns([1.8, 1.2, 1.3, 1.8, 1.8, 1.5, 1.0])
                    slr[0].caption(str(row.get('시간',''))[:16])
                    slr[1].caption(row.get('반',''))
                    slr[2].caption(str(row.get('날짜',''))[:10])
                    slr[3].caption(row.get('모델명',''))
                    slr[4].caption(row.get('변경사유',''))
                    slr[5].caption(row.get('작업자',''))
                    _slid = row.get('id')
                    if _slid and slr[6].button("삭제", key=f"del_slog_{_slid}", help="이 행 삭제"):
                        if delete_schedule_change_log_row(_slid):
                            _clear_schedule_cache()
                            st.session_state["_del_mgr_toast"] = " 일정 변경 이력 삭제 완료"; st.rerun()
        else:
            st.info("조건에 맞는 일정 변경 이력이 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_slog_all = "del_slog_all_ck"
        if not st.session_state.get(_ck_slog_all):
            if st.button(" 일정 변경 이력 전체 삭제", key="del_slog_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_slog_all] = True; st.rerun()
        else:
            st.error(" 일정 변경 이력 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _sla1, _sla2, _sla3 = st.columns([2,1,1])
            _sla1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
            if _sla2.button(" 예, 전체 삭제", key="del_slog_all_yes", type="primary", use_container_width=True):
                if delete_all_schedule_change_log():
                    _clear_schedule_cache()
                    st.session_state[_ck_slog_all] = False
                    st.session_state["_del_mgr_toast"] = " 일정 변경 이력 전체 삭제 완료"; st.rerun()
            if _sla3.button("취소", key="del_slog_all_no", use_container_width=True):
                st.session_state[_ck_slog_all] = False; st.rerun()

    # ─── 탭7: 월별 계획 수량 ──────────────────────────────────
    with del_tab7:
        @st.cache_data(ttl=60)
        def _load_plan_all():
            try:
                res = get_supabase().table("production_plan").select("*").order("월", desc=True).execute()
                return pd.DataFrame(res.data) if res.data else pd.DataFrame(
                    columns=['id','반','월','계획수량'])
            except Exception:
                return pd.DataFrame(columns=['id','반','월','계획수량'])

        plan_df = _load_plan_all()
        st.caption(f"현재 **{len(plan_df)}건** 등록됨")
        if st.button(" 새로고침", key="plan_del_refresh"):
            _clear_plan_cache(); st.rerun()

        # 필터
        pp1, pp2 = st.columns([1.5, 2])
        _pp_grp = pp1.selectbox("반", ["전체"] + PRODUCTION_GROUPS, key="d_plan_grp")
        _pp_kw  = pp2.text_input("월 검색", key="d_plan_kw", placeholder="예: 2026-03")
        ppdf = plan_df.copy()
        if _pp_grp != "전체": ppdf = ppdf[ppdf['반'] == _pp_grp]
        if _pp_kw.strip():   ppdf = ppdf[ppdf['월'].astype(str).str.contains(_pp_kw.strip(), na=False)]
        ppdf = ppdf.sort_values('월', ascending=False) if not ppdf.empty else ppdf

        if not ppdf.empty:
            with st.expander(f" 개별 삭제 목록 ({len(ppdf)}건)", expanded=False):
                pph = st.columns([2, 2, 2, 1])
                for c, t in zip(pph, ["반", "월", "계획 수량", "삭제"]):
                    c.markdown(f"<p style='font-size:0.72rem;font-weight:700;color:#8a7f72;margin:0;border-bottom:1px solid #e0d8c8;'>{t}</p>",
                               unsafe_allow_html=True)
                for _pi, row in enumerate(ppdf.to_dict('records')):
                    ppr = st.columns([2, 2, 2, 1])
                    ppr[0].write(row.get('반', ''))
                    ppr[1].write(str(row.get('월', '')))
                    ppr[2].write(f"{int(row.get('계획수량', 0)):,} EA")
                    _p_ban = row.get('반', '')
                    _p_wol = row.get('월', '')
                    if ppr[3].button("삭제", key=f"del_plan_{_pi}", help="이 행 삭제"):
                        if delete_production_plan_row(_p_ban, _p_wol):
                            _clear_plan_cache()
                            st.session_state.production_plan = load_production_plan()
                            st.session_state["_del_mgr_toast"] = f" 삭제 완료: {_p_ban} {_p_wol}"
                            st.rerun()
        else:
            st.info("조건에 맞는 계획 수량이 없습니다.")

        st.markdown("<hr style='margin:12px 0;border-color:#e0d8c8;'>", unsafe_allow_html=True)
        _ck_plan_all = "del_plan_all_ck"
        if not st.session_state.get(_ck_plan_all):
            if st.button(" 월별 계획 수량 전체 삭제", key="del_plan_all_btn",
                         type="secondary", use_container_width=False):
                st.session_state[_ck_plan_all] = True; st.rerun()
        else:
            st.error(" 월별 계획 수량 **전체**를 삭제합니다. 되돌릴 수 없습니다.")
            _ppa1, _ppa2, _ppa3 = st.columns([2, 1, 1])
            _ppa1.markdown("<p style='color:#c8605a;font-weight:bold;margin-top:8px;'>삭제 후 복구 불가</p>",
                           unsafe_allow_html=True)
            if _ppa2.button(" 예, 전체 삭제", key="del_plan_all_yes",
                            type="primary", use_container_width=True):
                if delete_all_production_plan():
                    _clear_plan_cache()
                    st.session_state.production_plan = load_production_plan()
                    st.session_state[_ck_plan_all] = False
                    st.session_state["_del_mgr_toast"] = " 월별 계획 수량 전체 삭제 완료"; st.rerun()
            if _ppa3.button("취소", key="del_plan_all_no", use_container_width=True):
                st.session_state[_ck_plan_all] = False; st.rerun()

    st.divider()

    # 기존 전체 초기화 버튼 (하위 호환)
    st.markdown("<p style='color:#8a7f72;font-size:0.85rem;'> 아래는 생산 이력만 초기화하는 기존 버튼입니다. 위 탭을 이용하세요.</p>", unsafe_allow_html=True)
    # 초기화 버튼 - 2단계 확인
    if 'confirm_reset' not in st.session_state:
        st.session_state.confirm_reset = False

    if not st.session_state.confirm_reset:
        if st.button(" 전체 데이터 초기화", type="secondary", use_container_width=False):
            st.session_state.confirm_reset = True
            st.rerun()
    else:
        st.error(" 정말로 전체 생산 데이터를 삭제하시겠습니까? **되돌릴 수 없습니다.**")
        cc1, cc2, cc3 = st.columns([2, 1, 1])
        cc1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가 — 신중히 결정하세요.</p>", unsafe_allow_html=True)
        if cc2.button(" 예, 삭제합니다", type="primary", use_container_width=True):
            if delete_all_rows():
                st.session_state.production_db = load_realtime_ledger()
                st.session_state.confirm_reset = False
                st.toast("전체 데이터가 초기화되었습니다.")
                st.rerun()
        if cc3.button("취소", use_container_width=True):
            st.session_state.confirm_reset = False
