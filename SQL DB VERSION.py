import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
from streamlit_autorefresh import st_autorefresh
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 세션 초기화
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템", layout="wide", initial_sidebar_state="expanded")
KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 구글 시트 연결
conn = st.connection("gsheets", type=GSheetsConnection)

# 사용자 권한 및 마스터 데이터 세션 초기화
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],
    "packing_team": ["포장 라인"]
}

if 'master_models' not in st.session_state:
    st.session_state.update({
        'master_models': ["EPS7150", "EPS7133", "T20i", "T20C"],
        'master_items_dict': {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        'current_line': "조립 라인", 'selected_cell': "CELL 1", 'login_status': False
    })

# =================================================================
# 2. 데이터 처리 및 공용 함수 (최적화)
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_data():
    """시트에서 계정과 실적 데이터를 동시에 로드하여 세션에 저장"""
    try:
        # 계정 로드 및 소수점 정제
        acc_df = conn.read(worksheet="sql_accounts_test", ttl=0)
        st.session_state.user_db = {
            str(r['id']).strip(): {
                "pw": str(r['pw']).replace('.0', '').strip(), 
                "role": str(r['role']).strip()
            } for _, r in acc_df.iterrows() if pd.notna(r['id'])
        }
        # 실적 로드
        log_df = conn.read(worksheet="sql_logs_test", ttl=0).fillna("")
        if '시리얼' in log_df.columns:
            log_df['시리얼'] = log_df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        st.session_state.production_db = log_df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")

def save_data(df, sheet_name="sql_logs_test"):
    try:
        conn.update(worksheet=sheet_name, data=df)
        st.session_state.production_db = df
        st.success("✅ 클라우드 동기화 완료")
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")

# 초기 로드 실행
if 'production_db' not in st.session_state:
    load_data()

# =================================================================
# 3. 사이드바 및 디자인 (구분선 복구)
# =================================================================
st.markdown("""
<style>
    .stApp { max-width: 1400px; margin: 0 auto; }
    .stButton button { width: 100%; border-radius: 8px; font-weight: 600; }
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; }
    .section-title { background-color: #f0f2f6; padding: 12px; border-radius: 8px; font-weight: bold; border-left: 5px solid #007bff; }
</style>
""", unsafe_allow_html=True)

def render_sidebar():
    st.sidebar.markdown(f"### 🏭 생산 관리 시스템\n**접속: {st.session_state.user_id}**")
    if st.sidebar.button("🚪 로그아웃", use_container_width=True):
        st.session_state.login_status = False
        st.rerun()
    
    st.sidebar.divider()
    my_allowed = ROLES.get(st.session_state.user_role, [])
    
    # 메뉴 그룹화
    menu_groups = {
        "📦 PRODUCTION": ["조립 라인", "검사 라인", "포장 라인", "리포트"],
        "🛠️ QUALITY": ["불량 공정", "수리 리포트"],
        "🔐 ADMIN": ["마스터 관리"]
    }
    
    for label, menus in menu_groups.items():
        allowed_menus = [m for m in menus if m in my_allowed]
        if allowed_menus:
            st.sidebar.caption(label)
            for m in allowed_menus:
                if st.sidebar.button(m, use_container_width=True, 
                                     type="primary" if st.session_state.current_line == m else "secondary"):
                    st.session_state.current_line = m
                    st.rerun()
            st.sidebar.divider()

# =================================================================
# 4. 로그인 관문
# =================================================================
if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.markdown("<h1 class='centered-title'>🔐 통합 관리 시스템</h1>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("접속 시작"):
                db = st.session_state.user_db
                if uid in db and db[uid]["pw"] == upw:
                    st.session_state.update({'login_status': True, 'user_id': uid, 'user_role': db[uid]["role"]})
                    st.rerun()
                else: st.error("❌ 아이디/비밀번호 오류")
    st.stop()

render_sidebar()

# =================================================================
# 5. 페이지 렌더링 함수 (최적화의 핵심: 페이지별 분리)
# =================================================================

def render_log_table(line_key, btn_text="완료 처리"):
    """공통 원장 출력 함수"""
    st.markdown(f"#### 📝 {line_key} 실시간 작업 원장")
    df = st.session_state.production_db
    f_df = df[df['라인'] == line_key]
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: st.info("대상 데이터 없음"); return

    cols = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    for col, head in zip(cols, ["기록 시간", "CELL", "모델", "코드", "S/N", "제어"]): col.write(f"**{head}**")
    
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델'])
        r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
        with r[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(btn_text, key=f"ok_{idx}"):
                    df.at[idx, '상태'] = "완료"; save_data(df); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    df.at[idx, '상태'] = "불량 처리 중"; save_data(df); st.rerun()
            else: st.write(f"✅ {row['상태']}")

# --- 조립 라인 페이지 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 조립 생산 라인</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    scols = st.columns(len(stations))
    for i, s in enumerate(stations):
        if scols[i].button(s, type="primary" if st.session_state.selected_cell == s else "secondary"):
            st.session_state.selected_cell = s; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            model = st.selectbox("투입 모델", ["선택하세요."] + st.session_state.master_models)
            with st.form("entry_form"):
                f1, f2 = st.columns(2)
                item = f1.selectbox("품목 코드", st.session_state.master_items_dict.get(model, ["모델 선택 대기"]))
                sn = f2.text_input("시리얼(S/N)")
                if st.form_submit_button("▶️ 생산 등록"):
                    if model != "선택하세요." and sn:
                        if sn in st.session_state.production_db['시리얼'].values: st.error("이미 등록된 시리얼")
                        else:
                            new = {'시간': get_now_kst_str(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': model, '품목코드': item, '시리얼': sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                            save_data(pd.concat([st.session_state.production_db, pd.DataFrame([new])], ignore_index=True))
                            st.rerun()
    render_log_table("조립 라인", "조립 완료")

# --- 품질/포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>🔍 {st.session_state.current_line} 현황</h2>", unsafe_allow_html=True)
    with st.expander("📥 입고 대기 물량 확인", expanded=True):
        wait_df = st.session_state.production_db[(st.session_state.production_db['라인'] == prev_line) & (st.session_state.production_db['상태'] == "완료")]
        if not wait_df.empty:
            wcols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if wcols[i % 4].button(f"입고: {row['시리얼']}", key=f"in_{idx}"):
                    df = st.session_state.production_db
                    df.at[idx, '라인'] = st.session_state.current_line
                    df.at[idx, '상태'] = "진행 중"
                    save_data(df); st.rerun()
        else: st.info("대기 물량 없음")
    render_log_table(st.session_state.current_line, "합격/완료")

# --- 리포트 페이지 ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    if not db.empty:
        m = st.columns(4)
        m[0].metric("총 투입", f"{len(db)} EA")
        m[1].metric("생산 완료", f"{len(db[(db['라인']=='포장 라인')&(db['상태']=='완료')])} EA")
        m[2].metric("재공(WIP)", f"{len(db[db['상태']=='진행 중'])} EA")
        m[3].metric("품질 이슈", f"{len(db[db['상태'].str.contains('불량', na=False)])} 건")
        
        c1, c2 = st.columns([1.8, 1.2])
        with c1: st.plotly_chart(px.bar(db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 분포"), use_container_width=True)
        with c2: st.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', title="모델별 비중"), use_container_width=True)
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 불량/수리 페이지 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리</h2>", unsafe_allow_html=True)
    bad_df = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad_df.empty: st.success("이슈 없음")
    else:
        for idx, row in bad_df.iterrows():
            with st.container(border=True):
                st.write(f"**대상 S/N: {row['시리얼']}**")
                c1, c2 = st.columns(2)
                cause = c1.text_input("원인", key=f"c_{idx}")
                action = c2.text_input("조치", key=f"a_{idx}")
                if st.button("수리 확정", key=f"rb_{idx}", type="primary"):
                    if cause and action:
                        df = st.session_state.production_db
                        df.at[idx, '상태'] = "수리 완료(재투입)"
                        df.at[idx, '증상'], df.at[idx, '수리'] = cause, action
                        save_data(df); st.rerun()

# --- 마스터 관리 (어드민) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if st.session_state.user_role == "master":
        with st.expander("👤 사용자 계정 추가", expanded=True):
            u1, u2, u3 = st.columns([3, 3, 2])
            new_id = u1.text_input("아이디")
            new_pw = u2.text_input("비밀번호")
            new_role = u3.selectbox("권한", list(ROLES.keys()))
            if st.button("계정 저장"):
                acc_df = conn.read(worksheet="sql_accounts_test", ttl=0)
                new_row = pd.DataFrame([{'id': new_id, 'pw': new_pw, 'role': new_role}])
                save_data(pd.concat([acc_df, new_row], ignore_index=True), "sql_accounts_test")
                st.rerun()
        if st.button("⚠️ 전체 실적 초기화", type="secondary"):
            save_data(pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자']))
            st.rerun()
