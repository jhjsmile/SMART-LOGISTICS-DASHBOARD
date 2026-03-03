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
# 1. 시스템 전역 설정 (v22.3 - 반응형)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v22.3",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
_refresh_count = st_autorefresh(interval=30000, key="pms_auto_refresh")
# autorefresh 카운터만 기록 - 팝업은 사용자가 직접 닫을 때까지 유지
if _refresh_count:
    st.session_state["_last_refresh_count"] = _refresh_count

PRODUCTION_GROUPS   = ["제조1반", "제조2반", "제조3반"]
CALENDAR_EDIT_ROLES = ["master", "admin", "control_tower", "schedule_manager"]

ROLES = {
    "master":        ["조립 라인", "검사 라인", "포장 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리"],
    "control_tower": ["생산 현황 리포트", "수리 현황 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team":       ["검사 라인", "불량 공정"],
    "packing_team":  ["포장 라인"],
    "admin":         ["조립 라인", "검사 라인", "포장 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리"],
    "schedule_manager": ["마스터 관리"]
}

ROLE_LABELS = {
    "master":        "👤 마스터 관리자",
    "admin":         "👤 관리자",
    "control_tower": "🗼 컨트롤 타워",
    "assembly_team": "🔧 조립 담당자",
    "qc_team":       "🔍 검사 담당자",
    "packing_team":  "📦 포장 담당자",
    "schedule_manager": "📅 일정 관리자",
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
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: #7eb8e8 !important;
        box-shadow: 0 0 0 2px rgba(126,184,232,0.25) !important;
    }

    /* ── 버튼 전체 공통 ── */
    .stButton > button,
    div[data-testid="stFormSubmitButton"] > button,
    button[kind="primary"],
    button[kind="secondary"] {
        display: flex !important; justify-content: center !important; align-items: center !important;
        margin-top: 1px !important; padding: 6px 10px !important; width: 100% !important;
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

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_pw(plain: str, hashed: str) -> bool:
    return hash_pw(plain) == hashed

def get_master_pw_hash() -> str | None:
    try:
        return st.secrets["connections"]["gsheets"]["master_admin_pw_hash"]
    except Exception:
        try:
            return st.secrets["master_admin_pw_hash"]
        except Exception:
            return None

# =================================================================
# 3. Supabase 연결 및 DB 함수
# =================================================================

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def keep_supabase_alive():
    try:
        get_supabase().table("production").select("id").limit(1).execute()
    except:
        pass

keep_supabase_alive()

def get_now_kst_str() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_realtime_ledger() -> pd.DataFrame:
    try:
        sb  = get_supabase()
        res = sb.table("production").select("*").order("created_at", desc=False).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df = df.drop(columns=[c for c in ['id','created_at'] if c in df.columns])
            return df.fillna("")
        return pd.DataFrame(columns=['시간','반','라인','cell','모델','품목코드','시리얼','상태','증상','수리','작업자'])
    except Exception as e:
        st.warning(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=['시간','반','라인','cell','모델','품목코드','시리얼','상태','증상','수리','작업자'])

def insert_row(row: dict) -> bool:
    try:
        get_supabase().table("production").insert(row).execute()
        return True
    except Exception as e:
        st.error(f"등록 실패: {e}"); return False

def update_row(시리얼: str, data: dict) -> bool:
    try:
        get_supabase().table("production").update(data).eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"업데이트 실패: {e}"); return False

def delete_all_rows() -> bool:
    try:
        get_supabase().table("production").delete().neq("시리얼", "IMPOSSIBLE_XYZ").execute()
        return True
    except Exception as e:
        st.error(f"초기화 실패: {e}"); return False

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
    except:
        return False

def delete_model_from_master(반: str, 모델명: str) -> bool:
    """반+모델명 전체 삭제 (해당 모델의 모든 품목 포함)"""
    try:
        get_supabase().table("model_master").delete()\
            .eq("반", 반).eq("모델명", 모델명).execute()
        return True
    except:
        return False

def delete_item_from_master(반: str, 모델명: str, 품목코드: str) -> bool:
    """특정 품목코드만 삭제"""
    try:
        get_supabase().table("model_master").delete()\
            .eq("반", 반).eq("모델명", 모델명).eq("품목코드", 품목코드).execute()
        return True
    except:
        return False

def delete_all_master_by_group(반: str) -> bool:
    """특정 반의 모델/품목 전체 삭제"""
    try:
        get_supabase().table("model_master").delete().eq("반", 반).execute()
        return True
    except:
        return False

def sync_master_to_session():
    """DB model_master → session_state group_master_models/items 동기화"""
    df = load_model_master()
    if df.empty:
        return
    models_map = {g: [] for g in PRODUCTION_GROUPS}
    items_map  = {g: {} for g in PRODUCTION_GROUPS}
    for _, r in df.iterrows():
        g  = str(r['반'])
        m  = str(r['모델명'])
        pn = str(r['품목코드'])
        if g not in models_map:
            continue
        if m not in models_map[g]:
            models_map[g].append(m)
        if m not in items_map[g]:
            items_map[g][m] = []
        if pn and pn not in items_map[g][m]:
            items_map[g][m].append(pn)
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
        return f"⚠️ 업로드 실패: {e}"

# =================================================================
# 4. 캘린더 다이얼로그
# =================================================================

@st.dialog("📅 일정 상세", width="large")
def dialog_view_day(selected_date: str):
    can_edit = st.session_state.user_role in CALENDAR_EDIT_ROLES
    sch_df   = st.session_state.schedule_db
    day_data = sch_df[sch_df['날짜'] == selected_date] if not sch_df.empty else pd.DataFrame()

    # ── 수정 모드: 목록 숨기고 수정 폼만 전체 표시 ──────────────
    if st.session_state.get("cal_action_sub") == "edit":
        sub_id  = st.session_state.get("cal_action_sub_data")
        sub_row = sch_df[sch_df['id'] == sub_id]
        if not sub_row.empty:
            r2 = sub_row.iloc[0]
            st.markdown(f"### ✏️ 일정 수정  <span style='font-size:0.82rem; color:#8a7f72;'>{selected_date}</span>", unsafe_allow_html=True)
            cur_cat2 = r2.get('카테고리', '조립계획')
            cat_idx2 = PLAN_CATEGORIES.index(cur_cat2) if cur_cat2 in PLAN_CATEGORIES else 0
            with st.form("inline_edit_form"):
                cat2   = st.selectbox("계획 유형 *", PLAN_CATEGORIES, index=cat_idx2)
                ie1, ie2 = st.columns(2)
                model2 = ie1.text_input("모델명", value=str(r2.get('모델명', '')))
                pn2    = ie2.text_input("P/N",    value=str(r2.get('pn', '')))
                ig1, ig2 = st.columns(2)
                qty2   = ig1.number_input("조립수", min_value=0, step=1, value=int(r2.get('조립수', 0) or 0))
                ship2  = ig2.text_input("출하계획", value=str(r2.get('출하계획', '')))
                note2  = st.text_input("특이사항", value=str(r2.get('특이사항', '')))
                s1, s2, s3 = st.columns(3)
                if s1.form_submit_button("💾 저장", use_container_width=True, type="primary"):
                    update_schedule(sub_id, {
                        '카테고리': cat2, 'pn': pn2.strip(), '모델명': model2.strip(),
                        '조립수': int(qty2), '출하계획': ship2.strip(), '특이사항': note2.strip()
                    })
                    st.session_state.schedule_db    = load_schedule()
                    st.session_state.cal_action     = None
                    st.session_state.cal_action_sub = None
                    st.rerun()
                if s2.form_submit_button("🔙 목록으로", use_container_width=True):
                    st.session_state.cal_action_sub = None
                    st.rerun()
                if s3.form_submit_button("🗑️ 삭제", use_container_width=True):
                    delete_schedule(sub_id)
                    st.session_state.schedule_db    = load_schedule()
                    st.session_state.cal_action     = None
                    st.session_state.cal_action_sub = None
                    st.rerun()
        return  # 수정 폼 표시 중 목록/하단 버튼 완전히 숨김

    # ── 일반 목록 모드 ───────────────────────────────────────────
    st.markdown(f"### 📆 {selected_date}  <span style='font-size:0.85rem; color:#8a7f72; font-weight:normal;'>총 {len(day_data)}건</span>", unsafe_allow_html=True)

    if not day_data.empty:
        # 반별 색상
        BAN_COLORS = {"제조1반": "#2471a3", "제조2반": "#1e8449", "제조3반": "#6c3483"}

        # 제조1반 → 제조2반 → 제조3반 순서로 그룹핑
        for ban in PRODUCTION_GROUPS:
            ban_rows = day_data[day_data['반'] == ban]
            if ban_rows.empty:
                continue

            ban_color = BAN_COLORS.get(ban, "#7a6f65")
            ban_bg    = ban_color + "12"

            # 반 헤더
            st.markdown(
                f"<div style='background:{ban_bg}; border-left:4px solid {ban_color}; "
                f"padding:7px 14px; border-radius:5px; margin:12px 0 4px 0;'>"
                f"<span style='color:{ban_color}; font-weight:bold; font-size:0.92rem;'>🏭 {ban}</span>"
                f"<span style='color:#8a7f72; font-size:0.8rem; margin-left:8px;'>{len(ban_rows)}건</span>"
                f"</div>",
                unsafe_allow_html=True
            )

            # 표 헤더
            col_w = [1.8, 2.8, 1.5, 1.2, 1.8, 0.9] if can_edit else [1.8, 2.8, 1.5, 1.2, 2.2]
            hdrs  = ["카테고리", "모델명", "P/N", "조립수", "출하계획"] + (["관리"] if can_edit else [])
            hcols = st.columns(col_w)
            for hc, hl in zip(hcols, hdrs):
                hc.markdown(
                    f"<p style='color:#8a7f72; font-size:0.72rem; font-weight:bold; "
                    f"margin:0 0 2px 0; padding-bottom:3px; border-bottom:1px solid #e0d8c8;'>{hl}</p>",
                    unsafe_allow_html=True
                )

            # 행 데이터 (카테고리 정렬)
            for _, r in ban_rows.sort_values('카테고리').iterrows():
                row_id  = r.get('id', None)
                cat_v   = str(r.get('카테고리', '기타'))
                cat_color = SCHEDULE_COLORS.get(cat_v, "#888")
                model_v = str(r.get('모델명', ''))
                pn_v    = str(r.get('pn', ''))
                qty_v   = r.get('조립수', 0)
                ship_v  = str(r.get('출하계획', ''))
                note_v  = str(r.get('특이사항', ''))
                # HTML 특수문자 이스케이프
                def _esc(s): return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                model_v = _esc(model_v); pn_v = _esc(pn_v)
                ship_v  = _esc(ship_v);  note_v = _esc(note_v)
                try:
                    qty_v = int(float(qty_v)) if qty_v not in (None, '', 'nan') else 0
                except:
                    qty_v = 0
                qty_str  = f"{qty_v}대" if qty_v else "-"
                ship_str = ship_v if ship_v and ship_v != 'nan' else "-"
                note_str = f" ⚠️ {note_v}" if note_v and note_v not in ('', 'nan') else ""

                rcols = st.columns(col_w)
                rcols[0].markdown(
                    f"<span style='background:{cat_color}22; color:{cat_color}; font-weight:bold; "
                    f"font-size:0.72rem; padding:1px 6px; border-radius:8px;'>{cat_v}</span>",
                    unsafe_allow_html=True
                )
                rcols[1].markdown(f"<p style='font-size:0.78rem; margin:2px 0; color:#2a2420; font-weight:bold;'>{model_v}{note_str}</p>", unsafe_allow_html=True)
                rcols[2].markdown(f"<p style='font-size:0.75rem; margin:2px 0; color:#5a5048;'>{pn_v or '-'}</p>", unsafe_allow_html=True)
                rcols[3].markdown(f"<p style='font-size:0.78rem; margin:2px 0; color:#2471a3; font-weight:bold;'>{qty_str}</p>", unsafe_allow_html=True)
                rcols[4].markdown(f"<p style='font-size:0.75rem; margin:2px 0; color:#5a5048;'>{ship_str}</p>", unsafe_allow_html=True)

                if can_edit and row_id:
                    confirm_key = f"del_confirm_{row_id}"
                    if not st.session_state.get(confirm_key, False):
                        bc1, bc2 = rcols[5].columns(2)
                        if bc1.button("✏️", key=f"mod_{row_id}", help="수정"):
                            st.session_state.cal_action_sub      = "edit"
                            st.session_state.cal_action_sub_data = int(row_id)
                            st.rerun()
                        if bc2.button("🗑️", key=f"del_{row_id}", help="삭제"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    else:
                        st.warning(f"⚠️ [{model_v}] 일정을 삭제하시겠습니까?")
                        y1, y2 = st.columns(2)
                        if y1.button("✅ 예, 삭제", key=f"del_yes_{row_id}", type="primary", use_container_width=True):
                            delete_schedule(int(row_id))
                            st.session_state.schedule_db = load_schedule()
                            st.session_state[confirm_key] = False
                            st.session_state.cal_action   = None
                            st.rerun()
                        if y2.button("취소", key=f"del_no_{row_id}", use_container_width=True):
                            st.session_state[confirm_key] = False
                            st.rerun()
    else:
        st.info("등록된 일정이 없습니다.")

    st.divider()
    if can_edit:
        if st.button("➕ 이 날짜에 일정 추가", use_container_width=True, type="primary"):
            st.session_state.cal_action      = "add"
            st.session_state.cal_action_data = selected_date
            st.rerun()
    if st.button("닫기", use_container_width=True):
        st.session_state.cal_action = None
        st.rerun()

@st.dialog("📅 일정 추가")
def dialog_add_schedule(selected_date: str):
    can_edit = st.session_state.user_role in CALENDAR_EDIT_ROLES
    if not can_edit:
        st.warning("일정 추가 권한이 없습니다.")
        if st.button("닫기"): st.rerun()
        return

    st.markdown(f"**날짜: {selected_date}**")
    with st.form("add_sch_form"):
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
                    '카테고리': cat,
                    'pn': pn.strip(), '모델명': model.strip(),
                    '조립수': int(qty), '출하계획': ship.strip(),
                    '특이사항': note_combined, '작성자': st.session_state.user_id
                }):
                    st.session_state.schedule_db = load_schedule()
                    st.session_state.cal_action  = None
                    st.rerun()
            else:
                st.warning("모델명 또는 특이사항을 입력해주세요.")

