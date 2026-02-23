import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io

# [라이브러리] 구글 드라이브 연동
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v16.4", layout="wide")

# [핵심] 사용자 역할(Role) 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
}

# 대한민국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

# CSS 스타일 정의
st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; }
    .alarm-banner { 
        background-color: #fff5f5; color: #c92a2a; padding: 15px; 
        border-radius: 8px; border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 20px;
        text-align: center;
    }
    .stat-box {
        background-color: #f0f2f6; border-radius: 10px; padding: 15px; text-align: center;
        border: 1px solid #e0e0e0; margin-bottom: 10px;
    }
    .stat-label { font-size: 0.9em; color: #555; font-weight: bold; }
    .stat-value { font-size: 1.8em; color: #007bff; font-weight: bold; }
    .stat-sub { font-size: 0.8em; color: #888; }
    .section-title { font-size: 1.2em; font-weight: bold; margin: 20px 0 10px 0; border-left: 5px solid #007bff; padding-left: 10px; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 및 드라이브 연결 함수
# =================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "폴더ID설정안됨"

        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"업로드실패({str(e)})"

# =================================================================
# 3. 세션 상태 초기화 및 기본 계정 설정
# =================================================================
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], 
        "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], 
        "T20C": ["T20C-S"]
    }
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# 4. 로그인 화면 및 사이드바 구성
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 계정 정보: master(전체), admin(관제), line1~3(현장)")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("계정 정보를 확인하세요.")
    st.stop()

# 사이드바 상단
st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.title(f"{st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def nav(name): 
    st.session_state.current_line = name
    st.rerun()

allowed = ROLES.get(st.session_state.user_role, [])

# 메뉴 그룹 1: 공정 및 리포트
menu_group_1 = ["조립 라인", "검사 라인", "포장 라인", "리포트"]
icons_1 = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "리포트":"📊"}
g1_ok = False
for m in menu_group_1:
    if m in allowed:
        g1_ok = True
        label = f"{icons_1[m]} {m}" + (" 현황" if "라인" in m else "") + (" 통합 대시보드" if m == "리포트" else "")
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

# 메뉴 그룹 2: 불량 및 수리
menu_group_2 = ["불량 공정", "수리 리포트"]
icons_2 = {"불량 공정":"🛠️", "수리 리포트":"📈"}
g2_ok = False
for m in menu_group_2:
    if m in allowed: 
        g2_ok = True

if g1_ok and g2_ok: 
    st.sidebar.divider()

for m in menu_group_2:
    if m in allowed:
        label = f"{icons_2[m]} {m}" + (" 센터" if m == "불량 공정" else "")
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

# 관리자 전용 메뉴
if "마스터 관리" in allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"):
        nav("마스터 관리")

# 하단 불량 알림
bad_count = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_count > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_count}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 공용 로직 (Update 방식 적용)
# =================================================================
@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심] 기존 행을 찾아 현재 라인으로 업데이트 (행 추가 금지)
        idx_list = db[db['시리얼'] == st.session_state.confirm_target].index
        if not idx_list.empty:
            idx = idx_list[0]
            db.at[idx, '시간'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
            db.at[idx, '라인'] = st.session_state.current_line
            db.at[idx, '상태'] = '진행 중'
            db.at[idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
        st.session_state.confirm_target = None
        st.rerun()
    if c2.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(current_line):
    db = st.session_state.production_db
    today_str = datetime.now(KST).strftime('%Y-%m-%d')
    today_current = db[(db['라인'] == current_line) & (db['시간'].astype(str).str.contains(today_str))].copy()
    
    today_input = len(today_current)
    today_output = len(today_current[today_current['상태'] == '완료'])

    buffer_count = 0
    prev_line = None
    if current_line == "검사 라인": prev_line = "조립 라인"
    elif current_line == "포장 라인": prev_line = "검사 라인"
    
    if prev_line:
        # 이전 단계가 '완료'이면서 아직 다음 단계로 입고되지 않은 데이터 카운트
        buffer_count = len(db[(db['라인'] == prev_line) & (db['상태'] == '완료')])
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev_line if prev_line else '신규'} 대기</div><div class='stat-value' style='color: #ff9800;'>{buffer_count if prev_line else '-'}</div><div class='stat-sub'>건 (누적)</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{today_input}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color: #28a745;'>{today_output}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)

def display_process_log(line_name, ok_label="완료"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    l_db = db[db['라인'] == line_name]
    
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty: 
        st.info("데이터가 없습니다.")
        return
    
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for col, txt in zip(lh, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): 
        col.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간'])
        lr[1].write(row['CELL'])
        lr[2].write(row['모델'])
        lr[3].write(row['품목코드'])
        lr[4].write(row['시리얼'])
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{idx}"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db)
                    st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db)
                    st.rerun()
            elif row['상태'] == "불량 처리 중": 
                st.markdown("<span style='color:red;'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else: 
                st.markdown("<span style='color:green;'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 메인 페이지 로직
# =================================================================

# --- 6-1. 조립 라인 (시리얼 중복 차단) ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인") 
    st.divider()

    cells = ["CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c
            st.rerun()
    
    with st.container(border=True):
        # 셀별 모델 독립 선택
        m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
        with st.form("asm_form"):
            r1, r2 = st.columns(2)
            i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델 선택 필요"])
            s_input = r2.text_input("시리얼 번호")
            if st.form_submit_button("▶️ 조립 등록", use_container_width=True, type="primary"):
                if m_choice != "선택하세요." and s_input:
                    db = st.session_state.production_db
                    # [규칙] 시리얼 중복 등록 차단
                    if s_input in db['시리얼'].values:
                        st.error(f"❌ '{s_input}'은(는) 이미 등록된 시리얼입니다. 중복 등록이 불가합니다.")
                    else:
                        new_row = {
                            '시간': datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'), 
                            '라인': "조립 라인", 
                            'CELL': st.session_state.selected_cell, 
                            '모델': m_choice, 
                            '품목코드': i_choice, 
                            '시리얼': s_input, 
                            '상태': '진행 중', 
                            '증상': '', 
                            '수리': '', 
                            '작업자': st.session_state.user_id
                        }
                        st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                        save_to_gsheet(st.session_state.production_db)
                        st.rerun()
    display_process_log("조립 라인")

# --- 6-2. 품질/포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    display_line_flow_stats(st.session_state.current_line) 
    st.divider()

    with st.container(border=True):
        db = st.session_state.production_db
        # 이전 공정이 완료된 항목만 필터링
        ready_items = db[(db['라인'] == prev_line) & (db['상태'] == "완료")]
        
        if not ready_items.empty:
            st.success(f"📦 입고 가능 대기: {len(ready_items)}건")
            grid = st.columns(4)
            for i, (idx, row) in enumerate(ready_items.iterrows()):
                if grid[i % 4].button(f"입고: {row['시리얼']}", key=f"btn_{row['시리얼']}"):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    confirm_entry_dialog()
        else: 
            st.info("입고 대기 중인 물량이 없습니다.")
            
    display_process_log(st.session_state.current_line, "합격" if st.session_state.current_line=="검사 라인" else "출고")

# --- 6-3. 통합 리포트 (막대 그래프 1/3 고정) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 대시보드</h2>", unsafe_allow_html=True)
    if st.button("🔄 최신 데이터 동기화"): 
        st.session_state.production_db = load_data()
        st.rerun()
        
    db = st.session_state.production_db
    if not db.empty:
        # 1인 1행이므로 len(db)가 곧 총 생산 수량
        t_done = len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])
        t_ng = len(db[db['상태'].str.contains("불량", na=False)])
        ftt = (t_done / len(db) * 100) if len(db) > 0 else 100
        
        met = st.columns(4)
        met[0].metric("최종 생산(포장완료)", f"{t_done} EA")
        met[1].metric("공정 진행 중", len(db[db['상태'] == '진행 중']))
        met[2].metric("누적 불량 건수", f"{t_ng} 건", delta=t_ng, delta_color="inverse")
        met[3].metric("총 등록 수량", len(db))
        
        st.divider()
        # [레이아웃] 막대 1/3, 파이 2/3
        c1, c2 = st.columns([1, 2])
        with c1:
            fig1 = px.bar(db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 제품 위치")
            fig1.update_yaxes(rangemode='tozero')
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            st.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 비중"), use_container_width=True)
        
        st.divider()
        st.markdown("##### 👷 현장 작업자별 처리 건수")
        c3, _ = st.columns([1, 2]) # 1/3 크기 고정
        with c3:
            fig2 = px.bar(db.groupby('작업자').size().reset_index(name='건수'), x='작업자', y='건수', color='작업자')
            fig2.update_yaxes(rangemode='tozero')
            st.plotly_chart(fig2, use_container_width=True)
            
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True)
    
    db = st.session_state.production_db
    today_str = datetime.now(KST).strftime('%Y-%m-%d')
    repair_wait = len(db[db['상태'] == "불량 처리 중"])
    repair_done_today = len(db[(db['상태'] == "수리 완료(재투입)") & (db['시간'].astype(str).str.contains(today_str))])
    
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 수리 대기 건</div><div class='stat-value' style='color: #f44336;'>{repair_wait}</div><div class='stat-sub'>건 (누적)</div></div>", unsafe_allow_html=True)
    with sc2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 수리 완료</div><div class='stat-value' style='color: #28a745;'>{repair_done_today}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)

    bad_list = db[db['상태'] == "불량 처리 중"]
    if bad_list.empty: 
        st.success("✅ 현재 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']} / 발생: {row['라인']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                
                sv = c1.text_input("불량 원인", key=f"s_{idx}")
                av = c2.text_input("수리 조치", key=f"a_{idx}")
                up_f = st.file_uploader("수리 사진 (Drive)", type=['jpg','png','jpeg'], key=f"img_{idx}")
                
                if c3.button("✅ 수리 완료", key=f"r_{idx}", type="primary", use_container_width=True):
                    if sv and av:
                        img_link = ""
                        if up_f:
                            with st.spinner("이미지 저장 중..."):
                                link_res = upload_image_to_drive(up_f, f"{row['시리얼']}_{datetime.now(KST).strftime('%H%M')}.jpg")
                                if "http" in link_res: img_link = f" [사진: {link_res}]"
                        
                        db.at[idx, '상태'] = "수리 완료(재투입)"
                        db.at[idx, '증상'] = sv
                        db.at[idx, '수리'] = av + img_link
                        db.at[idx, '작업자'] = st.session_state.user_id
                        save_to_gsheet(db)
                        st.success("수리 처리 완료!"); st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    rep_db = db[db['수리'] != ""]
    
    if not rep_db.empty:
        c_r1, c_r2 = st.columns([1, 2])
        with c_r1:
            fig_r1 = px.bar(rep_db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="라인별 수리 건수")
            fig_r1.update_yaxes(rangemode='tozero')
            st.plotly_chart(fig_r1, use_container_width=True)
        with c_r2:
            st.plotly_chart(px.pie(rep_db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="수리 모델 비중"), use_container_width=True)
        
        st.dataframe(rep_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("수리 내역이 존재하지 않습니다.")

# --- 6-6. 마스터 관리 (100% 완벽 복구) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 계정 관리</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth_form"):
            apw = st.text_input("관리자 비밀번호를 입력하세요.", type="password")
            if st.form_submit_button("인증하기"):
                if apw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else: 
                    st.error("비밀번호가 일치하지 않습니다.")
    else:
        if st.button("🔓 관리자 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False
            nav("리포트")

        st.markdown("<div class='section-title'>📋 기준정보 관리 (모델/품목)</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            with st.container(border=True):
                st.subheader("모델 등록")
                new_m = st.text_input("신규 모델명")
                if st.button("모델 추가", use_container_width=True):
                    if new_m and new_m not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m)
                        st.session_state.master_items_dict[new_m] = []
                        st.rerun()
                st.divider()
                sel_m = st.selectbox("품목 등록할 모델 선택", st.session_state.master_models)
                new_i = st.text_input("신규 품목코드")
                if st.button("품목 추가", use_container_width=True):
                    if new_i and new_i not in st.session_state.master_items_dict[sel_m]:
                        st.session_state.master_items_dict[sel_m].append(new_i)
                        st.rerun()
        with m_col2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 복구")
                csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 DB 다운로드 (CSV)", csv_data, f"backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                uploaded_csv = st.file_uploader("백업 파일 업로드 (기존 데이터와 병합)", type="csv")
                if uploaded_csv and st.button("📤 데이터 병합 실행", use_container_width=True):
                    merged_db = pd.concat([st.session_state.production_db, pd.read_csv(uploaded_csv)], ignore_index=True)
                    st.session_state.production_db = merged_db.drop_duplicates(subset=['시리얼'], keep='last')
                    save_to_gsheet(st.session_state.production_db)
                    st.success("데이터 병합 및 시트 업데이트 완료!")
                    st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👤 사용자 계정 관리</div>", unsafe_allow_html=True)
        u_col1, u_col2, u_col3 = st.columns([3, 3, 2])
        u_id = u_col1.text_input("계정 ID")
        u_pw = u_col2.text_input("계정 PW", type="password")
        u_ro = u_col3.selectbox("권한", list(ROLES.keys()))
        
        if st.button("사용자 등록/수정", use_container_width=True):
            if u_id and u_pw:
                st.session_state.user_db[u_id] = {"pw": u_pw, "role": u_ro}
                st.success(f"'{u_id}' 계정이 성공적으로 등록/수정되었습니다.")
                st.rerun()
        
        with st.expander("현재 시스템 등록 계정 목록 보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        if st.button("⚠️ 시스템 전체 데이터 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db)
            st.rerun()
