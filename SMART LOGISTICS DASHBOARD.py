import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리 (수리 사진 저장용)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의 (상세 스타일 복구)
# =================================================================
# 애플리케이션의 기본적인 페이지 설정을 수행합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.3", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 메뉴 권한 설정
# 각 계정별로 노출될 메뉴를 엄격하게 제한합니다.
# 특히 line4 계정은 repair_team 권한을 통해 수리 센터만 접근하게 됩니다.
ROLES = {
    "master": [
        "조립 라인", 
        "검사 라인", 
        "포장 라인", 
        "생산 리포트", 
        "불량 공정", 
        "수리 리포트", 
        "마스터 관리"
    ],
    "control_tower": [
        "생산 리포트", 
        "수리 리포트", 
        "마스터 관리"
    ],
    "assembly_team": [
        "조립 라인"
    ],
    "qc_team": [
        "검사 라인", 
        "불량 공정"
    ],
    "packing_team": [
        "포장 라인"
    ],
    "repair_team": [
        "불량 공정"
    ]
}

# CSS를 활용한 UI 디자인 정의
st.markdown("""
    <style>
    /* 전체 앱의 최대 너비를 조절합니다. */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼의 패딩과 너비를 최적화합니다. */
    .stButton button { 
        margin-top: 0px; 
        padding: 5px 10px; 
        width: 100%; 
    }
    
    /* 제목을 중앙에 배치하고 글꼴을 강조합니다. */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 25px 0; 
    }
    
    /* 불량 발생 시 시각적 알림을 주는 배너 스타일입니다. */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 15px; 
        border-radius: 10px; 
        border: 2px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
    }
    
    /* 상단 대시보드 통계 카드의 스타일입니다. */
    .stat-box {
        background-color: #f8f9fa; 
        border-radius: 12px; 
        padding: 20px; 
        text-align: center;
        border: 1px solid #dee2e6; 
        margin-bottom: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    
    .stat-label { 
        font-size: 0.95em; 
        color: #495057; 
        font-weight: bold; 
        margin-bottom: 5px;
    }
    
    .stat-value { 
        font-size: 2em; 
        color: #0d6efd; 
        font-weight: bold; 
    }
    
    .stat-sub { 
        font-size: 0.85em; 
        color: #6c757d; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 연동 및 데이터 관리 함수 (데이터 보호 강화)
# =================================================================
# 구글 시트 연결 객체를 생성합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 생성하여 반환하는 함수입니다."""
    return datetime.now() + timedelta(hours=9)

def load_data():
    """구글 시트에서 데이터를 안전하게 읽어오는 로직입니다."""
    try:
        # 데이터 시트 읽기 (캐시 없음)
        df = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호 데이터의 형식을 보정합니다.
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [데이터 보호] 로드 중 오류로 빈 값이 오면 세션을 유지하여 덮어쓰기를 방지합니다.
        if df.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
                
        return df
    except Exception as load_error:
        st.error(f"데이터 로드 실패: {load_error}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_command=False):
    """
    구글 시트에 데이터를 저장합니다. 
    is_reset_command가 True일 때만 빈 시트 저장을 허용합니다.
    """
    # [중요] 초기화 명령이 아닌데 데이터가 비어있으면 저장을 차단하여 사고를 방지합니다.
    if df.empty and not is_reset_command:
        st.error("❌ 시스템 보호: 비어있는 데이터가 감지되어 저장이 거부되었습니다. (새로고침 권장)")
        return False
    
    # API 요청 제한에 대비하여 3회 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            conn.update(data=df)
            st.cache_data.clear()
            return True
        except Exception as api_error:
            if attempt < 3:
                time.sleep(2)  # 2초 대기 후 재시도
                continue
            else:
                st.error(f"⚠️ 구글 서버 저장 오류 (최종 실패): {api_error}")
                return False

def upload_image_to_drive(file_object, file_name):
    """수리 조치 사진을 구글 드라이브에 업로드합니다."""
    try:
        # 인증 정보 로드
        secrets_data = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(secrets_data)
        
        # 구글 드라이브 API 서비스 생성
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # 대상 폴더 아이디 조회
        target_folder = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder:
            return "설정오류: 폴더ID없음"

        # 메타데이터 설정
        metadata = {
            'name': file_name, 
            'parents': [target_folder]
        }
        
        # 파일 스트림 업로드 준비
        media_upload = MediaIoBaseUpload(file_object, mimetype=file_object.type)
        
        # 실제 업로드 수행
        uploaded_file = drive_service.files().create(
            body=metadata, 
            media_body=media_upload, 
            fields='id, webViewLink'
        ).execute()
        
        return uploaded_file.get('webViewLink')
    except Exception as upload_err:
        return f"업로드실패: {str(upload_err)}"

# =================================================================
# 3. 세션 상태(Session State) 초기화 관리
# =================================================================
# 애플리케이션의 영속성을 위해 세션 상태를 정의합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 시스템 기본 계정 정보 정의
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"},
        "line4": {"pw": "4444", "role": "repair_team"}
    }

if 'login_status' not in st.session_state:
    st.session_state.login_status = False

if 'user_role' not in st.session_state:
    st.session_state.user_role = None

if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False

if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], 
        "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], 
        "T20C": ["T20C-S"]
    }