@st.dialog("✏️ 일정 수정/삭제")
def dialog_edit_schedule(sch_id: int):
    can_edit = st.session_state.user_role in CALENDAR_EDIT_ROLES
    sch_df   = st.session_state.schedule_db
    matched  = sch_df[sch_df['id'] == sch_id]
    if matched.empty:
        st.warning("일정을 찾을 수 없습니다.")
        if st.button("닫기"): st.rerun()
        return

    r = matched.iloc[0]
    st.markdown(f"**날짜: {r.get('날짜','')}**")

    if not can_edit:
        st.info(f"카테고리: {r.get('카테고리','')} / 모델명: {r.get('모델명','')} / 조립수: {r.get('조립수',0)}대")
        if st.button("닫기"): st.rerun()
        return

    cur_cat = r.get('카테고리', '조립계획')
    # 기존 데이터가 특이사항/기타 카테고리였으면 조립계획으로 fallback
    cat_idx = PLAN_CATEGORIES.index(cur_cat) if cur_cat in PLAN_CATEGORIES else 0

    with st.form("edit_sch_form"):
        cat   = st.selectbox("계획 유형 *", PLAN_CATEGORIES, index=cat_idx)
        fe1, fe2 = st.columns(2)
        model = fe1.text_input("모델명",   value=str(r.get('모델명','')))
        pn    = fe2.text_input("P/N",      value=str(r.get('pn','')))
        ff1, ff2 = st.columns(2)
        qty   = ff1.number_input("조립수", min_value=0, step=1, value=int(r.get('조립수', 0) or 0))
        ship  = ff2.text_input("출하계획", value=str(r.get('출하계획','')))
        note  = st.text_input("특이사항", value=str(r.get('특이사항','')))
        etc   = st.text_input("기타")
        c1, c2 = st.columns(2)
        if c1.form_submit_button("💾 저장", use_container_width=True, type="primary"):
            note_combined = " / ".join(filter(None, [note.strip(), etc.strip()]))
            update_schedule(sch_id, {
                '카테고리': cat, 'pn': pn.strip(), '모델명': model.strip(),
                '조립수': int(qty), '출하계획': ship.strip(), '특이사항': note_combined
            })
            st.session_state.schedule_db = load_schedule()
            st.session_state.cal_action  = None
            st.rerun()
        if c2.form_submit_button("🗑️ 삭제", use_container_width=True):
            delete_schedule(sch_id)
            st.session_state.schedule_db = load_schedule()
            st.session_state.cal_action  = None
            st.rerun()
    # 폼 밖 닫기 버튼 - 누르면 cal_action 초기화 후 닫힘
    if st.button("✖ 닫기", key="edit_close_btn", use_container_width=True):
        st.session_state.cal_action      = None
        st.session_state.cal_action_data = None
        st.rerun()

