import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [구글 서비스 연동을 위한 라이브러리]
# 서비스 계정 인증 및 드라이브 API 사용을 위한 설정
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# [1. 시스템 전역 설정]
# =================================================================
# 앱의 타이틀과 레이아웃(와이드 모드)을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v16.7",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST) 설정: 서버 위치에 상관없이 한국 시간으로 기록하기 위함
KST = timezone(timedelta(hours=9))

# 사용자 그룹별 권한(Role) 정의
# 각 라인 작업자와 관리자의 메뉴 접근 권한을 엄격히 분리합니다.
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
}

# [CSS 스타일 커스텀]
# 요청하신 이미지의 다크한 느낌과 전문적인 대시보드 UI를 구현하기 위한 스타일 시트입니다.
st.markdown("""
    <style>
    /* 메인 컨테이너 너비 제한 및 중앙 정렬 */
    .stApp { 
        max-width: 1400px; 
        margin: 0 auto; 
    }
    
    /* 버튼 공통 스타일: 현장 작업 편의를 위해 시인성을 높임 */
    .stButton button { 
        margin-top: 0px; 
        padding: 5px 15px; 
        width: 100%; 
        border-radius: 6px;
        font-weight: bold;
    }
    
    /* 제목 스타일: 다크 테마에 어울리는 밝은 텍스트 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 30px 0; 
        color: #f0f2f6;
        letter-spacing: -1px;
    }
    
    /* 긴급 불량 알림 배너: 시각적 경고 효과 극대화 */
    .alarm-banner { 
        background-color: #3d1414; 
        color: #ff5e5e; 
        padding: 20px; 
        border-radius: 12px; 
        border: 1px solid #ff4b4b; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(255, 75, 75, 0.15);
    }
    
    /* 대시보드 상단 통계 지표 박스 (Metric Box) */
    .stat-box {
        background-color: #1e2130; 
        border-radius: 12px; 
        padding: 22px; 
        text-align: center;
        border: 1px solid #3e445b; 
        margin-bottom: 18px;
        transition: all 0.2s ease-in-out;
    }
    .stat-box:hover {
        border-color: #00d4ff;
        background-color: #24293d;
    }
    .stat-label { font-size: 1.05em; color: #aab0c6; font-weight: bold; margin-bottom: 10px; }
    .stat-value { font-size: 2.3em; color: #00d4ff; font-weight: bold; }
    .stat-sub { font-size: 0.9em; color: #70758a; margin-top: 6px; }
    
    /* 섹션 타이틀 포인트 */
    .section-title { 
        font-size: 1.4em; 
        font-weight: bold; 
        margin: 35px 0 18px 0; 
        border-left: 6px solid #00d4ff; 
        padding-left: 15px; 
        color: #ffffff;
    }
    
    /* 다크 모드 사이드바 배경 */
    [data-testid="stSidebar"] {
        background-color: #0f121a;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# [2. 핵심 유틸리티 함수]
# =================================================================

def get_now_kst():
    """현재 한국 표준시를 'YYYY-MM-DD HH:MM:SS' 형식으로 반환합니다."""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 커넥션 객체 생성
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """구글 시트로부터 실시간 생산 데이터를 로드하고 전처리합니다."""
    try:
        # ttl=0 설정을 통해 캐시를 사용하지 않고 항상 시트의 최신 정보를 가져옵니다.
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 시리얼 번호가 소수점(.0)으로 표시되는 현상을 방지합니다.
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 시트 로드 실패 시 컬럼 구조만 갖춘 빈 데이터프레임을 생성합니다.
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """업데이트된 데이터프레임을 구글 시트에 즉시 저장하고 캐시를 초기화합니다."""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """불량 수리 사진을 구글 드라이브의 지정된 폴더에 업로드합니다."""
    try:
        # Secrets에서 구글 API 인증 정보를 로드합니다.
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 드라이브 API 서비스 객체를 생성합니다.
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 드라이브 폴더 ID 설정이 누락되었습니다."

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 파일 생성 및 업로드를 실행합니다.
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 업로드 실패: {str(e)}"

# =================================================================
# [3. 세션 상태(Session State) 초기화 관리]
# =================================================================

# 1) 생산 실적 데이터베이스 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 2) 마스터 사용자 계정 정보 정의
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }

# 3) UI 제어용 세션 상태 설정
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 4) 생산 기준 정보 초기화
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], 
        "EPS7133": ["7133-S", "7133-M"], 
        "T20i": ["T20i-P", "T20i-B"], 
        "T20C": ["T20C-S", "T20C-X"]
    }

if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [4. 로그인 인터페이스 및 사이드바 제어]
# =================================================================

# [로그인 화면 구성]
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.4, 1])
    with l_col:
        st.markdown("<h1 class='centered-title'>🛡️ PMS 통합 관리 시스템</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center; color:#888;'>Production Management & Tracking System</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            uid = st.text_input("계정 아이디", placeholder="아이디를 입력하세요")
            upw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
            
            login_btn = st.form_submit_button("시스템 접속하기", use_container_width=True)
            if login_btn:
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    # 접속 권한에 따른 첫 페이지 자동 이동
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 아이디 또는 비밀번호가 일치하지 않습니다.")
    st.stop()

# [사이드바 메뉴 구성]
st.sidebar.markdown("<h2 style='color:#00d4ff; text-align:center;'>🏭 PMS v16.7</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align:center;'><b>작업자:</b> {st.session_state.user_id}</p>", unsafe_allow_html=True)

if st.sidebar.button("🚪 안전하게 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 네비게이션 함수
def navigate_to(page_name): 
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한별 노출 메뉴 필터링
user_allowed = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 생산 공정
st.sidebar.caption("MAIN PROCESSES")
process_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "리포트":"📊"}
for page in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if page in user_allowed:
        label = f"{process_icons[page]} {page}"
        if page == "리포트": label = f"{process_icons[page]} 통합 대시보드"
        
        if st.sidebar.button(
            label, 
            use_container_width=True, 
            type="primary" if st.session_state.current_line == page else "secondary"
        ):
            navigate_to(page)

# 그룹 2: 품질 및 이력 관리
st.sidebar.divider()
st.sidebar.caption("QUALITY & HISTORY")
sub_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}
for page in ["불량 공정", "수리 리포트"]:
    if page in user_allowed:
        if st.sidebar.button(
            f"{sub_icons[page]} {page}", 
            use_container_width=True,
            type="primary" if st.session_state.current_line == page else "secondary"
        ):
            navigate_to(page)

# 그룹 3: 시스템 환경 설정
if "마스터 관리" in user_allowed:
    st.sidebar.divider()
    st.sidebar.caption("ADMINISTRATION")
    if st.sidebar.button(
        "🔐 마스터 기준 정보 관리", 
        use_container_width=True,
        type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"
    ):
        navigate_to("마스터 관리")

# 하단 불량 현황 알림 배너
pending_repair = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if pending_repair > 0:
    st.sidebar.warning(f"⚠️ 수리 대기 건수: {pending_repair}건")

# =================================================================
# [5. 공용 데이터 처리 엔진 (Update / Stats)]
# =================================================================

@st.dialog("📦 공정 단계 입고 확인")
def confirm_process_entry():
    """제품을 다음 공정으로 이동(Update)할 때 최종 확인하는 팝업 대화상자입니다."""
    st.warning(f"시리얼 번호: [ {st.session_state.confirm_target} ]")
    st.markdown(f"**현재 공정:** {st.session_state.current_line}")
    st.info("입고 승인 시 기존 데이터가 현재 공정 상태로 업데이트됩니다.")
    
    c1, c2 = st.columns(2)
    if c1.button("✅ 입고 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심 로직] 시리얼 번호를 기준으로 기존 행을 찾아 업데이트 (1제품 1행 방식)
        found_idx = db[db['시리얼'] == st.session_state.confirm_target].index
        if not found_idx.empty:
            target_idx = found_idx[0]
            db.at[target_idx, '시간'] = get_now_kst()
            db.at[target_idx, '라인'] = st.session_state.current_line
            db.at[target_idx, '상태'] = '진행 중'
            db.at[target_idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
            
        st.session_state.confirm_target = None
        st.rerun()
        
    if c2.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def display_page_stats(line_name):
    """각 페이지 상단에 위치하여 금일 생산 투입/완료/대기 수량을 보여줍니다."""
    db = st.session_state.production_db
    today_date = datetime.now(KST).strftime('%Y-%m-%d')
    
    # 해당 라인의 오늘 데이터 필터링
    today_data = db[(db['라인'] == line_name) & (db['시간'].astype(str).str.contains(today_date))]
    input_cnt = len(today_data)
    done_cnt = len(today_data[today_data['상태'] == '완료'])
    
    # 프로세스 버퍼(대기 물량) 계산
    buffer_cnt = 0
    prev_step = None
    if line_name == "검사 라인": prev_step = "조립 라인"
    elif line_name == "포장 라인": prev_step = "검사 라인"
    
    if prev_step:
        # 이전 단계에서 완료되었으나 아직 현재 단계로 넘어오지 않은 데이터
        buffer_cnt = len(db[(db['라인'] == prev_step) & (db['상태'] == '완료')])
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>⏳ {prev_step if prev_step else '신규'} 대기</div>
            <div class='stat-value' style='color:#ff9f43;'>{buffer_cnt if prev_step else '-'}</div>
            <div class='stat-sub'>공정 대기 물량</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>📥 금일 투입</div>
            <div class='stat-value'>{input_cnt}</div>
            <div class='stat-sub'>오늘 입고량</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>✅ 금일 완료</div>
            <div class='stat-value' style='color:#28c76f;'>{done_cnt}</div>
            <div class='stat-sub'>오늘 목표 달성</div>
        </div>""", unsafe_allow_html=True)

