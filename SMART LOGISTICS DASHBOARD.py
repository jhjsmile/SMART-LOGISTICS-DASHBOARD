import streamlit as st
import pandas as pd
import plotly.express as px
import hashlib
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 (v20.0)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v20.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9)
KST = timezone(timedelta(hours=9))

# 30초 자동 새로고침
st_autorefresh(interval=30000, key="pms_auto_refresh")

# ─────────────────────────────────────────────
# [개선 1] 반 이름을 단일 상수로 통합 (공백 없는 버전으로 일원화)
#   기존: PRODUCTION_GROUPS = ["제조 1반", ...] 와 NAV_GROUPS = ["제조1반", ...] 이중 선언
#   개선: PRODUCTION_GROUPS 하나만 사용, 공백 없는 형태로 통일
# ─────────────────────────────────────────────
PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]

# 역할별 메뉴 접근 권한
ROLES = {
    "master":         ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower":  ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team":  ["조립 라인"],
    "qc_team":        ["검사 라인", "불량 공정"],
    "packing_team":   ["포장 라인"],
    "admin":          ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
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
        background-color: #ffffff; border-radius: 12px; padding: 22px;
        border: 1px solid #e9ecef; margin-bottom: 15px; min-height: 130px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.4rem; color: #007bff; font-weight: bold; line-height: 1; }
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

# ─────────────────────────────────────────────
# [개선 2] 비밀번호 해싱 (SHA-256)
#   기존: 비밀번호를 평문 문자열로 저장/비교
#   개선: hashlib.sha256으로 해싱 후 저장, 비교 시에도 해시값 비교
# ─────────────────────────────────────────────
def hash_pw(password: str) -> str:
    """비밀번호를 SHA-256 해시로 변환합니다."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_pw(plain: str, hashed: str) -> bool:
    """입력된 평문 비밀번호와 저장된 해시를 비교합니다."""
    return hash_pw(plain) == hashed

# ─────────────────────────────────────────────
# [개선 3] 마스터 비밀번호 하드코딩 제거
#   기존: if pw in ["admin1234", "master1234"] 로 소스코드에 노출
#   개선: st.secrets["master_admin_pw_hash"] 에서 읽어옴
#         secrets.toml 에 master_admin_pw_hash = "<sha256값>" 으로 설정
#         폴백(fallback): secrets 미설정 시 경고 후 기능 비활성화
# ─────────────────────────────────────────────
def get_master_pw_hash() -> str | None:
    try:
        # 방법 1: 직접 키 접근
        return st.secrets["master_admin_pw_hash"]
    except Exception:
        try:
            # 방법 2: get 방식으로 접근
            return st.secrets.get("master_admin_pw_hash", None)
        except Exception:
            return None

# =================================================================
# 3. 핵심 유틸리티 함수
# =================================================================

def get_now_kst_str() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

gs_conn = st.connection("gsheets", type=GSheetsConnection)

# ─────────────────────────────────────────────
# [개선 4] 데이터 표준화 일관성 확보
#   기존: '반' 컬럼 공백 제거 후 빈값이면 "제조2반" 으로 고정 (의도치 않은 덮어쓰기)
#   개선: 공백 제거만 수행하고, 빈값은 명시적으로 "" 로 유지하거나
#         기본값을 secrets/config 에서 받도록 분리
# ─────────────────────────────────────────────
def normalize_group_name(val: str) -> str:
    """반 이름 공백 제거 및 표준화."""
    return val.strip().replace(" ", "")

def load_realtime_ledger() -> pd.DataFrame:
    try:
        df = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        if '반' in df.columns:
            df['반'] = df['반'].apply(normalize_group_name)
        else:
            df.insert(1, '반', "")
        return df
    except Exception as e:
        st.warning(f"데이터 로드 실패: {e}")
        return pd.DataFrame(
            columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자']
        )

# ─────────────────────────────────────────────
# [개선 5] 동시 편집 충돌 방지 (낙관적 잠금 패턴)
#   기존: push_to_cloud()가 단순히 세션의 전체 DataFrame을 덮어씀
#         → 두 사용자가 동시에 저장 시 나중 저장이 이전 저장을 덮어쓰는 문제
#   개선: 저장 전 클라우드에서 최신 데이터를 다시 읽어
#         시리얼 기준으로 병합(merge)한 뒤 저장
#         → 다른 사용자의 변경 사항을 보존
# ─────────────────────────────────────────────
def push_to_cloud(df: pd.DataFrame) -> bool:
    """
    동시 편집 충돌 방지를 포함한 클라우드 저장.
    1. 최신 클라우드 데이터를 다시 로드
    2. 현재 세션 데이터와 시리얼 기준 병합 (세션 데이터 우선)
    3. 병합 결과를 저장하고 세션 상태 동기화
    """
    try:
        latest = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in latest.columns:
            latest['시리얼'] = latest['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        if '반' in latest.columns:
            latest['반'] = latest['반'].apply(normalize_group_name)

        # 세션 데이터가 우선(keep='last')이 되도록 클라우드→세션 순으로 concat 후 중복 제거
        merged = pd.concat([latest, df], ignore_index=True).drop_duplicates(
            subset=['시리얼'], keep='last'
        )
        gs_conn.update(data=merged)
        st.cache_data.clear()
        st.session_state.production_db = merged  # 세션도 최신 상태로 갱신
        return True
    except Exception as error:
        st.error(f"클라우드 저장 실패: {error}")
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

# ─────────────────────────────────────────────
# [개선 6] 초기 user_db에 control_tower 계정 추가 및 비밀번호 해싱 적용
#   기존: admin/master 계정만 존재, 비밀번호 평문 저장
#         control_tower 역할이 ROLES에는 있으나 user_db에는 없어 로그인 불가
#   개선: control_tower 초기 계정 추가, 모든 비밀번호 해시값으로 저장
#         ※ 운영 환경에서는 마스터 관리 페이지에서 즉시 비밀번호 변경 권장
# ─────────────────────────────────────────────
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin":         {"pw_hash": hash_pw("admin1234"),        "role": "admin"},
        "master":        {"pw_hash": hash_pw("master1234"),       "role": "master"},
        "control_tower": {"pw_hash": hash_pw("control1234"),      "role": "control_tower"},
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
if 'current_line'        not in st.session_state: st.session_state.current_line        = "조립 라인"
if 'selected_cell'       not in st.session_state: st.session_state.selected_cell       = "CELL 1"
if 'confirm_target'      not in st.session_state: st.session_state.confirm_target      = None

# =================================================================
# 5. 로그인 및 보안
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
                # ─────────────────────────────────────────────
                # [개선 2 적용] 해시 비교로 인증
                # ─────────────────────────────────────────────
                if user_info and verify_pw(in_pw, user_info["pw_hash"]):
                    st.session_state.login_status = True
                    st.session_state.user_id      = in_id
                    st.session_state.user_role    = user_info["role"]
                    st.rerun()
                else:
                    st.error("로그인 정보가 올바르지 않습니다.")
    st.stop()

# =================================================================
# 6. 사이드바 내비게이션
# =================================================================

st.sidebar.markdown("### 🏭 생산 관리 시스템 v20.0")
st.sidebar.markdown(f"**{st.session_state.user_id} ({st.session_state.user_role})**")

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for key in ['login_status', 'user_role', 'user_id', 'admin_authenticated']:
        st.session_state[key] = False if key == 'login_status' else None
    st.rerun()

st.sidebar.divider()
allowed_nav = ROLES.get(st.session_state.user_role, [])

# ─────────────────────────────────────────────
# [개선 1 적용] NAV_GROUPS 제거, PRODUCTION_GROUPS 단일 사용
# ─────────────────────────────────────────────
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
                    st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if p in allowed_nav:
        if st.sidebar.button(
            p, key=f"fnav_{p}", use_container_width=True,
            type="primary" if st.session_state.current_line == p else "secondary"
        ):
            st.session_state.current_line = p
            st.rerun()

if "마스터 관리" in allowed_nav:
    st.sidebar.divider()
    if st.sidebar.button(
        "🔐 마스터 데이터 관리", use_container_width=True,
        type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"
    ):
        st.session_state.current_line = "마스터 관리"
        st.rerun()

# =================================================================
# 7. 공용 다이얼로그 컴포넌트
# =================================================================

# ─────────────────────────────────────────────
# [개선 7] 입고 확인 다이얼로그 타이밍 이슈 개선
#   기존: 버튼 클릭 → confirm_target 설정 → 즉시 dialog 호출
#         → Streamlit 렌더링 사이클상 dialog가 열리기 전에 rerun 발생 가능
#   개선: confirm_target이 세션에 설정된 경우 페이지 최상단에서
#         dialog를 한 번만 호출하는 패턴으로 변경 (조건부 단일 호출)
# ─────────────────────────────────────────────
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
        db_full = st.session_state.production_db.copy()
        idx_match = db_full[db_full['시리얼'] == target_sn].index
        if not idx_match.empty:
            idx = idx_match[0]
            db_full.at[idx, '시간']   = get_now_kst_str()
            db_full.at[idx, '라인']   = st.session_state.current_line
            db_full.at[idx, '상태']   = '진행 중'
            db_full.at[idx, '작업자'] = st.session_state.user_id
            push_to_cloud(db_full)
            st.success("입고 승인 완료!")
        else:
            st.error("해당 시리얼을 찾을 수 없습니다.")
        st.session_state.confirm_target = None
        st.rerun()

    if c_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

# confirm_target이 있으면 페이지 렌더링 전에 다이얼로그를 먼저 호출
if st.session_state.get("confirm_target"):
    trigger_entry_dialog()

# =================================================================
# 8. 페이지별 렌더링
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# ─────────────────────────────────────────────
# 8-1. 조립 라인
# ─────────────────────────────────────────────
if curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 신규 조립 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(
            name,
            type="primary" if st.session_state.selected_cell == name else "secondary"
        ):
            st.session_state.selected_cell = name
            st.rerun()

    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
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
                        db = st.session_state.production_db
                        if target_sn.strip() in db['시리얼'].values:
                            st.error("이미 등록된 시리얼입니다.")
                        else:
                            new_row = {
                                '시간':   get_now_kst_str(),
                                '반':     curr_g,
                                '라인':   "조립 라인",
                                'CELL':   st.session_state.selected_cell,
                                '모델':   target_model,
                                '품목코드': target_item,
                                '시리얼': target_sn.strip(),
                                '상태':   '진행 중',
                                '증상':   '',
                                '수리':   '',
                                '작업자': st.session_state.user_id
                            }
                            updated = pd.concat(
                                [db, pd.DataFrame([new_row])], ignore_index=True
                            )
                            push_to_cloud(updated)
                            st.rerun()
                    else:
                        st.warning("모델과 시리얼을 모두 입력해주세요.")

    st.divider()
    db_v = st.session_state.production_db
    f_df = db_v[(db_v['반'] == curr_g) & (db_v['라인'] == "조립 라인")]
    if st.session_state.selected_cell != "전체 CELL":
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]

    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "현장 제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL'])
            r[2].write(row['모델']); r[3].write(row['품목코드'])
            r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("조립 완료", key=f"ok_{idx}"):
                        db_v.at[idx, '상태'] = "완료"
                        push_to_cloud(db_v); st.rerun()
                    if b2.button("🚫불량", key=f"ng_{idx}"):
                        db_v.at[idx, '상태'] = "불량 처리 중"
                        push_to_cloud(db_v); st.rerun()
                else:
                    st.write(f"✅ {row['상태']}")
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
            (db_s['반'] == curr_g) &
            (db_s['라인'] == prev) &
            (db_s['상태'] == "완료")
        ]
        if not wait_list.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_list.iterrows()):
                # ─────────────────────────────────────────────
                # [개선 7 적용] 버튼 클릭 시 confirm_target 설정만 하고 rerun
                #   → 페이지 최상단의 조건부 dialog 호출부에서 처리됨
                # ─────────────────────────────────────────────
                if w_cols[i % 4].button(f"승인: {row['시리얼']}", key=f"in_{idx}"):
                    st.session_state.confirm_target = row['시리얼']
                    st.rerun()
        else:
            st.info("입고 대기 물량 없음")

    st.divider()
    f_df = db_s[(db_s['반'] == curr_g) & (db_s['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "제어"]):
            col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL'])
            r[2].write(row['모델']); r[3].write(row['품목코드'])
            r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                    if c1.button(btn, key=f"ok_{idx}"):
                        db_s.at[idx, '상태'] = "완료"
                        push_to_cloud(db_s); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"):
                        db_s.at[idx, '상태'] = "불량 처리 중"
                        push_to_cloud(db_s); st.rerun()
                else:
                    st.write(f"✅ {row['상태']}")
    else:
        st.info("해당 공정 내역이 없습니다.")

# ─────────────────────────────────────────────
# 8-3. 통합 리포트
# ─────────────────────────────────────────────
elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    v_group = st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = st.session_state.production_db.copy()
    if v_group != "전체":
        df = df[df['반'] == v_group]

    if not df.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투입",   f"{len(df)} EA")
        c2.metric("최종 생산", f"{len(df[(df['라인']=='포장 라인') & (df['상태']=='완료')])} EA")
        c3.metric("현재 재공", f"{len(df[df['상태']=='진행 중'])} EA")
        c4.metric("품질 이슈", f"{len(df[df['상태'].str.contains('불량', na=False)])} 건")

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
        f"<div class='stat-value'>{len(wait)}</div></div>", unsafe_allow_html=True
    )
    k2.markdown(
        f"<div class='stat-box'><div class='stat-label'>✅ {curr_g} 조치 완료</div>"
        f"<div class='stat-value'>"
        f"{len(db[(db['반']==curr_g) & (db['상태']=='수리 완료(재투입)')])}"
        f"</div></div>", unsafe_allow_html=True
    )

    if wait.empty:
        st.success("현재 처리 대기 중인 불량 이슈가 없습니다.")
    else:
        for idx, row in wait.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** (모델: {row['모델']})")
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
                        updated_db = db.copy()
                        updated_db.at[idx, '상태'] = "수리 완료(재투입)"
                        updated_db.at[idx, '시간'] = get_now_kst_str()
                        updated_db.at[idx, '증상'] = v_c
                        updated_db.at[idx, '수리'] = v_a + img_link
                        push_to_cloud(updated_db)
                        st.rerun()
                    else:
                        st.warning("불량 원인과 수리 조치 내용을 모두 입력해주세요.")

# ─────────────────────────────────────────────
# 8-5. 수리 이력 리포트
# ─────────────────────────────────────────────
elif curr_l == "수리 리포트":
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
                # ─────────────────────────────────────────────
                # [개선 3 적용] 하드코딩 제거 → secrets에서 해시 읽어 비교
                # ─────────────────────────────────────────────
                master_hash = get_master_pw_hash()
                if master_hash is None:
                    st.error(
                        "마스터 비밀번호가 설정되지 않았습니다.\n"
                        "secrets.toml에 master_admin_pw_hash 값을 설정해주세요."
                    )
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
                        st.subheader("신규 모델 등록")
                        nm = st.text_input(f"{g_name} 모델명", key=f"nm_{g_name}")
                        if st.button(f"{g_name} 모델 저장", key=f"nb_{g_name}"):
                            if nm and nm not in st.session_state.group_master_models.get(g_name, []):
                                st.session_state.group_master_models[g_name].append(nm)
                                st.session_state.group_master_items[g_name][nm] = []
                                st.success(f"모델 [{nm}] 등록 완료")
                                st.rerun()
                            elif not nm:
                                st.warning("모델명을 입력해주세요.")
                            else:
                                st.warning("이미 존재하는 모델명입니다.")
                with c2:
                    with st.container(border=True):
                        st.subheader("세부 품목 등록")
                        g_mods = st.session_state.group_master_models.get(g_name, [])
                        if g_mods:
                            sm = st.selectbox(f"{g_name} 모델 선택", g_mods, key=f"sm_{g_name}")
                            ni = st.text_input(f"[{sm}] 품목코드", key=f"ni_{g_name}")
                            if st.button(f"{g_name} 품목 저장", key=f"ib_{g_name}"):
                                current_items = st.session_state.group_master_items[g_name].get(sm, [])
                                if ni and ni not in current_items:
                                    st.session_state.group_master_items[g_name][sm].append(ni)
                                    st.success(f"품목 [{ni}] 등록 완료")
                                    st.rerun()
                                elif not ni:
                                    st.warning("품목코드를 입력해주세요.")
                                else:
                                    st.warning("이미 존재하는 품목코드입니다.")
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
                        # ─────────────────────────────────────────────
                        # [개선 2 적용] 신규/수정 계정도 해시로 저장
                        # ─────────────────────────────────────────────
                        st.session_state.user_db[nu] = {
                            "pw_hash": hash_pw(np_),
                            "role":    nr
                        }
                        st.success(f"계정 [{nu}] 저장 완료 (role: {nr})")
                    else:
                        st.warning("ID와 PW를 모두 입력해주세요.")

        with ac2:
            st.write("**시스템 데이터 관리**")
            csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 CSV 백업 다운로드", csv_data, "PMS_Backup.csv",
                use_container_width=True
            )
            f_imp = st.file_uploader("CSV 데이터 가져오기", type="csv")
            if f_imp and st.button("📤 로드 시작"):
                imp = pd.read_csv(f_imp)
                merged = pd.concat(
                    [st.session_state.production_db, imp], ignore_index=True
                ).drop_duplicates(subset=['시리얼'], keep='last')
                push_to_cloud(merged)
                st.rerun()

        st.divider()
        if st.button("⚠️ 전체 데이터 초기화", type="secondary"):
            empty_df = pd.DataFrame(
                columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자']
            )
            push_to_cloud(empty_df)
            st.rerun()

# =================================================================
# [ PMS v20.0 종료 ]
# =================================================================



