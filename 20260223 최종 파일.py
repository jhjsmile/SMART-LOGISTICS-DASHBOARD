import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v12.5", layout="wide")

# [고도화] 권한별 메뉴 접근 제어 목록
ROLES = {
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "manager": ["조립 라인", "검사 라인", "포장 라인", "리포트", "수리 리포트"],
    "worker": ["조립 라인", "검사 라인", "포장 라인", "불량 공정"]
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; }
    .section-title { 
        background-color: #f8f9fa; color: #000; padding: 15px; border-radius: 8px; 
        font-weight: bold; margin-bottom: 20px; border-left: 8px solid #007bff;
    }
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    .alarm-banner { 
        background-color: #fff5f5; color: #c92a2a; padding: 15px; 
        border-radius: 8px; border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 20px;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 연결 및 데이터 핸들링
# =================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        # 캐시 없이(ttl=0) 항상 최신 데이터를 가져옴
        return conn.read(ttl=0).fillna("")
    except:
        # 시트 로드 실패 시 빈 데이터프레임 반환 (컬럼 포맷 유지)
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    conn.update(data=df)
    st.cache_data.clear()

# =================================================================
# 3. 세션 상태 초기화 (v9.1 변수 + 고도화 변수)
# =================================================================
if 'production_db' not in st.session_state: st.session_state.production_db = load_data()
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {"EPS7150": ["7150-A"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]}
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# 4. 로그인 및 사이드바 (UI 배치 완벽 복구)
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status, st.session_state.user_id = True, uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.rerun()
                else: st.error("계정 정보를 확인하세요.")
    st.stop()

# 사이드바 상단
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): st.session_state.login_status = False; st.rerun()
st.sidebar.divider()

def nav(name): st.session_state.current_line = name; st.rerun()

# [메뉴 권한 필터링]
allowed = ROLES.get(st.session_state.user_role, ["조립 라인"])

# 그룹 1: 생산 및 리포트
menu_group_1 = ["조립 라인", "검사 라인", "포장 라인", "리포트"]
icons_1 = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "리포트":"📊"}

for m in menu_group_1:
    if m in allowed:
        label = f"{icons_1[m]} {m}" + (" 현황" if "라인" in m else "") + (" 통합 생산 리포트" if m == "리포트" else "")
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

# 그룹 2: 불량 수리 (구분선 후 배치 - v9.1 복구)
st.sidebar.divider()
menu_group_2 = ["불량 공정", "수리 리포트"]
icons_2 = {"불량 공정":"🛠️", "수리 리포트":"📈"}

for m in menu_group_2:
    if m in allowed:
        label = f"{icons_2[m]} {m}" + (" 센터" if m == "불량 공정" else "")
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

# 그룹 3: 관리자 (구분선 후 배치)
if st.session_state.user_role == "admin":
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"):
        nav("마스터 관리")

# [고도화] 지능형 알림 배너
bad_count = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_count > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_count}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 공용 컴포넌트 (v9.1 로직 복구 + 작업자 로그 추가)
# =================================================================
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        new_row = {
            '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': st.session_state.current_line, 
            'CELL': "-", '모델': st.session_state.confirm_model, '품목코드': st.session_state.confirm_item, 
            '시리얼': st.session_state.confirm_target, '상태': '진행 중', '증상': '', '수리': '', 
            '작업자': st.session_state.user_id # [고도화] 작업자 자동 기록
        }
        st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        save_to_gsheet(st.session_state.production_db)
        st.session_state.confirm_target = None; st.rerun()
    if c2.button("❌ 취소", use_container_width=True): st.session_state.confirm_target = None; st.rerun()

