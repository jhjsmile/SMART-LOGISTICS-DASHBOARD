import streamlit as st
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# =================================================================
# 1. 전역 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v7.8", layout="wide")
ADMIN_PASSWORD = "admin1234"

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

if 'current_line' not in st.session_state:
    st.session_state.current_line = "조립 라인"

if 'is_authenticated' not in st.session_state:
    st.session_state.is_authenticated = False

if 'admin_page' not in st.session_state:
    st.session_state.admin_page = False

if 'confirm_target' not in st.session_state:
    st.session_state.confirm_target = None

if 'selected_cell' not in st.session_state:
    st.session_state.selected_cell = "CELL 1"

# 모델/품목 입력 상태 유지를 위한 전용 키 초기화
if 'active_model' not in st.session_state:
    st.session_state.active_model = "선택하세요"
if 'active_item' not in st.session_state:
    st.session_state.active_item = ""

# =================================================================
# 3. 다이얼로그 정의
# =================================================================
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 물량을 현재 공정으로 입고하시겠습니까?")
    st.write(f"**상세 정보:** {st.session_state.confirm_model} / {st.session_state.confirm_item}")
    
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ 승인 및 입고", type="primary", use_container_width=True):
        new_row = {
            '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '라인': st.session_state.current_line, 'CELL': "-",
            '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item,
            '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''
        }
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None
        st.rerun()
    if col_cancel.button("❌ 입고 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

# =================================================================
# 4. 사이드바 내비게이션
# =================================================================
st.sidebar.title("🏭 생산 통합 관리 v7.8")
st.sidebar.markdown("---")

def nav_to(line_name, is_admin=False):
    st.session_state.current_line = line_name
    st.session_state.admin_page = is_admin
    st.rerun()

if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "조립 라인" and not st.session_state.admin_page else "secondary"): nav_to("조립 라인")
if st.sidebar.button("🔍 검사 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "검사 라인" and not st.session_state.admin_page else "secondary"): nav_to("검사 라인")
if st.sidebar.button("🚚 포장 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "포장 라인" and not st.session_state.admin_page else "secondary"): nav_to("포장 라인")
st.sidebar.divider()
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True): nav_to("리포트")
if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True): nav_to("불량 공정")
if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.admin_page else "secondary"): nav_to(st.session_state.current_line, is_admin=True)