# =================================================================
# 5. 세션 상태 초기화
# =================================================================

if 'schedule_db'     not in st.session_state: st.session_state.schedule_db     = load_schedule()
if 'production_db'   not in st.session_state: st.session_state.production_db   = load_realtime_ledger()
if 'cal_year'         not in st.session_state: st.session_state.cal_year         = datetime.now(KST).year
if 'cal_month'        not in st.session_state: st.session_state.cal_month        = datetime.now(KST).month
if 'cal_month_year'   not in st.session_state: st.session_state.cal_month_year   = datetime.now(KST).year
if 'cal_month_month'  not in st.session_state: st.session_state.cal_month_month  = datetime.now(KST).month
if 'cal_view'        not in st.session_state: st.session_state.cal_view        = "주별"
if 'cal_week_idx'    not in st.session_state: st.session_state.cal_week_idx    = 0
if 'cal_action'      not in st.session_state: st.session_state.cal_action      = None
if 'cal_action_data' not in st.session_state: st.session_state.cal_action_data = None
if 'cal_action_sub'      not in st.session_state: st.session_state.cal_action_sub      = None
if 'cal_action_sub_data' not in st.session_state: st.session_state.cal_action_sub_data = None

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin":         {"pw_hash": hash_pw("admin1234"),   "role": "admin"},
        "master":        {"pw_hash": hash_pw("master1234"),  "role": "master"},
        "control_tower": {"pw_hash": hash_pw("control1234"), "role": "control_tower"},
    }