if 'current_line' not in st.session_state:
    st.session_state.current_line = "조립 라인"

if 'selected_cell' not in st.session_state:
    st.session_state.selected_cell = "CELL 1"

if 'repair_cache' not in st.session_state:
    st.session_state.repair_cache = {}

# =================================================================
# 4. 사용자 인증 및 사이드바 구성
# =================================================================

# 미인증 사용자의 경우 로그인 화면을 렌더링합니다.
if not st.session_state.login_status:
    # 중앙 정렬을 위한 컬럼 배치
    _, center_col, _ = st.columns([1, 1.2, 1])
    
    with center_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 공지: 마스터 계정(master) 또는 담당 공정 계정으로 접속하세요.")
        
        with st.form("main_login_form"):
            login_id = st.text_input("아이디(ID)")
            login_pw = st.text_input("비밀번호(PW)", type="password")
            
            btn_login = st.form_submit_button("시스템 접속", use_container_width=True)
            
            if btn_login:
                # 계정 정보를 확인합니다.
                if login_id in st.session_state.user_db:
                    correct_pw = st.session_state.user_db[login_id]["pw"]
                    
                    if login_pw == correct_pw:
                        # 로그인 세션 활성화
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = login_id
                        st.session_state.user_role = st.session_state.user_db[login_id]["role"]
                        
                        # 권한에 따른 초기 메뉴 설정
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("입력하신 비밀번호가 올바르지 않습니다.")
                else:
                    st.error("등록되지 않은 아이디입니다.")
    st.stop()

