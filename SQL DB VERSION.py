import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import text

# =================================================================
# 1. 시스템 전역 설정 및 SQL 연결
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 SQL", layout="wide")
KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_sql_refresh")

# secrets.toml의 [connections.postgresql] 설정을 읽어옵니다.
conn = st.connection("postgresql", type="sql")

# 사용자 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],
    "packing_team": ["포장 라인"]
}

# =================================================================
# 2. SQL 데이터 처리 함수
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_data_sql():
    """SQL 서버에서 계정 및 로그 데이터를 최신순으로 로드"""
    try:
        acc_df = conn.query("SELECT * FROM accounts", ttl=0)
        st.session_state.user_db = {
            str(r['id']): {"pw": str(r['pw']), "role": r['role']} for _, r in acc_df.iterrows()
        }
        st.session_state.production_db = conn.query("SELECT * FROM production_logs ORDER BY 시간 DESC", ttl=0)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")

def run_sql_query(query, params):
    """INSERT / UPDATE 전용 함수"""
    try:
        with conn.session as s:
            s.execute(text(query), params)
            s.commit()
        load_data_sql() 
        st.success("✅ SQL 서버 동기화 완료")
    except Exception as e:
        st.error(f"저장 오류: {e}")

# =================================================================
# 3. 세션 및 초기 데이터 로드
# =================================================================
if 'user_db' not in st.session_state: 
    load_data_sql()

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# 마스터 데이터 (수정 가능)
st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
st.session_state.master_items_dict = {
    "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
    "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
}

# =================================================================
# 4. UI/UX 디자인 (CSS 및 사이드바)
# =================================================================
st.markdown("""
<style>
    .stApp { max-width: 1400px; margin: 0 auto; }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; }
    .section-title { background-color: #f0f2f6; padding: 10px; border-radius: 8px; font-weight: bold; border-left: 5px solid #007bff; }
</style>
""", unsafe_allow_html=True)

if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("접속 시작", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.update({"login_status":True, "user_id":uid, "user_role":st.session_state.user_db[uid]["role"]})
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("❌ 아이디 또는 비밀번호가 틀립니다.")
    st.stop()

# --- 사이드바 메뉴 (구분선 디자인 복구) ---
st.sidebar.markdown(f"### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"**접속자: {st.session_state.user_id}**")
if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.rerun()

st.sidebar.divider()

my_allowed = ROLES.get(st.session_state.user_role, [])

st.sidebar.caption("📦 PRODUCTION")
for p in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if p in my_allowed:
        if st.sidebar.button(p, use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            st.session_state.current_line = p; st.rerun()

st.sidebar.divider()
st.sidebar.caption("🛠️ QUALITY")
for p in ["불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(p, use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            st.session_state.current_line = p; st.rerun()

# =================================================================
# 5. 각 페이지 렌더링 (조립 라인 실적 입력 로직 포함)
# =================================================================

if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 생산 공정</h2>", unsafe_allow_html=True)
    
    # CELL 선택 버튼들
    stations = ["CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    scols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if scols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"):
            st.session_state.selected_cell = name; st.rerun()

    with st.container(border=True):
        st.markdown(f"#### ➕ {st.session_state.selected_cell} 생산 등록")
        t_model = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
        with st.form("assembly_form"):
            f1, f2 = st.columns(2)
            t_item = f1.selectbox("품목 코드", st.session_state.master_items_dict.get(t_model, ["모델 선택 대기"]))
            t_sn = f2.text_input("시리얼(S/N)")
            if st.form_submit_button("▶️ 생산 등록", use_container_width=True, type="primary"):
                if t_model != "선택하세요." and t_sn:
                    # [SQL 전용 저장 쿼리]
                    query = "INSERT INTO production_logs (시간, 라인, CELL, 모델, 품목코드, 시리얼, 상태, 작업자) VALUES (:t, :l, :c, :m, :i, :s, :st, :u)"
                    params = {"t": get_now_kst_str(), "l": "조립 라인", "c": st.session_state.selected_cell, "m": t_model, "i": t_item, "s": t_sn, "st": "진행 중", "u": st.session_state.user_id}
                    run_sql_query(query, params)
                    st.rerun()

    st.divider()
    st.dataframe(st.session_state.production_db[st.session_state.production_db['라인']=="조립 라인"], use_container_width=True, hide_index=True)

# 이후 리포트, 불량공정 등 다른 페이지들도 이와 같은 구조로 계속 추가됩니다.
