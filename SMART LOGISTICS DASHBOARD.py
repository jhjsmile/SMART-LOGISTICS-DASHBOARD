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
    .status-ok { color: #28a745; font-weight: bold; }
    .status-ng { color: #dc3545; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 세션 상태(Session State) 초기화
# =================================================================
# 10. 계정 DB (ID/PW 부여)
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "user1": {"pw": "user1234", "role": "user"}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'user_id' not in st.session_state: st.session_state.user_id = None
# 11. 마스터 관리 2차 인증 상태
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
# 3. 로그인 로직
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 시스템 로그인")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            # 1. 인증 버튼에 엔터값 추가
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.rerun()
                else: st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

# =================================================================
# 4. 사이드바 및 공용 함수
# =================================================================
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("시스템 로그아웃", use_container_width=True):
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

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    st.write(f"**상세 정보:** {st.session_state.confirm_model} / {st.session_state.confirm_item}")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ 승인", type="primary", use_container_width=True):
        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''}
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None; st.rerun()
    if col_cancel.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 5. 메인 화면 - 조립 라인
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 작업")
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary", key=f"cbtn_{c}"):
            st.session_state.selected_cell = c; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 신규 등록")
            # 6. 모델 선택 초기값 "선택하세요." 및 품목코드 연동
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="m_select_asm")
            with st.form("asm_form"):
                reg1, reg2 = st.columns(2)
                # 2. 모델 선택 시 품목 리스트 연동
                i_opts = st.session_state.master_items_dict.get(m_choice, []) if m_choice != "선택하세요." else ["모델을 선택하세요."]
                i_choice = reg1.selectbox("품목 선택", i_opts)
                s_input = reg2.text_input("시리얼 번호 스캔")
                # 3. 조립 시작 등록 엔터값 추가
                if st.form_submit_button("▶️ 조립 시작 등록", type="primary", use_container_width=True):
                    if m_choice != "선택하세요." and s_input:
                        db = st.session_state.production_db
                        # 7. 모델/시리얼 같아도 품목 다르면 입력 가능
                        dup = db[(db['모델']==m_choice) & (db['품목코드']==i_choice) & (db['시리얼']==s_input) & (db['상태'] != "완료")]
                        if dup.empty:
                            new_data = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True); st.rerun()
                        else: st.error("이미 공정 진행 중인 데이터입니다.")
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
# 6. 메인 화면 - 품질 검사 라인 (8번 요청 반영)
# =================================================================
elif st.session_state.current_line == "검사 라인":
    st.title("🔍 품질 검사 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="insp_m")
        # 8. 전체선택 삭제, 품목 필수 선택
        si_opts = ["품목을 선택하세요."] + st.session_state.master_items_dict.get(sm, []) if sm != "선택하세요." else ["모델 선택 필요"]
        si = f2.selectbox("품목 선택", si_opts, key="insp_i")
        if sm != "선택하세요." and si != "품목을 선택하세요.":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "조립 라인") & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            done_sns = db[db['라인'] == "검사 라인"]['시리얼'].unique()
            avail = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail:
                st.success(f"📦 대기 물량: {len(avail)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"ibtn_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")

# =================================================================
# 7. 메인 화면 - 출하 포장 라인 (8번 요청 반영)
# =================================================================
elif st.session_state.current_line == "포장 라인":
    st.title("🚚 출하 포장 현황")
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key="pack_m")
        si_opts = ["품목을 선택하세요."] + st.session_state.master_items_dict.get(sm, []) if sm != "선택하세요." else ["모델 선택 필요"]
        si = f2.selectbox("품목 선택", si_opts, key="pack_i")
        if sm != "선택하세요." and si != "품목을 선택하세요.":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "검사 라인") & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            done_sns = db[db['라인'] == "포장 라인"]['시리얼'].unique()
            avail = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail:
                st.success(f"📦 대기 물량: {len(avail)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"pbtn_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")

# =================================================================
# 8. 메인 화면 - 통합 생산 리포트 (4, 5, 9번 반영)
# =================================================================
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 실적 분석")
    main_db = st.session_state.production_db
    if not main_db.empty:
        met = st.columns(4)
        met[0].metric("최종 완료", len(main_db[main_db['상태'] == '완료']))
        met[1].metric("진행 중", len(main_db[main_db['상태'] == '진행 중']))
        met[2].metric("누적 불량", len(main_db[main_db['상태'].str.contains("불량")]))
        met[3].metric("수리 완료", len(main_db[main_db['상태'].str.contains("재투입")]))
        st.divider()
        c_left, c_right = st.columns([3, 2])
        with c_left:
            fig_bar = px.bar(main_db[main_db['상태'] == '완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="라인별 양품 실적")
            # 5. 타이틀 중앙 정렬, 9. y축 정수 표시
            fig_bar.update_layout(title={'text': "라인별 양품 실적", 'y':0.95, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top'}, yaxis=dict(dtick=1, tickformat='d'), margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_bar, use_container_width=True)
        with c_right:
            fig_pie = px.pie(main_db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 투입 비중")
            fig_pie.update_layout(title={'text': "모델별 투입 비중", 'y':0.95, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top'}, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_pie, use_container_width=True)
        # 4. 명칭 변경: 생산 현황
        st.markdown("<div class='section-title'>📝 생산 현황</div>", unsafe_allow_html=True)
        st.dataframe(main_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# =================================================================
# 9. 메인 화면 - 불량 수리 센터
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 제품 수리 센터")
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("✅ 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                s_val = c1.text_input("불량 원인", key=f"rs_{idx}")
                a_val = c2.text_input("수리 조치", key=f"ra_{idx}")
                if c3.button("완료/재투입", key=f"rb_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"; st.rerun()

# =================================================================
# 10. 마스터 관리 (11번 인증 및 로그아웃 포함)
# =================================================================
elif st.session_state.current_line == "마스터 관리" and st.session_state.user_role == "admin":
    st.title("🔐 마스터 데이터 관리")
    # 11. 마스터 인증 기능
    if not st.session_state.admin_authenticated:
        _, auth_c, _ = st.columns([1, 1, 1])
        with auth_c:
            st.subheader("관리자 2차 인증")
            with st.form("admin_v"):
                apw = st.text_input("관리자 PW", type="password")
                if st.form_submit_button("인증하기"):
                    if apw == "admin1234": st.session_state.admin_authenticated = True; st.rerun()
                    else: st.error("PW 오류")
    else:
        # 11. 로그아웃(세션 종료) 버튼
        if st.button("🔓 관리자 세션 종료"):
            st.session_state.admin_authenticated = False; st.session_state.current_line = "조립 라인"; st.rerun()
        
        st.markdown("<div class='section-title'>📋 기준 정보 설정</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1:
            with st.container(border=True):
                st.write("**모델 관리**")
                m_add = st.text_input("신규 모델")
                if st.button("등록"):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
        with m2:
            with st.container(border=True):
                st.write("**품목 관리**")
                ms = st.selectbox("모델", st.session_state.master_models)
                is_add = st.text_input("신규 품목")
                if st.button("품목 등록"):
                    if is_add and is_add not in st.session_state.master_items_dict[ms]:
                        st.session_state.master_items_dict[ms].append(is_add); st.rerun()
        
        st.divider()
        st.markdown("<div class='section-title'>👥 계정 권한 관리 (ID/PW 부여)</div>", unsafe_allow_html=True)
        u1, u2 = st.columns(2)
        with u1:
            with st.form("user_reg"):
                uid, upw = st.text_input("신규 ID"), st.text_input("신규 PW")
                urole = st.radio("권한", ["user", "admin"], horizontal=True)
                if st.form_submit_button("계정 저장"):
                    st.session_state.user_db[uid] = {"pw": upw, "role": urole}; st.rerun()
        with u2: st.write("**등록 계정**"); st.write(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("<div class='section-title'>📤 데이터 업로드/다운로드</div>", unsafe_allow_html=True)
        up_file = st.file_uploader("CSV 업로드", type="csv")
        b1, b2, b3 = st.columns(3)
        b1.button("💾 모델 백업"); b2.button("💾 품목 백업")
        if b3.button("⚠️ DB 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()
