import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 API 연동 라이브러리 (사진 저장 및 관리 전용)
# 현장에서 촬영한 수리 증빙 사진을 클라우드에 안전하게 보관하기 위해 필수적입니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 애플리케이션 기본 설정 및 시스템 환경 정의
# =================================================================
# 웹 브라우저 상단 탭에 표시될 제목과 전체 레이아웃의 너비를 설정합니다.
# 현장의 넓은 모니터에서 보기 편하도록 'wide' 레이아웃을 채택하였습니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v19.3 (상세 확장판)", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 공정별 메뉴 접근 권한 매핑
# 이 시스템은 작업자의 직분에 따라 메뉴 노출을 제어하여 불필요한 혼선을 방지합니다.
# 특히 'repair_team(line4)'은 불량 수리 공정에 특화된 권한을 가집니다.
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
        "불량 공정" # line4 전용 수리 권한
    ]
}

# =================================================================
# 2. UI 디자인 및 시인성 향상을 위한 상세 CSS 정의
# =================================================================
# 현장의 열악한 조명이나 바쁜 작업 중에도 한눈에 들어올 수 있도록 
# 버튼 크기, 폰트 두께, 카드 디자인을 아주 상세하게 설정합니다.
st.markdown("""
    <style>
    /* 전체 애플리케이션의 배경색과 폰트 정렬을 최적화합니다. */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
        font-family: 'Pretendard', sans-serif;
    }
    
    /* 공정 제어 버튼의 스타일을 크고 굵게 설정하여 오작동을 방지합니다. */
    .stButton button { 
        margin-top: 2px; 
        padding: 6px 10px !important;  /* 상하 여백을 줄여 버튼 높이 축소 */
        width: 100%; 
        font-size: 0.95em;             /* 글자 크기를 작게 하여 콤팩트하게 변경 */
        font-weight: 700;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: all 0.2s ease;
    }
    
    /* 버튼 클릭 시 시각적 피드백을 줍니다. */
    .stButton button:active {
        transform: scale(0.97);
    }
    
    /* 각 페이지 상단의 중앙 정렬된 대형 제목 스타일입니다. */
    .centered-title { 
        text-align: center; 
        font-weight: 900; 
        margin: 30px 0; 
        color: #1e272e;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.05);
    }
    
    /* 긴급 불량 발생 시 작업자가 즉시 인지할 수 있도록 하는 경고 배너입니다. */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #d63031; 
        padding: 24px; 
        border-radius: 15px; 
        border: 2px solid #ff7675; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        font-size: 1.2em;
        box-shadow: 0 4px 15px rgba(214, 48, 49, 0.1);
    }
    
    /* 대시보드 KPI 정보를 담는 카드의 세부 디자인입니다. */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 20px; 
        padding: 30px; 
        text-align: center;
        border: 1px solid #dfe6e9; 
        margin-bottom: 20px;
        box-shadow: 0 8px 16px rgba(0,0,0,0.03);
    }
    
    .stat-label { 
        font-size: 1.1em; 
        color: #636e72; 
        font-weight: 700; 
        margin-bottom: 12px;
    }
    
    .stat-value { 
        font-size: 2.6em; 
        color: #0984e3; 
        font-weight: 900; 
    }
    
    .stat-sub { 
        font-size: 0.95em; 
        color: #b2bec3; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 3. 데이터 연동 및 핵심 처리 함수 (동기화 문제 완벽 해결)
# =================================================================
# 구글 시트와의 실시간 양방향 통신을 위한 객체를 선언합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """서버 시각이 아닌 한국 표준시(KST)를 생성하여 반환합니다."""
    # 9시간의 시차를 보정하여 정확한 한국 시각을 계산합니다.
    kst_offset = timedelta(hours=9)
    kst_current_time = datetime.now() + kst_offset
    return kst_current_time

def load_data():
    """구글 시트로부터 최신 생산 데이터를 로드하고 데이터 형식을 보정합니다."""
    try:
        # 캐시 유효 시간을 0으로 설정하여 항상 최신 데이터를 강제 로드합니다.
        df_from_sheet = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 숫자형으로 오인되어 소수점(.0)이 붙는 현상을 문자열 처리를 통해 해결합니다.
        if '시리얼' in df_from_sheet.columns:
            df_from_sheet['시리얼'] = df_from_sheet['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어 로직] 사용자가 구글 시트에서 직접 데이터를 삭제했을 경우에도 시스템이 멈추지 않도록
        # 기본 컬럼 구조를 갖춘 데이터프레임을 생성하여 반환합니다.
        if df_from_sheet.empty:
            empty_struct = pd.DataFrame(columns=[
                '시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'
            ])
            return empty_struct
            
        return df_from_sheet
    except Exception as load_error:
        st.error(f"데이터 연동 중 기술적 오류 발생: {load_error}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_command=False):
    """
    변경된 생산 데이터를 구글 시트에 업데이트합니다.
    [핵심 수정] is_reset_command가 True일 때만 빈 데이터를 강제로 덮어씌워 초기화를 완료합니다.
    """
    # 1. 초기화 상황이 아닌데 데이터가 비어있으면 작업자의 실수로 간주하고 저장을 차단합니다.
    if df.empty and not is_reset_command:
        st.error("❌ 데이터 보호 알림: 빈 데이터 저장이 감지되어 작업이 차단되었습니다. 페이지를 새로고침 하세요.")
        return False
    
    # 2. 구글 시트 API의 통신 불안정 환경에 대비하여 최대 3회 자동 재시도를 수행합니다.
    # 시트 업데이트 시 기존 데이터를 완전히 덮어씌우는 Overwrite 모드로 동작합니다.
    for attempt in range(1, 4):
        try:
            # 구글 시트 업데이트 명령 실행
            conn.update(data=df)
            
            # 반영 즉시 앱 내부의 모든 캐시 데이터를 무효화하여 모든 사용자에게 최신본을 노출합니다.
            st.cache_data.clear()
            return True
        except Exception as update_err:
            if attempt < 3:
                # 2초간 대기 후 다시 시도하여 일시적인 네트워크 장애를 극복합니다.
                time.sleep(2)
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (3회 시도 완료): {update_err}")
                return False

def upload_image_to_drive(file_obj, filename_to_save):
    """현장에서 촬영한 수리 증빙 사진을 구글 드라이브에 안전하게 업로드합니다."""
    try:
        # secrets에 저장된 보안 인증 정보를 로드합니다.
        raw_auth_info = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_auth_info)
        
        # 구글 드라이브 서비스 인스턴스를 생성합니다.
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # 수리 사진이 저장될 전용 폴더의 ID를 확인합니다.
        target_folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder_id:
            return "오류: 드라이브 폴더 설정 미비"

        # 파일의 메타데이터 및 미디어 스트림을 구성합니다.
        file_metadata_cfg = {
            'name': filename_to_save, 
            'parents': [target_folder_id]
        }
        media_stream = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 업로드 명령을 실행하고 웹에서 볼 수 있는 링크를 획득합니다.
        file_created = drive_service.files().create(
            body=file_metadata_cfg, 
            media_body=media_stream, 
            fields='id, webViewLink'
        ).execute()
        
        return file_created.get('webViewLink')
    except Exception as drive_api_err:
        return f"사진 업로드 실패: {str(drive_api_err)}"

# =================================================================
# 4. 세션 상태(Session State) 변수 및 마스터 데이터 초기화
# =================================================================
# 애플리케이션 수명 주기 동안 유지되어야 할 공통 변수들을 세션에 등록합니다.

if 'production_db' not in st.session_state:
    # 앱 시작 시 구글 시트에서 기초 데이터를 최초 로드합니다.
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 시스템에 등록된 계정 정보와 권한 등급을 정의합니다.
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
    # 생산 관리가 필요한 제품 마스터 모델 리스트입니다.
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    # 모델별로 유효한 품목코드 리스트를 매핑합니다.
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], 
        "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], 
        "T20C": ["T20C-S"]
    }

if 'current_line' not in st.session_state:
    # 현재 작업자가 위치한 메뉴 상태를 추적합니다.
    st.session_state.current_line = "조립 라인"

if 'selected_cell' not in st.session_state:
    # 조립 라인의 구역(CELL) 선택 상태를 유지합니다.
    st.session_state.selected_cell = "CELL 1"

if 'repair_cache' not in st.session_state:
    # 수리 입력 도중 페이지 이동 시 데이터 유실을 방지하기 위한 캐시입니다.
    st.session_state.repair_cache = {}

# =================================================================
# 5. 사용자 인증 및 내비게이션 관리 (Verbose Style)
# =================================================================

# 로그인하지 않은 경우 화면을 구성합니다.
if not st.session_state.login_status:
    # 화면을 3분할하여 가독성 있게 중앙에 로그인 박스를 배치합니다.
    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    
    with col_c:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 공정 담당자 계정으로 로그인하여 주시기 바랍니다.")
        
        with st.form("system_entry_form"):
            input_user_id = st.text_input("아이디(ID) 입력")
            input_user_pw = st.text_input("비밀번호(PW) 입력", type="password")
            
            trigger_login_btn = st.form_submit_button("시스템 접속하기", use_container_width=True)
            
            if trigger_login_btn:
                # 등록된 사용자 데이터베이스에서 계정 정보를 조회합니다.
                if input_user_id in st.session_state.user_db:
                    correct_pw_match = st.session_state.user_db[input_user_id]["pw"]
                    
                    if input_user_pw == correct_pw_match:
                        # 로그인 성공 처리 및 최신 데이터 동기화
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = input_user_id
                        st.session_state.user_role = st.session_state.user_db[input_user_id]["role"]
                        
                        # 권한 등급별 초기 메뉴를 설정하고 페이지를 리프레시합니다.
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("입력한 비밀번호가 유효하지 않습니다.")
                else:
                    st.error("등록된 계정 정보가 없습니다. 관리자에게 문의하세요.")
    st.stop()

# 사이드바 사용자 프로필 및 시스템 로그아웃
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 (접속 중)")
if st.sidebar.button("🔓 시스템 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환을 수행하는 공용 함수 정의
def change_page(page_name_target):
    st.session_state.current_line = page_name_target
    st.rerun()

# 사용자 권한 메뉴 리스트 추출
my_allowed_menus = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 공정 관리 메뉴
prod_menus = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
prod_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for menu_name in prod_menus:
    if menu_name in my_allowed_menus:
        menu_display_label = f"{prod_icons[menu_name]} {menu_name}" + (" 현황" if "라인" in menu_name else "")
        # 현재 메뉴는 시각적으로 강조 표시합니다.
        menu_button_style = "primary" if st.session_state.current_line == menu_name else "secondary"
        
        if st.sidebar.button(menu_display_label, use_container_width=True, type=menu_button_style):
            change_page(menu_name)

# 그룹 2: 사후 수리 및 공정 분석 메뉴
repair_menus = ["불량 공정", "수리 리포트"]
repair_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for menu_name in repair_menus:
    if menu_name in my_allowed_menus:
        repair_display_label = f"{repair_icons[menu_name]} {menu_name}"
        repair_button_style = "primary" if st.session_state.current_line == menu_name else "secondary"
        
        if st.sidebar.button(repair_display_label, use_container_width=True, type=repair_button_style):
            change_page(menu_name)

# 그룹 3: 마스터 기준 정보 관리
if "마스터 관리" in my_allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        change_page("마스터 관리")

# 하단 긴급 불량 발생 알림 (수리 대기 물량 자동 집계)
ng_pending_records = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not ng_pending_records.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 전체 공정에 {len(ng_pending_records)}건의 불량 수리 대기 제품이 존재합니다.</div>", unsafe_allow_html=True)

# =================================================================
# 6. 비즈니스 로직 및 공용 컴포넌트 (워크플로우 제어)
# =================================================================

def add_perf_divider(df_input, line_name_val):
    """지정된 생산 실적(10대 단위) 달성 시 구분선을 시트에 삽입하여 시인성을 확보합니다."""
    kst_today_stamp = get_kst_now().strftime('%Y-%m-%d')
    
    # 오늘 해당 라인에서 발생한 순수 실적(구분선 제외) 개수를 집계합니다.
    current_perf_qty = len(df_input[
        (df_input['라인'] == line_name_val) & 
        (df_input['시간'].astype(str).str.contains(kst_today_stamp)) & 
        (df_input['상태'] != "구분선")
    ])
    
    # 10대 달성 시마다 고유한 구분선 행을 데이터프레임에 병합합니다.
    if current_perf_qty > 0 and current_perf_qty % 10 == 0:
        perf_marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {current_perf_qty}대 생산 실적 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        df_with_divider = pd.concat([df_input, pd.DataFrame([perf_marker_row])], ignore_index=True)
        return df_with_divider
    return df_input

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    """제품을 다음 단계로 이동시키기 위해 기존 행의 공정 위치를 갱신합니다. (단일 행 트래킹)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    st.write(f"현재 제품의 위치 정보가 '{st.session_state.current_line}'으로 정식 업데이트됩니다.")
    
    btn_col_ok, btn_col_no = st.columns(2)
    
    if btn_col_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        full_db_ref = st.session_state.production_db
        
        # [복합키 고유 매칭] 품목코드와 시리얼 번호가 일치하는 단일 행의 인덱스를 찾아냅니다.
        # 제품 식별 기준: '품목코드' + '시리얼'
        row_find_idx = full_db_ref[
            (full_db_ref['품목코드'] == st.session_state.confirm_item) & 
            (full_db_ref['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not row_find_idx.empty:
            target_idx_ptr = row_find_idx[0]
            
            # [Workflow 업데이트] 신규 행을 생성하지 않고 기존 정보의 위치와 상태만 변경합니다.
            full_db_ref.at[target_idx_ptr, '라인'] = st.session_state.current_line
            full_db_ref.at[target_idx_ptr, '상태'] = '진행 중'
            full_db_ref.at[target_idx_ptr, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            full_db_ref.at[target_idx_ptr, '작업자'] = st.session_state.user_id
            
            # 구글 시트에 실시간 반영
            if save_to_gsheet(full_db_ref):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 실패: 시트에서 해당 품목코드 및 시리얼 조합을 조회할 수 없습니다.")
            
    if btn_col_no.button("❌ 승인 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_dashboard_stats(line_name_str):
    """상단 통계 영역 렌더링 (대기 및 금일 실적 집계 로직)"""
    db_source_ref = st.session_state.production_db
    today_kst_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 금일 해당 공정의 투입 및 완료 수량을 집계합니다.
    today_records_in_line = db_source_ref[
        (db_source_ref['라인'] == line_name_str) & 
        (db_source_ref['시간'].astype(str).str.contains(today_kst_str)) & 
        (db_source_ref['상태'] != '구분선')
    ]
    
    val_total_in = len(today_records_in_line)
    val_total_done = len(today_records_in_line[today_records_in_line['상태'] == '완료'])
    
    # 이전 단계 공정에서의 입고 대기 재공 물량을 산출합니다.
    val_waiting_qty = 0
    previous_step_name = None
    
    if line_name_str == "검사 라인": previous_step_name = "조립 라인"
    elif line_name_str == "포장 라인": previous_step_name = "검사 라인"
    
    if previous_step_name:
        # 단일 행 추적 방식이므로 이전 라인에서 '완료' 상태인 행의 개수가 곧 대기 물량이 됩니다.
        waiting_pool_df = db_source_ref[
            (db_source_ref['라인'] == previous_step_name) & 
            (db_source_ref['상태'] == '완료')
        ]
        val_waiting_qty = len(waiting_pool_df)
        
    # 통계 레이아웃 시각화 (stat-box 활용)
    met_c1, met_c2, met_c3 = st.columns(3)
    
    with met_c1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {previous_step_name if previous_step_name else '공정'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{val_waiting_qty if previous_step_name else '-'}</div>
                <div class='stat-sub'>건 (누적 입고 대기)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with met_c2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name_str} 작업 중</div>
                <div class='stat-value'>{val_total_in}</div>
                <div class='stat-sub'>건 (금일 투입 실적)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with met_c3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name_str} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{val_total_done}</div>
                <div class='stat-sub'>건 (금일 완료 수량)</div>
            </div>
            """, unsafe_allow_html=True)

def display_live_process_table(line_name_val, btn_label_ok="완료 처리"):
    """실시간 공정 로그 테이블 및 작업 제어 인터페이스를 표시합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name_val} 실시간 공정 로그</h3>", unsafe_allow_html=True)
    
    full_db_ptr = st.session_state.production_db
    # 해당 라인의 물량만 필터링합니다.
    view_data_ptr = full_db_ptr[full_db_ptr['라인'] == line_name_val]
    
    # 조립 라인일 경우 선택된 CELL 필터를 적용합니다.
    if line_name_val == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_data_ptr = view_data_ptr[view_data_ptr['CELL'] == st.session_state.selected_cell]
        
    if view_data_ptr.empty:
        st.info(f"현재 {line_name_val}에 등록된 공정 데이터가 조회되지 않습니다.")
        return
        
    # 테이블 헤더 구성
    header_col_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_text_list = ["최종기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "상태 변경 제어"]
    
    for i, head_txt in enumerate(header_text_list):
        header_col_ui[i].write(f"**{head_txt}**")
        
    # 데이터 행을 최신순으로 정렬하여 렌더링합니다.
    for row_idx_val, row_data_val in view_data_ptr.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리 (시각적 리듬감 부여)
        if row_data_val['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f8f9fa; padding: 7px; text-align: center; border-radius: 10px; font-weight: bold; color: #636e72; border: 1px dashed #dfe6e9;'>📦 {row_data_val['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        data_col_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        data_col_ui[0].write(row_data_val['시간'])
        data_col_ui[1].write(row_data_val['CELL'])
        data_col_ui[2].write(row_data_val['모델'])
        data_col_ui[3].write(row_data_val['품목코드'])
        data_col_ui[4].write(row_data_val['시리얼'])
        
        with data_col_ui[5]:
            status_current_val = row_data_val['상태']
            
            # 작업 가능 상태일 때만 제어 버튼을 활성화합니다.
            if status_current_val in ["진행 중", "수리 완료(재투입)"]:
                btn_c_ok, btn_c_ng = st.columns(2)
                
                # 중복 키 방지를 위해 행 인덱스를 버튼 키로 활용합니다.
                if btn_c_ok.button(btn_label_ok, key=f"btn_ok_act_{row_idx_val}"):
                    full_db_ptr.at[row_idx_val, '상태'] = "완료"
                    full_db_ptr.at[row_idx_val, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(full_db_ptr):
                        st.rerun()
                        
                if btn_c_ng.button("🚫불량 발생", key=f"btn_ng_act_{row_idx_val}"):
                    full_db_ptr.at[row_idx_val, '상태'] = "불량 처리 중"
                    full_db_ptr.at[row_idx_val, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(full_db_ptr):
                        st.rerun()
                        
            elif status_current_val == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 대기 중 (Repair)</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 공정 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 7. 메뉴별 상세 기능 및 화면 렌더링 (v19.3 최종 수정)
# =================================================================

# -----------------------------------------------------------------
# 7-1. 조립 라인 페이지 (워크플로우 시작 - 복합키 중복 체크 핵심)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_dashboard_stats("조립 라인")
    st.divider()
    
    # CELL 선택 UI 구성 (작업 구역 분할)
    cell_name_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_grid_cols = st.columns(len(cell_name_list))
    
    for idx_c, c_name_ui in enumerate(cell_name_list):
        if btn_grid_cols[idx_c].button(c_name_ui, type="primary" if st.session_state.selected_cell == c_name_ui else "secondary"):
            st.session_state.selected_cell = c_name_ui
            st.rerun()
            
    # 특정 셀이 선택되었을 때만 신규 등록 인터페이스를 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 조립 등록")
            
            # 모델 선택박스 (마스터 모델 기준)
            sel_model_in = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"model_sel_widget_{st.session_state.selected_cell}")
            
            with st.form("new_assembly_registration_form"):
                row_f1_in, row_f2_in = st.columns(2)
                
                # 모델 기반 품목 리스트 자동 연동
                items_available_list = st.session_state.master_items_dict.get(sel_model_in, ["모델을 먼저 선택하세요."])
                sel_item_in = row_f1_in.selectbox("품목코드 선택", items_available_list)
                
                sel_serial_in = row_f2_in.text_input("시리얼 번호(S/N) 입력")
                
                btn_reg_trigger = st.form_submit_button("▶️ 생산 등록 진행", use_container_width=True, type="primary")
                
                if btn_reg_trigger:
                    if sel_model_in != "선택하세요." and sel_serial_in != "":
                        db_ptr_p = st.session_state.production_db
                        
                        # [복합키 중복 체크] 제품 간 '품목코드' + '시리얼'이 절대 중복되지 않도록 엄격히 검사합니다.
                        # 모델명은 같을 수 있으나 제품 식별 고유키는 품목코드와 시리얼의 조합입니다.
                        dup_search_records = db_ptr_p[
                            (db_ptr_p['품목코드'] == sel_item_in) & 
                            (db_ptr_p['시리얼'] == sel_serial_in) & 
                            (db_ptr_p['상태'] != "구분선")
                        ]
                        
                        if not dup_search_records.empty:
                            st.error(f"❌ 중복 등록 차단: 품목코드 [ {sel_item_in} ] 및 시리얼 [ {sel_serial_in} ] 제품은 이미 등록되어 있습니다.")
                        else:
                            # 신규 행 데이터 생성
                            new_entry_data = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': sel_model_in, 
                                '품목코드': sel_item_in, 
                                '시리얼': sel_serial_in, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 병합 및 실적 구분선 자동 체크
                            df_new_updated = pd.concat([db_ptr_p, pd.DataFrame([new_entry_data])], ignore_index=True)
                            df_new_updated = add_perf_divider(df_new_updated, "조립 라인")
                            
                            st.session_state.production_db = df_new_updated
                            
                            # 구글 시트에 즉시 반영
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 누락 없이 입력해 주십시오.")
                        
    display_live_process_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 7-2. 검사 및 포장 라인 페이지 (전체보기 제거 및 복합키 매칭 반영)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_now_nm = st.session_state.current_line
    icon_now_nm = "🔍" if line_now_nm == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_now_nm} {line_now_nm} 공정 현황</h2>", unsafe_allow_html=True)
    
    display_dashboard_stats(line_now_nm)
    st.divider()
    
    # 이전 단계 공정 정의
    prev_step_nm_str = "조립 라인" if line_now_nm == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_step_nm_str} 완료 물량 입고 승인")
        
        # [핵심] 작업자 혼선을 원천 방지하기 위해 '전체보기'를 삭제하고 반드시 모델을 먼저 선택하게 합니다.
        model_f_sel_in = st.selectbox("입고 대상 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"f_m_sel_{line_now_nm}")
        
        if model_f_sel_in != "선택하세요.":
            db_all_ref = st.session_state.production_db
            
            # 이전 공정에서 '완료' 상태로 대기 중인 특정 모델 물량 조회
            waiting_pool_list = db_all_ref[
                (db_all_ref['라인'] == prev_step_nm_str) & 
                (db_all_ref['상태'] == "완료") & 
                (db_all_ref['모델'] == model_f_sel_in)
            ]
            
            if not waiting_pool_list.empty:
                st.success(f"📦 현재 입고 가능한 [ {model_f_sel_in} ] 물량이 {len(waiting_pool_list)}건 조회되었습니다.")
                
                # 버튼 그리드 구성 (DuplicateKey 방지를 위해 복합 고유 정보 활용)
                in_btn_grid_cols = st.columns(4)
                for i, row_item in enumerate(waiting_pool_list.itertuples()):
                    sn_val_ptr = row_item.시리얼
                    md_val_ptr = row_item.모델
                    it_val_ptr = row_item.품목코드
                    
                    # 버튼 키에 모델, 품목코드, 시리얼을 모두 조합하여 절대적인 고유성을 부여합니다.
                    btn_unique_key = f"in_act_btn_{md_val_ptr}_{it_val_ptr}_{sn_val_ptr}_{line_now_nm}"
                    
                    if in_btn_grid_cols[i % 4].button(f"📥 입고: {sn_val_ptr}", key=btn_unique_key):
                        st.session_state.confirm_target = sn_val_ptr
                        st.session_state.confirm_model = md_val_ptr
                        st.session_state.confirm_item = it_val_ptr # 행 매칭을 위해 품목코드 저장
                        confirm_entry_dialog()
            else:
                st.info(f"현재 [ {model_f_sel_in} ] 모델의 입고 대기 물량이 존재하지 않습니다.")
        else:
            st.warning("작업을 진행할 모델을 목록에서 먼저 선택해 주십시오.")
            
    display_live_process_table(line_now_nm, "검사 합격" if line_now_nm == "검사 라인" else "최종 출하 완료")

# -----------------------------------------------------------------
# 7-3. 생산 리포트 통합 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 통합 대시보드</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    rpt_db_view = st.session_state.production_db
    
    if not rpt_db_view.empty:
        # 데이터 정제 (시각적 구분선 행 제거)
        clean_rpt_db = rpt_db_view[rpt_db_view['상태'] != '구분선']
        
        # 주요 KPI 지표 산출 로직
        # 최종 포장 라인에서 '완료'된 제품이 실질적인 완제품 생산량입니다.
        total_finished_qty = len(clean_rpt_db[
            (clean_rpt_db['라인'] == '포장 라인') & 
            (clean_rpt_db['상태'] == '완료')
        ])
        
        total_ng_count = len(clean_rpt_db[clean_rpt_db['상태'].str.contains("불량", na=False)])
        
        # FTT(First Time Through) 직행률 산출
        ftt_rate_calc = (total_finished_qty / (total_finished_qty + total_ng_count) * 100) if (total_finished_qty + total_ng_count) > 0 else 100
            
        # 상단 메트릭 섹션 렌더링
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("최종 완제품 출하", f"{total_finished_qty} EA")
        m_col2.metric("전 공정 재공 물량", len(clean_rpt_db[clean_rpt_db['상태'] == '진행 중']))
        m_col3.metric("누적 불량 발생", f"{total_ng_count} 건", delta=total_ng_count, delta_color="inverse")
        m_col4.metric("직행률(FTT)", f"{ftt_rate_calc:.1f}%")
        
        st.divider()
        
        # 데이터 시각화 차트 섹션
        chart_col1, chart_col2 = st.columns([3, 2])
        
        with chart_col1:
            dist_data_line = clean_rpt_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(dist_data_line, x='라인', y='수량', color='라인', title="공정 단계별 실시간 제품 분포"), use_container_width=True)
            
        with chart_col2:
            dist_data_model = clean_rpt_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(dist_data_model, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성"), use_container_width=True)
            
        st.markdown("##### 🔍 상세 공정 통합 생산 이력 데이터 (최신순)")
        st.dataframe(rpt_db_view.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회할 수 있는 생산 기록 데이터가 아직 존재하지 않습니다.")

# -----------------------------------------------------------------
# 7-4. 불량 수리 센터 (line4 권한 대응 및 사진 업로드)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True)
    display_dashboard_stats("조립 라인")
    
    # 불량 처리 중 상태인 데이터만 필터링합니다.
    repair_pending_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if repair_pending_list.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치 및 재투입이 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(repair_pending_list)}건")
        
        for idx_row, data_row in repair_pending_list.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **품목코드: {data_row['품목코드']}** | S/N: {data_row['시리얼']} | 모델: {data_row['모델']} | 발생: {data_row['라인']}")
                
                # 수리 원인 및 조치 입력 필드 레이아웃
                in_col1, in_col2, in_col3 = st.columns([4, 4, 2])
                
                # 세션 캐시로부터 기존 입력값 로드
                cache_symp = st.session_state.repair_cache.get(f"sym_{idx_row}", "")
                cache_act = st.session_state.repair_cache.get(f"act_{idx_row}", "")
                
                input_symptom = in_col1.text_input("불량 원인 상세 기술", value=cache_symp, key=f"in_sym_{idx_row}")
                input_action = in_col2.text_input("수리 및 조치 사항", value=cache_act, key=f"in_act_{idx_row}")
                
                # 실시간 캐시 업데이트 (입력 보존)
                st.session_state.repair_cache[f"sym_{idx_row}"] = input_symptom
                st.session_state.repair_cache[f"act_{idx_row}"] = input_action
                
                # 증빙 사진 업로더 인터페이스
                repair_photo_file = st.file_uploader("수리 사진(JPG/PNG) 첨부", type=['jpg','png','jpeg'], key=f"rep_ph_{idx_row}")
                
                if repair_photo_file:
                    st.image(repair_photo_file, width=300, caption="업로드 대기 중인 사진")
                    
                if in_col3.button("🔧 수리 완료 등록", key=f"btn_finish_rep_{idx_row}", type="primary", use_container_width=True):
                    if input_symptom and input_action:
                        result_photo_link = ""
                        
                        if repair_photo_file is not None:
                            with st.spinner("사진을 구글 드라이브에 안전하게 저장 중입니다..."):
                                ts_mark_str = get_kst_now().strftime('%Y%m%d_%H%M')
                                fn_save_name = f"{data_row['시리얼']}_REPAIR_{ts_mark_str}.jpg"
                                uploaded_url = upload_image_to_drive(repair_photo_file, fn_save_name)
                                
                                if "http" in uploaded_url:
                                    result_photo_link = f" [사진보기: {uploaded_url}]"
                        
                        # 데이터베이스 상태 업데이트 로직 실행
                        st.session_state.production_db.at[idx_row, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx_row, '증상'] = input_symptom
                        st.session_state.production_db.at[idx_row, '수리'] = input_action + result_photo_link
                        st.session_state.production_db.at[idx_row, '작업자'] = st.session_state.user_id
                        
                        # 구글 시트 최종 업데이트
                        if save_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 제거 및 화면 갱신
                            st.session_state.repair_cache.pop(f"sym_{idx_row}", None)
                            st.session_state.repair_cache.pop(f"act_{idx_row}", None)
                            st.success("수리 완료 보고서가 성공적으로 등록되었습니다.")
                            st.rerun()
                    else:
                        st.error("불량 원인과 조치 사항을 모두 입력해야 등록이 가능합니다.")

# -----------------------------------------------------------------
# 7-5. 마스터 관리 (강제 초기화 버그 완벽 수정 영역)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리자 전용 마스터 센터</h2>", unsafe_allow_html=True)
    
    # 관리자 세션 보안 인증
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form_ui"):
            st.write("안전한 시스템 관리를 위해 관리자 권한 인증이 필요합니다.")
            input_pw_admin = st.text_input("관리자 비밀번호 입력 (admin1234)", type="password")
            
            if st.form_submit_button("권한 인증하기"):
                if input_pw_admin in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 전용 기능이 개방되었습니다.")
                    st.rerun()
                else:
                    st.error("인증 실패: 비밀번호가 일치하지 않습니다.")
    else:
        if st.sidebar.button("🔓 마스터 모드 종료"):
            st.session_state.admin_authenticated = False
            change_page("생산 리포트")

        st.markdown("### 📋 1. 마스터 기준 데이터 관리")
        adm_c1, adm_c2 = st.columns(2)
        
        with adm_c1:
            with st.container(border=True):
                st.write("**신규 모델 등록 관리**")
                new_model_name_in = st.text_input("추가할 모델 명칭")
                if st.button("➕ 모델 신규 등록", use_container_width=True):
                    if new_model_name_in and new_model_name_in not in st.session_state.master_models:
                        st.session_state.master_models.append(new_model_name_in)
                        st.session_state.master_items_dict[new_model_name_in] = []
                        st.success(f"'{new_model_name_in}' 모델이 등록되었습니다.")
                        st.rerun()

        with adm_c2:
            with st.container(border=True):
                st.write("**품목코드 마스터 매핑**")
                sel_model_adm = st.selectbox("품목 추가 대상 모델", st.session_state.master_models)
                new_item_code_in = st.text_input("신규 품목코드 명칭")
                if st.button("➕ 품목코드 매핑 완료", use_container_width=True):
                    if new_item_code_in and new_item_code_in not in st.session_state.master_items_dict[sel_model_adm]:
                        st.session_state.master_items_dict[sel_model_adm].append(new_item_code_in)
                        st.success(f"[{sel_model_adm}] 전용 품목코드가 등록되었습니다.")
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 물리적 초기화 제어")
        adm_row2_c1, adm_row2_c2 = st.columns(2)
        
        with adm_row2_c1:
            st.write("현재까지 기록된 전체 데이터를 CSV 파일로 안전하게 백업합니다.")
            csv_export_blob = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 전체 실적 데이터 백업 다운로드", 
                csv_export_blob, 
                f"production_full_backup_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with adm_row2_c2:
            st.write("구글 시트 내의 모든 실적 데이터를 영구적으로 삭제합니다.")
            # [초기화 핵심 버그 수정]
            # 버튼 클릭 시 빈 데이터프레임 구조를 생성하여 구글 API로 강제 덮어쓰기(Overwrite)를 수행합니다.
            if st.button("🚫 시스템 전체 생산 데이터 초기화 (물리적 삭제)", type="secondary", use_container_width=True):
                 st.error("경고: 실행 시 구글 시트의 모든 실적 데이터가 삭제되며 복구가 불가능합니다.")
                 if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기 실행"):
                     # 컬럼 헤더만 정의된 빈 데이터프레임 객체 생성
                     reset_struct_df = pd.DataFrame(columns=[
                         '시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'
                     ])
                     st.session_state.production_db = reset_struct_df
                     
                     # force_reset 모드(is_reset_command=True)로 저장 함수 호출하여 시트 비움
                     if save_to_gsheet(reset_struct_df, is_reset_command=True):
                         # 성공 시 앱의 모든 캐시를 비우고 홈으로 이동
                         st.cache_data.clear()
                         st.success("시스템 및 구글 시트의 데이터가 성공적으로 초기화되었습니다.")
                         st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 계정 권한 및 ID/PW 관리")
        u_adm_c1, u_adm_c2, u_adm_c3 = st.columns([3, 3, 2])
        target_uid_in = u_adm_c1.text_input("생성/수정할 ID")
        target_upw_in = u_adm_c2.text_input("새 비밀번호 설정", type="password")
        target_role_in = u_adm_c3.selectbox("권한 등급 설정", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 정보 업데이트 및 권한 부여", use_container_width=True):
            if target_uid_in and target_upw_in:
                st.session_state.user_db[target_uid_in] = {"pw": target_upw_in, "role": target_role_in}
                st.success(f"[{target_uid_in}] 계정 정보가 성공적으로 반영되었습니다."); st.rerun()