if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조1반": ["NEW-101", "NEW-102"],
        "제조2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조3반": ["AION-X", "AION-Z"]
    }

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조1반": {"NEW-101": ["101-A"], "NEW-102": ["102-A"]},
        "제조2반": {
            "EPS7150": ["7150-A", "7150-B"],
            "EPS7133": ["7133-S", "7133-Standard"],
            "T20i":    ["T20i-P", "T20i-Premium"],
            "T20C":    ["T20C-S", "T20C-Standard"]
        },
        "제조3반": {"AION-X": ["AX-PRO"], "AION-Z": ["AZ-ULTRA"]}
    }

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
                user_info = st.session_state.user_db.get(in_id)
                if user_info and verify_pw(in_pw, user_info["pw_hash"]):
                    st.session_state.login_status  = True
                    st.session_state.user_id       = in_id
                    st.session_state.user_role     = user_info["role"]
                    st.session_state.production_db = load_realtime_ledger()
                    st.session_state.schedule_db   = load_schedule()
                    st.rerun()
                else:
                    st.error("로그인 정보가 올바르지 않습니다.")
    st.stop()

# =================================================================
# 7. 사이드바
# =================================================================

def clear_cal():
    st.session_state.cal_action      = None
    st.session_state.cal_action_data = None

st.sidebar.markdown("### 🏭 생산 관리 시스템 v22.3")
st.sidebar.markdown(f"**{ROLE_LABELS.get(st.session_state.user_role, '')}**")
st.sidebar.caption(f"ID: {st.session_state.user_id}")
st.sidebar.divider()

