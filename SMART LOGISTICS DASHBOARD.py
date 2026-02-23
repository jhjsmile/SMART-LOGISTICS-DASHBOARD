import streamlit as st
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# =================================================================
# 1. 전역 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v7.5", layout="wide")

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .section-title { 
        background-color: #f8f9fa; 
        color: #000000 !important; 
        padding: 15px; 
        border-radius: 8px; 
        font-weight: bold; 
        margin-bottom: 20px; 
        border-left: 8px solid #007bff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .preview-box {
        border: 2px solid #e9ecef;
        padding: 15px;
        border-radius: 10px;
        background-color: #ffffff;
    }
    .repair-tag { 
        background-color: #fff3cd; 
        color: #856404 !important; 
        padding: 4px 12px; 
        border-radius: 15px; 
        font-weight: bold; 
        font-size: 0.8rem;
        border: 1px solid #ffeeba;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 세션 상태(Session State) 초기화
# =================================================================
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "user1": {"pw": "user1234", "role": "user"}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

if 'production_db' not in st.session_state:
    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리'])

if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B", "7150-C"],
        "EPS7133": ["7133-S", "7133-D"],
        "T20i": ["T20i-PRO", "T20i-BASE"],
        "T20C": ["T20C-Standard"]
    }

if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'confirm_target' not in st.session_state: st.session_state.confirm_target = None

# =================================================================
# 3. 로그인 처리
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 시스템 로그인")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.rerun()
                else: st.error("계정 정보를 확인하세요.")
    st.stop()

# =================================================================
# 4. 사이드바 내비게이션
# =================================================================
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.session_state.admin_authenticated = False
    st.rerun()

st.sidebar.divider()
def nav(name):
    st.session_state.current_line = name
    st.rerun()

if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): nav("조립 라인")
if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): nav("검사 라인")
if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): nav("포장 라인")
st.sidebar.divider()
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): nav("리포트")
if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): nav("불량 공정")

if st.session_state.user_role == "admin":
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav("마스터 관리")

# 공용 다이얼로그
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    if st.button("✅ 승인", type="primary", use_container_width=True):
        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''}
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 5. 메인 화면 로직
# =================================================================

# --- 마스터 관리 (인증 및 로그아웃 기능 추가) ---
if st.session_state.current_line == "마스터 관리":
    st.title("🔐 마스터 데이터 관리")
    
    if not st.session_state.admin_authenticated:
        _, auth_c, _ = st.columns([1, 1, 1])
        with auth_c:
            st.subheader("관리자 2차 인증")
            with st.form("admin_verify"):
                v_pw = st.text_input("관리자 비밀번호", type="password")
                if st.form_submit_button("인증하기", use_container_width=True):
                    if v_pw == "admin1234":
                        st.session_state.admin_authenticated = True; st.rerun()
                    else: st.error("비밀번호가 틀립니다.")
    else:
        # 상단에 관리자 세션 로그아웃 버튼 배치
        c1, c2 = st.columns([8, 2])
        c2.button("🔓 관리자 세션 종료", on_click=lambda: st.session_state.update({"admin_authenticated": False, "current_line": "조립 라인"}), use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 기준 정보 개별 설정</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.write("**[모델 관리]**")
                m_add = st.text_input("신규 모델")
                if st.button("추가"):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
        with col2:
            with st.container(border=True):
                st.write("**[품목 관리]**")
                m_sel = st.selectbox("대상 모델", st.session_state.master_models)
                i_add = st.text_input("신규 품목")
                if st.button("품목 추가"):
                    if i_add and i_add not in st.session_state.master_items_dict[m_sel]:
                        st.session_state.master_items_dict[m_sel].append(i_add); st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👥 계정 권한 관리</div>", unsafe_allow_html=True)
        u1, u2 = st.columns(2)
        with u1:
            with st.form("u_reg"):
                uid, upw = st.text_input("ID"), st.text_input("PW")
                urole = st.radio("권한", ["user", "admin"], horizontal=True)
                if st.form_submit_button("사용자 등록/수정"):
                    st.session_state.user_db[uid] = {"pw": upw, "role": urole}; st.rerun()
        with u2: st.write("**등록 계정**"); st.write(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("<div class='section-title'>📤 데이터 백업 및 초기화</div>", unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        b1.button("💾 모델 백업"); b2.button("💾 품목 백업")
        if b3.button("⚠️ 전체 데이터 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()

# --- 조립 라인 ---
elif st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 현황")
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"):
            st.session_state.selected_cell = c; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("asm_form"):
                r1, r2 = st.columns(2)
                i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델을 선택하세요."])
                s_input = r2.text_input("시리얼 번호")
                if st.form_submit_button("▶️ 조립 등록", type="primary", use_container_width=True):
                    if m_choice != "선택하세요." and s_input:
                        new_data = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True); st.rerun()

    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    st.subheader(f"📊 {st.session_state.selected_cell} 로그")
    if not l_db.empty:
        for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([3, 2, 2, 2, 3])
            lr[0].write(row['시간']); lr[1].write(row['모델']); lr[2].write(row['품목코드']); lr[3].write(row['시리얼'])
            with lr[4]:
                if row['상태'] == "진행 중":
                    if st.button("완료", key=f"ok_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                else: st.success("🟢 완료")

# --- 품질 검사 ---
elif st.session_state.current_line == "검사 라인":
    st.title("🔍 품질 검사 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델", ["선택하세요."] + st.session_state.master_models)
        si = f2.selectbox("품목", st.session_state.master_items_dict.get(sm, []) if sm!="선택하세요." else ["모델 선택 필요"])
        if sm != "선택하세요." and si != "모델 선택 필요":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "조립 라인") & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            avail = [s for s in ready['시리얼'].unique() if s not in db[db['라인'] == "검사 라인"]['시리얼'].unique()]
            if avail:
                for sn in avail:
                    if st.button(f"입고: {sn}", key=f"i_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
            else: st.info("대기 물량 없음")

# --- 출하 포장 ---
elif st.session_state.current_line == "포장 라인":
    st.title("🚚 출하 포장 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델", ["선택하세요."] + st.session_state.master_models)
        si = f2.selectbox("품목", st.session_state.master_items_dict.get(sm, []) if sm!="선택하세요." else ["모델 선택 필요"])
        if sm != "선택하세요." and si != "모델 선택 필요":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "검사 라인") & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            avail = [s for s in ready['시리얼'].unique() if s not in db[db['라인'] == "포장 라인"]['시리얼'].unique()]
            if avail:
                for sn in avail:
                    if st.button(f"입고: {sn}", key=f"p_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()

# --- 리포트 ---
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 리포트")
    db = st.session_state.production_db
    if not db.empty:
        c1, c2 = st.columns([3, 2])
        with c1:
            fig1 = px.bar(db[db['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="라인별 양품 실적")
            fig1.update_layout(title_x=0.5, yaxis=dict(dtick=1))
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            fig2 = px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', title="모델별 투입 비중")
            fig2.update_layout(title_x=0.5)
            st.plotly_chart(fig2, use_container_width=True)
        st.markdown("<div class='section-title'>📝 생산 현황</div>", unsafe_allow_html=True)
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 수리 센터")
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("대기 물량 없음")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"S/N: {row['시리얼']} ({row['모델']})")
                if st.button("수리 완료 및 재투입", key=f"r_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"; st.rerun()