def display_process_log(line_name, ok_label="완료"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그 현황</h3>", unsafe_allow_html=True)
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty: st.info("데이터가 없습니다."); return
    
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for col, txt in zip(lh, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): col.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id # 완료 처리자 기록
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id # 불량 처리자 기록
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span class='status-red'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else: st.markdown("<span class='status-green'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 메인 페이지 로직 (v9.1 기능 전수 복구)
# =================================================================

# --- 6-1. 조립 라인 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
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
                i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델 선택 필요"])
                s_input = r2.text_input("시리얼 번호")
                if st.form_submit_button("▶️ 조립 등록", use_container_width=True, type="primary"):
                    if m_choice != "선택하세요." and s_input:
                        if not st.session_state.production_db[(st.session_state.production_db['시리얼'] == s_input) & (st.session_state.production_db['상태'] != "완료")].empty:
                            st.error("❌ 이미 진행 중인 시리얼입니다.")
                        else:
                            new_row = {
                                '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, 
                                '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
                            save_to_gsheet(st.session_state.production_db); st.rerun()
    display_process_log("조립 라인", "완료")

# --- 6-2. 품질/포장 라인 ---
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
                st.success(f"📦 대기 물량: {len(avail)}건")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"입고: {sn}", key=f"btn_{sn}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = sn, sm, si; confirm_entry_dialog()
            else: st.info("대기 물량이 없습니다.")
    display_process_log(st.session_state.current_line, "합격" if st.session_state.current_line=="검사 라인" else "출고")

# --- 6-3. 통합 리포트 ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 리포트</h2>", unsafe_allow_html=True)
    if st.button("🔄 최신 데이터 동기화"): st.session_state.production_db = load_data(); st.rerun()
    db = st.session_state.production_db
    if not db.empty:
        t_done = len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])
        t_ng = len(db[db['상태'].str.contains("불량", na=False)])
        ftt = (t_done / (t_done + t_ng) * 100) if (t_done + t_ng) > 0 else 100
        
        met = st.columns(4)
        met[0].metric("최종 생산", f"{t_done} EA")
        met[1].metric("진행 중", len(db[db['상태'] == '진행 중']))
        met[2].metric("누적 불량", f"{t_ng} 건", delta=t_ng, delta_color="inverse")
        met[3].metric("직행률(FTT)", f"{ftt:.1f}%")
        
        st.divider(); c1, c2 = st.columns([3, 2])
        with c1: st.plotly_chart(px.bar(db[db['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 실적"), use_container_width=True)
        with c2: st.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 비중"), use_container_width=True)
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 수리 센터 (입력보존 + 미리보기) ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True)
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']} / 발생: {row['라인']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                
                # 세션 캐시를 활용한 입력값 보존
                cache_s = st.session_state.repair_cache.get(f"s_{idx}", "")
                cache_a = st.session_state.repair_cache.get(f"a_{idx}", "")
                sv = c1.text_input("불량 원인", value=cache_s, key=f"s_{idx}")
                av = c2.text_input("수리 조치", value=cache_a, key=f"a_{idx}")
                st.session_state.repair_cache[f"s_{idx}"], st.session_state.repair_cache[f"a_{idx}"] = sv, av
                
                # 사진 미리보기 (UI 기능)
                up_f = st.file_uploader("수리 사진 미리보기", type=['jpg','png','jpeg'], key=f"img_{idx}")
                if up_f: st.image(up_f, width=250)
                
                if c3.button("✅ 수리 완료", key=f"r_{idx}", type="primary", use_container_width=True):
                    if sv and av:
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'], st.session_state.production_db.at[idx, '수리'] = sv, av
                        st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                        save_to_gsheet(st.session_state.production_db)
                        st.session_state.repair_cache.pop(f"s_{idx}", None); st.session_state.repair_cache.pop(f"a_{idx}", None)
                        st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 리포트</h2>", unsafe_allow_html=True)
    rep_db = st.session_state.production_db[(st.session_state.production_db['상태'].str.contains("재투입", na=False)) | (st.session_state.production_db['수리'] != "")]
    if not rep_db.empty:
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(rep_db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="라인별 수리 건수"), use_container_width=True)
        with c2: st.plotly_chart(px.pie(rep_db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="수리 모델 비중"), use_container_width=True)
        st.dataframe(rep_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# --- 6-6. 마스터 관리 (v9.1 UI 및 기능 복구) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 계정 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth"):
            apw = st.text_input("관리자 PW (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if apw == "admin1234": st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("인증 실패")
    else:
        if st.button("🔓 관리 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False; nav("조립 라인")

        st.markdown("<div class='section-title'>📋 기준정보 및 데이터 관리</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1:
            with st.container(border=True):
                st.subheader("모델 및 품목 등록")
                nm = st.text_input("신규 모델 추가")
                if st.button("모델 등록", use_container_width=True):
                    if nm and nm not in st.session_state.master_models:
                        st.session_state.master_models.append(nm); st.session_state.master_items_dict[nm] = []; st.rerun()
                st.divider()
                sm = st.selectbox("품목 등록용 모델 선택", st.session_state.master_models)
                ni = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록", use_container_width=True):
                    if ni and ni not in st.session_state.master_items_dict[sm]:
                        st.session_state.master_items_dict[sm].append(ni); st.rerun()

        with m2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 로드")
                csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 생산 데이터 다운로드 (CSV)", csv, f"backup_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                up_f = st.file_uploader("백업 파일 로드 (CSV)", type="csv")
                if up_f and st.button("📤 데이터 업로드 (병합)", use_container_width=True):
                    st.session_state.production_db = pd.concat([st.session_state.production_db, pd.read_csv(up_f)], ignore_index=True)
                    save_to_gsheet(st.session_state.production_db); st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👤 사용자 계정 관리 (ID/PW 부여)</div>", unsafe_allow_html=True)
        u_col1, u_col2, u_col3 = st.columns([3, 3, 2])
        new_uid = u_col1.text_input("신규 생성 ID")
        new_upw = u_col2.text_input("신규 생성 PW", type="password")
        new_role = u_col3.selectbox("권한 설정", ["user", "admin", "worker", "manager"])
        
        if st.button("계정 생성 및 업데이트", use_container_width=True):
            if new_uid and new_upw:
                st.session_state.user_db[new_uid] = {"pw": new_upw, "role": new_role}
                st.success(f"[{new_uid}] 계정 등록 완료"); st.rerun()
        
        with st.expander("현재 시스템 등록 계정 확인"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        if st.button("⚠️ 시스템 전체 DB 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db); st.rerun()