# 사이드바 레이아웃
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("🔓 시스템 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환 함수
def navigate_to(page_name):
    st.session_state.current_line = page_name
    st.rerun()

# 권한에 기반한 동적 메뉴 생성
current_user_allowed = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 생산 공정 라인
menu_group_p = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_group_p = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for page in menu_group_p:
    if page in current_user_allowed:
        page_label = f"{icons_group_p[page]} {page}" + (" 현황" if "라인" in page else "")
        page_style = "primary" if st.session_state.current_line == page else "secondary"
        
        if st.sidebar.button(page_label, use_container_width=True, type=page_style):
            navigate_to(page)

# 그룹 2: 사후 관리 및 분석
menu_group_r = ["불량 공정", "수리 리포트"]
icons_group_r = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for page in menu_group_r:
    if page in current_user_allowed:
        page_label = f"{icons_group_r[page]} {page}"
        page_style = "primary" if st.session_state.current_line == page else "secondary"
        
        if st.sidebar.button(page_label, use_container_width=True, type=page_style):
            navigate_to(page)

# 그룹 3: 관리자 영역
if "마스터 관리" in current_user_allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_to("마스터 관리")

# 시스템 하단 불량품 존재 알림
current_bad_items = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not current_bad_items.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 수리 대기 물량이 {len(current_bad_items)}건 발견되었습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 로직 및 공용 UI 컴포넌트
# =================================================================

def check_and_add_marker(df, line_name):
    """지정된 생산 실적(10대) 달성 시 구분선 행을 시트에 추가합니다."""
    kst_today = get_kst_now().strftime('%Y-%m-%d')
    
    # 오늘 실적(구분선 제외) 개수를 파악합니다.
    current_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(kst_today)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대 달성 시마다 시각적 구분선을 삽입합니다.
    if current_count > 0 and current_count % 10 == 0:
        marker_data = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {current_count}대 생산 완료", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        return pd.concat([df, pd.DataFrame([marker_data])], ignore_index=True)
    return df

@st.dialog("📦 공정 이동 최종 확인")
def confirm_entry_dialog():
    """제품이 다음 단계로 넘어갈 때 단일 행의 상태를 업데이트합니다."""
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 제품을 '{st.session_state.current_line}'으로 입고 처리하시겠습니까?")
    st.write("승인 시 기존 공정 기록은 현재 공정으로 갱신됩니다.")
    
    col_ok, col_no = st.columns(2)
    
    if col_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_current = st.session_state.production_db
        
        # 모델과 시리얼 번호를 조합하여 대상 제품의 고유 행 인덱스를 찾습니다.
        target_row_idx = db_current[
            (db_current['모델'] == st.session_state.confirm_model) & 
            (db_current['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not target_row_idx.empty:
            idx = target_row_idx[0]
            
            # [단일 행 추적 핵심 로직] 기존 행의 공정 위치와 상태 정보를 갱신합니다.
            db_current.at[idx, '라인'] = st.session_state.current_line
            db_current.at[idx, '상태'] = '진행 중'
            db_current.at[idx, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db_current.at[idx, '작업자'] = st.session_state.user_id
            
            # 데이터 저장 및 새로고침
            if save_to_gsheet(db_current):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터베이스에서 해당 시리얼 번호를 찾을 수 없습니다.")
            
    if col_no.button("❌ 승인 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(line_name):
    """상단 통계 영역 렌더링 (대기물량 및 당일 실적 산출)"""
    db = st.session_state.production_db
    kst_today_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 해당 라인의 금일 투입 및 완료 수량
    current_line_data = db[
        (db['라인'] == line_name) & 
        (db['시간'].astype(str).str.contains(kst_today_str)) & 
        (db['상태'] != '구분선')
    ]
    
    total_in = len(current_line_data)
    total_done = len(current_line_data[current_line_data['상태'] == '완료'])
    
    # 이전 단계로부터 입고 대기 중인 물량 계산
    pending_count = 0
    previous_step = None
    
    if line_name == "검사 라인": previous_step = "조립 라인"
    elif line_name == "포장 라인": previous_step = "검사 라인"
    
    if previous_step:
        # 이전 공정에서 '완료' 상태가 되어 입고 처리를 기다리는 행들을 가져옵니다.
        pending_list = db[
            (db['라인'] == previous_step) & 
            (db['상태'] == '완료')
        ]
        pending_count = len(pending_list)
        
    # 시각적 지표 카드 렌더링
    st_col1, st_col2, st_col3 = st.columns(3)
    
    with st_col1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {previous_step if previous_step else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{pending_count if previous_step else '-'}</div>
                <div class='stat-sub'>건 (공정 간 재공)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{total_in}</div>
                <div class='stat-sub'>건 (당일 투입)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{total_done}</div>
                <div class='stat-sub'>건 (당일 완료)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, confirm_label="완료 처리"):
    """작업 로그 테이블 표시 및 공정 제어 버튼 제공"""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 생산 로그</h3>", unsafe_allow_html=True)
    
    full_db = st.session_state.production_db
    # 해당 라인 소속 물량만 추출
    log_view_db = full_db[full_db['라인'] == line_name]
    
    # 조립 라인의 경우 선택된 CELL 필터를 적용합니다.
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        log_view_db = log_view_db[log_view_db['CELL'] == st.session_state.selected_cell]
        
    if log_view_db.empty:
        st.info(f"현재 {line_name}에 표시할 데이터가 존재하지 않습니다.")
        return
        
    # 테이블 헤더 라인
    head_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_titles = ["기록시간", "CELL", "모델정보", "품목코드", "시리얼번호", "상태 변경 제어"]
    
    for i, title in enumerate(header_titles):
        head_cols[i].write(f"**{title}**")
        
    # 데이터 행 최신순으로 정렬하여 표시
    for idx, row in log_view_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행에 대한 시각적 처리
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f1f3f5; padding: 6px; text-align: center; border-radius: 6px; font-weight: bold; color: #495057; border: 1px dashed #ced4da;'>📦 {row['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        data_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        data_cols[0].write(row['시간'])
        data_cols[1].write(row['CELL'])
        data_cols[2].write(row['모델'])
        data_cols[3].write(row['품목코드'])
        data_cols[4].write(row['시리얼'])
        
        with data_cols[5]:
            status_now = row['상태']
            
            # 작업이 가능한 상태일 때만 버튼 노출
            if status_now in ["진행 중", "수리 완료(재투입)"]:
                col_btn1, col_btn2 = st.columns(2)
                
                if col_btn1.button(confirm_label, key=f"btn_done_{idx}"):
                    full_db.at[idx, '상태'] = "완료"
                    full_db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(full_db):
                        st.rerun()
                        
                if col_btn2.button("🚫 불량 발생", key=f"btn_bad_{idx}"):
                    full_db.at[idx, '상태'] = "불량 처리 중"
                    full_db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(full_db):
                        st.rerun()
                        
            elif status_now == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 대기 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 메뉴별 상세 렌더링 로직 (Workflow 및 초기화 수정)
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 페이지
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 필터링 인터페이스 구성
    cells_array = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_grid = st.columns(len(cells_array))
    
    for i, c_name in enumerate(cells_array):
        if btn_grid[i].button(c_name, type="primary" if st.session_state.selected_cell == c_name else "secondary"):
            st.session_state.selected_cell = c_name
            st.rerun()
            
    # 개별 셀이 선택되었을 때만 생산 등록 폼 표시
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 생산 등록")
            
            # 모델 선택
            target_model = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("new_assembly_form"):
                row_f1, row_f2 = st.columns(2)
                
                # 모델 기반 품목 리스트 로드
                items_available = st.session_state.master_items_dict.get(target_model, ["모델 정보 없음"])
                target_item = row_f1.selectbox("품목코드 선택", items_available)
                
                target_sn = row_f2.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 생산 기록 생성", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn != "":
                        db_ptr = st.session_state.production_db
                        
                        # [전수 중복 생산 체크]
                        dup_search = db_ptr[
                            (db_ptr['모델'] == target_model) & 
                            (db_ptr['시리얼'] == target_sn) & 
                            (db_ptr['상태'] != "구분선")
                        ]
                        
                        if not dup_search.empty:
                            st.error(f"❌ 오류: '{target_sn}' 번호는 이미 생산 중이거나 완료된 이력이 있습니다.")
                        else:
                            # 신규 행 객체 생성
                            entry_obj = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': target_model, 
                                '품목코드': target_item, 
                                '시리얼': target_sn, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 병합 및 구분선 삽입 검사
                            new_db_frame = pd.concat([db_ptr, pd.DataFrame([entry_obj])], ignore_index=True)
                            new_db_frame = check_and_add_marker(new_db_frame, "조립 라인")
                            
                            st.session_state.production_db = new_db_frame
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호는 필수 입력 사항입니다.")
                        
    display_process_log_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 페이지 (상태 전이 방식)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_now = st.session_state.current_line
    icon_now = "🔍" if line_now == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_now} {line_now} 공정 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(line_now)
    st.divider()
    
    # 이전 단계 공정명 정의
    prev_step_name = "조립 라인" if line_now == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_step_name} 물량 입고 접수")
        
        # 필터링 영역
        col_f1, col_f2 = st.columns(2)
        filter_m = col_f1.selectbox("모델 필터링", ["전체"] + st.session_state.master_models, key=f"filter_{line_now}")
        
        # 대기 물량 조회 로직
        current_db_all = st.session_state.production_db
        
        # 이전 공정에서 완료되고 현재 공정 입고를 기다리는 제품 필터링
        waiting_list_df = current_db_all[
            (current_db_all['라인'] == prev_step_name) & 
            (current_db_all['상태'] == "완료")
        ]
        
        if filter_m != "전체":
            waiting_list_df = waiting_list_df[waiting_list_df['모델'] == filter_m]
            
        if not waiting_list_df.empty:
            st.success(f"현재 총 {len(waiting_list_df)}건의 입고 가능한 물량이 조회되었습니다.")
            
            # 버튼 레이아웃 (그리드 방식)
            btn_cols_grid = st.columns(4)
            for i, row_item in enumerate(waiting_list_df.itertuples()):
                sn_val = row_item.시리얼
                model_val = row_item.모델
                
                if btn_cols_grid[i % 4].button(f"📥 입고: {sn_val}", key=f"btn_in_{sn_val}_{line_now}"):
                    st.session_state.confirm_target = sn_val
                    st.session_state.confirm_model = model_val
                    confirm_entry_dialog()
        else:
            st.info(f"현재 {prev_step_name}에서 넘어온 입고 대기 물량이 없습니다.")
            
    display_process_log_table(line_now, "검사 통과" if line_now == "검사 라인" else "출하 준비 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 페이지
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 통합 리포트</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    rpt_db = st.session_state.production_db
    
    if not rpt_db.empty:
        # 데이터 정제 (구분선 제거)
        clean_rpt_db = rpt_db[rpt_db['상태'] != '구분선']
        
        # KPI 산출
        # 포장 완료까지 도달한 제품이 최종 생산 수량입니다.
        done_qty = len(clean_rpt_db[
            (clean_rpt_db['라인'] == '포장 라인') & 
            (clean_rpt_db['상태'] == '완료')
        ])
        
        ng_qty = len(clean_rpt_db[clean_rpt_db['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출
        ftt_score = 0
        if (done_qty + ng_qty) > 0:
            ftt_score = (done_qty / (done_qty + ng_qty)) * 100
        else:
            ftt_score = 100
            
        # 대시보드 메트릭 표시
        met_r1, met_r2, met_r3, met_r4 = st.columns(4)
        met_r1.metric("최종 출하 실적", f"{done_qty} EA")
        met_r2.metric("전공정 가동 중", len(clean_rpt_db[clean_rpt_db['상태'] == '진행 중']))
        met_r3.metric("누적 불량 건수", f"{ng_qty} 건", delta=ng_qty, delta_color="inverse")
        met_r4.metric("직행률(FTT)", f"{ftt_score:.1f}%")
        
        st.divider()
        
        # 차트 레이아웃
        vis_c1, vis_c2 = st.columns([3, 2])
        
        with vis_c1:
            line_dist = clean_rpt_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_dist, x='라인', y='수량', color='라인', title="공정 단계별 제품 분포 상황"), use_container_width=True)
            
        with vis_c2:
            model_pie_data = clean_rpt_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie_data, values='수량', names='모델', hole=0.3, title="생산 모델별 구성비"), use_container_width=True)
            
        st.markdown("##### 🔍 상세 생산 및 공정 기록 전체 보기")
        st.dataframe(rpt_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회할 생산 기록이 없습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (line4 권한 대응 영역)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True)
    
    # 조립 라인 현황을 참고용으로 상단에 배치합니다.
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중인 행들만 추출합니다.
    repair_target_db = st.session_state.production_db
    bad_items_list = repair_target_db[repair_target_db['상태'] == "불량 처리 중"]
    
    if bad_items_list.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치가 완료되었습니다.")
    else:
        st.markdown(f"##### 수리 대기 건수: {len(bad_items_list)}건")
        
        for idx_row, row_data in bad_items_list.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **시리얼: {row_data['시리얼']}** | 모델: {row_data['모델']} | 발생공정: {row_data['라인']}")
                
                # 수리 입력 필드 구성
                col_i1, col_i2, col_i3 = st.columns([4, 4, 2])
                
                # 이전 입력값 복구 (캐시)
                cause_cache = st.session_state.repair_cache.get(f"s_{idx_row}", "")
                action_cache = st.session_state.repair_cache.get(f"a_{idx_row}", "")
                
                input_cause = col_i1.text_input("불량 원인(Symptom)", value=cause_cache, key=f"in_s_{idx_row}")
                input_action = col_i2.text_input("수리 조치(Action)", value=action_cache, key=f"in_a_{idx_row}")
                
                # 실시간 캐시 업데이트
                st.session_state.repair_cache[f"s_{idx_row}"] = input_cause
                st.session_state.repair_cache[f"a_{idx_row}"] = input_action
                
                # 수리 완료 증빙 사진 업로드
                uploaded_photo = st.file_uploader("수리 조치 사진(JPG/PNG)", type=['jpg','png','jpeg'], key=f"photo_{idx_row}")
                
                if uploaded_photo:
                    st.image(uploaded_photo, width=280, caption="업로드된 수리 증빙 사진")
                    
                if col_i3.button("🔧 수리 완료 등록", key=f"finish_{idx_row}", type="primary", use_container_width=True):
                    if input_cause and input_action:
                        web_link_str = ""
                        
                        if uploaded_photo is not None:
                            with st.spinner("수리 증빙 사진을 서버에 저장하고 있습니다..."):
                                time_mark = get_kst_now().strftime('%Y%m%d_%H%M')
                                save_name = f"{row_data['시리얼']}_FIX_{time_mark}.jpg"
                                upload_url = upload_image_to_drive(uploaded_photo, save_name)
                                
                                if "http" in upload_url:
                                    web_link_str = f" [사진링크: {upload_url}]"
                        
                        # 상태 업데이트 로직
                        repair_target_db.at[idx_row, '상태'] = "수리 완료(재투입)"
                        repair_target_db.at[idx_row, '증상'] = input_cause
                        repair_target_db.at[idx_row, '수리'] = input_action + web_link_str
                        repair_target_db.at[idx_row, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(repair_target_db):
                            # 성공 시 입력값 캐시 비우기
                            st.session_state.repair_cache.pop(f"s_{idx_row}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_row}", None)
                            st.success("성공적으로 수리 보고가 완료되었습니다.")
                            st.rerun()
                    else:
                        st.error("원인 분석과 수리 조치 내용을 모두 기입해 주세요.")

# -----------------------------------------------------------------
# 6-5. 수리 분석 리포트
# -----------------------------------------------------------------
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 이력 분석 리포트</h2>", unsafe_allow_html=True)
    
    source_db = st.session_state.production_db
    # 수리 완료 기록이 남은 행들만 필터링합니다.
    repair_history_df = source_db[
        (source_db['상태'].str.contains("재투입", na=False)) | 
        (source_db['수리'] != "")
    ]
    
    if not repair_history_df.empty:
        stat_c1, stat_c2 = st.columns(2)
        
        with stat_c1:
            # 공정별 불량 발생 비중 분석
            line_bad_data = repair_history_df.groupby('라인').size().reset_index(name='건수')
            st.plotly_chart(px.bar(line_bad_data, x='라인', y='건수', title="공정 단계별 불량 빈도"), use_container_width=True)
            
        with stat_c2:
            # 모델별 불량 빈도 분석
            model_bad_data = repair_history_df.groupby('모델').size().reset_index(name='건수')
            st.plotly_chart(px.pie(model_bad_data, values='건수', names='모델', hole=0.3, title="불량 모델 구성 비율"), use_container_width=True)
            
        st.markdown("##### 📋 상세 수리 및 조치 완료 이력 데이터")
        st.dataframe(repair_history_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재 분석할 수리 데이터가 존재하지 않습니다.")

# -----------------------------------------------------------------
# 6-6. 마스터 데이터 및 초기화 관리 (수정됨)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리 및 데이터 설정</h2>", unsafe_allow_html=True)
    
    # 관리자 비밀번호 인증 절차
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            st.write("안전한 시스템 관리를 위해 관리자 인증이 필요합니다.")
            admin_pw_in = st.text_input("관리자 PW 입력 (기본: admin1234)", type="password")
            
            if st.form_submit_button("권한 인증"):
                if admin_pw_in in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 기능이 활성화되었습니다.")
                    st.rerun()
                else:
                    st.error("잘못된 비밀번호입니다.")
    else:
        if st.button("🔓 관리자 메뉴 잠금", use_container_width=True):
            st.session_state.admin_authenticated = False
            navigate_to("생산 리포트")

        st.markdown("### 📋 1. 마스터 정보 관리")
        adm_row1_c1, adm_row1_c2 = st.columns(2)
        
        with adm_row1_c1:
            with st.container(border=True):
                st.write("**신규 모델 추가**")
                input_new_m = st.text_input("새 모델명")
                
                if st.button("모델 등록하기", use_container_width=True):
                    if input_new_m and input_new_m not in st.session_state.master_models:
                        st.session_state.master_models.append(input_new_m)
                        st.session_state.master_items_dict[input_new_m] = []
                        st.success(f"'{input_new_m}' 모델 등록 성공")
                        st.rerun()

        with adm_row1_c2:
            with st.container(border=True):
                st.write("**품목코드 마스터 관리**")
                sel_m = st.selectbox("대상 모델 선택", st.session_state.master_models)
                input_new_i = st.text_input("새 품목코드")
                
                if st.button("품목코드 등록하기", use_container_width=True):
                    if input_new_i and input_new_i not in st.session_state.master_items_dict[sel_m]:
                        st.session_state.master_items_dict[sel_m].append(input_new_i)
                        st.success(f"[{sel_m}] 품목 등록 완료")
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 로드")
        adm_row2_c1, adm_row2_c2 = st.columns(2)
        
        with adm_row2_c1:
            st.write("현재 구글 시트의 전체 데이터를 CSV로 다운로드합니다.")
            csv_blob = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            
            st.download_button(
                "📥 전체 실적 CSV 다운로드", 
                csv_blob, 
                f"production_log_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with adm_row2_c2:
            st.write("백업된 CSV 파일을 업로드하여 기존 데이터에 병합합니다.")
            csv_file = st.file_uploader("백업 CSV 선택", type="csv")
            
            if csv_file and st.button("📤 데이터 로드 및 시트 업데이트", use_container_width=True):
                upload_df = pd.read_csv(csv_file)
                # 시리얼 번호 타입 강제 보정
                if '시리얼' in upload_df.columns:
                    upload_df['시리얼'] = upload_df['시리얼'].astype(str)
                
                st.session_state.production_db = pd.concat([st.session_state.production_db, upload_df], ignore_index=True)
                
                if save_to_gsheet(st.session_state.production_db):
                    st.success("데이터 병합 저장이 완료되었습니다.")
                    st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 권한 및 계정 제어")
        
        u_adm_c1, u_adm_c2, u_adm_c3 = st.columns([3, 3, 2])
        u_adm_id = u_adm_c1.text_input("생성할 ID")
        u_adm_pw = u_adm_c2.text_input("생성할 PW", type="password")
        u_adm_role = u_adm_c3.selectbox("부여할 권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성/수정 반영", use_container_width=True):
            if u_adm_id and u_adm_pw:
                st.session_state.user_db[u_adm_id] = {"pw": u_adm_pw, "role": u_adm_role}
                st.success(f"계정 [{u_adm_id}]이(가) 등록되었습니다.")
                st.rerun()
        
        with st.expander("현재 시스템 등록 계정 상세 리스트"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("### ⚠️ 4. 시스템 위험 관리 (전체 초기화)")
        # [수정 사항] 초기화 시 is_reset_command=True 인자를 전달하여 시트 비우기를 허용합니다.
        if st.button("🚫 시스템 전체 생산 데이터 초기화", type="secondary", use_container_width=True):
             st.error("경고: 초기화 실행 시 구글 시트의 모든 실적 데이터가 영구 삭제됩니다.")
             if st.button("❌ 위험 감수: 전체 삭제 확정"):
                 # 빈 데이터프레임 생성
                 empty_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 st.session_state.production_db = empty_db
                 
                 # 초기화 모드로 저장 요청
                 if save_to_gsheet(empty_db, is_reset_command=True):
                     st.success("구글 시트 및 시스템 데이터가 완전히 초기화되었습니다.")
                     st.rerun()
