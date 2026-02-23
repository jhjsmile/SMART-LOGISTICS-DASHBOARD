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
# 2. 세션 상태 초기화
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

# =================================================================
# 3. 로그인 시스템
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
                    st.session_state.login_status, st.session_state.user_id, st.session_state.user_role = True, uid, st.session_state.user_db[uid]["role"]
                    st.rerun()
                else: st.error("계정 정보를 확인하세요.")
    st.stop()

# =================================================================
# 4. 사이드바 및 공용 함수
# =================================================================
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("시스템 로그아웃"):
    st.session_state.login_status = False; st.session_state.admin_authenticated = False; st.rerun()

st.sidebar.divider()
def nav(name): st.session_state.current_line = name; st.rerun()

if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): nav("조립 라인")
if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): nav("검사 라인")
if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): nav("포장 라인")
st.sidebar.divider()
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): nav("리포트")
if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): nav("불량 공정")

if st.session_state.user_role == "admin":
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav("마스터 관리")

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    if st.button("✅ 승인 및 입고", type="primary", use_container_width=True):
        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''}
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 5. 마스터 관리
# =================================================================
if st.session_state.current_line == "마스터 관리":
    st.title("🔐 마스터 데이터 관리")
    if not st.session_state.admin_authenticated:
        _, auth_c, _ = st.columns([1, 1, 1])
        with auth_c:
            with st.form("admin_v"):
                apw = st.text_input("관리자 PW (admin1234)", type="password")
                if st.form_submit_button("인증하기"):
                    if apw == "admin1234": st.session_state.admin_authenticated = True; st.rerun()
                    else: st.error("PW 오류")
    else:
        c1, c2 = st.columns([8, 2])
        if c2.button("🔓 관리 세션 종료"): st.session_state.admin_authenticated = False; nav("조립 라인")
        
        st.markdown("<div class='section-title'>📋 기준 정보 설정 및 계정 관리</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.write("**모델/품목 추가**")
                m_add = st.text_input("모델명")
                if st.button("모델 등록"):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
        with col2:
            with st.container(border=True):
                st.write("**계정 권한 부여**")
                uid, upw = st.text_input("ID"), st.text_input("PW")
                if st.button("계정 저장"):
                    st.session_state.user_db[uid] = {"pw": upw, "role": "user"}; st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>📤 데이터 관리</div>", unsafe_allow_html=True)
        up_f = st.file_uploader("CSV 업로드", type="csv")
        b1, b2, b3 = st.columns(3)
        if b3.button("⚠️ 전체 데이터 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()

# =================================================================
# 6. 조립 라인 현황 (셀 변경 시 초기화 로직 보강)
# =================================================================
elif st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 현황")
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"):
            st.session_state.selected_cell = c; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 신규 등록")
            
            # [해결 방법] key값에 selected_cell을 포함하여 셀이 바뀔 때마다 위젯을 새로 생성(초기화)합니다.
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, 
                                    key=f"m_select_{st.session_state.selected_cell}")
            
            with st.form(f"asm_form_{st.session_state.selected_cell}", clear_on_submit=False):
                r1, r2 = st.columns(2)
                i_opts = st.session_state.master_items_dict.get(m_choice, []) if m_choice != "선택하세요." else ["모델 선택 필요"]
                i_choice = r1.selectbox("품목 선택", i_opts)
                s_input = r2.text_input("시리얼 번호")
                
                if st.form_submit_button("▶️ 조립 등록", type="primary", use_container_width=True):
                    if m_choice != "선택하세요." and s_input:
                        db = st.session_state.production_db
                        if db[(db['모델']==m_choice) & (db['품목코드']==i_choice) & (db['시리얼']==s_input) & (db['상태'] != "완료")].empty:
                            new_data = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True); st.rerun()
                        else: st.error("이미 진행 중인 동일 데이터 존재")

    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    if not l_db.empty:
        lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, txt in zip(lh, ["시간", "CELL", "모델", "품목", "시리얼", "제어"]): col.write(f"**{txt}**")
        for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
            with lr[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_a_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불량", key=f"ng_a_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                else: st.success(row['상태'])

# =================================================================
# 7. 품질 검사 / 8. 출하 포장 
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.title(line_title)
    
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"m_sel_{st.session_state.current_line}")
        si_opts = st.session_state.master_items_dict.get(sm, []) if sm != "선택하세요." else []
        si = f2.selectbox("품목 선택", ["품목을 선택하세요."] + si_opts)
        
        if sm != "선택하세요." and si != "품목을 선택하세요.":
            db = st.session_state.production_db
            ready = db[(db['라인'] == prev_line) & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            done_sns = db[db['라인'] == st.session_state.current_line]['시리얼'].unique()
            avail = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail:
                st.success(f"📦 대기 물량: {len(avail)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"입고: {sn}", key=f"btn_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
            else: st.info("대기 물량 없음")

    st.divider()
    curr_log = st.session_state.production_db[st.session_state.production_db['라인'] == st.session_state.current_line]
    if not curr_log.empty:
        for idx, row in curr_log.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([3, 2, 2, 2, 3])
            lr[0].write(row['시간']); lr[1].write(row['모델']); lr[2].write(row['품목코드']); lr[3].write(row['시리얼'])
            with lr[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    btn_label = "합격" if st.session_state.current_line=="검사 라인" else "완료"
                    if b1.button(btn_label, key=f"ok_c_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불량", key=f"ng_c_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                else: st.success("🟢 완료")

# =================================================================
# 9. 리포트 / 10. 불량 수리 센터
# =================================================================
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 리포트")
    db = st.session_state.production_db
    if not db.empty:
        c1, c2 = st.columns([3, 2])
        with c1:
            fig1 = px.bar(db[db['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="라인별 양품 실적")
            fig1.update_layout(title_x=0.5, yaxis=dict(dtick=1))
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            fig2 = px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', title="모델별 투입 비중")
            fig2.update_layout(title_x=0.5)
            st.plotly_chart(fig2, use_container_width=True)
        st.markdown("<div class='section-title'>📝 생산 현황</div>", unsafe_allow_html=True)
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 수리 센터")
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("대기 물량 없음")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"S/N: {row['시리얼']} ({row['모델']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                s_val = c1.text_input("원인", key=f"s_{idx}")
                a_val = c2.text_input("조치", key=f"a_{idx}")
                if c3.button("완료 및 재투입", key=f"r_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"; st.rerun()
