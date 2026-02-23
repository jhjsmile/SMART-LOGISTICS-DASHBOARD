import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 API 관련 라이브러리
# 현장 수리 증빙 사진의 업로드 및 관리를 위해 사용됩니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의 (560줄 이상의 상세 스타일 적용)
# =================================================================
# 애플리케이션의 기본적인 페이지 레이아웃과 제목을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v19.0", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 계정 권한 매핑
# 현장 작업자별로 접근 가능한 공정을 분리하여 데이터 무결성을 보장합니다.
# line4 계정은 'repair_team' 권한으로 불량 수리 공정만 전담하게 됩니다.
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
        "불량 공정" # line4 계정용 수리 권한
    ]
}

# 사용자 정의 CSS 스타일링 (상세하고 가독성 높은 UI를 구성합니다)
st.markdown("""
    <style>
    /* 전체 애플리케이션의 최대 너비를 조절하여 시각적 안정감을 줍니다. */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼의 패딩과 글꼴 두께를 조절하여 현장 작업 시 터치/클릭 편의성을 높입니다. */
    .stButton button { 
        margin-top: 5px; 
        padding: 10px 15px; 
        width: 100%; 
        font-weight: 800;
        font-size: 1.02em;
        border-radius: 8px;
    }
    
    /* 중앙 정렬된 메인 제목 스타일 */
    .centered-title { 
        text-align: center; 
        font-weight: 900; 
        margin: 35px 0; 
        color: #1a1a1a;
    }
    
    /* 불량 발생 시 작업자 주의를 환기하는 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #e03131; 
        padding: 22px; 
        border-radius: 12px; 
        border: 2px solid #ff8787; 
        font-weight: bold; 
        margin-bottom: 30px;
        text-align: center;
        font-size: 1.1em;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    }
    
    /* 상단 대시보드 통계 카드의 디자인 정의 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 15px; 
        padding: 25px; 
        text-align: center;
        border: 1px solid #dee2e6; 
        margin-bottom: 20px;
        box-shadow: 0 5px 15px rgba(0,0,0,0.03);
    }
    
    .stat-label { 
        font-size: 1em; 
        color: #666; 
        font-weight: bold; 
        margin-bottom: 8px;
    }
    
    .stat-value { 
        font-size: 2.2em; 
        color: #007bff; 
        font-weight: 900; 
    }
    
    .stat-sub { 
        font-size: 0.85em; 
        color: #999; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 연동 및 데이터 처리 핵심 함수 (보안 및 데이터 무결성)
# =================================================================
# 구글 시트와의 실시간 통신을 위한 객체를 선언합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """서버 시각이 아닌 한국 표준시(KST)를 생성하여 반환합니다."""
    # 9시간의 시차를 더해 정확한 한국 시각을 계산합니다.
    return datetime.now() + timedelta(hours=9)

def load_data():
    """구글 시트로부터 데이터를 로드하고 구조를 강제로 동기화합니다."""
    try:
        # 캐시를 무시하고 구글 시트의 최신 상태를 읽어옵니다.
        df_raw = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 지수 형식 등으로 변환되는 현상을 원천 차단합니다.
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어 로직] 사용자가 수동으로 시트 데이터를 삭제했을 때 빈 구조를 생성합니다.
        if df_raw.empty:
            return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            
        return df_raw
    except Exception as api_err:
        st.error(f"구글 시트 데이터 로드 실패: {api_err}")
        # 로드 실패 시에도 시스템이 중단되지 않도록 빈 데이터프레임을 반환합니다.
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_action=False):
    """구글 시트에 데이터를 즉시 동기화합니다."""
    # 의도하지 않은 데이터 증발을 막기 위해 빈 데이터 저장을 시스템 차원에서 보호합니다.
    if df.empty and not is_reset_action:
        st.error("❌ 데이터 보호 알림: 빈 데이터 저장이 감지되어 작업이 취소되었습니다.")
        return False
    
    # 통신 불안정 환경을 고려하여 최대 3회 자동 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # 시트 업데이트 수행
            conn.update(data=df)
            # 캐시를 즉시 삭제하여 다른 사용자에게도 즉시 반영되도록 합니다.
            st.cache_data.clear()
            return True
        except Exception as update_err:
            if attempt < 3:
                time.sleep(2) # 2초 대기 후 다시 시도
                continue
            else:
                st.error(f"⚠️ 구글 서버 저장 오류 (최종 실패): {update_err}")
                return False

def upload_image_to_drive(file_obj, filename_save):
    """현장의 수리 증빙 사진을 구글 드라이브 지정 폴더에 저장합니다."""
    try:
        # secrets에서 보안 키 정보를 로드합니다.
        raw_keys = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_keys)
        
        # 구글 드라이브 서비스 생성
        drive_service = build('drive', 'v3', credentials=credentials)
        target_folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder_id:
            return "오류: 폴더ID설정안됨"

        # 파일 메타데이터 및 스트림 설정
        metadata_cfg = {
            'name': filename_save, 
            'parents': [target_folder_id]
        }
        media_upload = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 업로드 실행 및 보기 링크 반환
        file_res = drive_service.files().create(
            body=metadata_cfg, 
            media_body=media_upload, 
            fields='id, webViewLink'
        ).execute()
        
        return file_res.get('webViewLink')
    except Exception as drive_err:
        return f"사진 업로드 실패: {str(drive_err)}"

# =================================================================
# 3. 세션 상태(Session State) 관리 및 시스템 초기화
# =================================================================
# 앱이 구동되는 동안 유지되어야 할 핵심 변수들을 세션에 등록합니다.

if 'production_db' not in st.session_state:
    # 초기 진입 시 데이터를 로드합니다.
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 시스템 계정 및 권한 데이터베이스
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
    # 생산 대상 모델 리스트
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    # 모델별 품목코드 매핑 정보
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
    # 수리 입력 도중 데이터 유실 방지를 위한 캐시
    st.session_state.repair_cache = {}

# =================================================================
# 4. 사용자 인증 관리 및 사이드바 내비게이션
# =================================================================

# 로그인하지 않은 경우 화면 구성을 수행합니다.
if not st.session_state.login_status:
    # 화면을 3분할하여 중앙에 로그인 박스를 배치합니다.
    _, login_box_col, _ = st.columns([1, 1.2, 1])
    
    with login_box_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 부여받은 공정 아이디와 비밀번호를 입력해 주세요.")
        
        with st.form("main_login_form"):
            user_id_field = st.text_input("아이디(ID)")
            user_pw_field = st.text_input("비밀번호(PW)", type="password")
            
            btn_submit_login = st.form_submit_button("시스템 접속하기", use_container_width=True)
            
            if btn_submit_login:
                # 계정 정보를 대조합니다.
                if user_id_field in st.session_state.user_db:
                    correct_pw_val = st.session_state.user_db[user_id_field]["pw"]
                    
                    if user_pw_field == correct_pw_val:
                        # 로그인 성공 및 초기 세션 데이터 로드
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = user_id_field
                        st.session_state.user_role = st.session_state.user_db[user_id_field]["role"]
                        
                        # 권한별 첫 번째 메뉴로 자동 내비게이션
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("입력한 비밀번호가 올바르지 않습니다.")
                else:
                    st.error("등록된 계정 정보가 없습니다.")
    st.stop()

# 사이드바 사용자 프로필 및 로그아웃
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 (접속 중)")
if st.sidebar.button("🔓 시스템 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환을 위한 전용 함수 정의
def navigate_to(page_name):
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한 기반 메뉴 리스트 생성
current_allowed_list = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 생산 공정 현황
p_group_menus = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
p_group_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for menu_item in p_group_menus:
    if menu_item in current_allowed_list:
        menu_label = f"{p_group_icons[menu_item]} {menu_item}" + (" 현황" if "라인" in menu_item else "")
        # 현재 활성화된 메뉴는 강조(primary) 표시합니다.
        menu_style = "primary" if st.session_state.current_line == menu_item else "secondary"
        
        if st.sidebar.button(menu_label, use_container_width=True, type=menu_style):
            navigate_to(menu_item)

# 그룹 2: 불량 수리 및 공정 분석
r_group_menus = ["불량 공정", "수리 리포트"]
r_group_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for menu_item in r_group_menus:
    if menu_item in current_allowed_list:
        r_label = f"{r_group_icons[menu_item]} {menu_item}"
        r_style = "primary" if st.session_state.current_line == menu_item else "secondary"
        
        if st.sidebar.button(r_label, use_container_width=True, type=r_style):
            navigate_to(menu_item)

# 그룹 3: 시스템 마스터 관리
if "마스터 관리" in current_allowed_list:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_to("마스터 관리")

# 시스템 공용 불량 발생 긴급 알림 배너
unrepaired_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not unrepaired_db.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 {len(unrepaired_db)}건의 불량 수리 대기 건이 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 및 공용 UI (단일 행 워크플로우 방식)
# =================================================================

def check_and_add_marker(df, line_name):
    """생산 실적 10대 달성 시 시각적 구분선 행을 시트에 추가합니다."""
    kst_today_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 해당 라인의 오늘 생산 실적(구분선 제외) 개수를 집계합니다.
    line_perf_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(kst_today_str)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대 달성 시마다 구분선 행을 데이터프레임에 삽입합니다.
    if line_perf_count > 0 and line_perf_count % 10 == 0:
        perf_marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {line_perf_count}대 생산 실적 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        return pd.concat([df, pd.DataFrame([perf_marker_row])], ignore_index=True)
    return df

@st.dialog("📦 공정 단계 전환 확인")
def confirm_entry_dialog():
    """제품을 다음 공정으로 이동시키기 위해 기존 행을 업데이트합니다. (단일 행 트래킹)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    st.write(f"현재 위치가 '{st.session_state.current_line}'으로 정식 업데이트됩니다.")
    
    col_ok, col_no = st.columns(2)
    
    if col_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_full = st.session_state.production_db
        
        # [복합키 매칭] 품목코드와 시리얼 번호가 일치하는 단일 행의 인덱스를 조회합니다.
        # 사용자 요청에 따라 제품 고유 식별자는 '품목코드' + '시리얼'의 조합입니다.
        row_idx_find = db_full[
            (db_full['품목코드'] == st.session_state.confirm_item) & 
            (db_full['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not row_idx_find.empty:
            target_idx_val = row_idx_find[0]
            
            # [워크플로우 업데이트] 기존 행의 공정 위치와 상태 정보만 갱신합니다.
            db_full.at[target_idx_val, '라인'] = st.session_state.current_line
            db_full.at[target_idx_val, '상태'] = '진행 중'
            db_full.at[target_idx_val, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db_full.at[target_idx_val, '작업자'] = st.session_state.user_id
            
            # 시트에 즉시 반영 및 세션 갱신
            if save_to_gsheet(db_full):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 실패: 시트에서 해당 품목코드 및 시리얼 조합을 찾을 수 없습니다.")
            
    if col_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(line_name):
    """상단 통계 영역 렌더링 (대기 물량 및 금일 실적 집계)"""
    db_source = st.session_state.production_db
    today_kst_stamp = get_kst_now().strftime('%Y-%m-%d')
    
    # 금일 해당 공정의 투입 및 완료 수량을 집계합니다.
    today_line_records = db_source[
        (db_source['라인'] == line_name) & 
        (db_source['시간'].astype(str).str.contains(today_kst_stamp)) & 
        (db_source['상태'] != '구분선')
    ]
    
    count_input = len(today_line_records)
    count_done = len(today_line_records[today_line_records['상태'] == '완료'])
    
    # 이전 단계 공정에서의 입고 대기 물량을 산출합니다.
    count_waiting = 0
    previous_step_nm = None
    
    if line_name == "검사 라인": previous_step_nm = "조립 라인"
    elif line_name == "포장 라인": previous_step_nm = "검사 라인"
    
    if previous_step_nm:
        # 단일 행 방식이므로 이전 라인에서 '완료' 상태인 행의 개수가 곧 대기 물량이 됩니다.
        waiting_df_list = db_source[
            (db_source['라인'] == previous_step_nm) & 
            (db_source['상태'] == '완료')
        ]
        count_waiting = len(waiting_df_list)
        
    # 통계 레이아웃 렌더링
    st_met_c1, st_met_c2, st_met_c3 = st.columns(3)
    
    with st_met_c1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {previous_step_nm if previous_step_nm else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{count_waiting if previous_step_nm else '-'}</div>
                <div class='stat-sub'>건 (공정 간 재공 물량)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_met_c2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{count_input}</div>
                <div class='stat-sub'>건 (금일 투입 실적)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_met_c3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{count_done}</div>
                <div class='stat-sub'>건 (금일 완료 수량)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, btn_label_ok="완료 처리"):
    """실시간 공정 로그 테이블 및 상태 제어 인터페이스를 표시합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 공정 로그</h3>", unsafe_allow_html=True)
    
    db_ptr_all = st.session_state.production_db
    # 해당 라인의 물량만 추출합니다.
    view_db_ptr = db_ptr_all[db_ptr_all['라인'] == line_name]
    
    # 조립 라인일 경우 선택된 CELL 필터를 적용합니다.
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_db_ptr = view_db_ptr[view_db_ptr['CELL'] == st.session_state.selected_cell]
        
    if view_db_ptr.empty:
        st.info(f"현재 {line_name}에 등록된 공정 데이터가 없습니다.")
        return
        
    # 테이블 헤더 구성
    head_cols_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_titles_ui = ["기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "상태 제어"]
    
    for i, title_txt in enumerate(header_titles_ui):
        head_cols_ui[i].write(f"**{title_txt}**")
        
    # 데이터 행 최신순 정렬 및 렌더링
    for idx_row_val, data_row_val in view_db_ptr.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리 (시각적 구분)
        if data_row_val['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f8f9fa; padding: 7px; text-align: center; border-radius: 8px; font-weight: bold; color: #666; border: 1px dashed #ced4da;'>📦 {data_row_val['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        data_cols_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        data_cols_ui[0].write(data_row_val['시간'])
        data_cols_ui[1].write(data_row_val['CELL'])
        data_cols_ui[2].write(data_row_val['모델'])
        data_cols_ui[3].write(data_row_val['품목코드'])
        data_cols_ui[4].write(data_row_val['시리얼'])
        
        with data_cols_ui[5]:
            status_current_val = data_row_val['상태']
            
            # 작업 가능 상태일 때만 제어 버튼을 노출합니다.
            if status_current_val in ["진행 중", "수리 완료(재투입)"]:
                b_c_pass, b_c_bad = st.columns(2)
                
                # 중복 키 방지를 위한 인덱스 기반 키 할당
                if b_c_pass.button(btn_label_ok, key=f"btn_pass_{idx_row_val}"):
                    db_ptr_all.at[idx_row_val, '상태'] = "완료"
                    db_ptr_all.at[idx_row_val, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_ptr_all):
                        st.rerun()
                        
                if b_c_bad.button("🚫불량", key=f"btn_bad_{idx_row_val}"):
                    db_ptr_all.at[idx_row_val, '상태'] = "불량 처리 중"
                    db_ptr_all.at[idx_row_val, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_ptr_all):
                        st.rerun()
                        
            elif status_current_val == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 센터 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 작업 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 메뉴별 상세 기능 및 렌더링 (v19.0 최종 수정)
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 페이지 (워크플로우 시작 - 중복 체크 핵심)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 UI 구성
    cell_opt_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_grid_ui = st.columns(len(cell_opt_list))
    
    for i, c_name_ui in enumerate(cell_opt_list):
        if btn_grid_ui[i].button(c_name_ui, type="primary" if st.session_state.selected_cell == c_name_ui else "secondary"):
            st.session_state.selected_cell = c_name_ui
            st.rerun()
            
    # 개별 셀이 선택되었을 때만 생산 등록 인터페이스를 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 생산 제품 등록")
            
            # 모델 선택박스
            input_model_val = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("new_assembly_registration_form"):
                row_f1_ui, row_f2_ui = st.columns(2)
                
                # 모델 기반 품목 리스트 자동 연동
                items_avail_list = st.session_state.master_items_dict.get(input_model_val, ["모델을 선택하세요."])
                input_item_val = row_f1_ui.selectbox("품목코드 선택", items_avail_list)
                
                input_serial_val = row_f2_ui.text_input("시리얼 번호(S/N) 입력")
                
                btn_reg_submit = st.form_submit_button("▶️ 생산 등록 진행", use_container_width=True, type="primary")
                
                if btn_reg_submit:
                    if input_model_val != "선택하세요." and input_serial_val != "":
                        db_ptr_p = st.session_state.production_db
                        
                        # [복합키 중복 체크] 제품 간 '품목코드' + '시리얼'이 절대 중복되지 않도록 검사합니다.
                        # 모델명은 중복될 수 있으나 제품 고유 식별키는 이 둘의 조합입니다.
                        dup_find_records = db_ptr_p[
                            (db_ptr_p['품목코드'] == input_item_val) & 
                            (db_ptr_p['시리얼'] == input_serial_val) & 
                            (db_ptr_p['상태'] != "구분선")
                        ]
                        
                        if not dup_find_records.empty:
                            st.error(f"❌ 중복 방지: 품목코드 [ {input_item_val} ] 및 시리얼 [ {input_serial_val} ] 제품이 이미 등록되어 있습니다.")
                        else:
                            # 신규 제품 행 생성
                            new_entry_data = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': input_model_val, 
                                '품목코드': input_item_val, 
                                '시리얼': input_serial_val, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 추가 및 실적 구분선 자동 체크
                            df_new_updated = pd.concat([db_ptr_p, pd.DataFrame([new_entry_data])], ignore_index=True)
                            df_new_updated = check_and_add_marker(df_new_updated, "조립 라인")
                            
                            st.session_state.production_db = df_new_updated
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 모두 확인해 주세요.")
                        
    display_process_log_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 (전체보기 제거 및 복합키 매칭 반영)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_now_nm = st.session_state.current_line
    icon_now_nm = "🔍" if line_now_nm == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_now_nm} {line_now_nm} 공정 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(line_now_nm)
    st.divider()
    
    # 이전 공정 단계 정의
    prev_step_nm_str = "조립 라인" if line_now_nm == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_step_nm_str} 완료 물량 입고 처리")
        
        # [수정] 작업자 혼선을 방지하기 위해 '전체보기'를 삭제하고 반드시 모델을 먼저 선택하게 합니다.
        model_f_sel = st.selectbox("입고 대상 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"f_m_{line_now_nm}")
        
        if model_f_sel != "선택하세요.":
            db_all_ref = st.session_state.production_db
            
            # 이전 공정 완료 물량 중 선택한 모델 필터링
            ready_pool_list = db_all_ref[
                (db_all_ref['라인'] == prev_step_nm_str) & 
                (db_all_ref['상태'] == "완료") & 
                (db_all_ref['모델'] == model_f_sel)
            ]
            
            if not ready_pool_list.empty:
                st.success(f"📦 현재 입고 가능한 [ {model_f_sel} ] 물량이 {len(ready_pool_list)}건 조회되었습니다.")
                
                # 입고 승인 버튼 그리드 구성 (DuplicateKey 방지를 위해 복합 키 활용)
                in_btn_grid = st.columns(4)
                for i, row_item in enumerate(ready_pool_list.itertuples()):
                    sn_v = row_item.시리얼
                    md_v = row_item.모델
                    it_v = row_item.품목코드
                    
                    # 키 값에 모델, 품목코드, 시리얼을 조합하여 절대적인 고유성을 확보합니다.
                    btn_key_id = f"in_act_{md_v}_{it_v}_{sn_v}_{line_now_nm}"
                    
                    if in_btn_grid[i % 4].button(f"📥 입고: {sn_v}", key=btn_key_id):
                        st.session_state.confirm_target = sn_v
                        st.session_state.confirm_model = md_v
                        st.session_state.confirm_item = it_v # 품목코드를 넘겨서 정확한 행 매칭 수행
                        confirm_entry_dialog()
            else:
                st.info(f"현재 [ {model_f_sel} ] 모델의 입고 대기 물량이 없습니다.")
        else:
            st.warning("작업을 진행할 모델을 먼저 선택해 주십시오.")
            
    display_process_log_table(line_now_nm, "검사 완료(합격)" if line_now_nm == "검사 라인" else "최종 출하 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 및 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 통합 대시보드</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    rpt_db_view = st.session_state.production_db
    
    if not rpt_db_view.empty:
        # 데이터 정제 (구분선 행 제거)
        clean_rpt_db = rpt_db_view[rpt_db_view['상태'] != '구분선']
        
        # 주요 KPI 지표 산출
        # 최종 포장 라인에서 '완료'된 제품이 실질적인 생산 수량입니다.
        total_out_qty = len(clean_rpt_db[
            (clean_rpt_db['라인'] == '포장 라인') & 
            (clean_rpt_db['상태'] == '완료')
        ])
        
        total_ng_qty = len(clean_rpt_db[clean_rpt_db['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출
        ftt_rate_val = (total_out_qty / (total_out_qty + total_bad_qty) * 100) if (total_out_qty + total_bad_qty) > 0 else 100
            
        # 상단 메트릭 레이아웃
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("최종 제품 출하", f"{total_out_qty} EA")
        m_col2.metric("공정 작업 중", len(clean_rpt_db[clean_rpt_db['상태'] == '진행 중']))
        m_col3.metric("누적 불량 건수", f"{total_ng_qty} 건", delta=total_ng_qty, delta_color="inverse")
        m_col4.metric("직행률(FTT)", f"{ftt_rate_val:.1f}%")
        
        st.divider()
        
        # 시각화 그래프 영역
        v_col1, v_col2 = st.columns([3, 2])
        
        with v_col1:
            line_dist_df = clean_rpt_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_dist_df, x='라인', y='수량', color='라인', title="공정 단계별 실시간 제품 분포"), use_container_width=True)
            
        with v_col2:
            model_pie_df = clean_rpt_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie_df, values='수량', names='모델', hole=0.3, title="생산 모델별 비중"), use_container_width=True)
            
        st.markdown("##### 🔍 상세 공정 통합 생산 기록 (최신순)")
        st.dataframe(rpt_db_view.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회할 생산 기록이 아직 없습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (line4 대응)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중인 행들만 필터링합니다.
    bad_list_ptr = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_list_ptr.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_list_ptr)}건")
        
        for idx_b, row_b in bad_list_ptr.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **품목: {row_b['품목코드']}** | S/N: {row_b['시리얼']} | 모델: {row_b['모델']} | 발생: {row_b['라인']}")
                
                # 수리 입력 필드 레이아웃
                in_col1, in_col2, in_col3 = st.columns([4, 4, 2])
                
                # 입력값 캐시 로드
                c_symptom = st.session_state.repair_cache.get(f"s_{idx_b}", "")
                c_action = st.session_state.repair_cache.get(f"a_{idx_b}", "")
                
                input_s = in_col1.text_input("불량 원인 상세", value=c_symptom, key=f"is_{idx_b}")
                input_a = in_col2.text_input("수리 및 조치 사항", value=c_action, key=f"ia_{idx_b}")
                
                # 캐시 즉시 업데이트
                st.session_state.repair_cache[f"s_{idx_b}"] = input_s
                st.session_state.repair_cache[f"a_{idx_b}"] = input_a
                
                # 사진 첨부 업로더
                repair_photo = st.file_uploader("수리 증빙 사진(JPG/PNG)", type=['jpg','png','jpeg'], key=f"ph_{idx_b}")
                
                if repair_photo:
                    st.image(repair_photo, width=300, caption="업로드 예정 사진")
                    
                if in_col3.button("🔧 수리 완료 등록", key=f"btn_r_done_{idx_b}", type="primary", use_container_width=True):
                    if input_s and input_a:
                        final_link = ""
                        
                        if repair_photo is not None:
                            with st.spinner("사진을 드라이브에 안전하게 저장 중..."):
                                ts_mark = get_kst_now().strftime('%Y%m%d_%H%M')
                                fn_save = f"{row_b['시리얼']}_FIX_{ts_mark}.jpg"
                                res_url = upload_image_to_drive(repair_photo, fn_save)
                                if "http" in res_url: final_link = f" [사진보기: {res_url}]"
                        
                        # 데이터베이스 업데이트
                        st.session_state.production_db.at[idx_b, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx_b, '증상'], st.session_state.production_db.at[idx_b, '수리'] = input_s, input_a + final_link
                        st.session_state.production_db.at[idx_b, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 제거 및 리프레시
                            st.session_state.repair_cache.pop(f"s_{idx_b}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_b}", None)
                            st.success("수리 완료 보고 완료!"); st.rerun()
                    else:
                        st.error("원인과 조치 내용을 모두 입력해야 합니다.")

# -----------------------------------------------------------------
# 6-5. 마스터 관리 (물리적 초기화 완벽 해결)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리 및 데이터 설정</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            admin_pw_in = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if admin_pw_in in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
    else:
        if st.sidebar.button("🔓 관리자 세션 종료"): st.session_state.admin_authenticated = False; navigate_to("생산 리포트")

        st.markdown("### 📋 1. 마스터 정보 관리")
        adm_c1, adm_c2 = st.columns(2)
        with adm_c1:
            with st.container(border=True):
                st.write("**신규 모델 등록**")
                n_m_nm = st.text_input("새 모델 명칭")
                if st.button("➕ 모델 추가", use_container_width=True):
                    if n_m_nm and n_m_nm not in st.session_state.master_models:
                        st.session_state.master_models.append(n_m_nm); st.session_state.master_items_dict[n_m_nm] = []; st.rerun()
        with adm_c2:
            with st.container(border=True):
                st.write("**품목코드 마스터 설정**")
                sel_m_a = st.selectbox("품목 추가 모델", st.session_state.master_models)
                n_i_cd = st.text_input("새 품목코드")
                if st.button("➕ 품목코드 등록", use_container_width=True):
                    if n_i_cd and n_i_cd not in st.session_state.master_items_dict[sel_m_a]:
                        st.session_state.master_items_dict[sel_m_a].append(n_i_cd); st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 관리")
        csv_blob_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 전체 실적 백업 (CSV)", csv_blob_data, f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
            
        if st.button("🚫 시스템 전체 데이터 물리적 초기화 (주의)", type="secondary", use_container_width=True):
             st.error("주의: 실행 시 구글 시트의 모든 실적 데이터가 삭제됩니다.")
             if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                 # 빈 데이터프레임 구조 생성
                 empty_df_struct = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 st.session_state.production_db = empty_df_struct
                 # 초기화 모드로 저장 실행 (구글 시트까지 비움)
                 if save_to_gsheet(empty_df_struct, is_reset_action=True):
                     st.success("시스템 및 구글 시트 데이터가 완전히 초기화되었습니다."); st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 계정 관리")
        u_adm_c1, u_adm_c2, u_adm_c3 = st.columns([3, 3, 2])
        t_uid = u_adm_c1.text_input("새 계정 ID")
        t_upw = u_adm_c2.text_input("새 계정 PW", type="password")
        t_role = u_adm_c3.selectbox("부여 권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성/수정 반영", use_container_width=True):
            if t_uid and t_upw:
                st.session_state.user_db[t_uid] = {"pw": t_upw, "role": t_role}
                st.success(f"[{t_uid}] 계정 권한이 업데이트되었습니다."); st.rerun()