def render_process_log_table(line_filter, ok_label="완료 처리"):
    """각 공정 라인별로 현재 진행 중인 제품 리스트와 제어 버튼을 렌더링합니다."""
    st.markdown(f"<div class='section-title'>📋 {line_filter} 실시간 작업 현황</div>", unsafe_allow_html=True)
    
    db = st.session_state.production_db
    current_df = db[db['라인'] == line_filter]
    
    # 조립 라인의 경우 선택된 CELL 데이터만 상세히 보여줌
    if line_filter == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        current_df = current_df[current_df['CELL'] == st.session_state.selected_cell]
    
    if current_df.empty:
        st.info("현재 처리 중인 제품이 없습니다. 상단에서 입고를 먼저 진행하세요.")
        return
    
    # 표 헤더 출력
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    labels = ["업데이트 시간", "구분", "모델명", "품목코드", "시리얼 번호", "공정 제어"]
    for col, txt in zip(h_cols, labels):
        col.markdown(f"**{txt}**")
    
    # 데이터 행 반복 렌더링
    for idx, row in current_df.sort_values('시간', ascending=False).iterrows():
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        r_cols[0].write(row['시간'])
        r_cols[1].write(row['CELL'])
        r_cols[2].write(row['모델'])
        r_cols[3].write(row['품목코드'])
        r_cols[4].write(f"`{row['시리얼']}`")
        
        with r_cols[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_ok, b_ng = st.columns(2)
                if b_ok.button(ok_label, key=f"ok_{idx}", type="secondary"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db)
                    st.rerun()
                if b_ng.button("🚫 불량", key=f"ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db)
                    st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span style='color:#ff4b4b;'>🔴 불량 분석 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#28c76f;'>🟢 공정 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# [6. 페이지별 메인 렌더링 로직]
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 제품 조립 등록 및 관리</h2>", unsafe_allow_html=True)
    display_page_stats("조립 라인")
    
    st.divider()
    # 워크스테이션(CELL) 선택
    cells_list = ["CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    cell_tabs = st.columns(len(cells_list))
    for i, name in enumerate(cells_list):
        if cell_tabs[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary", use_container_width=True):
            st.session_state.selected_cell = name
            st.rerun()
            
    # 신규 시리얼 등록 양식
    with st.container(border=True):
        st.markdown(f"#### ➕ {st.session_state.selected_cell} 생산 투입 등록")
        # 셀 독립성 유지를 위해 고유 Key 사용
        model_sel = st.selectbox("생산 대상 모델", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
        
        with st.form(f"assembly_entry_{st.session_state.selected_cell}"):
            f1, f2 = st.columns(2)
            item_options = st.session_state.master_items_dict.get(model_sel, ["모델을 선택해 주세요"])
            item_sel = f1.selectbox("품목 코드 선택", item_options)
            sn_val = f2.text_input("시리얼 번호(S/N) 입력", placeholder="스캐너 또는 수동 입력")
            
            reg_btn = st.form_submit_button("신규 조립 생산 시작", type="primary", use_container_width=True)
            if reg_btn:
                if model_sel == "선택하세요." or not sn_val:
                    st.error("모델과 시리얼 번호를 정확히 입력해 주세요.")
                else:
                    full_db = st.session_state.production_db
                    # [규칙] 시리얼 중복 방지
                    if sn_val in full_db['시리얼'].values:
                        st.error(f"❌ 중복 오류: 시리얼 '{sn_val}'은 이미 시스템에 등록되어 있습니다.")
                    else:
                        new_row = {
                            '시간': get_now_kst(),
                            '라인': "조립 라인",
                            'CELL': st.session_state.selected_cell,
                            '모델': model_sel,
                            '품목코드': item_sel,
                            '시리얼': sn_val,
                            '상태': '진행 중',
                            '증상': '', '수리': '',
                            '작업자': st.session_state.user_id
                        }
                        st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new_row])], ignore_index=True)
                        save_to_gsheet(st.session_state.production_db)
                        st.success(f"성공: {sn_val} 제품이 조립 라인에 입고되었습니다.")
                        st.rerun()
    
    render_process_log_table("조립 라인")

# --- 6-2. 품질 검사 / 출하 포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    cur_page = st.session_state.current_line
    icon_map = {"검사 라인": "🔍", "포장 라인": "🚚"}
    st.markdown(f"<h2 class='centered-title'>{icon_map[cur_page]} {cur_page} 공정 관리</h2>", unsafe_allow_html=True)
    display_page_stats(cur_page)
    
    st.divider()
    st.markdown("<div class='section-title'>📥 입고 승인 대기 리스트</div>", unsafe_allow_html=True)
    
    # 이전 단계 완료 데이터 필터링
    prev_map = {"검사 라인": "조립 라인", "포장 라인": "검사 라인"}
    prev_step = prev_map[cur_page]
    
    db_ref = st.session_state.production_db
    wait_list = db_ref[(db_ref['라인'] == prev_step) & (db_ref['상태'] == "완료")]
    
    if not wait_list.empty:
        st.success(f"현재 {len(wait_list)}개의 제품이 이전 공정에서 입고를 기다리고 있습니다.")
        # 그리드 형태로 카드 배치
        grid = st.columns(4)
        for i, (idx, row) in enumerate(wait_list.iterrows()):
            with grid[i % 4]:
                with st.container(border=True):
                    st.markdown(f"**S/N: {row['시리얼']}**")
                    st.caption(f"{row['모델']} | {row['품목코드']}")
                    if st.button(f"공정 입고 승인", key=f"step_up_{idx}", use_container_width=True, type="primary"):
                        st.session_state.confirm_target = row['시리얼']
                        st.session_state.confirm_model = row['모델']
                        st.session_state.confirm_item = row['품목코드']
                        confirm_process_entry()
    else:
        st.info("이전 공정에서 입고 대기 중인 물량이 없습니다.")
        
    render_process_log_table(cur_page, ok_label="검사 합격" if cur_page == "검사 라인" else "출하 완료")

# --- 6-3. 통합 대시보드 (이미지 스타일 복구 버전) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 현황 통합 대시보드</h2>", unsafe_allow_html=True)
    
    # 상단 갱신 제어
    refresh_col, _ = st.columns([1, 4])
    if refresh_col.button("🔄 데이터 새로고침", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db = st.session_state.production_db
    if not db.empty:
        # 통합 KPI 분석
        total_p = len(db)
        final_p = len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])
        wip_p = len(db[db['상태'] == '진행 중'])
        error_p = len(db[db['상태'].str.contains("불량", na=False)])
        ftt_rate = (final_p / total_p * 100) if total_p > 0 else 0
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 투입량", f"{total_p} EA")
        k2.metric("최종 생산 완료", f"{final_p} EA", delta=f"{final_p}건")
        k3.metric("누적 불량 발생", f"{error_p} 건", delta=error_p, delta_color="inverse")
        k4.metric("공정 직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        
        # [복구] 이미지 e2eb1e 스타일 차트 구현부
        chart_c1, chart_c2 = st.columns([1, 2])
        
        with chart_c1:
            # 1) 공정별 제품 위치 바 차트 (이미지 색상 매핑 및 정수 표기 적용)
            pos_data = db.groupby('라인').size().reset_index(name='수량')
            # 라인 정렬 순서 강제
            pos_data['sort_val'] = pos_data['라인'].map({"조립 라인":0, "검사 라인":1, "포장 라인":2})
            pos_data = pos_data.sort_values('sort_val')
            
            fig_pos = px.bar(
                pos_data, 
                x='라인', 
                y='수량', 
                color='라인',
                title="<b>공정별 제품 위치</b>",
                color_discrete_map={
                    "검사 라인": "#A0D1FB", # 라이트 블루 (이미지 스타일)
                    "조립 라인": "#0068C9", # 블루 (이미지 스타일)
                    "포장 라인": "#FFABAB"  # 핑크/코랄 (이미지 스타일)
                },
                template="plotly_dark"
            )
            
            # [핵심 수정] Y축 수량 정수 표기 고정 및 디자인 세부 조정
            fig_pos.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                xaxis_title="라인",
                yaxis_title="수량",
                showlegend=True,
                bargap=0.4 # 막대 너비 조절
            )
            # dtick=1을 사용하여 1, 2, 3 단위로 정수만 표시하게 함
            fig_pos.update_yaxes(dtick=1, rangemode='tozero', gridcolor='#333')
            
            st.plotly_chart(fig_pos, use_container_width=True)
            
        with chart_c2:
            # 2) 모델별 비중 파이 차트 (도넛 형태 및 다크 테마)
            pie_data = db.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(
                pie_data, 
                values='수량', 
                names='모델', 
                hole=0.45,
                title="<b>모델별 비중</b>",
                color_discrete_sequence=px.colors.qualitative.Pastel,
                template="plotly_dark"
            )
            fig_pie.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)'
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 생산 실적 원장</div>", unsafe_allow_html=True)
        # 전체 데이터프레임 최신순 정렬 출력
        st.dataframe(
            db.sort_values('시간', ascending=False), 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.warning("분석할 데이터가 존재하지 않습니다. 먼저 제품을 등록해 주세요.")

# --- 6-4. 불량 및 수리 관리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 완료 처리</h2>", unsafe_allow_html=True)
    
    full_db = st.session_state.production_db
    fail_list = full_db[full_db['상태'] == "불량 처리 중"]
    
    # 상단 수리 통계
    today_prefix = datetime.now(KST).strftime('%Y-%m-%d')
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>🛠️ 현재 수리 대기 물량</div>
            <div class='stat-value' style='color:#ff5e5e;'>{len(fail_list)}</div>
            <div class='stat-sub'>누적 불량 건수</div>
        </div>""", unsafe_allow_html=True)
    with sc2:
        today_repairs = len(full_db[(full_db['상태'] == "수리 완료(재투입)") & (full_db['시간'].astype(str).str.contains(today_prefix))])
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>✅ 금일 수리 완료 건</div>
            <div class='stat-value' style='color:#28c76f;'>{today_repairs}</div>
            <div class='stat-sub'>오늘의 복구 실적</div>
        </div>""", unsafe_allow_html=True)
        
    if fail_list.empty:
        st.success("현재 수리 대기 중인 불량 제품이 없습니다. 현장 품질이 양호합니다.")
    else:
        for idx, row in fail_list.iterrows():
            with st.container(border=True):
                st.markdown(f"#### 🚨 불량 관리 번호: {row['시리얼']}")
                st.write(f"**발생 위치:** {row['라인']} | **모델:** {row['모델']} | **담당:** {row['작업자']}")
                
                c_in, c_img, c_done = st.columns([4, 4, 2])
                with c_in:
                    s_val = st.text_input("불량 원인 상세", placeholder="예: 센서 접촉 불량", key=f"sv_{idx}")
                    a_val = st.text_input("수리 및 조치 사항", placeholder="예: 케이블 재결착 및 테스트", key=f"av_{idx}")
                with c_img:
                    f_up = st.file_uploader("수리 사진 등록(Drive)", type=['jpg','png','jpeg'], key=f"img_{idx}")
                    if f_up: st.image(f_up, width=150)
                with c_done:
                    st.write("") # 간격 보정
                    if st.button("수리 완료 & 재투입", key=f"repair_fin_{idx}", type="primary", use_container_width=True):
                        if not s_val or not a_val:
                            st.error("분석 원인과 조치 사항을 반드시 입력해야 합니다.")
                        else:
                            photo_link = ""
                            if f_up:
                                with st.spinner("이미지를 클라우드에 저장 중..."):
                                    res_link = upload_image_to_drive(f_up, f"REPAIR_{row['시리얼']}_{datetime.now(KST).strftime('%H%M')}.jpg")
                                    if "http" in res_link: photo_link = f" [사진 확인: {res_link}]"
                            
                            full_db.at[idx, '상태'] = "수리 완료(재투입)"
                            full_db.at[idx, '증상'] = s_val
                            full_db.at[idx, '수리'] = a_val + photo_link
                            full_db.at[idx, '작업자'] = st.session_state.user_id
                            save_to_gsheet(full_db)
                            st.rerun()

