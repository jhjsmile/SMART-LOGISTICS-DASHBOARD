import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 연결
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 SQL TEST", layout="wide", initial_sidebar_state="expanded")
KST = timezone(timedelta(hours=9))

# 자동 새로고침 (30초)
st_autorefresh(interval=30000, key="pms_auto_refresh_final")

# 구글 시트 연결
conn = st.connection("gsheets", type=GSheetsConnection)

# 사용자 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],
    "packing_team": ["포장 라인"]
}

# [디자인] 전역 CSS
st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { width: 100%; border-radius: 8px; font-weight: 600; white-space: nowrap !important; }
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
    .section-title { background-color: #f8f9fa; padding: 16px 20px; border-radius: 10px; font-weight: bold; border-left: 10px solid #007bff; }
    .stat-box { display: flex; flex-direction: column; align-items: center; background-color: #ffffff; border-radius: 12px; padding: 22px; border: 1px solid #e9ecef; }
    .stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; }
    .stat-value { font-size: 2.4rem; color: #007bff; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 및 데이터 로드 함수
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_test_logs():
    try:
        df = conn.read(worksheet="sql_logs_test", ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except:
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def load_test_accounts():
    default_acc = {"master": {"pw": "master1234", "role": "master"}}
    try:
        df = conn.read(worksheet="sql_accounts_test", ttl=0)
        if df is None or df.empty: return default_acc
        acc_dict = {}
        for _, row in df.iterrows():
            uid = str(row['id']).strip() if pd.notna(row['id']) else ""
            if uid:
                raw_pw = str(row['pw']).strip() if pd.notna(row['pw']) else ""
                if raw_pw.endswith('.0'): raw_pw = raw_pw[:-2]
                acc_dict[uid] = {"pw": raw_pw, "role": str(row['role']).strip() if pd.notna(row['role']) else "user"}
        return acc_dict
    except:
        return default_acc

def push_to_cloud(df):
    try:
        conn.update(worksheet="sql_logs_test", data=df)
        st.success("✅ 클라우드 데이터 동기화 완료")
        st.session_state.production_db = df
    except Exception as e:
        st.error(f"저장 오류: {e}")

# =================================================================
# 3. 세션 상태 관리
# =================================================================
if 'user_db' not in st.session_state: st.session_state.user_db = load_test_accounts()
if 'production_db' not in st.session_state: st.session_state.production_db = load_test_logs()
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
        "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
    }
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# =================================================================
# 4. 로그인 화면 및 사이드바 (디자인 완벽 복구)
# =================================================================

if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 및 접속 시작", use_container_width=True):
                db = st.session_state.user_db
                if input_id in db and db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = db[input_id]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("❌ 정보가 올바르지 않습니다.")
    st.stop()

# --- 사이드바 메뉴 (구분선 및 캡션 포함) ---
st.sidebar.markdown(f"### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"**접속자: {st.session_state.user_id}**")
if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.rerun()

st.sidebar.divider() # --- [구분선 1] ---

def handle_nav(p_name):
    st.session_state.current_line = p_name
    st.rerun()

my_allowed = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 생산 및 리포트
st.sidebar.caption("📦 PRODUCTION & REPORT")
for p in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if p in my_allowed:
        if st.sidebar.button(p, use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            handle_nav(p)

st.sidebar.divider() # --- [구분선 2] ---

# 그룹 2: 품질 관리
st.sidebar.caption("🛠️ QUALITY CONTROL")
for p in ["불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(p, use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            handle_nav(p)

# 그룹 3: 시스템 관리
if st.session_state.user_role == "master" or "마스터 관리" in my_allowed:
    st.sidebar.divider() # --- [구분선 3] ---
    st.sidebar.caption("🔐 SYSTEM ADMIN")
    if st.sidebar.button("마스터 관리", use_container_width=True, type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"):
        handle_nav("마스터 관리")

# =================================================================
# 5. 핵심 비즈니스 로직 (공용 컴포넌트)
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    st.warning(f"승인 대상 S/N: [ {st.session_state.confirm_target} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_full = st.session_state.production_db
        idx_match = db_full[db_full['시리얼'] == st.session_state.confirm_target].index
        if not idx_match.empty:
            idx = idx_match[0]
            db_full.at[idx, '시간'] = get_now_kst_str()
            db_full.at[idx, '라인'] = st.session_state.current_line
            db_full.at[idx, '상태'] = '진행 중'
            db_full.at[idx, '작업자'] = st.session_state.user_id
            push_to_cloud(db_full)
        st.session_state.confirm_target = None
        st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def draw_v17_optimized_log(line_key, ok_btn_txt="완료 처리"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_source = st.session_state.production_db
    f_df = db_source[db_source['라인'] == line_key]
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: 
        st.info("현재 해당 공정에 할당된 제품 데이터가 없습니다.")
        return

    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    header_labels = ["기록 시간", "작업구분(CELL)", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]
    for col, txt in zip(h_row, header_labels): col.write(f"**{txt}**")
    
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r_row[0].write(row['시간'])
        r_row[1].write(row['CELL'] if row['CELL'] != "-" else "N/A")
        r_row[2].write(row['모델'])
        r_row[3].write(row['품목코드'])
        r_row[4].write(f"`{row['시리얼']}`")
        with r_row[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_btn_txt, key=f"ok_{idx}"):
                    db_source.at[idx, '상태'] = "완료"
                    push_to_cloud(db_source); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    db_source.at[idx, '상태'] = "불량 처리 중"
                    push_to_cloud(db_source); st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span style='color:red'>🔴 분석 대기</span>", unsafe_allow_html=True)
            else: st.markdown("<span style='color:green'>🟢 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 렌더링 (화면 출력 로직)
# =================================================================

# --- 6-1. 조립 라인 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 조립 생산 라인 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    station_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if station_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 등록")
            target_model = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("entry_form"):
                f1, f2 = st.columns(2)
                t_item = f1.selectbox("품목 코드", st.session_state.master_items_dict.get(target_model, ["모델 선택 대기"]))
                t_sn = f2.text_input("시리얼(S/N)")
                if st.form_submit_button("▶️ 생산 등록"):
                    if target_model != "선택하세요." and t_sn:
                        full_db = st.session_state.production_db
                        if t_sn in full_db['시리얼'].values: st.error("중복 시리얼")
                        else:
                            new = {'시간': get_now_kst_str(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': target_model, '품목코드': t_item, '시리얼': t_sn, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                            st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    draw_v17_optimized_log("조립 라인", "조립 완료")

# --- 6-2. 품질 / 포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    pg_title = "🔍 품질 검사 공정" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    pv_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{pg_title}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 입고 승인 대기 물량</div>", unsafe_allow_html=True)
        wait_df = st.session_state.production_db[(st.session_state.production_db['라인'] == pv_line) & (st.session_state.production_db['상태'] == "완료")]
        if not wait_df.empty:
            cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if cols[i % 4].button(f"입고: {row['시리얼']}", key=f"in_{row['시리얼']}"):
                    st.session_state.confirm_target = row['시리얼']
                    trigger_entry_dialog()
        else: st.info("대기 물량 없음")
    draw_v17_optimized_log(st.session_state.current_line, "검사 합격" if st.session_state.current_line=="검사 라인" else "포장 완료")

# --- 6-3. 리포트 ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    if not db.empty:
        m = st.columns(4)
        m[0].metric("총 투입", f"{len(db)} EA")
        m[1].metric("완료 실적", f"{len(db[(db['라인']=='포장 라인')&(db['상태']=='완료')])} EA")
        m[2].metric("재공(WIP)", f"{len(db[db['상태']=='진행 중'])} EA")
        m[3].metric("품질 이슈", f"{len(db[db['상태'].str.contains('불량', na=False)])} 건")
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else: st.warning("데이터 없음")

# --- 6-4. 불량 공정 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치</h2>", unsafe_allow_html=True)
    db_bad = st.session_state.production_db
    wait_list = db_bad[db_bad['상태'] == "불량 처리 중"]
    if wait_list.empty: st.success("품질 이슈 없음")
    else:
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.write(f"**대상 S/N: {row['시리얼']}**")
                c1, c2 = st.columns(2)
                cause = c1.text_input("원인 분석", key=f"c_{idx}")
                action = c2.text_input("조치 내용", key=f"a_{idx}")
                if st.button("수리 완료 확정", key=f"btn_{idx}", type="primary"):
                    if cause and action:
                        db_bad.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad.at[idx, '시간'] = get_now_kst_str()
                        db_bad.at[idx, '증상'], db_bad.at[idx, '수리'] = cause, action
                        push_to_cloud(db_bad); st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 이력 리포트</h2>", unsafe_allow_html=True)
    hist = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    st.dataframe(hist[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# --- 6-6. 마스터 관리 ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_gate"):
            pw = st.text_input("마스터 암호", type="password")
            if st.form_submit_button("인증"):
                if pw == "master1234": st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("인증 실패")
    else:
        st.subheader("계정 관리")
        u1, u2, u3 = st.columns([3, 3, 2])
        rid = u1.text_input("새 ID")
        rpw = u2.text_input("새 PW")
        rrl = u3.selectbox("권한", list(ROLES.keys()))
        if st.button("계정 생성 및 저장"):
            if rid and rpw:
                st.session_state.user_db[rid] = {"pw": rpw, "role": rrl}
                acc_df = pd.DataFrame.from_dict(st.session_state.user_db, orient='index').reset_index()
                acc_df.columns = ['id', 'pw', 'role']
                conn.update(worksheet="sql_accounts_test", data=acc_df)
                st.success("저장 완료"); st.rerun()

# =================================================================
# [ PMS v17.8 최종 소스코드 종료 ]
# =================================================================
# (현준 님의 기존 페이지 렌더링 if/elif문 코드를 이어서 붙여넣으시면 됩니다)
