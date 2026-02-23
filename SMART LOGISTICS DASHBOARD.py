import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [라이브러리 로드] 구글 드라이브 API 및 인증 관련
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 환경 설정 (System Configurations)
# =================================================================
# 애플리케이션의 기본 페이지 설정 및 레이아웃 정의
st.set_page_config(
    page_title="생산 통합 관리 시스템 v17.3",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST) 타임존 설정
# 서버의 위치와 관계없이 모든 시간 기록을 한국 시간으로 통일합니다.
KST = timezone(timedelta(hours=9))

# 사용자 그룹별 권한(Role-Based Access Control) 정의
# 각 권한에 따라 사이드바 메뉴 노출 여부가 결정됩니다.
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [UI 디자인 스타일 시트] - v9.1 오리지널 스타일 복구
# 섹션 타이틀의 파란색 포인트와 가독성 높은 레이아웃을 정의합니다.
st.markdown("""
    <style>
    /* 전체 앱 컨테이너 너비를 1200px로 제한하여 가독성 확보 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 공용 버튼 스타일: 현장 작업자의 터치/클릭 편의성 증대 */
    .stButton button { 
        margin-top: 0px; 
        padding: 4px 12px; 
        width: 100%; 
        border-radius: 6px;
        font-weight: 500;
    }
    
    /* 제목 및 텍스트 중앙 정렬 정의 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 25px 0; 
    }
    
    /* v9.1 스타일 섹션 타이틀: 파란색 왼쪽 테두리 포인트 */
    .section-title { 
        background-color: #f8f9fa; 
        color: #111; 
        padding: 18px; 
        border-radius: 10px; 
        font-weight: bold; 
        margin-bottom: 22px; 
        border-left: 10px solid #007bff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* 상태 표시용 색상 클래스 */
    .status-red { color: #e03131; font-weight: bold; }
    .status-green { color: #2f9e44; font-weight: bold; }
    
    /* 요약 통계 박스 (Stat Box) 디자인 */
    .stat-box {
        background-color: #f1f3f5; 
        border-radius: 12px; 
        padding: 20px; 
        text-align: center;
        border: 1px solid #dee2e6; 
        margin-bottom: 15px;
    }
    .stat-label { font-size: 0.95em; color: #495057; font-weight: bold; }
    .stat-value { font-size: 2.0em; color: #1971c2; font-weight: bold; }
    .stat-sub { font-size: 0.85em; color: #868e96; }
    
    /* 실시간 긴급 알림 배너 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 18px; 
        border-radius: 10px; 
        border: 1px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(201, 42, 42, 0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 유틸리티 함수 (Utility Functions)
# =================================================================

def get_now_kst():
    """
    현재 시스템 시간을 한국 표준시(KST) 기준으로 생성합니다.
    형식: YYYY-MM-DD HH:MM:SS
    """
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 스프레드시트 커넥션 초기화 (gsheets 연동)
conn = st.connection("gsheets", type=GSheetsConnection)

def load_realtime_data():
    """
    구글 시트로부터 실시간 생산 데이터를 가져옵니다.
    데이터 무결성을 위해 시리얼 번호의 소수점 표현을 정규화합니다.
    """
    try:
        # ttl=0 설정을 통해 캐시를 비활성화하고 매번 실시간 데이터를 읽어옵니다.
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 숫자로 자동 인식된 시리얼 번호 뒤의 .0을 제거합니다.
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터가 아예 없는 초기 구동 상태일 경우 표준 컬럼을 생성합니다.
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_gsheet(df):
    """
    업데이트된 데이터프레임을 클라우드 구글 시트에 저장합니다.
    저장 후 시스템 내부 캐시를 삭제하여 다음 조회 시 반영되게 합니다.
    """
    try:
        conn.update(data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"시트 업데이트 실패: {e}")

def drive_image_upload(file_obj, filename):
    """
    작업자가 업로드한 수리 사진을 구글 드라이브 특정 폴더로 전송합니다.
    성공 시 사진을 조회할 수 있는 webViewLink를 반환합니다.
    """
    try:
        # st.secrets에 등록된 서비스 계정 정보를 가져옵니다.
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 드라이브 API 서비스 생성
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 클라우드 폴더 ID가 설정되지 않았습니다."

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 실제 파일 업로드 명령 실행
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 업로드 실패 원인: {str(e)}"

# =================================================================
# 3. 세션 상태 관리 (Session State Initialization)
# =================================================================

# 생산 실적 데이터 초기화
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_realtime_data()

# 기본 계정 시스템 (관리자 admin 포함)
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

# 애플리케이션 로그인 및 권한 상태 제어
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 공정 기준 정보 (생산 가능 모델 및 품목 매핑)
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], 
        "EPS7133": ["7133-S", "7133-M"], 
        "T20i": ["T20i-P", "T20i-Premium"], 
        "T20C": ["T20C-S", "T20C-Standard"]
    }

# 현재 페이지 및 셀 선택 정보
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 화면 및 사이드바 내비게이션 (v17.2 디자인)
# =================================================================

# [로그인 인터페이스 처리]
if not st.session_state.login_status:
    _, login_col, _ = st.columns([1, 1.3, 1])
    with login_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("main_login"):
            input_id = st.text_input("아이디(ID)", placeholder="계정 아이디를 입력하세요")
            input_pw = st.text_input("비밀번호(PW)", type="password", placeholder="비밀번호를 입력하세요")
            
            if st.form_submit_button("로그인 진행", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    # 로그인 성공 시 권한에 따른 초기 페이지 지정
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 입력하신 계정 정보가 정확하지 않습니다.")
    st.stop()

# [사이드바 구성] - 사용자 요청 v17.2 디자인 반영
st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{st.session_state.user_id} 작업자**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def switch_page(p_name): 
    """사이드바 버튼 클릭 시 페이지를 전환합니다."""
    st.session_state.current_line = p_name
    st.rerun()

# 접속한 계정의 권한 목록 가져오기
access_list = ROLES.get(st.session_state.user_role, [])

# 공정 및 리포트 메뉴 버튼
if "조립 라인" in access_list:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): 
        switch_page("조립 라인")
if "검사 라인" in access_list:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): 
        switch_page("검사 라인")
if "포장 라인" in access_list:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): 
        switch_page("포장 라인")
if "리포트" in access_list:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): 
        switch_page("리포트")

st.sidebar.divider()
# 불량 관리 메뉴 버튼
if "불량 공정" in access_list:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): 
        switch_page("불량 공정")
if "수리 리포트" in access_list:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): 
        switch_page("수리 리포트")

# 관리자 전용 메뉴
if st.session_state.user_role == "admin" or "마스터 관리" in access_list:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        switch_page("마스터 관리")

# [실시간 모니터링 알림] - 수리 대기 건수가 있을 때 모든 페이지 상단 노출
active_bad_count = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if active_bad_count > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 상황 전파: 수리 대기 중인 불량 제품이 {active_bad_count}건 있습니다. 확인 부탁드립니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 (Core Logic)
# =================================================================

@st.dialog("📦 공정 단계 입고 승인")
def popup_confirm_entry():
    """
    제품이 다음 공정으로 이동할 때 호출됩니다.
    기존의 시리얼 행을 찾아서 '업데이트'만 수행하여 1인 1행 원칙을 지킵니다.
    """
    st.warning(f"승인 대상 시리얼: [ {st.session_state.confirm_target} ]")
    st.info(f"이동 목표 공정: {st.session_state.current_line}")
    st.write("입고를 승인하면 현재 시간과 작업자 정보로 데이터가 갱신됩니다.")
    
    col_a, col_b = st.columns(2)
    if col_a.button("✅ 최종 승인", type="primary", use_container_width=True):
        db_main = st.session_state.production_db
        # 시리얼 번호를 고유 키로 사용하여 행 인덱스 검색
        target_rows = db_main[db_main['시리얼'] == st.session_state.confirm_target].index
        if not target_rows.empty:
            idx = target_rows[0]
            db_main.at[idx, '시간'] = get_now_kst()
            db_main.at[idx, '라인'] = st.session_state.current_line
            db_main.at[idx, '상태'] = '진행 중'
            db_main.at[idx, '작업자'] = st.session_state.user_id
            # 클라우드 시트에 변경 내역 반영
            push_to_gsheet(db_main)
            
        st.session_state.confirm_target = None
        st.success("입고 처리가 완료되었습니다."); st.rerun()
        
    if col_b.button("❌ 입고 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def draw_log_table_v9(line_name, btn_label="완료 처리"):
    """
    v9.1 스타일의 테이블 레이아웃을 사용하여 공정 로그를 렌더링합니다.
    작업 상태에 따라 완료/불량 버튼을 동적으로 생성합니다.
    """
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_source = st.session_state.production_db
    filtered_db = db_source[db_source['라인'] == line_name]
    
    # 조립 라인의 경우 각 CELL별로 로그를 분리하여 가독성 증대
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        filtered_db = filtered_db[filtered_db['CELL'] == st.session_state.selected_cell]
    
    if filtered_db.empty: 
        st.info("현재 해당 공정에 할당된 제품이 없습니다.")
        return
    
    # [v9.1 디자인] 컬럼 비중 유지: [2.5, 1, 1.5, 1.5, 2, 3]
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_titles = ["기록 시간", "공정구분", "모델", "코드", "S/N 시리얼", "현장 제어"]
    for col, txt in zip(h_cols, header_titles): 
        col.write(f"**{txt}**")
    
    # 최신 기록이 상단에 오도록 정렬하여 출력
    for idx, row in filtered_db.sort_values('시간', ascending=False).iterrows():
        row_c = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        row_c[0].write(row['시간'])
        row_c[1].write(row['CELL'])
        row_c[2].write(row['모델'])
        row_c[3].write(row['품목코드'])
        row_c[4].write(f"`{row['시리얼']}`")
        
        with row_c[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                act_a, act_b = st.columns(2)
                if act_a.button(btn_label, key=f"ok_idx_{idx}", type="secondary"):
                    db_source.at[idx, '상태'] = "완료"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_gsheet(db_source); st.rerun()
                if act_b.button("🚫불량", key=f"ng_idx_{idx}"):
                    db_source.at[idx, '상태'] = "불량 처리 중"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_gsheet(db_source); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴품질분석</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢조립완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 세부 페이지 렌더링 (Page Views)
# =================================================================

# --- 6-1. 조립 라인 페이지 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 현장 조립 라인 관리</h2>", unsafe_allow_html=True)
    
    # CELL(작업대) 선택 시스템 (v9.1 인터페이스 복구)
    work_cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    tab_cols = st.columns(len(work_cells))
    for i, name in enumerate(work_cells):
        if tab_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
            
    # 특정 CELL 선택 시에만 신규 제품 등록 폼 노출
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 제품 투입")
            model_pick = st.selectbox("생산 대상 모델", ["선택하세요."] + st.session_state.master_models, key=f"am_{st.session_state.selected_cell}")
            with st.form("assembly_entry_form"):
                fc1, fc2 = st.columns(2)
                item_pick = fc1.selectbox("세부 품목코드", st.session_state.master_items_dict.get(model_pick, []) if model_pick!="선택하세요." else ["모델 선택 대기"])
                serial_input = fc2.text_input("제품 시리얼(S/N) 스캔")
                
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if model_pick != "선택하세요." and serial_input:
                        db_current = st.session_state.production_db
                        # [규칙] 시리얼 중복 등록 절대 금지
                        if serial_input in db_current['시리얼'].values:
                            st.error(f"❌ 중복 오류: 시리얼 '{serial_input}'은 이미 투입된 제품입니다.")
                        else:
                            new_row_data = {
                                '시간': get_now_kst(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': model_pick, '품목코드': item_pick, '시리얼': serial_input, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_current, pd.DataFrame([new_row_data])], ignore_index=True)
                            push_to_gsheet(st.session_state.production_db); st.rerun()
    
    draw_log_table_v9("조립 라인", "완료")

# --- 6-2. 품질 / 포장 라인 페이지 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 실시간 품질 검사" if st.session_state.current_line == "검사 라인" else "🚚 제품 출하 포장"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 이전 공정 완료 제품 (입고 대기)</div>", unsafe_allow_html=True)
        db_ref = st.session_state.production_db
        # 이전 공정에서 '완료'된 항목 중 아직 현재 공정에 들어오지 않은 데이터 필터링
        wait_df = db_ref[(db_ref['라인'] == prev_line) & (db_ref['상태'] == "완료")]
        
        if not wait_df.empty:
            st.success(f"현재 총 {len(wait_df)}개의 제품이 입고 승인을 기다리고 있습니다.")
            grid_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if grid_cols[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_btn_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    popup_confirm_entry()
        else: 
            st.info("현재 입고 가능한 대기 물량이 없습니다. 공정 흐름을 확인하세요.")
            
    draw_log_table_v9(st.session_state.current_line, "합격처리" if st.session_state.current_line=="검사 라인" else "포장완료")

# --- 6-3. 통합 리포트 대시보드 (디자인 최적화 버전) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 대시보드</h2>", unsafe_allow_html=True)
    db_report = st.session_state.production_db
    
    if not db_report.empty:
        # 주요 운영 KPI 지표 산출
        q_total = len(db_report)
        q_finish = len(db_report[(db_report['라인'] == '포장 라인') & (db_report['상태'] == '완료')])
        q_wip = len(db_report[db_report['상태'] == '진행 중'])
        q_bad = len(db_report[db_report['상태'].str.contains("불량", na=False)])
        
        m_row = st.columns(4)
        m_row[0].metric("누적 총 투입", f"{q_total} EA")
        m_row[1].metric("최종 생산 실적", f"{q_finish} EA", delta=f"{q_finish}건")
        m_row[2].metric("현장 재공(WIP)", f"{q_wip} EA")
        m_row[3].metric("불량 발생 건수", f"{q_bad} 건", delta=q_bad, delta_color="inverse")
        
        st.divider()
        # [레이아웃] 막대 그래프 넓게(1.8), 도넛 그래프 작게(1.2) - v17.0 설정 반영
        layout_l, layout_r = st.columns([1.8, 1.2])
        
        with layout_l:
            # 1) 공정별 위치 바 차트 (격자선 및 정수 표기 적용)
            pos_summary = db_report.groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(
                pos_summary, x='라인', y='수량', color='라인', 
                title="<b>[공정 단계별 제품 분포]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_white"
            )
            fig_bar.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', 
                paper_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=50, b=20)
            )
            # [핵심] Y축 수량을 짝수가 아닌 1, 2, 3... 정수 단위로 표기
            fig_bar.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with layout_r:
            # 2) 모델 비중 도넛 차트 (물리적 크기 축소 설정)
            model_summary = db_report.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(
                model_summary, values='수량', names='모델', hole=0.5, 
                title="<b>[제품 모델별 비중]</b>",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            # 차트 높이를 350으로 축소하여 아담하게 배치
            fig_pie.update_layout(height=350, margin=dict(l=40, r=40, t=60, b=40))
            st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 통합 생산 관리 원장</div>", unsafe_allow_html=True)
        st.dataframe(db_report.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 아직 입력되지 않았습니다.")

# --- 6-4. 불량 수리 센터 (수리 업무 처리) ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치 관리</h2>", unsafe_allow_html=True)
    db_bad_handle = st.session_state.production_db
    wait_list = db_bad_handle[db_bad_handle['상태'] == "불량 처리 중"]
    
    # 상단 수리 업무 현황 대시보드
    sc1, sc2 = st.columns(2)
    with sc1: 
        st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 분석 대기 중</div><div class='stat-value' style='color:#e03131;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    with sc2:
        today_rep_ref = datetime.now(KST).strftime('%Y-%m-%d')
        finish_today = len(db_bad_handle[(db_bad_handle['상태'] == "수리 완료(재투입)") & (db_bad_handle['시간'].astype(str).str.contains(today_rep_ref))])
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 조치 완료</div><div class='stat-value' style='color:#2f9e44;'>{finish_today}</div></div>", unsafe_allow_html=True)

    if wait_list.empty: 
        st.success("✅ 현재 분석 및 조치가 필요한 불량 제품이 없습니다.")
    else:
        # 불량 제품별 조치 카드 생성
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.markdown(f"**대상 S/N: `{row['시리얼']}`** (모델: {row['모델']} / 발생: {row['라인']})")
                
                # [v17.1 레이아웃] 원인/내용 바로 밑에 이미지와 확정 버튼 배치
                # 1행: 입력 필드
                row1_c1, row1_c2 = st.columns(2)
                cause_text = row1_c1.text_input("⚠️ 불량 원인 분석", placeholder="원인을 기술하세요", key=f"rc_{idx}")
                action_text = row1_c2.text_input("🛠️ 수리 조치 사항", placeholder="조치 내용을 기술하세요", key=f"ra_{idx}")
                
                # 2행: 파일 업로드 및 버튼
                row2_c1, row2_c2 = st.columns([3, 1])
                img_file = row2_c1.file_uploader("📸 조치 증빙 사진 등록", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                
                # 버튼 세로 위치 조절을 위한 공백
                row2_c2.write("") 
                if row2_c2.button("✅ 수리 확정", key=f"rb_{idx}", type="primary", use_container_width=True):
                    if cause_text and action_text:
                        photo_url = ""
                        if img_file:
                            with st.spinner("증빙 사진 저장 중..."):
                                upload_res = drive_image_upload(img_file, f"REP_{row['시리얼']}.jpg")
                                if "http" in upload_res: photo_url = f" [증빙사진: {upload_res}]"
                        
                        # 데이터 업데이트 처리
                        db_bad_handle.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad_handle.at[idx, '증상'], db_bad_handle.at[idx, '수리'] = cause_text, action_text + photo_url
                        db_bad_handle.at[idx, '작업자'] = st.session_state.user_id
                        push_to_gsheet(db_bad_handle); st.rerun()
                    else:
                        st.error("필수 항목(원인 및 조치내용)을 입력해야 합니다.")

# --- 6-5. 수리 리포트 페이지 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 분석 이력 리포트</h2>", unsafe_allow_html=True)
    db_history = st.session_state.production_db
    repair_df = db_history[db_history['수리'] != ""]
    
    if not repair_df.empty:
        # 리포트 통계 시각화 (동일 레이아웃 적용)
        hl_col, hr_col = st.columns([1.8, 1.2])
        with hl_col:
            fig_h_bar = px.bar(repair_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 이슈 발생 빈도", template="plotly_white")
            fig_h_bar.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_h_bar, use_container_width=True)
        with hr_col:
            fig_h_pie = px.pie(repair_df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 품질 비중")
            fig_h_pie.update_layout(height=350)
            st.plotly_chart(fig_h_pie, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 불량 분석 및 조치 내역 원장</div>", unsafe_allow_html=True)
        st.dataframe(repair_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재 기록된 수리 내역이 존재하지 않습니다.")

# --- 6-6. 마스터 관리 (시스템 어드민) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 시스템 관리</h2>", unsafe_allow_html=True)
    
    # 2단계 관리자 인증 처리
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_v17_3"):
            master_pass = st.text_input("마스터 비밀번호 입력 (admin1234)", type="password")
            if st.form_submit_button("인증 실행"):
                if master_pass == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호가 올바르지 않습니다.")
    else:
        # 인증 성공 시 도구 노출
        if st.button("🔓 관리자 세션 종료(Lock)", use_container_width=True):
            st.session_state.admin_authenticated = False; switch_page("조립 라인")

        # [섹션 1] 기준정보 관리 도구
        st.markdown("<div class='section-title'>📋 생산 기준정보 및 DB 제어</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        
        with m_col1:
            with st.container(border=True):
                st.subheader("모델/품목 신규 등록")
                m_new_name = st.text_input("신규 생산 모델명")
                if st.button("모델 등록 확정", use_container_width=True):
                    if m_new_name and m_new_name not in st.session_state.master_models:
                        st.session_state.master_models.append(m_new_name)
                        st.session_state.master_items_dict[m_new_name] = []; st.rerun()
                st.divider()
                m_sel_target = st.selectbox("품목 연결 모델 선택", st.session_state.master_models)
                i_new_code = st.text_input("신규 품목코드 명칭")
                if st.button("품목 등록 확정", use_container_width=True):
                    if i_new_code and i_new_code not in st.session_state.master_items_dict[m_sel_target]:
                        st.session_state.master_items_dict[m_sel_target].append(i_new_code); st.rerun()

        with m_col2:
            with st.container(border=True):
                st.subheader("백업 데이터 추출 및 복구")
                # CSV 백업 파일 생성 및 다운로드 버튼
                db_csv_buffer = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 실적 CSV 백업 다운로드", db_csv_buffer, f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # 백업 파일 업로드 및 병합(Merge) 로직
                f_upload = st.file_uploader("복구용 CSV 파일 업로드", type="csv")
                if f_upload and st.button("📤 데이터 로드 및 병합 실행", use_container_width=True):
                    try:
                        loaded_df = pd.read_csv(f_upload)
                        combined_db = pd.concat([st.session_state.production_db, loaded_df], ignore_index=True)
                        # 중복 시리얼은 가장 최신 기록만 남기고 필터링
                        st.session_state.production_db = combined_db.drop_duplicates(subset=['시리얼'], keep='last')
                        push_to_gsheet(st.session_state.production_db); st.rerun()
                    except: st.error("파일 구조 오류: 유효한 PMS 백업 파일이 아닙니다.")

        # [섹션 2] 사용자 계정 보안 관리
        st.divider()
        st.markdown("<div class='section-title'>👤 시스템 사용자 계정 및 권한 관리</div>", unsafe_allow_html=True)
        uc1, uc2, uc3 = st.columns([3, 3, 2])
        reg_id = uc1.text_input("신규 등록 ID")
        reg_pw = uc2.text_input("비밀번호 설정", type="password")
        reg_rl = uc3.selectbox("부여할 권한", ["user", "admin"])
        
        if st.button("계정 생성/정보 업데이트", use_container_width=True):
            if reg_id and reg_pw:
                st.session_state.user_db[reg_id] = {"pw": reg_pw, "role": reg_rl}
                st.success(f"사용자 '{reg_id}'의 정보가 정상적으로 반영되었습니다."); st.rerun()
        
        with st.expander("현재 시스템 등록 계정 전체 리스트"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        # [긴급 도구] 시스템 초기화
        if st.button("⚠️ 시스템 전체 실적 데이터 삭제 (초기화)", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_to_gsheet(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v17.3 배포용 통합 코드 종료 ]
# =================================================================



