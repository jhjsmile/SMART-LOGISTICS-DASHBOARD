import streamlit as st
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# =================================================================
# 1. 전역 시스템 설정 및 스타일 정의 (디자인 100% 복구)
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v7.7", layout="wide")
ADMIN_PASSWORD = "admin1234"

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .section-title { 
        background-color: #f8f9fa; color: #000000 !important; padding: 15px; 
        border-radius: 8px; font-weight: bold; margin-bottom: 20px; 
        border-left: 8px solid #007bff; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .repair-tag { 
        background-color: #fff3cd; color: #856404 !important; padding: 4px 12px; 
        border-radius: 15px; font-weight: bold; font-size: 0.8rem; border: 1px solid #ffeeba;
    }
    .bad-tag {
        background-color: #f8d7da; color: #721c24 !important; padding: 4px 12px;
        border-radius: 15px; font-weight: bold; font-size: 0.8rem; border: 1px solid #f5c6cb;
    }
    .status-done { color: #28a745; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 세션 상태 초기화 (데이터 무결성 유지)
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

# =================================================================
# 3. 공정 입고 승인 다이얼로그 (무생략)
# =================================================================
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 물량을 현재 공정으로 입고하시겠습니까?")
    st.write(f"**상세 정보:** {st.session_state.confirm_model} / {st.session_state.confirm_item}")
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button("✅ 승인 및 입고", type="primary", width='stretch'):
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
    if col_cancel.button("❌ 입고 취소", width='stretch'):
        st.session_state.confirm_target = None
        st.rerun()

# =================================================================
# 4. 사이드바 내비게이션 (모든 메뉴 복구)
# =================================================================
st.sidebar.title("🏭 MES 생산 관리 v7.7")
st.sidebar.markdown(f"**User Mode:** {'Admin' if st.session_state.is_authenticated else 'Operator'}")
st.sidebar.divider()

def nav_to(line_name, is_admin=False):
    st.session_state.current_line = line_name
    st.session_state.admin_page = is_admin
    st.rerun()

st.sidebar.subheader("📍 공정 현황")
if st.sidebar.button("📦 조립 라인 현황", width='stretch', type="primary" if st.session_state.current_line == "조립 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("조립 라인")
if st.sidebar.button("🔍 검사 라인 현황", width='stretch', type="primary" if st.session_state.current_line == "검사 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("검사 라인")
if st.sidebar.button("🚚 포장 라인 현황", width='stretch', type="primary" if st.session_state.current_line == "포장 라인" and not st.session_state.admin_page else "secondary"):
    nav_to("포장 라인")

st.sidebar.divider()
st.sidebar.subheader("⚙️ 관리 도구")
if st.sidebar.button("📊 통합 생산 리포트", width='stretch', type="primary" if st.session_state.current_line == "리포트" else "secondary"):
    nav_to("리포트")
if st.sidebar.button("🛠️ 불량 수리 센터", width='stretch', type="primary" if st.session_state.current_line == "불량 공정" else "secondary"):
    nav_to("불량 공정")
if st.sidebar.button("🔐 시스템 마스터 관리", width='stretch', type="primary" if st.session_state.admin_page else "secondary"):
    nav_to(st.session_state.current_line, is_admin=True)

# =================================================================
# 5. [관리자 모드] (기준 정보 및 CSV 기능)
# =================================================================
if st.session_state.admin_page:
    st.title("🔐 시스템 마스터 제어판")
    if not st.session_state.is_authenticated:
        _, a_col, _ = st.columns([1, 1.5, 1])
        with a_col:
            with st.container(border=True):
                st.subheader("관리자 인증")
                p_input = st.text_input("접속 비밀번호", type="password")
                if st.button("인증하기", width='stretch'):
                    if p_input == ADMIN_PASSWORD:
                        st.session_state.is_authenticated = True
                        st.rerun()
                    else: st.error("비밀번호 불일치")
    else:
        st.markdown("<div class='section-title'>📋 생산 기준 정보(Master) 설정</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            with st.container(border=True):
                st.write("**[모델 리스트]**")
                m_add = st.text_input("추가 모델명")
                if st.button("➕ 모델 등록", width='stretch'):
                    if m_add and m_add not in st.session_state.master_models:
                        st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
                st.divider()
                m_del = st.selectbox("삭제 모델", st.session_state.master_models)
                if st.button("🗑️ 모델 삭제", width='stretch'):
                    st.session_state.master_models.remove(m_del); st.rerun()
        with m_col2:
            with st.container(border=True):
                st.write("**[품목 코드]**")
                m_target = st.selectbox("대상 모델", st.session_state.master_models)
                i_add = st.text_input(f"신규 품목코드")
                if st.button("➕ 품목 등록", width='stretch'):
                    if i_add and i_add not in st.session_state.master_items_dict[m_target]:
                        st.session_state.master_items_dict[m_target].append(i_add); st.rerun()
                st.divider()
                i_del = st.selectbox("삭제 품목", st.session_state.master_items_dict.get(m_target, []))
                if st.button("🗑️ 품목 삭제", width='stretch'):
                    st.session_state.master_items_dict[m_target].remove(i_del); st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>📂 데이터베이스 관리</div>", unsafe_allow_html=True)
        u_col1, u_col2 = st.columns(2)
        with u_col1:
            with st.container(border=True):
                st.write("**📤 CSV 데이터 업로드**")
                uploaded_file = st.file_uploader("파일 선택", type=['csv'])
                if uploaded_file is not None:
                    st.session_state.production_db = pd.read_csv(uploaded_file); st.success("데이터 적용 완료")
        with u_col2:
            with st.container(border=True):
                st.write("**📥 데이터 백업 다운로드**")
                csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button(label="📊 전체 실적 다운로드", data=csv_data, file_name=f"MES_Backup_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", width='stretch')
                if st.button("⚠️ DB 초기화", width='stretch'):
                    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()
        
        if st.sidebar.button("🔓 로그아웃", width='stretch'):
            st.session_state.is_authenticated = False; st.session_state.admin_page = False; st.rerun()

# =================================================================
# 6. 조립 라인 (불량 상태 차단 & 대량 생산 로직)
# =================================================================
elif st.session_state.current_line == "조립 라인":
    st.title("📦 조립 공정 작업대")
    c_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    cols = st.columns(len(c_list))
    for i, cname in enumerate(c_list):
        if cols[i].button(cname, type="primary" if st.session_state.selected_cell == cname else "secondary", key=f"c_{cname}"):
            st.session_state.selected_cell = cname; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"📝 {st.session_state.selected_cell} 생산 투입 등록")
            r1, r2, r3 = st.columns(3)
            m_choice = r1.selectbox("모델 선택", ["선택"] + st.session_state.master_models)
            i_opts = st.session_state.master_items_dict.get(m_choice, []) if m_choice != "선택" else []
            i_choice = r2.selectbox("품목 선택", ["선택"] + i_opts)
            s_input = r3.text_input("시리얼 번호 스캔")
            
            if st.button("▶️ 생산 등록", type="primary", width='stretch'):
                if m_choice != "선택" and i_choice != "선택" and s_input:
                    db = st.session_state.production_db
                    # 대량 생산 규칙: 모델/품목/시리얼 3가지가 모두 중복될 때만 차단
                    duplicate = db[(db['모델'] == m_choice) & (db['품목코드'] == i_choice) & (db['시리얼'] == s_input)]
                    if not duplicate.empty: st.error(f"❌ 중복 시리얼: {s_input}은 이미 등록되어 있습니다.")
                    else:
                        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True); st.rerun()

    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if not l_db.empty:
        header = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        for col, lab in zip(header, ["시간", "CELL", "모델", "품목", "시리얼", "현황/제어"]): col.write(f"**{lab}**")
        for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
            row_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
            row_cols[0].write(row['시간']); row_cols[1].write(row['CELL']); row_cols[2].write(row['모델']); row_cols[3].write(row['품목코드']); row_cols[4].write(row['시리얼'])
            with row_cols[5]:
                # 불량 차단 핵심 로직
                if row['상태'] == "불량 처리 중":
                    st.markdown("<span class='bad-tag'>🚫 불량수리 대기 (잠금)</span>", unsafe_allow_html=True)
                elif row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    if row['상태'] == "수리 완료(재투입)": st.markdown("<span class='repair-tag'>수리완료</span>", unsafe_allow_html=True)
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("불량", key=f"ng_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                else: st.markdown("<span class='status-done'>🟢 조립완료</span>", unsafe_allow_html=True)

# =================================================================
# 7. 검사 및 포장 라인 (입고 프로세스 & 불량 잠금)
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_name = st.session_state.current_line
    st.title(f"{'🔍' if '검사' in line_name else '🚚'} {line_name} 현황")
    source_line = "조립 라인" if "검사" in line_name else "검사 라인"
    
    with st.container(border=True):
        st.subheader("📥 공정 입고 승인 대기")
        f1, f2 = st.columns(2)
        # 필터에서 '전체' 제거 (사용자 요청사항)
        sel_m = f1.selectbox("대상 모델 선택", st.session_state.master_models)
        sel_i = f2.selectbox("대상 품목 선택", st.session_state.master_items_dict.get(sel_m, []))
        
        db = st.session_state.production_db
        ready = db[(db['라인'] == source_line) & (db['상태'] == "완료") & (db['모델'] == sel_m) & (db['품목코드'] == sel_i)]
        done_sns = db[db['라인'] == line_name]['시리얼'].unique()
        avail_sns = [s for s in ready['시리얼'].unique() if s not in done_sns]
        
        if avail_sns:
            st.write(f"🔔 입고 가능 수량: {len(avail_sns)}건")
            grid = st.columns(4)
            for i, sn in enumerate(avail_sns):
                if grid[i % 4].button(f"🆔 {sn}", key=f"in_{line_name}_{sn}", width='stretch'):
                    st.session_state.confirm_target = sn; st.session_state.confirm_model = sel_m; st.session_state.confirm_item = sel_i; confirm_entry_dialog()
        else: st.info("입고 대기 물량이 없습니다.")

    st.divider()
    log_l = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    if not log_l.empty:
        header = st.columns([2.5, 1.5, 1.5, 2, 3])
        for col, lab in zip(header, ["시간", "모델", "품목", "시리얼", "최종판정"]): col.write(f"**{lab}**")
        for idx, row in log_l.sort_values('시간', ascending=False).iterrows():
            row_cols = st.columns([2.5, 1.5, 1.5, 2, 3])
            row_cols[0].write(row['시간']); row_cols[1].write(row['모델']); row_cols[2].write(row['품목코드']); row_cols[3].write(row['시리얼'])
            with row_cols[4]:
                if row['상태'] == "불량 처리 중":
                    st.markdown("<span class='bad-tag'>🚫 불량수리 대기</span>", unsafe_allow_html=True)
                elif row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("합격", key=f"ok_l_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                    if b2.button("불량", key=f"ng_l_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
                else: st.markdown("<span class='status-done'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# 8. 통합 생산 리포트 (차트 기능 무삭제)
# =================================================================
elif st.session_state.current_line == "리포트":
    st.title("📊 통합 생산 실적 리포트")
    db = st.session_state.production_db
    if not db.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("최종 포장 완료", f"{len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])} EA")
        m2.metric("현재 공정 중", f"{len(db[db['상태'] == '진행 중'])} EA")
        m3.metric("누적 불량 발생", f"{len(db[db['상태'].str.contains('불량', na=False)])} 건")
        m4.metric("수리 재투입", f"{len(db[db['상태'].str.contains('재투입', na=False)])} 건")
        
        st.divider()
        c1, c2 = st.columns([3, 2])
        with c1:
            line_sum = db[db['상태'] == '완료'].groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_sum, x='라인', y='수량', color='라인', text='수량', title="라인별 완료 실적"), use_container_width=True)
        with c2:
            model_sum = db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_sum, values='수량', names='모델', hole=0.3, title="투입 모델 비중"), use_container_width=True)
        
        st.subheader("📋 실시간 생산 로그 데이터")
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True)
    else: st.info("분석할 데이터가 존재하지 않습니다.")

