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
# 계정 DB (ID: {pw, role})
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "user1": {"pw": "user1234", "role": "user"}
    }

if 'login_status' not in st.session_state:
    st.session_state.login_status = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None

# 생산 데이터
if 'production_db' not in st.session_state:
    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리'])

# 마스터 데이터
if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B", "7150-C"],
        "EPS7133": ["7133-S", "7133-D"],
        "T20i": ["T20i-PRO", "T20i-BASE"],
        "T20C": ["T20C-Standard"]
    }

if 'current_line' not in st.session_state:
    st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state:
    st.session_state.selected_cell = "CELL 1"
if 'confirm_target' not in st.session_state:
    st.session_state.confirm_target = None

# =================================================================
# 3. 로그인 화면
# =================================================================
def login_screen():
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 생산 관리 시스템 로그인")
        with st.form("login_form"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

if not st.session_state.login_status:
    login_screen()
    st.stop()

# =================================================================
# 4. 사이드바 및 공통 함수
# =================================================================
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
st.sidebar.info(f"권한: {st.session_state.user_role}")
if st.sidebar.button("로그아웃", use_container_width=True):
    st.session_state.login_status = False; st.rerun()

st.sidebar.divider()

def nav_to(line_name):
    st.session_state.current_line = line_name
    st.rerun()

# 메뉴 구성
if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "조립 라인" else "secondary"):
    nav_to("조립 라인")
if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line == "검사 라인" else "secondary"):
    nav_to("검사 라인")
if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line == "포장 라인" else "secondary"):
    nav_to("포장 라인")

st.sidebar.divider()
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line == "리포트" else "secondary"):
    nav_to("리포트")
if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line == "불량 공정" else "secondary"):
    nav_to("불량 공정")