allowed_nav = ROLES.get(st.session_state.user_role, [])

if st.sidebar.button("🏠 메인 현황판", use_container_width=True,
    type="primary" if st.session_state.current_line == "현황판" else "secondary"):
    clear_cal()
    st.session_state.production_db = load_realtime_ledger()
    st.session_state.schedule_db   = load_schedule()
    st.session_state.current_line  = "현황판"
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

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for k in ['login_status','user_role','user_id','admin_authenticated']:
        st.session_state[k] = False if k == 'login_status' else None
    st.rerun()

# =================================================================
# 8. 입고 확인 다이얼로그
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    target_sn = st.session_state.get("confirm_target")
    if not target_sn:
        if st.button("닫기"): st.rerun()
        return
    st.warning(f"승인 대상 S/N: [ {target_sn} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        update_row(target_sn, {
            '시간': get_now_kst_str(), '라인': st.session_state.current_line,
            '상태': '진행 중', '작업자': st.session_state.user_id
        })
        st.session_state.production_db  = load_realtime_ledger()
        st.session_state.confirm_target = None
        st.rerun()
    if c_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

if st.session_state.get("confirm_target"):
    trigger_entry_dialog()

# 캘린더 다이얼로그
if st.session_state.cal_action == "view_day":
    dialog_view_day(st.session_state.cal_action_data)
elif st.session_state.cal_action == "add":
    dialog_add_schedule(st.session_state.cal_action_data)