# =================================================================
# 9. 불량 수리 센터 (수리 필수 입력 로직)
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.title("🛠️ 불량 수리 센터")
    db = st.session_state.production_db
    bad_list = db[db['상태'] == "불량 처리 중"]
    
    if bad_list.empty:
        st.success("✅ 모든 물량이 정상입니다. 수리 대기 중인 제품이 없습니다.")
    else:
        st.warning(f"총 {len(bad_list)}건의 수리 대기 건이 있습니다.")
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.write(f"**대상 S/N:** {row['시리얼']} | **모델:** {row['모델']} | **발생지:** {row['라인']}")
                r1, r2, r3 = st.columns([4, 4, 2])
                s_input = r1.text_input("불량 원인 상세", key=f"s_{idx}", placeholder="예: 구동부 소음")
                a_input = r2.text_input("수리 조치 내용", key=f"a_{idx}", placeholder="예: 구리스 도포")
                if r3.button("🔧 수리 완료 및 재투입", key=f"btn_r_{idx}", width='stretch'):
                    if s_input and a_input:
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = s_input
                        st.session_state.production_db.at[idx, '수리'] = a_input
                        st.success("수리 완료! 해당 공정에서 다시 완료 처리가 가능합니다."); st.rerun()
                    else: st.warning("증상과 조치 내용을 모두 입력해야 합니다.")
