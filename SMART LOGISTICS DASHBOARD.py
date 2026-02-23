import streamlit as st
import pandas as pd
from datetime import datetime
import io
import plotly.express as px

# =================================================================
# 1. 전역 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v8.8", layout="wide")

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .centered-title { text-align: center; font-weight: bold; margin-top: 20px; margin-bottom: 20px; }
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
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 세션 상태 초기화
# =================================================================
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}, "user1": {"pw": "user1234", "role": "user"}}
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'production_db' not in st.session_state:
    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리'])
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {"EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]}
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 3. 로그인 및 사이드바 내비게이션
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid, upw = st.text_input("ID"), st.text_input("PW", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status, st.session_state.user_id, st.session_state.user_role = True, uid, st.session_state.user_db[uid]["role"]
                    st.rerun()
                else: st.error("정보 오류")
    st.stop()

st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): st.session_state.login_status = False; st.rerun()
st.sidebar.divider()
def nav(name): st.session_state.current_line = name; st.rerun()

if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): nav("조립 라인")
if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): nav("검사 라인")
if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): nav("포장 라인")
if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): nav("리포트")
st.sidebar.divider()
if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): nav("불량 공정")
if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): nav("수리 리포트")
if st.session_state.user_role == "admin":
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav("마스터 관리")

# =================================================================
# 4. 공용 함수
# =================================================================
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': ''}
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.confirm_target = None; st.rerun()
    if c2.button("❌ 취소", use_container_width=True): st.session_state.confirm_target = None; st.rerun()

def display_process_log(line_name, ok_label="완료"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그 현황</h3>", unsafe_allow_html=True)
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    if l_db.empty: st.info("데이터 없음"); return
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for col, txt in zip(lh, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): col.write(f"**{txt}**")
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{line_name}_{idx}"): st.session_state.production_db.at[idx, '상태'] = "완료"; st.rerun()
                if b2.button("🚫불량", key=f"ng_{line_name}_{idx}"): st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"; st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span class='status-red'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else: st.markdown("<span class='status-green'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# 5. 메인 로직
# =================================================================

# --- 5.1 조립/검사/포장 로직 (생략 없이 통합) ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 작업</h2>", unsafe_allow_html=True)
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): st.session_state.selected_cell = c; st.rerun()
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"ms_{st.session_state.selected_cell}")
            with st.form(f"asm_f_{st.session_state.selected_cell}"):
                r1, r2 = st.columns(2)
                i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델 선택 필요"])
                s_input = r2.text_input("시리얼 번호")
                if st.form_submit_button("▶️ 조립 등록", type="primary", use_container_width=True):
                    if m_choice != "선택하세요." and s_input:
                        db = st.session_state.production_db
                        if not db[(db['시리얼'] == s_input) & (db['상태'] != "완료")].empty: st.error("❌ 중복 등록 불가")
                        else:
                            new_data = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': ''}
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_data])], ignore_index=True); st.rerun()
    display_process_log("조립 라인", "완료")

elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"sm_{st.session_state.current_line}")
        si = f2.selectbox("품목 선택", ["품목 선택"] + st.session_state.master_items_dict.get(sm, []) if sm != "선택하세요." else ["품목 선택"], key=f"si_{st.session_state.current_line}")
        if sm != "선택하세요." and si != "품목 선택":
            db = st.session_state.production_db
            ready = db[(db['라인'] == prev_line) & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            avail = [s for s in ready['시리얼'].unique() if s not in db[db['라인'] == st.session_state.current_line]['시리얼'].unique()]
            if avail:
                st.success(f"📦 대기: {len(avail)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"입고: {sn}", key=f"btn_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
    display_process_log(st.session_state.current_line, "합격" if st.session_state.current_line=="검사 라인" else "출고")

# --- 5.2 리포트 및 수리 센터 (생략 없이 통합) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    if not db.empty:
        c1, c2 = st.columns([3, 2])
        with c1: st.plotly_chart(px.bar(db[db['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="라인별 실적"), use_container_width=True)
        with c2: st.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델 비중"), use_container_width=True)
        st.divider(); st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True)
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("대기 없음")
    else:
        line_icons = {"조립 라인": "📦 조립", "검사 라인": "🔍 품질", "포장 라인": "🚚 출하"}
        for idx, row in bad.iterrows():
            with st.container(border=True):
                icon = line_icons.get(row['라인'], "🏭 기타")
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']} / 발생: {icon})")
                c1, c2, c3 = st.columns([4, 4, 2])
                sv = c1.text_input("원인", key=f"s_{idx}")
                av = c2.text_input("조치", key=f"a_{idx}")
                if c3.button("✅ 수리 완료", key=f"r_{idx}", use_container_width=True, disabled=not(sv.strip() and av.strip())):
                    st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                    st.session_state.production_db.at[idx, '증상'], st.session_state.production_db.at[idx, '수리'] = sv, av
                    st.rerun()

elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 리포트</h2>", unsafe_allow_html=True)
    rep_db = st.session_state.production_db[st.session_state.production_db['상태'].str.contains("재투입", na=False)]
    if not rep_db.empty:
        st.plotly_chart(px.bar(rep_db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="발생 라인별 수리 건수"), use_container_width=True)
        st.dataframe(rep_db[['시간', '라인', '모델', '시리얼', '증상', '수리']], use_container_width=True, hide_index=True)

# =================================================================
# 6. 마스터 관리 (업로드 / 다운로드 기능 복구)
# =================================================================
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_v"):
            apw = st.text_input("관리자 PW", type="password")
            if st.form_submit_button("인증"):
                if apw == "admin1234": st.session_state.admin_authenticated = True; st.rerun()
    else:
        if st.button("🔓 인증 종료"): st.session_state.admin_authenticated = False; nav("조립 라인")
        
        # --- [복구된 데이터 업로드/다운로드 섹션] ---
        st.markdown("<div class='section-title'>💾 데이터 백업 및 외부 파일 로드</div>", unsafe_allow_html=True)
        down_col, up_col = st.columns(2)
        
        with down_col:
            st.write("**현재 데이터 내보내기**")
            csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(label="📥 생산 로그 CSV 다운로드", data=csv, file_name=f"prod_log_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        
        with up_col:
            st.write("**외부 데이터 불러오기**")
            uploaded_file = st.file_uploader("CSV 파일 선택", type="csv")
            if uploaded_file is not None:
                if st.button("📤 데이터 로드 (병합)", use_container_width=True):
                    try:
                        new_df = pd.read_csv(uploaded_file)
                        st.session_state.production_db = pd.concat([st.session_state.production_db, new_df], ignore_index=True)
                        st.success("데이터 로드 완료!"); st.rerun()
                    except Exception as e: st.error(f"오류: {e}")

        st.divider()
        st.markdown("<div class='section-title'>📋 기준정보 설정</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1:
            nm = st.text_input("신규 모델명")
            if st.button("모델 추가"):
                if nm and nm not in st.session_state.master_models: st.session_state.master_models.append(nm); st.session_state.master_items_dict[nm] = []; st.rerun()
        with m2:
            sel_m = st.selectbox("모델 선택", st.session_state.master_models)
            ni = st.text_input("신규 품목코드")
            if st.button("품목 추가"):
                if ni and ni not in st.session_state.master_items_dict[sel_m]: st.session_state.master_items_dict[sel_m].append(ni); st.rerun()
        
        st.divider()
        if st.button("⚠️ 전체 DB 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리']); st.rerun()