elif st.session_state.cal_action == "edit":
    dialog_edit_schedule(st.session_state.cal_action_data)

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

                # 카테고리별 건수 집계
                cat_counts = {}
                event_count = 0
                if not day_data.empty:
                    for _, r in day_data.iterrows():
                        cat = str(r.get("카테고리","기타")) if r.get("카테고리") else "기타"
                        cat_counts[cat] = cat_counts.get(cat, 0) + 1
                        event_count += 1

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
def render_calendar_monthly():
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
                title="<b>반별 공정 진행 현황</b>", template="plotly_white"
            )
            fig.update_yaxes(dtick=1)
            fig.update_layout(margin=dict(t=40,b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02))
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
        재공 = len(gdf[gdf['상태']=='진행 중'])
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
    st.markdown(f"<div class='section-title'>📋 오늘({today_str}) {curr_g} 작업 일정</div>", unsafe_allow_html=True)

    if today_sch.empty:
        st.info("오늘 등록된 작업 일정이 없습니다.")
    else:
        for _, sr in today_sch.iterrows():
            cat   = str(sr.get('카테고리', '기타'))
            color = SCHEDULE_COLORS.get(cat, "#888")
            model = str(sr.get('모델명', ''))
            pn    = str(sr.get('pn', ''))
            qty   = sr.get('조립수', 0)
            try:
                qty = int(float(qty)) if qty not in (None, '', 'nan') else 0
            except:
                qty = 0
            ship  = str(sr.get('출하계획', ''))
            note  = str(sr.get('특이사항', ''))

            with st.container(border=True):
                ca, cb = st.columns([3, 1])
                with ca:
                    st.markdown(f"**{cat}** &nbsp; {model}" + (f" `{pn}`" if pn and pn != 'nan' else ""))
                with cb:
                    st.metric(label="조립수", value=f"{qty:,} 대")
                if ship and ship != 'nan':
                    st.caption(f"📦 출하계획: {ship}")
                if note and note != 'nan':
                    st.warning(f"⚠️ {note}", icon=None)

        # 일정 전체 보기 토글
        with st.expander(f"📅 {curr_g} 이번 달 전체 일정 보기"):
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

    with st.container(border=True):
        st.markdown(f"#### ➕ {curr_g} 신규 생산 등록")
        g_models     = st.session_state.group_master_models.get(curr_g, [])
        target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + g_models)
        with st.form("entry_gate_form"):
            f_c1, f_c2  = st.columns(2)
            g_items     = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
            target_item = f_c1.selectbox("품목 코드", g_items if target_model != "선택하세요." else ["모델 선택 대기"])
            target_sn   = f_c2.text_input("제품 시리얼(S/N) 입력")
            if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                if target_model != "선택하세요." and target_sn.strip():
                    if insert_row({
                        '시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인",
                        'cell': "", '모델': target_model, '품목코드': target_item,
                        '시리얼': target_sn.strip(), '상태': '진행 중',
                        '증상': '', '수리': '', '작업자': st.session_state.user_id
                    }):
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                else:
                    st.warning("모델과 시리얼을 모두 입력해주세요.")

    st.divider()
    db_v = st.session_state.production_db
    f_df = db_v[(db_v['반'] == curr_g) & (db_v['라인'] == "조립 라인")]

    # ── 모델/품목별 수량 카운트 ──────────────────────────────────
    if not f_df.empty:
        st.markdown(f"<div class='section-title'>📊 {curr_g} 조립 라인 수량 현황</div>", unsafe_allow_html=True)
        # 모델+품목 그룹핑
        grp = f_df.groupby(['모델','품목코드'])
        count_rows = []
        for (model, pn), gdf in grp:
            total    = len(gdf)
            done     = len(gdf[gdf['상태'] == '완료'])
            wip      = len(gdf[gdf['상태'].isin(['진행 중','수리 완료(재투입)'])])
            defect   = len(gdf[gdf['상태'].str.contains('불량', na=False)])
            count_rows.append((model, pn, total, done, wip, defect))

        # 카드 렌더링 (모델별)
        for (model, pn, total, done, wip, defect) in count_rows:
            pct     = int(done / total * 100) if total > 0 else 0
            with st.container(border=True):
                mc1, mc2 = st.columns([3, 1])
                mc1.markdown(f"**{model}**" + (f" `{pn}`" if pn else ""))
                mc2.markdown(f"완료율 **{pct}%**")
                # 진행바
                st.progress(min(pct, 100) / 100)
                # 수치
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("전체", total)
                sc2.metric("✅ 완료", done)
                sc3.metric("🏗️ 작업중", wip)
                sc4.metric("🚨 불량", defect, delta=None if defect == 0 else f"{defect}건", delta_color="inverse")

    # ── 생산 이력 테이블 ──────────────────────────────────────────
    if not f_df.empty:
        sc1, sc2 = st.columns([1, 1])
        sn_search = sc1.text_input("🔍 시리얼 검색", placeholder="S/N 일부 입력...", key=f"sn_search_{curr_g}")
        if sn_search.strip():
            f_df = f_df[f_df['시리얼'].str.contains(sn_search.strip(), case=False, na=False)]
        h = st.columns([2.2, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간","모델","품목","시리얼","현장 제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['모델'])
            r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    ck_ok = f"ck_ok_{idx}"; ck_ng = f"ck_ng_{idx}"
                    if not st.session_state.get(ck_ok) and not st.session_state.get(ck_ng):
                        b1, b2 = st.columns(2)
                        if b1.button("조립 완료", key=f"ok_{idx}"):
                            st.session_state[ck_ok] = True; st.rerun()
                        if b2.button("🚫불량", key=f"ng_{idx}"):
                            st.session_state[ck_ng] = True; st.rerun()
                    elif st.session_state.get(ck_ok):
                        st.warning(f"✅ [{row['시리얼']}] 조립 완료 처리하시겠습니까?")
                        y1, y2 = st.columns(2)
                        if y1.button("확인", key=f"ok_y_{idx}", type="primary", use_container_width=True):
                            update_row(row['시리얼'], {'상태':'완료','시간':get_now_kst_str()})
                            st.session_state.production_db = load_realtime_ledger()
                            st.session_state[ck_ok] = False; st.rerun()
                        if y2.button("취소", key=f"ok_n_{idx}", use_container_width=True):
                            st.session_state[ck_ok] = False; st.rerun()
                    elif st.session_state.get(ck_ng):
                        st.error(f"🚫 [{row['시리얼']}] 불량 처리하시겠습니까?")
                        y1, y2 = st.columns(2)
                        if y1.button("확인", key=f"ng_y_{idx}", type="primary", use_container_width=True):
                            update_row(row['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str()})
                            st.session_state.production_db = load_realtime_ledger()
                            st.session_state[ck_ng] = False; st.rerun()
                        if y2.button("취소", key=f"ng_n_{idx}", use_container_width=True):
                            st.session_state[ck_ng] = False; st.rerun()
                else:
                    if "불량" in str(row['상태']):
                        st.markdown(f"<div style='background:#fde8e7;color:#7a2e2a;padding:6px 12px;border-radius:8px;text-align:center;font-weight:bold;border:1px solid #e8908a;'>🚫 {row['상태']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='background:#d4f0e2;color:#1f6640;padding:6px 12px;border-radius:8px;text-align:center;font-weight:bold;border:1px solid #7ec8a0;'>✅ {row['상태']}</div>", unsafe_allow_html=True)
    else:
        st.info("등록된 생산 내역이 없습니다.")

# ── 검사 / 포장 라인 ─────────────────────────────────────────────
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l} 현황</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "검사 라인"

    db_s = st.session_state.production_db
    wait_list = db_s[(db_s['반']==curr_g)&(db_s['라인']==prev)&(db_s['상태']=="완료")]
    st.markdown(f"<div class='section-title'>📥 이전 공정({prev}) 완료 — 입고 대기</div>", unsafe_allow_html=True)
    if not wait_list.empty:
        # 모델/품목별 수량 카운트 (조립라인 수량현황 스타일)
        grp_w = wait_list.groupby(['모델','품목코드'])
        for (w_model, w_pn), w_gdf in grp_w:
            w_total = len(w_gdf)
            with st.container(border=True):
                wc1, wc2 = st.columns([3, 1])
                wc1.markdown(f"**{w_model}**" + (f" `{w_pn}`" if w_pn else ""))
                wc2.metric("대기 수량", f"{w_total}대")
                # 개별 시리얼 승인 버튼
                sn_cols = st.columns(min(4, w_total))
                for i, (idx, row) in enumerate(w_gdf.iterrows()):
                    if sn_cols[i % min(4, w_total)].button(f"📥 {row['시리얼']}", key=f"in_{idx}", use_container_width=True):
                        st.session_state.confirm_target = row['시리얼']; st.rerun()
    else:
        st.info("입고 대기 물량 없음")

    st.divider()
    f_df = db_s[(db_s['반']==curr_g)&(db_s['라인']==curr_l)]
    if not f_df.empty:
        h = st.columns([2.2, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간","모델","품목","시리얼","제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['모델'])
            r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    btn_lbl = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                    qck_ok = f"qck_ok_{idx}"; qck_ng = f"qck_ng_{idx}"
                    if not st.session_state.get(qck_ok) and not st.session_state.get(qck_ng):
                        c1, c2 = st.columns(2)
                        if c1.button(btn_lbl, key=f"ok_{idx}"):
                            st.session_state[qck_ok] = True; st.rerun()
                        if c2.button("🚫불량", key=f"ng_{idx}"):
                            st.session_state[qck_ng] = True; st.rerun()
                    elif st.session_state.get(qck_ok):
                        st.warning(f"✅ [{row['시리얼']}] {btn_lbl} 처리하시겠습니까?")
                        y1, y2 = st.columns(2)
                        if y1.button("확인", key=f"qok_y_{idx}", type="primary", use_container_width=True):
                            update_row(row['시리얼'], {'상태':'완료','시간':get_now_kst_str()})
                            st.session_state.production_db = load_realtime_ledger()
                            st.session_state[qck_ok] = False; st.rerun()
                        if y2.button("취소", key=f"qok_n_{idx}", use_container_width=True):
                            st.session_state[qck_ok] = False; st.rerun()
                    elif st.session_state.get(qck_ng):
                        st.error(f"🚫 [{row['시리얼']}] 불량 처리하시겠습니까?")
                        y1, y2 = st.columns(2)
                        if y1.button("확인", key=f"qng_y_{idx}", type="primary", use_container_width=True):
                            update_row(row['시리얼'], {'상태':'불량 처리 중','시간':get_now_kst_str()})
                            st.session_state.production_db = load_realtime_ledger()
                            st.session_state[qck_ng] = False; st.rerun()
                        if y2.button("취소", key=f"qng_n_{idx}", use_container_width=True):
                            st.session_state[qck_ng] = False; st.rerun()
                else:
                    if "불량" in str(row['상태']):
                        st.markdown(f"<div style='background:#fde8e7;color:#7a2e2a;padding:6px 12px;border-radius:8px;text-align:center;font-weight:bold;border:1px solid #e8908a;'>🚫 {row['상태']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='background:#d4f0e2;color:#1f6640;padding:6px 12px;border-radius:8px;text-align:center;font-weight:bold;border:1px solid #7ec8a0;'>✅ {row['상태']}</div>", unsafe_allow_html=True)
    else:
        st.info("해당 공정 내역이 없습니다.")

# ── 생산 현황 리포트 ─────────────────────────────────────────────
elif curr_l == "생산 현황 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    v_group = st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = st.session_state.production_db.copy()
    if v_group != "전체": df = df[df['반'] == v_group]

    if not df.empty:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("총 투입",      f"{len(df)} EA")
        c2.metric("최종 생산",    f"{len(df[(df['라인']=='포장 라인')&(df['상태']=='완료')])} EA")
        c3.metric("현재 작업 중", f"{len(df[df['상태']=='진행 중'])} EA")
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

    # 처리 대기 목록 (선택 반)
    has_any = False
    for g in target_groups:
        wait = db[(db['반']==g)&(db['상태']=="불량 처리 중")]
        if wait.empty: continue
        has_any = True
        st.markdown(f"#### 📍 {g} 불량 처리 대기")
        for idx, row in wait.iterrows():
            with st.container(border=True):
                st.markdown(f"모델: `{row['모델']}` &nbsp;|&nbsp; 코드: `{row['품목코드']}` &nbsp;|&nbsp; S/N: `{row['시리얼']}`")
                r1, r2 = st.columns(2)
                v_c = r1.text_input("불량 원인", key=f"c_{idx}")
                v_a = r2.text_input("수리 조치", key=f"a_{idx}")
                c_f, c_b = st.columns([3,1])
                img = c_f.file_uploader("사진 첨부", type=['jpg','png'], key=f"i_{idx}")
                c_b.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if c_b.button("확정", key=f"b_{idx}", type="primary"):
                    if v_c and v_a:
                        img_link = f" [사진: {upload_img_to_drive(img, row['시리얼'])}]" if img else ""
                        update_row(row['시리얼'], {
                            '상태': "수리 완료(재투입)", '시간': get_now_kst_str(),
                            '증상': v_c, '수리': v_a + img_link
                        })
                        st.session_state.production_db = load_realtime_ledger(); st.rerun()
                    else:
                        st.warning("불량 원인과 수리 조치 내용을 모두 입력해주세요.")
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
                            "제조2반": ["2026-03-05","조립계획","TMP6133002","S6133 GRIFFIN [13.3\"]","30","3/15 30" ,"정상",""],
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
                                    except:
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
                            if str(ban) == "제조2반" and str(model or "").startswith("S6133 GRIFFIN") and str(date_val) == "2026-03-05":
                                continue
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
                                for row in filtered:
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

        with sch_tab2:
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
                    ac1, ac2, ac3 = st.columns([2,1,1])
                    ac1.markdown("<p style='color:#c8605a; font-weight:bold; margin-top:8px;'>삭제 후 복구 불가</p>", unsafe_allow_html=True)
                    if ac2.button("✅ 예, 전체 삭제", type="primary", use_container_width=True, key="sch_all_del_yes"):
                        for _, row in sch_list.iterrows():
                            delete_schedule(int(row['id']))
                        st.session_state.schedule_db = load_schedule()
                        st.session_state[all_del_key] = False
                        st.success("전체 일정이 삭제되었습니다.")
                        st.rerun()
                    if ac3.button("취소", use_container_width=True, key="sch_all_del_no"):
                        st.session_state[all_del_key] = False
                        st.rerun()
                st.divider()
                for _, row in sch_list.sort_values('날짜').iterrows():
                    cat   = row.get('카테고리','기타')
                    color = SCHEDULE_COLORS.get(cat, "#888")
                    r1,r2,r3,r4,r5,r6,r7,r8 = st.columns([1.0,0.8,1.2,1.5,2,0.8,2,0.8])
                    r1.markdown(f"<span style='background:{color}22; border-left:3px solid {color}; padding:3px 6px; border-radius:4px; font-size:0.8rem;'>{cat}</span>", unsafe_allow_html=True)
                    r2.write(row.get('반',''))
                    r3.write(row.get('날짜',''))
                    r4.write(row.get('pn',''))
                    r5.write(row.get('모델명',''))
                    r6.write(f"{row.get('조립수',0)}대")
                    r7.write(row.get('특이사항',''))
                    row_id = row['id']
                    del_ck = f"sch_del_ck_{row_id}"
                    if not st.session_state.get(del_ck, False):
                        if r8.button("🗑️", key=f"del_sch_{row_id}", help="삭제"):
                            st.session_state[del_ck] = True
                            st.rerun()
                    else:
                        with r8:
                            st.warning("삭제?")
                            if st.button("✅", key=f"del_sch_yes_{row_id}"):
                                delete_schedule(int(row_id))
                                st.session_state.schedule_db = load_schedule()
                                st.session_state[del_ck] = False
                                st.rerun()
                            if st.button("✗", key=f"del_sch_no_{row_id}"):
                                st.session_state[del_ck] = False
                                st.rerun()
            else:
                st.info("등록된 일정이 없습니다.")

        st.divider()

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
            with st.form("user_mgmt"):
                st.markdown("<p style='color:#2a2420; font-weight:bold; margin-bottom:8px;'>👤 사용자 계정 생성/업데이트</p>", unsafe_allow_html=True)
                nu  = st.text_input("ID")
                np_ = st.text_input("PW", type="password")
                nr  = st.selectbox("Role", ["admin","master","control_tower","assembly_team","qc_team","packing_team","schedule_manager"])
                if st.form_submit_button("사용자 저장"):
                    if nu and np_:
                        st.session_state.user_db[nu] = {"pw_hash": hash_pw(np_), "role": nr}
                        st.success(f"계정 [{nu}] 저장 완료")
                    else: st.warning("ID와 PW를 모두 입력해주세요.")

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