# --- 6-5. 수리 이력 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 분석 및 수리 완료 리포트</h2>", unsafe_allow_html=True)
    db_hist = st.session_state.production_db
    history_df = db_hist[db_hist['수리'] != ""]
    
    if history_df.empty:
        st.info("기록된 불량 수리 이력이 아직 없습니다.")
    else:
        # 수리 통계 차트
        rh1, rh2 = st.columns([1, 2])
        with rh1:
            fig_rh1 = px.bar(history_df.groupby('라인').size().reset_index(name='건수'), x='라인', y='건수', title="공정별 불량 빈도", template="plotly_dark")
            fig_rh1.update_yaxes(dtick=1) # 정수 표기 적용
            st.plotly_chart(fig_rh1, use_container_width=True)
        with rh2:
            st.plotly_chart(px.pie(history_df.groupby('모델').size().reset_index(name='건수'), values='건수', names='모델', title="모델별 불량 비중", template="plotly_dark"), use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 수리 조치 내역 원장</div>", unsafe_allow_html=True)
        st.dataframe(
            history_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']].sort_values('시간', ascending=False),
            use_container_width=True,
            hide_index=True
        )

# --- 6-6. 마스터 관리 (540줄 규모 유지를 위한 풀 로직) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리자 기준 정보 설정</h2>", unsafe_allow_html=True)
    
    # 관리자 세션 2차 인증
    if not st.session_state.admin_authenticated:
        _, auth_box, _ = st.columns([1, 1, 1])
        with auth_box:
            with st.form("admin_security_verify"):
                pass_field = st.text_input("관리자 전용 액세스 비밀번호", type="password")
                if st.form_submit_button("인증 실행"):
                    if pass_field in ["admin1234", "master1234"]:
                        st.session_state.admin_authenticated = True
                        st.rerun()
                    else: st.error("접근 권한이 없습니다.")
    else:
        # 인증 완료 시 노출되는 관리 도구
        if st.sidebar.button("🔓 관리자 세션 잠금"):
            st.session_state.admin_authenticated = False
            st.rerun()
            
        adm_t1, adm_t2, adm_t3 = st.tabs(["📋 기준 정보 관리", "👤 사용자 계정 관리", "💾 데이터베이스 제어"])
        
        with adm_t1:
            st.markdown("<div class='section-title'>📍 모델 및 품목 기준 정보 등록</div>", unsafe_allow_html=True)
            ac1, ac2 = st.columns(2)
            with ac1:
                with st.container(border=True):
                    st.subheader("신규 생산 모델 등록")
                    new_model_name = st.text_input("모델 명칭", placeholder="예: EPS9000")
                    if st.button("모델 리스트 추가", use_container_width=True):
                        if new_model_name and new_model_name not in st.session_state.master_models:
                            st.session_state.master_models.append(new_model_name)
                            st.session_state.master_items_dict[new_model_name] = []
                            st.success(f"성공: '{new_model_name}' 모델 등록 완료")
                            st.rerun()
            with ac2:
                with st.container(border=True):
                    st.subheader("모델별 품목코드 연결")
                    target_model = st.selectbox("품목을 추가할 모델 선택", st.session_state.master_models)
                    new_item_code = st.text_input("신규 품목코드", placeholder="예: 9000-PRO")
                    if st.button("품목 리스트 추가", use_container_width=True):
                        if new_item_code and new_item_code not in st.session_state.master_items_dict[target_model]:
                            st.session_state.master_items_dict[target_model].append(new_item_code)
                            st.success(f"성공: '{target_model}' 모델에 품목 '{new_item_code}' 등록")
                            st.rerun()
                            
        with adm_t2:
            st.markdown("<div class='section-title'>👥 시스템 접근 계정 관리</div>", unsafe_allow_html=True)
            with st.container(border=True):
                uc_1, uc_2, uc_3 = st.columns([3, 3, 2])
                target_uid = uc_1.text_input("사용자 ID 설정")
                target_upw = uc_2.text_input("비밀번호 설정", type="password")
                target_uro = uc_3.selectbox("부여할 권한 그룹", list(ROLES.keys()))
                
                if st.button("계정 생성 및 권한 업데이트", use_container_width=True):
                    if target_uid and target_upw:
                        st.session_state.user_db[target_uid] = {"pw": target_upw, "role": target_uro}
                        st.success(f"사용자 '{target_uid}' 정보가 업데이트되었습니다.")
                        st.rerun()
            
            st.write("**현재 시스템 등록 계정 정보**")
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
            
        with adm_t3:
            st.markdown("<div class='section-title'>📊 데이터 백업 및 복구 도구</div>", unsafe_allow_html=True)
            with st.container(border=True):
                st.write("**시스템 데이터 백업 (Export)**")
                current_raw = st.session_state.production_db
                csv_file = current_raw.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 전체 생산 데이터 CSV 다운로드",
                    data=csv_file,
                    file_name=f"PMS_BACKUP_{datetime.now(KST).strftime('%Y%m%d_%H%M')}.csv",
                    mime='text/csv',
                    use_container_width=True
                )
                
                st.divider()
                st.write("**시스템 데이터 복구 및 병합 (Import)**")
                file_load = st.file_uploader("복구할 CSV 파일을 선택하세요.", type="csv")
                if file_load and st.button("📤 데이터 로드 및 시트 업데이트", use_container_width=True):
                    try:
                        loaded_df = pd.read_csv(file_load)
                        # 중복 제거 병합 로직
                        merged_raw = pd.concat([st.session_state.production_db, loaded_df], ignore_index=True)
                        st.session_state.production_db = merged_raw.drop_duplicates(subset=['시리얼'], keep='last')
                        save_to_gsheet(st.session_state.production_db)
                        st.success("데이터 로드 및 시트 동기화 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"파일 구조 오류: {str(e)}")
                        
                st.divider()
                st.write("**전체 초기화 (Wipe Out)**")
                if st.button("⚠️ 시스템 초기화: 모든 생산 실적 데이터 삭제", type="secondary", use_container_width=True):
                    # 모든 실적 제거 및 빈 데이터셋 시트 전송
                    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()

# =================================================================
# [ PMS v16.7 배포 버전 종료 ]
# =================================================================