if st.session_state.user_role == "admin":
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"):
        nav_to("마스터 관리")

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 물량을 현재 공정으로 입고하시겠습니까?")
    st.write(f"**상세 정보:** {st.session_state.confirm_model} / {st.session_state.confirm_item}")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ 승인 및 입고", type="primary", use_container_width=True):
        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''}
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None; st.rerun()
    if col_cancel.button("❌ 입고 취소", use_container_width=True):
        st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 5. 메인 로직 - 조립 라인
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 작업")
    c_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    cols = st.columns(len(c_list))
    for i, cname in enumerate(c_list):
        if cols[i].button(cname, type="primary" if st.session_state.selected_cell == cname else "secondary", key=f"cbtn_{cname}"):
            st.session_state.selected_cell = cname; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 신규 등록")
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="m_choice")
            with st.form("assembly_reg_form", clear_on_submit=False):
                reg1, reg2 = st.columns(2)
                i_opts = st.session_state.master_items_dict.get(m_choice, []) if m_choice != "선택하세요." else ["모델을 선택하세요."]
                i_choice = reg1.selectbox("품목 선택", i_opts)
                s_input = reg2.text_input("시리얼 번호 스캔")
                if st.form_submit_button("▶️ 조립 시작 등록", type="primary", use_container_width=True):
                    if m_choice != "선택하세요." and s_input:
                        db = st.session_state.production_db
                        if db[(db['모델'] == m_choice) & (db['품목코드'] == i_choice) & (db['시리얼'] == s_input) & (db['상태'] != "완료")].empty:
                            new_data = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True); st.rerun()
                        else: st.error("이미 진행 중인 데이터입니다.")

    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if not l_db.empty:
        lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, txt in zip(lh, ["등록시간", "CELL", "모델명", "품목코드", "시리얼", "상태제어"]): col.write(f"**{txt}**")
        for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
            with lr[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_a_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불량", key=f"ng_a_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                elif row['상태'] == "불량 처리 중": st.error("🔴 수리실")
                else: st.success("🟢 완료")

# =================================================================
# 6. 메인 로직 - 품질 검사 라인
# =================================================================
elif st.session_state.current_line == "검사 라인":
    st.title("🔍 품질 검사 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sel_m = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="ins_m")
        i_opts = ["품목을 선택하세요."] + st.session_state.master_items_dict.get(sel_m, []) if sel_m != "선택하세요." else ["모델을 선택하세요."]
        sel_i = f2.selectbox("품목 선택", i_opts, key="ins_i")
        if sel_m != "선택하세요." and sel_i != "품목을 선택하세요.":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "조립 라인") & (db['상태'] == "완료") & (db['모델'] == sel_m) & (db['품목코드'] == sel_i)]
            done_sns = db[db['라인'] == "검사 라인"]['시리얼'].unique()
            avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail_sns:
                st.success(f"📦 대기 물량: {len(avail_sns)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail_sns):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"ibtn_{sn}", use_container_width=True):
                        st.session_state.confirm_target = sn; st.session_state.confirm_model = sel_m; st.session_state.confirm_item = sel_i; confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")
    st.divider()
    log_insp = st.session_state.production_db[st.session_state.production_db['라인'] == "검사 라인"]
    if not log_insp.empty:
        lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, txt in zip(lh, ["검사시간", "CELL", "모델명", "품목코드", "시리얼", "판정"]): col.write(f"**{txt}**")
        for idx, row in log_insp.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            lr[0].write(row['시간']); lr[1].write("-"); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
            with lr[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("합격", key=f"ok_i_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불합격", key=f"ng_i_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                elif row['상태'] == "불량 처리 중": st.error("🔴 수리실")
                else: st.success("🟢 합격완료")

# =================================================================
# 7. 메인 로직 - 출하 포장 라인
# =================================================================
elif st.session_state.current_line == "포장 라인":
    st.title("🚚 출하 포장 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sel_m = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="pk_m")
        i_opts = ["품목을 선택하세요."] + st.session_state.master_items_dict.get(sel_m, []) if sel_m != "선택하세요." else ["모델을 선택하세요."]
        sel_i = f2.selectbox("품목 선택", i_opts, key="pk_i")
        if sel_m != "선택하세요." and sel_i != "품목을 선택하세요.":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "검사 라인") & (db['상태'] == "완료") & (db['모델'] == sel_m) & (db['품목코드'] == sel_i)]
            done_sns = db[db['라인'] == "포장 라인"]['시리얼'].unique()
            avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail_sns:
                st.success(f"📦 대기 물량: {len(avail_sns)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail_sns):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"pbtn_{sn}", use_container_width=True):
                        st.session_state.confirm_target = sn; st.session_state.confirm_model = sel_m; st.session_state.confirm_item = sel_i; confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")
    st.divider()
    log_pack = st.session_state.production_db[st.session_state.production_db['라인'] == "포장 라인"]
    if not log_pack.empty:
        lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, txt in zip(lh, ["포장시간", "CELL", "모델명", "품목코드", "시리얼", "상태"]): col.write(f"**{txt}**")
        for idx, row in log_pack.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            lr[0].write(row['시간']); lr[1].write("-"); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
            with lr[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_p_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불량", key=f"ng_p_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                elif row['상태'] == "불량 처리 중": st.error("🔴 수리실")
                else: st.success("🟢 포장완료")

# =================================================================
# 8. 메인 로직 - 통합 생산 리포트
# =================================================================
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 실적 분석")
    main_db = st.session_state.production_db
    if not main_db.empty:
        met = st.columns(4)
        met[0].metric("최종 완료", len(main_db[main_db['상태'] == '완료']))
        met[1].metric("공정 진행중", len(main_db[main_db['상태'] == '진행 중']))
        met[2].metric("누적 불량", len(main_db[main_db['상태'].str.contains("불량")]))
        met[3].metric("수리 완료", len(main_db[main_db['상태'].str.contains("재투입")]))
        st.divider()
        c_left, c_right = st.columns([3, 2])
        with c_left:
            fig_bar = px.bar(main_db[main_db['상태'] == '완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="라인별 양품 실적")
            fig_bar.update_layout(title={'text': "라인별 양품 실적", 'y':0.95, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top'}, yaxis=dict(dtick=1, tickformat='d'), margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_bar, use_container_width=True)
        with c_right:
            fig_pie = px.pie(main_db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 투입 비중")
            fig_pie.update_layout(title={'text': "모델별 투입 비중", 'y':0.95, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top'}, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_pie, use_container_width=True)
        st.markdown("<div class='section-title'>📝 생산 현황</div>", unsafe_allow_html=True)
        st.dataframe(main_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else: st.info("데이터가 없습니다.")

# =================================================================
# 9. 메인 로직 - 불량 수리 센터
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 제품 수리 센터")
    bad_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad_list.empty: st.success("✅ 현재 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.write(f"**[수리 대상] S/N: {row['시리얼']}** ({row['모델']} / 발생: {row['라인']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                s_val = c1.text_input("불량 원인", key=f"rs_{idx}")
                a_val = c2.text_input("수리 조치", key=f"ra_{idx}")
                if c3.button("✅ 완료 및 재투입", key=f"rb_{idx}", use_container_width=True):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"; st.session_state.production_db.at[idx, '증상'] = s_val; st.session_state.production_db.at[idx, '수리'] = a_val; st.rerun()

# =================================================================
# 10. 메인 로직 - 마스터 관리 (최종 끝부분)
# =================================================================
elif st.session_state.current_line == "마스터 관리" and st.session_state.user_role == "admin":
    st.title("🔐 시스템 마스터 데이터 관리")
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        with st.container(border=True):
            st.write("**[모델 관리]**")
            m_add = st.text_input("신규 모델")
            if st.button("모델 추가"):
                if m_add and m_add not in st.session_state.master_models:
                    st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
    with m_col2:
        with st.container(border=True):
            st.write("**[품목 관리]**")
            m_sel = st.selectbox("대상 모델", st.session_state.master_models)
            i_add = st.text_input("신규 품목")
            if st.button("품목 추가"):
                if i_add and i_add not in st.session_state.master_items_dict[m_sel]:
                    st.session_state.master_items_dict[m_sel].append(i_add); st.rerun()

    st.divider()
    st.markdown("<div class='section-title'>👥 계정 권한 관리</div>", unsafe_allow_html=True)
    u_c1, u_c2 = st.columns(2)
    with u_c1:
        with st.form("user_reg"):
            uid = st.text_input("ID")
            upw = st.text_input("PW")
            urole = st.radio("권한", ["user", "admin"])
            if st.form_submit_button("사용자 등록/수정"):
                st.session_state.user_db[uid] = {"pw": upw, "role": urole}; st.rerun()
    with u_c2:
        st.write("**등록된 계정**")
        st.write(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

    st.divider()
    st.markdown("<div class='section-title'>📤 데이터 관리</div>", unsafe_allow_html=True)
    up_f = st.file_uploader("CSV 업로드")
    b1, b2, b3 = st.columns(3)
    b1.button("💾 모델 백업")
    b2.button("💾 품목 백업")
    if b3.button("⚠️ 전체 초기화", type="secondary"):
        st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()
