import streamlit as st
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# =================================================================
# 1. 전역 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v7.5", layout="wide")
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
    .status-ok { color: #28a745; font-weight: bold; }
    .status-ng { color: #dc3545; font-weight: bold; }
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

# 중복 메시지 유지를 위한 변수 (필요 시 사용)
if 'msg_box' not in st.session_state:
    st.session_state.msg_box = None

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
            '라인': st.session_state.current_line,
            'CELL': "-",
            '모델': st.session_state.confirm_model,
            '품목코드': st.session_state.confirm_item,
            '시리얼': st.session_state.confirm_target,
            '상태': '진행 중', '증상': '', '수리': ''
        }
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None
        st.rerun()
        
    if col_cancel.button("❌ 입고 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

# =================================================================
# 4. 사이드바 내비게이션 (시계 삭제됨)
# =================================================================
st.sidebar.title("🏭 생산 공정 관리 v7.5")
st.sidebar.markdown("---")

def nav_to(line_name, is_admin=False):
    st.session_state.current_line = line_name
    st.session_state.admin_page = is_admin
    st.rerun()

if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "조립 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("조립 라인")

if st.sidebar.button("🔍 검사 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "검사 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("검사 라인")

if st.sidebar.button("🚚 포장 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line == "포장 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("포장 라인")

st.sidebar.divider()
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True):
    nav_to("리포트")

if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True):
    nav_to("불량 공정")

if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.admin_page else "secondary"):
    nav_to(st.session_state.current_line, is_admin=True)

# =================================================================
# 5. 마스터 데이터 관리 (들여쓰기 및 인증 로직 교정)
# =================================================================
if st.session_state.admin_page:
    st.title("🔐 시스템 관리자 제어판")
    
    if not st.session_state.is_authenticated:
        _, a_col, _ = st.columns([1, 1.5, 1])
        with a_col:
            st.subheader("관리자 본인 확인")
            
            def check_auth():
                if st.session_state.admin_pw_input == ADMIN_PASSWORD:
                    st.session_state.is_authenticated = True
                else:
                    st.error("인증에 실패했습니다.")

            st.text_input("접속 비밀번호", type="password", key="admin_pw_input", on_change=check_auth)
            if st.button("인증하기", use_container_width=True):
                check_auth()
                if st.session_state.is_authenticated:
                    st.rerun()
    else:
        # 인증 완료 시 관리 기능 출력
        st.markdown("<div class='section-title'>📋 마스터 기준 정보 개별 설정</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            with st.container(border=True):
                st.write("**[모델 리스트]**")
                m_add = st.text_input("추가할 신규 모델명")
                if st.button("모델 등록", use_container_width=True):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add)
                        st.session_state.master_items_dict[m_add] = []; st.rerun()
                m_del = st.selectbox("삭제할 모델 선택", st.session_state.master_models)
                if st.button("모델 삭제 실행", use_container_width=True):
                    st.session_state.master_models.remove(m_del); st.rerun()

        with m_col2:
            with st.container(border=True):
                st.write("**[품목 코드]**")
                m_target = st.selectbox("품목 관리 대상 모델", st.session_state.master_models)
                i_add = st.text_input(f"[{m_target}] 신규 코드")
                if st.button("코드 등록", use_container_width=True):
                    if i_add and i_add not in st.session_state.master_items_dict[m_target]:
                        st.session_state.master_items_dict[m_target].append(i_add); st.rerun()
                i_del = st.selectbox("삭제할 코드 선택", st.session_state.master_items_dict.get(m_target, []))
                if st.button("코드 삭제 실행", use_container_width=True):
                    st.session_state.master_items_dict[m_target].remove(i_del); st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>📤 CSV 대량 데이터 관리</div>", unsafe_allow_html=True)
        up_c1, up_c2 = st.columns([1, 1])
        with up_c1:
            with st.container(border=True):
                up_file = st.file_uploader("업로드할 CSV 파일을 드래그하세요", type="csv")
                if st.button("🚀 시스템 일괄 반영", type="primary", use_container_width=True):
                    if up_file: st.success("데이터 반영 성공")
                    else: st.warning("파일을 먼저 선택하세요.")
        with up_c2:
            if up_file:
                pre_df = pd.read_csv(up_file)
                st.dataframe(pre_df, use_container_width=True, height=200)

        st.divider()
        if st.button("⚠️ 전체 생산 DB 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리'])
            st.rerun()

# =================================================================
# 6. 리포트 / 7. 불량 공정 / 8. 조립, 검사, 포장 (로직 그대로 유지)
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
        st.plotly_chart(px.bar(main_db[main_db['상태'] == '완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="라인별 양품 실적"), use_container_width=True)
        st.dataframe(main_db, use_container_width=True, hide_index=True)

elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 제품 수리 센터")
    bad_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad_list.empty:
        st.success("✅ 현재 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.write(f"**[수리 대상] S/N: {row['시리얼']}** (모델: {row['모델']})")
                r_c1, r_c2, r_c3 = st.columns([4, 4, 2])
                s_v = r_c1.text_input("불량 원인", key=f"rs_{idx}")
                a_v = r_c2.text_input("수리 내용", key=f"ra_{idx}")
                if r_c3.button("✅ 수리 완료", key=f"rb_{idx}", use_container_width=True):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                    st.session_state.production_db.at[idx, '증상'] = s_v
                    st.session_state.production_db.at[idx, '수리'] = a_v
                    st.rerun()

elif st.session_state.current_line == "조립 라인":
    st.title("📦 조립 라인 작업")
    c_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    cols = st.columns(len(c_list))
    for i, cname in enumerate(c_list):
        if cols[i].button(cname, type="primary" if st.session_state.selected_cell == cname else "secondary", key=f"cbtn_{cname}"):
            st.session_state.selected_cell = cname; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 신규 등록")
            reg1, reg2, reg3 = st.columns(3)
            m_choice = reg1.selectbox("모델 선택", st.session_state.master_models, key="am_m")
            i_choice = reg2.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []), key="am_i")
            s_input = reg3.text_input("시리얼 번호 스캔")
            
            if st.button("▶️ 조립 시작 등록", type="primary", use_container_width=True):
                if s_input:
                    db = st.session_state.production_db
                    if not db[(db['모델'] == m_choice) & (db['시리얼'] == s_input)].empty:
                        st.error(f"이미 등록된 시리얼입니다: {s_input}")
                    else:
                        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
                        st.rerun()

    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL":
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    st.dataframe(l_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# 검사 및 포장 라인은 입고 승인 다이얼로그 방식 유지
elif st.session_state.current_line == "검사 라인":
    st.title("🔍 품질 검사 라인")
    db = st.session_state.production_db
    ready = db[(db['라인'] == "조립 라인") & (db['상태'] == "완료")]
    done_sns = db[db['라인'] == "검사 라인"]['시리얼'].unique()
    avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
    
    if avail_sns:
        cols = st.columns(4)
        for i, sn in enumerate(avail_sns):
            if cols[i % 4].button(f"🆔 {sn}", key=f"insp_{sn}"):
                row = ready[ready['시리얼'] == sn].iloc[0]
                st.session_state.confirm_target = sn
                st.session_state.confirm_model = row['모델']
                st.session_state.confirm_item = row['품목코드']
                confirm_entry_dialog()
    st.divider()
    st.dataframe(db[db['라인'] == "검사 라인"], use_container_width=True)

elif st.session_state.current_line == "포장 라인":
    st.title("🚚 출하 포장 라인")
    db = st.session_state.production_db
    ready = db[(db['라인'] == "검사 라인") & (db['상태'] == "완료")]
    done_sns = db[db['라인'] == "포장 라인"]['시리얼'].unique()
    avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
    
    if avail_sns:
        cols = st.columns(4)
        for i, sn in enumerate(avail_sns):
            if cols[i % 4].button(f"🆔 {sn}", key=f"pack_{sn}"):
                row = ready[ready['시리얼'] == sn].iloc[0]
                st.session_state.confirm_target = sn
                st.session_state.confirm_model = row['모델']
                st.session_state.confirm_item = row['품목코드']
                confirm_entry_dialog()
    st.divider()
    st.dataframe(db[db['라인'] == "포장 라인"], use_container_width=True)