# =================================================================
# 5. 마스터 데이터 관리 (인증 엔터 연동)
# =================================================================
if st.session_state.admin_page:
    st.title("🔐 시스템 관리자 제어판")
    if not st.session_state.is_authenticated:
        _, a_col, _ = st.columns([1, 1.5, 1])
        with a_col:
            st.subheader("관리자 본인 확인")
            with st.form("admin_auth"):
                p_input = st.text_input("접속 비밀번호", type="password")
                if st.form_submit_button("인증하기", use_container_width=True):
                    if p_input == ADMIN_PASSWORD:
                        st.session_state.is_authenticated = True; st.rerun()
                    else: st.error("인증에 실패했습니다.")
    else:
        st.markdown("<div class='section-title'>📋 마스터 기준 정보 설정</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            with st.container(border=True):
                st.write("**[모델 리스트]**")
                m_add = st.text_input("추가할 신규 모델명")
                if st.button("모델 등록"):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
                m_del = st.selectbox("삭제 모델", st.session_state.master_models)
                if st.button("모델 삭제"): st.session_state.master_models.remove(m_del); st.rerun()
        with m_col2:
            with st.container(border=True):
                st.write("**[품목 코드]**")
                m_target = st.selectbox("품목 관리 대상", st.session_state.master_models)
                i_add = st.text_input(f"[{m_target}] 신규 코드")
                if st.button("코드 등록"):
                    if i_add and i_add not in st.session_state.master_items_dict[m_target]:
                        st.session_state.master_items_dict[m_target].append(i_add); st.rerun()
                i_del = st.selectbox("삭제 코드", st.session_state.master_items_dict.get(m_target, []))
                if st.button("코드 삭제"): st.session_state.master_items_dict[m_target].remove(i_del); st.rerun()
        if st.button("로그아웃"): st.session_state.is_authenticated = False; st.rerun()

# =================================================================
# 6. 생산 통합 리포트
# =================================================================
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 실적 분석")
    main_db = st.session_state.production_db
    if not main_db.empty:
        met1, met2, met3, met4 = st.columns(4)
        met1.metric("최종 완료", len(main_db[main_db['상태'] == '완료']))
        met2.metric("공정 진행중", len(main_db[main_db['상태'] == '진행 중']))
        met3.metric("누적 불량", len(main_db[main_db['상태'].str.contains("불량", na=False)]))
        met4.metric("수리 완료", len(main_db[main_db['상태'].str.contains("재투입", na=False)]))
        
        st.divider()
        c_left, c_right = st.columns(2)
        with c_left:
            perf_df = main_db[main_db['상태'] == '완료'].groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(perf_df, x='라인', y='수량', color='라인', title="라인별 양품 실적")
            fig_bar.update_layout(title_x=0.5, bargap=0.6, showlegend=False)
            fig_bar.update_xaxes(showticklabels=False, title=None)
            st.plotly_chart(fig_bar, use_container_width=True)
        with c_right:
            pie_df = main_db.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(pie_df, values='수량', names='모델', hole=0.3, title="모델별 투입 비중")
            fig_pie.update_layout(title_x=0.5)
            st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("<div class='section-title'>📝 생산 현황</div>", unsafe_allow_html=True)
        st.dataframe(main_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
        st.markdown("<div class='section-title'>🛠️ 불량 및 수리 현황</div>", unsafe_allow_html=True)
        h_df = main_db[main_db['상태'].str.contains("불량|수리|재투입", na=False)].sort_values('시간', ascending=False)
        st.dataframe(h_df, use_container_width=True, hide_index=True)

# =================================================================
# 7. 조립 라인 (로직 수정: 모델/품목 연동 및 상태 유지)
# =================================================================
elif st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 작업")
    c_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    cols = st.columns(len(c_list))
    for i, cname in enumerate(c_list):
        if cols[i].button(cname, type="primary" if st.session_state.selected_cell == cname else "secondary"):
            st.session_state.selected_cell = cname
            # 셀 변경 시에만 입력값 초기화
            st.session_state.active_model = "선택하세요"
            st.session_state.active_item = ""
            st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 신규 등록")
            
            # 레이아웃 유지를 위한 컬럼 구성 (Selectbox는 Form 밖으로 배치하여 즉시 반응)
            reg1, reg2, reg3 = st.columns(3)
            
            # 1. 모델 선택 (반응형)
            model_options = ["선택하세요"] + st.session_state.master_models
            m_choice = reg1.selectbox("모델 선택", model_options, key="active_model")
            
            # 2. 품목 선택 (모델 선택 시에만 활성화)
            is_disabled = (m_choice == "선택하세요")
            i_opts = st.session_state.master_items_dict.get(m_choice, []) if not is_disabled else []
            i_choice = reg2.selectbox("품목 선택", i_opts, key="active_item", disabled=is_disabled)
            
            # 3. 시리얼 입력 및 버튼 (Enter 키 연동을 위해 Form 사용)
            with reg3.form("registration_form", clear_on_submit=False):
                s_input = st.text_input("시리얼 번호 스캔 (입력 후 Enter)", disabled=is_disabled, value="")
                submit_btn = st.form_submit_button("▶️ 조립 시작 등록", type="primary", use_container_width=True)
                
                if submit_btn:
                    if is_disabled:
                        st.error("모델을 먼저 선택해주세요.")
                    elif not s_input:
                        st.warning("시리얼 번호를 입력해주세요.")
                    else:
                        db = st.session_state.production_db
                        if not db[db['시리얼'] == s_input].empty:
                            st.error(f"이미 등록된 시리얼입니다: {s_input}")
                        else:
                            # 등록 후에도 m_choice, i_choice는 session_state 키값에 의해 유지됨
                            new_data = {
                                '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                '라인': "조립 라인", 'CELL': st.session_state.selected_cell,
                                '모델': m_choice, '품목코드': i_choice, '시리얼': s_input,
                                '상태': '진행 중', '증상': '', '수리': ''
                            }
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True)
                            st.rerun()

    st.divider()
    st.subheader("📊 실시간 작업 로그")
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    if not l_db.empty:
        lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, txt in zip(lh, ["등록시간", "CELL", "모델", "품목", "시리얼", "상태제어"]): col.write(f"**{txt}**")
        for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
            lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
            with lr[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("🚫불량", key=f"ng_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                else: st.write(row['상태'])

# =================================================================
# 8. 검사 / 포장 / 불량 공정 (기존 기능 유지)
# =================================================================
elif st.session_state.current_line == "검사 라인":
    st.title("🔍 품질 검사 라인")
    st.markdown("<div class='section-title'>📥 검사 입고 대상 (조립 완료 물량)</div>", unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sel_m = f1.selectbox("모델 선택", ["선택하세요"] + st.session_state.master_models, key="insp_m")
        if sel_m != "선택하세요":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "조립 라인") & (db['상태'] == "완료") & (db['모델'] == sel_m)]
            done_sns = db[db['라인'] == "검사 라인"]['시리얼'].unique()
            avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail_sns:
                grid = st.columns(4)
                for i, sn in enumerate(avail_sns):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"insp_{sn}"):
                        st.session_state.confirm_target = sn; st.session_state.confirm_model = sel_m
                        st.session_state.confirm_item = ready[ready['시리얼']==sn]['품목코드'].values[0]
                        confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")

elif st.session_state.current_line == "포장 라인":
    st.title("🚚 출하 포장 라인")
    st.markdown("<div class='section-title'>📥 포장 입고 대상 (검사 합격 물량)</div>", unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sel_m = f1.selectbox("모델 선택", ["선택하세요"] + st.session_state.master_models, key="pack_m")
        if sel_m != "선택하세요":
            db = st.session_state.production_db
            ready = db[(db['라인'] == "검사 라인") & (db['상태'] == "완료") & (db['모델'] == sel_m)]
            done_sns = db[db['라인'] == "포장 라인"]['시리얼'].unique()
            avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
            if avail_sns:
                grid = st.columns(4)
                for i, sn in enumerate(avail_sns):
                    if grid[i % 4].button(f"🆔 {sn}", key=f"pack_{sn}"):
                        st.session_state.confirm_target = sn; st.session_state.confirm_model = sel_m
                        st.session_state.confirm_item = ready[ready['시리얼']==sn]['품목코드'].values[0]
                        confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")

elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 수리 센터")
    bad_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if not bad_list.empty:
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.write(f"**대상 S/N: {row['시리얼']}** ({row['모델']})")
                r1, r2, r3 = st.columns([4, 4, 2])
                symp = r1.text_input("불량 증상", key=f"s_{idx}")
                repa = r2.text_input("수리 내용", key=f"r_{idx}")
                if r3.button("✅ 수리 완료/재투입", key=f"b_{idx}", use_container_width=True):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                    st.session_state.production_db.at[idx, '증상'] = symp; st.session_state.production_db.at[idx, '수리'] = repa
                    st.rerun()
    else: st.success("대기 중인 수리 물량이 없습니다.")
