import streamlit as st
import pandas as pd
import plotly.express as px
import hashlib
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 (v21.0 - Supabase 버전)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v21.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]

ROLES = {
    "master":        ["조립 라인", "검사 라인", "포장 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리"],
    "control_tower": ["생산 현황 리포트", "수리 현황 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team":       ["검사 라인", "불량 공정"],
    "packing_team":  ["포장 라인"],
    "admin":         ["조립 라인", "검사 라인", "포장 라인", "생산 현황 리포트", "불량 공정", "수리 현황 리포트", "마스터 관리"]
}

ROLE_LABELS = {
    "master":        "👤 마스터 관리자",
    "admin":         "👤 관리자",
    "control_tower": "🗼 컨트롤 타워",
    "assembly_team": "🔧 조립 담당자",
    "qc_team":       "🔍 검사 담당자",
    "packing_team":  "📦 포장 담당자",
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; overflow-x: hidden; }
    .stButton button {
        display: flex; justify-content: center; align-items: center;
        margin-top: 1px; padding: 6px 10px; width: 100%; border-radius: 8px;
        font-weight: 600; white-space: nowrap !important; overflow: hidden;
        text-overflow: ellipsis; transition: all 0.2s ease;
    }
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
    .section-title {
        background-color: #f8f9fa; color: #111; padding: 16px 20px;
        border-radius: 10px; font-weight: bold; margin: 10px 0 25px 0;
        border-left: 10px solid #007bff; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-box {
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        background-color: #ffffff; border-radius: 12px; padding: 16px 8px;
        border: 1px solid #e9ecef; margin-bottom: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        width: 100%; box-sizing: border-box; overflow: hidden; word-break: keep-all;
    }
    .stat-label {
        font-size: clamp(0.6rem, 1.2vw, 0.9rem); color: #6c757d;
        font-weight: bold; margin-bottom: 8px;
        writing-mode: horizontal-tb !important; white-space: nowrap;
    }
    .stat-value {
        font-size: clamp(1rem, 2vw, 2.4rem); color: #007bff;
        font-weight: bold; line-height: 1;
        writing-mode: horizontal-tb !important; white-space: nowrap;
    }
    .button-spacer { margin-top: 28px; }
    .status-red { color: #fa5252; font-weight: bold; }
    .status-green { color: #40c057; font-weight: bold; }
    .alarm-banner {
        background-color: #fff5f5; color: #c92a2a; padding: 18px; border-radius: 12px;
        border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 25px;
        text-align: center; box-shadow: 0 2px 10px rgba(201, 42, 42, 0.1);
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
    url  = st.secrets["supabase"]["url"]
    key  = st.secrets["supabase"]["key"]
    return create_client(url, key)

def keep_supabase_alive():
    """
    Supabase 무료 플랜 7일 자동 일시정지 방지
    앱 실행 시마다 가벼운 쿼리를 보내 활성 상태 유지
    """
    try:
        sb = get_supabase()
        sb.table("production").select("id").limit(1).execute()
    except:
        pass

# 앱 실행 시마다 활성화 유지
keep_supabase_alive()

def get_now_kst_str() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_realtime_ledger() -> pd.DataFrame:
    """Supabase에서 전체 생산 데이터 로드"""
    try:
        sb = get_supabase()
        res = sb.table("production").select("*").order("created_at", desc=False).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            # 불필요한 컬럼 제거
            drop_cols = [c for c in ['id', 'created_at'] if c in df.columns]
            df = df.drop(columns=drop_cols)
            df = df.fillna("")
            return df
        return pd.DataFrame(
            columns=['시간','반','라인','cell','모델','품목코드','시리얼','상태','증상','수리','작업자']
        )
    except Exception as e:
        st.warning(f"데이터 로드 실패: {e}")
        return pd.DataFrame(
            columns=['시간','반','라인','cell','모델','품목코드','시리얼','상태','증상','수리','작업자']
        )

def insert_row(row: dict) -> bool:
    """새 행 삽입 (시리얼 중복 시 실패)"""
    try:
        sb = get_supabase()
        sb.table("production").insert(row).execute()
        return True
    except Exception as e:
        st.error(f"등록 실패: {e}")
        return False

def update_row(시리얼: str, update_data: dict) -> bool:
    """시리얼 기준으로 행 업데이트"""
    try:
        sb = get_supabase()
        sb.table("production").update(update_data).eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"업데이트 실패: {e}")
        return False

def delete_all_rows() -> bool:
    """전체 데이터 삭제"""
    try:
        sb = get_supabase()
        sb.table("production").delete().neq("시리얼", "IMPOSSIBLE_VALUE_XYZ").execute()
        return True
    except Exception as e:
        st.error(f"초기화 실패: {e}")
        return False

def upload_img_to_drive(file_obj, serial_no: str) -> str:
    try:
        gcp_info = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded = drive_svc.files().create(
            body=meta_data, media_body=media, fields='id, webViewLink'
        ).execute()
        return uploaded.get('webViewLink', "")
    except Exception as err:
        return f"⚠️ 이미지 업로드 실패: {str(err)}"

# =================================================================
# 4. 세션 상태 초기화
# =================================================================

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_realtime_ledger()

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

if 'login_status'        not in st.session_state: st.session_state.login_status        = False
if 'user_role'           not in st.session_state: st.session_state.user_role           = None
if 'user_id'             not in st.session_state: st.session_state.user_id             = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'selected_group'      not in st.session_state: st.session_state.selected_group      = "제조2반"
if 'current_line'        not in st.session_state: st.session_state.current_line        = "현황판"
if 'selected_cell'       not in st.session_state: st.session_state.selected_cell       = "CELL 1"
if 'confirm_target'      not in st.session_state: st.session_state.confirm_target      = None

# =================================================================
# 5. 로그인
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
                    st.session_state.login_status = True
                    st.session_state.user_id      = in_id
                    st.session_state.user_role    = user_info["role"]
                    st.session_state.production_db = load_realtime_ledger()
                    st.rerun()
                else:
                    st.error("로그인 정보가 올바르지 않습니다.")
    st.stop()

# =================================================================
# 6. 사이드바 내비게이션
# =================================================================

st.sidebar.markdown("### 🏭 생산 관리 시스템 v21.0")
role_label = ROLE_LABELS.get(st.session_state.user_role, st.session_state.user_role)
st.sidebar.markdown(f"**{role_label}**")
st.sidebar.caption(f"ID: {st.session_state.user_id}")

st.sidebar.divider()
allowed_nav = ROLES.get(st.session_state.user_role, [])

if st.sidebar.button(
    "🏠 메인 현황판", use_container_width=True,
    type="primary" if st.session_state.current_line == "현황판" else "secondary"
):
    st.session_state.production_db = load_realtime_ledger()
    st.session_state.current_line = "현황판"
    st.rerun()

st.sidebar.divider()

for group in PRODUCTION_GROUPS:
    exp = (
        st.session_state.selected_group == group
        and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"]
    )
    with st.sidebar.expander(f"📍 {group}", expanded=exp):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in allowed_nav:
                active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(
                    f"{p} 현황", key=f"nav_{group}_{p}",
                    use_container_width=True,
                    type="primary" if active else "secondary"
                ):
                    st.session_state.selected_group = group
                    st.session_state.current_line   = p
                    st.session_state.production_db  = load_realtime_ledger()
                    st.rerun()
        if group == PRODUCTION_GROUPS[-1] and "불량 공정" in allowed_nav:
            if st.sidebar.button(
                "🚫 불량 공정", key="nav_defect",
                use_container_width=True,
                type="primary" if st.session_state.current_line == "불량 공정" else "secondary"
            ):
                st.session_state.current_line  = "불량 공정"
                st.session_state.production_db = load_realtime_ledger()
                st.rerun()

st.sidebar.divider()

for p in ["생산 현황 리포트", "수리 현황 리포트"]:
    if p in allowed_nav:
        if st.sidebar.button(
            p, key=f"fnav_{p}", use_container_width=True,
            type="primary" if st.session_state.current_line == p else "secondary"
        ):
            st.session_state.current_line  = p
            st.session_state.production_db = load_realtime_ledger()
            st.rerun()

if "마스터 관리" in allowed_nav:
    st.sidebar.divider()
    if st.sidebar.button(
        "🔐 마스터 데이터 관리", use_container_width=True,
        type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"
    ):
        st.session_state.current_line = "마스터 관리"
        st.rerun()

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for key in ['login_status', 'user_role', 'user_id', 'admin_authenticated']:
        st.session_state[key] = False if key == 'login_status' else None
    st.rerun()

# =================================================================
# 7. 입고 확인 다이얼로그
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    target_sn = st.session_state.get("confirm_target")
    if not target_sn:
        st.warning("대상 시리얼 정보가 없습니다.")
        if st.button("닫기"):
            st.rerun()
        return
    st.warning(f"승인 대상 S/N: [ {target_sn} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        success = update_row(target_sn, {
            '시간':   get_now_kst_str(),
            '라인':   st.session_state.current_line,
            '상태':   '진행 중',
            '작업자': st.session_state.user_id
        })
        if success:
            st.session_state.production_db = load_realtime_ledger()
            st.success("입고 승인 완료!")
        st.session_state.confirm_target = None
        st.rerun()
    if c_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

if st.session_state.get("confirm_target"):
    trigger_entry_dialog()

# =================================================================
# 8. 페이지별 렌더링
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# ─────────────────────────────────────────────
# 8-0. 메인 현황판
# ─────────────────────────────────────────────
if curr_l == "현황판":
    st.markdown("<h2 class='centered-title'>🏭 생산 통합 현황판</h2>", unsafe_allow_html=True)
    st.caption(f"🕐 마지막 업데이트: {get_now_kst_str()}")

    db_all = st.session_state.production_db

    # 전체 요약 카드
    st.markdown("<div class='section-title'>📊 전체 반 생산 요약</div>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(
        f"<div class='stat-box'><div class='stat-label'>📦 총 투입</div>"
        f"<div class='stat-value'>{len(db_all)}</div></div>", unsafe_allow_html=True)
    col2.markdown(
        f"<div class='stat-box'><div class='stat-label'>✅ 최종 완료</div>"
        f"<div class='stat-value'>{len(db_all[(db_all['라인']=='포장 라인') & (db_all['상태']=='완료')])}</div></div>", unsafe_allow_html=True)
    col3.markdown(
        f"<div class='stat-box'><div class='stat-label'>🏗️ 작업 중</div>"
        f"<div class='stat-value'>{len(db_all[db_all['상태']=='진행 중'])}</div></div>", unsafe_allow_html=True)
    col4.markdown(
        f"<div class='stat-box'><div class='stat-label'>🚨 불량 이슈</div>"
        f"<div class='stat-value'>{len(db_all[db_all['상태'].str.contains('불량', na=False)])}</div></div>", unsafe_allow_html=True)

    st.divider()

    # 실시간 차트
    if not db_all.empty:
        st.markdown("<div class='section-title'>📈 실시간 차트</div>", unsafe_allow_html=True)
        ch1, ch2 = st.columns([1.8, 1.2])
        with ch1:
            fig = px.bar(
                db_all.groupby(['반', '라인']).size().reset_index(name='수량'),
                x='라인', y='수량', color='반', barmode='group',
                title="<b>반별 공정 진행 현황</b>", template="plotly_white"
            )
            fig.update_yaxes(dtick=1)
            st.plotly_chart(fig, use_container_width=True, key="dashboard_bar")
        with ch2:
            fig2 = px.pie(
                db_all.groupby('상태').size().reset_index(name='수량'),
                values='수량', names='상태', hole=0.5,
                title="<b>전체 상태 비중</b>"
            )
            st.plotly_chart(fig2, use_container_width=True, key="dashboard_pie")

    st.divider()

    # 반별 현황 카드
    st.markdown("<div class='section-title'>🏭 반별 생산 현황</div>", unsafe_allow_html=True)
    cards_html = "<div style=\"display:flex; gap:12px; width:100%; box-sizing:border-box;\">"
    for g in PRODUCTION_GROUPS:
        gdf = db_all[db_all['반'] == g]
        완료 = len(gdf[(gdf['라인']=='포장 라인') & (gdf['상태']=='완료')])
        재공 = len(gdf[gdf['상태']=='진행 중'])
        불량 = len(gdf[gdf['상태'].str.contains('불량', na=False)])
        투입 = len(gdf)
        cards_html += (
            f"<div style=\"flex:1; background:#1e1e1e; border:1px solid #333; border-radius:14px; padding:16px; box-sizing:border-box; min-width:0;\">"
            f"<div style=\"font-size:clamp(0.9rem, 1.5vw, 1.1rem); font-weight:bold; margin-bottom:12px; color:#fff;\">📍 {g}</div>"
            f"<div style=\"background:#2a2a2a; border-radius:10px; padding:12px; text-align:center; margin-bottom:10px;\">"
            f"<div style=\"font-size:clamp(0.6rem, 1vw, 0.8rem); color:#aaa; font-weight:bold; margin-bottom:4px;\">총 투입</div>"
            f"<div style=\"font-size:clamp(1.2rem, 2.5vw, 2rem); color:#4dabf7; font-weight:bold;\">{투입} EA</div>"
            f"</div>"
            f"<div style=\"display:flex; gap:6px;\">"
            f"<div style=\"flex:1; background:#2a2a2a; border-radius:10px; padding:10px 4px; text-align:center; min-width:0;\">"
            f"<div style=\"font-size:clamp(0.5rem, 0.9vw, 0.72rem); color:#aaa; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;\">✅ 완료</div>"
            f"<div style=\"font-size:clamp(1rem, 2vw, 1.6rem); color:#40c057; font-weight:bold;\">{완료}</div>"
            f"</div>"
            f"<div style=\"flex:1; background:#2a2a2a; border-radius:10px; padding:10px 4px; text-align:center; min-width:0;\">"
            f"<div style=\"font-size:clamp(0.5rem, 0.9vw, 0.72rem); color:#aaa; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;\">🏗️ 작업중</div>"
            f"<div style=\"font-size:clamp(1rem, 2vw, 1.6rem); color:#4dabf7; font-weight:bold;\">{재공}</div>"
            f"</div>"
            f"<div style=\"flex:1; background:#2a2a2a; border-radius:10px; padding:10px 4px; text-align:center; min-width:0;\">"
            f"<div style=\"font-size:clamp(0.5rem, 0.9vw, 0.72rem); color:#aaa; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;\">🚨 불량</div>"
            f"<div style=\"font-size:clamp(1rem, 2vw, 1.6rem); color:#fa5252; font-weight:bold;\">{불량}</div>"
            f"</div>"
            f"</div>"
            f"</div>"
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)

    if db_all.empty:
        st.info("등록된 생산 데이터가 없습니다.")

# ─────────────────────────────────────────────
# 8-1. 조립 라인
# ─────────────────────────────────────────────
elif curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 신규 조립 현황</h2>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(f"#### ➕ {curr_g} 신규 생산 등록")
        g_models = st.session_state.group_master_models.get(curr_g, [])
        target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + g_models)
        with st.form("entry_gate_form"):
            f_c1, f_c2 = st.columns(2)
            g_items = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
            target_item = f_c1.selectbox(
                "품목 코드",
                g_items if target_model != "선택하세요." else ["모델 선택 대기"]
            )
            target_sn = f_c2.text_input("제품 시리얼(S/N) 입력")
            if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                if target_model != "선택하세요." and target_sn.strip():
                    new_row = {
                        '시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인",
                        'cell': "", '모델': target_model, '품목코드': target_item,
                        '시리얼': target_sn.strip(), '상태': '진행 중',
                        '증상': '', '수리': '', '작업자': st.session_state.user_id
                    }
                    if insert_row(new_row):
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                else:
                    st.warning("모델과 시리얼을 모두 입력해주세요.")

    st.divider()
    db_v = st.session_state.production_db
    f_df = db_v[(db_v['반'] == curr_g) & (db_v['라인'] == "조립 라인")]

    if not f_df.empty:
        h = st.columns([2.2, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "모델", "품목", "시리얼", "현장 제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간'])
            r[1].write(row['모델']); r[2].write(row['품목코드'])
            r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("조립 완료", key=f"ok_{idx}"):
                        update_row(row['시리얼'], {'상태': '완료', '시간': get_now_kst_str()})
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                    if b2.button("🚫불량", key=f"ng_{idx}"):
                        update_row(row['시리얼'], {'상태': '불량 처리 중', '시간': get_now_kst_str()})
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                else:
                    if "불량" in str(row['상태']):
                        st.markdown(f"<div style='background:#fa5252; color:white; padding:6px 12px; border-radius:8px; text-align:center; font-weight:bold;'>🚫 {row['상태']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='background:#40c057; color:white; padding:6px 12px; border-radius:8px; text-align:center; font-weight:bold;'>✅ {row['상태']}</div>", unsafe_allow_html=True)
    else:
        st.info("등록된 생산 내역이 없습니다.")

# ─────────────────────────────────────────────
# 8-2. 검사 / 포장 라인
# ─────────────────────────────────────────────
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l} 현황</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "검사 라인"

    with st.container(border=True):
        st.markdown(f"#### 📥 이전 공정({prev}) 완료 입고 대기")
        db_s = st.session_state.production_db
        wait_list = db_s[
            (db_s['반'] == curr_g) & (db_s['라인'] == prev) & (db_s['상태'] == "완료")
        ]
        if not wait_list.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_list.iterrows()):
                if w_cols[i % 4].button(f"승인: {row['시리얼']}", key=f"in_{idx}"):
                    st.session_state.confirm_target = row['시리얼']
                    st.rerun()
        else:
            st.info("입고 대기 물량 없음")

    st.divider()
    f_df = db_s[(db_s['반'] == curr_g) & (db_s['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([2.2, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "모델", "품목", "시리얼", "제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간'])
            r[1].write(row['모델']); r[2].write(row['품목코드'])
            r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                    if c1.button(btn, key=f"ok_{idx}"):
                        update_row(row['시리얼'], {'상태': '완료', '시간': get_now_kst_str()})
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"):
                        update_row(row['시리얼'], {'상태': '불량 처리 중', '시간': get_now_kst_str()})
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                else:
                    if "불량" in str(row['상태']):
                        st.markdown(f"<div style='background:#fa5252; color:white; padding:6px 12px; border-radius:8px; text-align:center; font-weight:bold;'>🚫 {row['상태']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='background:#40c057; color:white; padding:6px 12px; border-radius:8px; text-align:center; font-weight:bold;'>✅ {row['상태']}</div>", unsafe_allow_html=True)
    else:
        st.info("해당 공정 내역이 없습니다.")

# ─────────────────────────────────────────────
# 8-3. 생산 현황 리포트
# ─────────────────────────────────────────────
elif curr_l == "생산 현황 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    v_group = st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = st.session_state.production_db.copy()
    if v_group != "전체":
        df = df[df['반'] == v_group]

    if not df.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투입",      f"{len(df)} EA")
        c2.metric("최종 생산",    f"{len(df[(df['라인']=='포장 라인') & (df['상태']=='완료')])} EA")
        c3.metric("현재 작업 중", f"{len(df[df['상태']=='진행 중'])} EA")
        c4.metric("품질 이슈",    f"{len(df[df['상태'].str.contains('불량', na=False)])} 건")

        st.divider()
        cl, cr = st.columns([1.8, 1.2])
        with cl:
            fig_b = px.bar(
                df.groupby('라인').size().reset_index(name='수량'),
                x='라인', y='수량', color='라인',
                title="<b>[공정 단계별 제품 분포 현황]</b>", template="plotly_white"
            )
            fig_b.update_yaxes(dtick=1)
            st.plotly_chart(fig_b, use_container_width=True)
        with cr:
            fig_p = px.pie(
                df.groupby('모델').size().reset_index(name='수량'),
                values='수량', names='모델', hole=0.5,
                title="<b>[생산 모델별 비중]</b>"
            )
            st.plotly_chart(fig_p, use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회 가능한 데이터가 없습니다.")

# ─────────────────────────────────────────────
# 8-4. 불량 분석 및 수리 조치
# ─────────────────────────────────────────────
elif curr_l == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    wait = db[(db['반'] == curr_g) & (db['상태'] == "불량 처리 중")]

    k1, k2 = st.columns(2)
    k1.markdown(
        f"<div class='stat-box'><div class='stat-label'>🛠️ {curr_g} 분석 대기</div>"
        f"<div class='stat-value'>{len(wait)}</div></div>", unsafe_allow_html=True)
    k2.markdown(
        f"<div class='stat-box'><div class='stat-label'>✅ {curr_g} 조치 완료</div>"
        f"<div class='stat-value'>{len(db[(db['반']==curr_g) & (db['상태']=='수리 완료(재투입)')])}</div></div>",
        unsafe_allow_html=True)

    if wait.empty:
        st.success("현재 처리 대기 중인 불량 이슈가 없습니다.")
    else:
        for idx, row in wait.iterrows():
            with st.container(border=True):
                st.markdown(
                    f"모델: `{row['모델']}` &nbsp;|&nbsp; "
                    f"코드: `{row['품목코드']}` &nbsp;|&nbsp; "
                    f"S/N: `{row['시리얼']}`"
                )
                r1, r2 = st.columns(2)
                v_c = r1.text_input("불량 원인", key=f"c_{idx}")
                v_a = r2.text_input("수리 조치", key=f"a_{idx}")
                c_f, c_b = st.columns([3, 1])
                img = c_f.file_uploader("사진 첨부", type=['jpg', 'png'], key=f"i_{idx}")
                c_b.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if c_b.button("확정", key=f"b_{idx}", type="primary"):
                    if v_c and v_a:
                        img_link = ""
                        if img:
                            img_link = f" [사진: {upload_img_to_drive(img, row['시리얼'])}]"
                        update_row(row['시리얼'], {
                            '상태': "수리 완료(재투입)",
                            '시간': get_now_kst_str(),
                            '증상': v_c,
                            '수리': v_a + img_link
                        })
                        st.session_state.production_db = load_realtime_ledger()
                        st.rerun()
                    else:
                        st.warning("불량 원인과 수리 조치 내용을 모두 입력해주세요.")

# ─────────────────────────────────────────────
# 8-5. 수리 현황 리포트
# ─────────────────────────────────────────────
elif curr_l == "수리 현황 리포트":
    st.markdown("<h2 class='centered-title'>📈 품질 분석 및 수리 이력 리포트</h2>", unsafe_allow_html=True)
    db_hist = st.session_state.production_db
    hist_df = db_hist[db_hist['수리'].astype(str).str.strip() != ""]

    if not hist_df.empty:
        c_l, c_r = st.columns([1.8, 1.2])
        with c_l:
            fig_hb = px.bar(
                hist_df.groupby('라인').size().reset_index(name='수량'),
                x='라인', y='수량', title="공정별 이슈 빈도"
            )
            st.plotly_chart(fig_hb, use_container_width=True)
        with c_r:
            fig_hp = px.pie(
                hist_df.groupby('모델').size().reset_index(name='수량'),
                values='수량', names='모델', hole=0.4, title="모델별 불량 비중"
            )
            st.plotly_chart(fig_hp, use_container_width=True)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else:
        st.info("기록된 이슈 내역이 없습니다.")

# ─────────────────────────────────────────────
# 8-6. 마스터 관리
# ─────────────────────────────────────────────
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        with st.form("admin_verify"):
            pw = st.text_input("마스터 비밀번호", type="password")
            if st.form_submit_button("인증"):
                master_hash = get_master_pw_hash()
                if master_hash is None:
                    st.error("마스터 비밀번호가 설정되지 않았습니다.")
                elif verify_pw(pw, master_hash):
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
    else:
        st.markdown("<div class='section-title'>📋 반별 독립 모델/품목 설정</div>", unsafe_allow_html=True)
        tabs = st.tabs([f"{g} 설정" for g in PRODUCTION_GROUPS])

        for i, g_name in enumerate(PRODUCTION_GROUPS):
            with tabs[i]:
                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        st.subheader("신규 모델 대량 등록")
                        st.caption("여러 모델은 줄바꿈(Enter)으로 구분해서 입력하세요.")
                        nm_bulk = st.text_area(f"{g_name} 모델명", key=f"nm_{g_name}", height=150,
                                               placeholder="예시:\nEPS7150\nEPS7133\nT20i")
                        if st.button(f"{g_name} 모델 저장", key=f"nb_{g_name}"):
                            if nm_bulk.strip():
                                nm_list = [x.strip() for x in nm_bulk.strip().splitlines() if x.strip()]
                                added, skipped = [], []
                                for nm in nm_list:
                                    if nm not in st.session_state.group_master_models.get(g_name, []):
                                        st.session_state.group_master_models[g_name].append(nm)
                                        st.session_state.group_master_items[g_name][nm] = []
                                        added.append(nm)
                                    else:
                                        skipped.append(nm)
                                if added:
                                    st.success(f"등록 완료: {', '.join(added)}")
                                if skipped:
                                    st.warning(f"이미 존재: {', '.join(skipped)}")
                                st.rerun()
                            else:
                                st.warning("모델명을 입력해주세요.")
                with c2:
                    with st.container(border=True):
                        st.subheader("세부 품목 대량 등록")
                        g_mods = st.session_state.group_master_models.get(g_name, [])
                        if g_mods:
                            sm = st.selectbox(f"{g_name} 모델 선택", g_mods, key=f"sm_{g_name}")
                            st.caption("여러 품목은 줄바꿈(Enter)으로 구분해서 입력하세요.")
                            ni_bulk = st.text_area(f"[{sm}] 품목코드", key=f"ni_{g_name}", height=150,
                                                   placeholder="예시:\n7150-A\n7150-B\n7150-C")
                            if st.button(f"{g_name} 품목 저장", key=f"ib_{g_name}"):
                                if ni_bulk.strip():
                                    ni_list = [x.strip() for x in ni_bulk.strip().splitlines() if x.strip()]
                                    current_items = st.session_state.group_master_items[g_name].get(sm, [])
                                    added, skipped = [], []
                                    for ni in ni_list:
                                        if ni not in current_items:
                                            st.session_state.group_master_items[g_name][sm].append(ni)
                                            added.append(ni)
                                        else:
                                            skipped.append(ni)
                                    if added:
                                        st.success(f"등록 완료: {', '.join(added)}")
                                    if skipped:
                                        st.warning(f"이미 존재: {', '.join(skipped)}")
                                    st.rerun()
                                else:
                                    st.warning("품목코드를 입력해주세요.")
                        else:
                            st.warning("등록된 모델이 없습니다. 왼쪽에서 모델을 먼저 등록하세요.")

        st.divider()
        st.subheader("계정 및 데이터 관리")
        ac1, ac2 = st.columns(2)

        with ac1:
            with st.form("user_mgmt"):
                st.write("**사용자 계정 생성/업데이트**")
                nu  = st.text_input("ID")
                np_ = st.text_input("PW", type="password")
                nr  = st.selectbox(
                    "Role",
                    ["admin", "master", "control_tower", "assembly_team", "qc_team", "packing_team"]
                )
                if st.form_submit_button("사용자 저장"):
                    if nu and np_:
                        st.session_state.user_db[nu] = {"pw_hash": hash_pw(np_), "role": nr}
                        st.success(f"계정 [{nu}] 저장 완료 (role: {nr})")
                    else:
                        st.warning("ID와 PW를 모두 입력해주세요.")

        with ac2:
            st.write("**시스템 데이터 관리**")
            
            db_export = st.session_state.production_db.copy()
            
            # 반 필터
            export_group = st.selectbox(
                "반 선택", ["전체"] + PRODUCTION_GROUPS, key="export_group"
            )
            
            # 날짜 필터
            ex_c1, ex_c2 = st.columns(2)
            start_date = ex_c1.date_input("시작 날짜", key="export_start")
            end_date   = ex_c2.date_input("종료 날짜", key="export_end")
            
            # 필터 적용
            if export_group != "전체":
                db_export = db_export[db_export['반'] == export_group]
            
            if '시간' in db_export.columns and not db_export.empty:
                try:
                    db_export['시간_dt'] = pd.to_datetime(db_export['시간'])
                    db_export = db_export[
                        (db_export['시간_dt'].dt.date >= start_date) &
                        (db_export['시간_dt'].dt.date <= end_date)
                    ]
                    db_export = db_export.drop(columns=['시간_dt'])
                except:
                    pass
            
            st.caption(f"📋 조회 결과: **{len(db_export)}건**")
            
            csv_data = db_export.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 CSV 다운로드", csv_data,
                f"PMS_{export_group}_{start_date}~{end_date}.csv",
                use_container_width=True
            )

            # 엑셀 다운로드
            import io
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                db_export.to_excel(writer, index=False, sheet_name='생산데이터')
            excel_data = excel_buffer.getvalue()
            st.download_button(
                "📊 Excel 다운로드", excel_data,
                f"PMS_{export_group}_{start_date}~{end_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        st.divider()
        if st.button("⚠️ 전체 데이터 초기화", type="secondary"):
            if delete_all_rows():
                st.session_state.production_db = load_realtime_ledger()
                st.success("전체 데이터가 초기화되었습니다.")
                st.rerun()

# =================================================================
# [ PMS v21.0 Supabase 버전 종료 ]
# =================================================================






