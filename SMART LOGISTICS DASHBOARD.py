import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리 (사진 저장 전용)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의 (560줄 스타일을 위해 상세히 전개)
# =================================================================
# 애플리케이션의 기본 환경을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.4", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 메뉴 권한
# 현장 계정별로 필요한 메뉴만 노출하도록 설계되었습니다.
# line4 계정은 repair_team 권한을 가집니다.
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

# UI 디자인 설정을 위한 CSS 코드입니다.
st.markdown("""
    <style>
    /* 전체 애플리케이션의 가독성을 높이기 위한 레이아웃 설정 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼의 높이와 여백을 현장 작업에 최적화합니다. */
    .stButton button { 
        margin-top: 0px; 
        padding: 8px 10px; 
        width: 100%; 
        font-weight: bold;
    }
    
    /* 중앙 정렬된 대형 제목 스타일 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 30px 0; 
        color: #1e1e1e;
    }
    
    /* 실시간 불량 알림 배너 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 20px; 
        border-radius: 12px; 
        border: 2px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 30px;
        text-align: center;
        font-size: 1.1em;
    }
    
    /* 통계 지표를 나타내는 카드 스타일 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 15px; 
        padding: 25px; 
        text-align: center;
        border: 1px solid #dee2e6; 
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.07);
    }
    
    .stat-label { 
        font-size: 1em; 
        color: #6c757d; 
        font-weight: 600; 
        margin-bottom: 8px;
    }
    
    .stat-value { 
        font-size: 2.2em; 
        color: #007bff; 
        font-weight: 800; 
    }
    
    .stat-sub { 
        font-size: 0.9em; 
        color: #adb5bd; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 연동 및 데이터 처리 함수 (초기화 로직 대폭 수정)
# =================================================================
# 구글 시트와 연결을 수행합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 생성합니다."""
    now = datetime.now() + timedelta(hours=9)
    return now

def load_data():
    """시트에서 데이터를 로드합니다. 실패 시 세션의 데이터를 보호합니다."""
    try:
        # 시트 데이터 읽기
        df = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호 형식 보정 (소수점 제거)
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어 로직] 로드 결과가 비어있어도 세션에 데이터가 있다면 기존 데이터를 유지함
        if df.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
                
        return df
    except Exception as e:
        st.error(f"데이터 로드 에러: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, force_reset=False):
    """
    구글 시트에 데이터를 업데이트합니다.
    [핵심 수정] force_reset이 True일 경우, 헤더만 남기고 전체 행을 삭제하도록 강제 업데이트합니다.
    """
    # 1. 일반적인 상황에서 빈 데이터가 저장되는 것을 방지합니다.
    if df.empty and not force_reset:
        st.error("❌ 저장 보호: 빈 데이터가 전송되어 저장이 차단되었습니다.")
        return False
    
    # 2. 초기화 명령인 경우, 구글 API가 인식할 수 있도록 컬럼만 있는 데이터프레임을 구성합니다.
    if force_reset:
        # 모든 행을 삭제하기 위해 컬럼명만 정의된 데이터프레임을 사용합니다.
        data_to_save = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
    else:
        data_to_save = df

    # 3. 3회 재시도 로직을 통해 안정성을 확보합니다.
    for attempt in range(1, 4):
        try:
            conn.update(data=data_to_save)
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2)  # 네트워크 지연 대비 대기
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (3회 시도 완료): {api_err}")
                return False

def upload_image_to_drive(file_data, file_name):
    """수리 사진을 구글 드라이브에 저장합니다."""
    try:
        # 구글 API 인증 정보 로드
        creds_info = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        
        # 드라이브 서비스 구축
        service = build('drive', 'v3', credentials=credentials)
        
        # 드라이브 폴더 아이디
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "오류: 폴더 ID 미설정"

        file_metadata = {
            'name': file_name, 
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_data, mimetype=file_data.type)
        
        # 업로드 실행
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        return f"사진 업로드 실패: {str(e)}"

# =================================================================
# 3. 세션 상태(Session State) 초기화 관리
# =================================================================
# 시스템 구동에 필요한 초기 변수들을 설정합니다.

if 'production_db' not in st.session_state:
    # 초기 실행 시 시트에서 데이터를 가져옵니다.
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 사용자 계정 마스터 DB
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
# 4. 로그인 및 사이드바 메뉴 (상세 전개)
# =================================================================

# 로그인 상태가 아닐 때 표시할 화면
if not st.session_state.login_status:
    # 중앙 정렬 컬럼 구성
    col_left, col_center, col_right = st.columns([1, 1.3, 1])
    
    with col_center:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 v18.4</h2>", unsafe_allow_html=True)
        st.info("💡 공지: 승인된 계정으로 로그인하여 공정 작업을 시작하십시오.")
        
        with st.form("user_login_form"):
            user_id_field = st.text_input("아이디(ID)")
            user_pw_field = st.text_input("비밀번호(PW)", type="password")
            
            login_trigger = st.form_submit_button("시스템 접속", use_container_width=True)
            
            if login_trigger:
                # 계정 존재 유무 확인
                if user_id_field in st.session_state.user_db:
                    stored_pw = st.session_state.user_db[user_id_field]["pw"]
                    
                    if user_pw_field == stored_pw:
                        # 로그인 세션 활성화 및 데이터 초기 로드
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = user_id_field
                        st.session_state.user_role = st.session_state.user_db[user_id_field]["role"]
                        
                        # 권한별 첫 번째 페이지로 이동
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("비밀번호가 올바르지 않습니다.")
                else:
                    st.error("등록된 사용자 아이디가 없습니다.")
    st.stop()

# 사이드바 상단 사용자 정보
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 (접속 중)")
if st.sidebar.button("🔓 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환 전용 함수
def navigate_to_page(target):
    st.session_state.current_line = target
    st.rerun()

# 사용 권한이 있는 메뉴만 가져옵니다.
my_allowed_list = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 공정 라인
p_menus = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
p_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for page_name in p_menus:
    if page_name in my_allowed_list:
        p_label = f"{p_icons[page_name]} {page_name}" + (" 현황" if "라인" in page_name else "")
        p_style = "primary" if st.session_state.current_line == page_name else "secondary"
        
        if st.sidebar.button(p_label, use_container_width=True, type=p_style):
            navigate_to_page(page_name)

# 그룹 2: 수리 및 사후 관리
r_menus = ["불량 공정", "수리 리포트"]
r_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for page_name in r_menus:
    if page_name in my_allowed_list:
        r_label = f"{r_icons[page_name]} {page_name}"
        r_style = "primary" if st.session_state.current_line == page_name else "secondary"
        
        if st.sidebar.button(r_label, use_container_width=True, type=r_style):
            navigate_to_page(page_name)

# 그룹 3: 관리자 마스터 기능
if "마스터 관리" in my_allowed_list:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_to_page("마스터 관리")

# 하단 불량품 발생 알림창
bad_rows_check = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not bad_rows_check.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 공정 내 불량 제품이 {len(bad_rows_check)}건 존재합니다. 수리를 진행하세요.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 로직 및 UI 공용 컴포넌트 (Workflow 방식)
# =================================================================

def check_and_add_marker(df_data, current_line):
    """실적 10대마다 구분선을 시트에 추가하여 시인성을 확보합니다."""
    kst_now_date = get_kst_now().strftime('%Y-%m-%d')
    
    # 오늘 해당 라인의 순수 실적을 파악합니다.
    line_total_today = len(df_data[
        (df_data['라인'] == current_line) & 
        (df_data['시간'].astype(str).str.contains(kst_now_date)) & 
        (df_data['상태'] != "구분선")
    ])
    
    # 10대 달성 시마다 마커 행을 삽입합니다.
    if line_total_today > 0 and line_total_today % 10 == 0:
        marker_data_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {line_total_today}대 생산 완료", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        df_new = pd.concat([df_data, pd.DataFrame([marker_data_row])], ignore_index=True)
        return df_new
    return df_data

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    """다음 공정으로 이동할 때 기존 행을 찾아 업데이트합니다. (단일 행 추적)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ]을(를) {st.session_state.current_line}으로 입고하시겠습니까?")
    st.write("확인 시 해당 제품의 현재 공정 위치가 변경됩니다.")
    
    btn_col1, btn_col2 = st.columns(2)
    
    if btn_col1.button("✅ 입고 승인", type="primary", use_container_width=True):
        full_db = st.session_state.production_db
        
        # 모델과 시리얼이 일치하는 행을 조회합니다.
        row_find = full_db[
            (full_db['모델'] == st.session_state.confirm_model) & 
            (full_db['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not row_find.empty:
            idx_target = row_find[0]
            
            # [Workflow 핵심] 행을 새로 만들지 않고 기존 행의 위치와 상태를 갱신합니다.
            full_db.at[idx_target, '라인'] = st.session_state.current_line
            full_db.at[idx_target, '상태'] = '진행 중'
            full_db.at[idx_target, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            full_db.at[idx_target, '작업자'] = st.session_state.user_id
            
            # 저장 및 새로고침
            if save_to_gsheet(full_db):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터베이스 매칭 실패: 해당 시리얼 번호를 찾을 수 없습니다.")
            
    if btn_col2.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(line_name):
    """상단 통계 바 렌더링 (대기 물량 및 금일 실적)"""
    db_source = st.session_state.production_db
    today_stamp = get_kst_now().strftime('%Y-%m-%d')
    
    # 해당 라인의 금일 투입 및 완료 수량 집계
    line_data_today = db_source[
        (db_source['라인'] == line_name) & 
        (db_source['시간'].astype(str).str.contains(today_stamp)) & 
        (db_source['상태'] != '구분선')
    ]
    
    qty_in = len(line_data_today)
    qty_out = len(line_data_today[line_data_today['상태'] == '완료'])
    
    # 이전 단계 공정에서 입고를 기다리는 재공 수량 파악
    qty_waiting = 0
    prev_step = None
    
    if line_name == "검사 라인": prev_step = "조립 라인"
    elif line_name == "포장 라인": prev_step = "검사 라인"
    
    if prev_step:
        # 이전 공정에서 '완료' 상태가 되어 있는 제품의 총 개수를 구합니다.
        # 단일 행 방식이므로 해당 제품들은 공정이 바뀔 때까지 이전 라인 완료 상태에 머뭅니다.
        waiting_df = db_source[
            (db_source['라인'] == prev_step) & 
            (db_source['상태'] == '완료')
        ]
        qty_waiting = len(waiting_df)
        
    # 통계 레이아웃 렌더링
    st_c1, st_c2, st_c3 = st.columns(3)
    
    with st_c1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {prev_step if prev_step else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{qty_waiting if prev_step else '-'}</div>
                <div class='stat-sub'>건 (누적 대기 물량)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_c2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{qty_in}</div>
                <div class='stat-sub'>건 (금일 투입)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_c3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{qty_out}</div>
                <div class='stat-sub'>건 (금일 완료)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, confirm_btn_text="완료 처리"):
    """실시간 작업 목록과 공정 제어 버튼을 테이블 형태로 표시합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    
    db_full = st.session_state.production_db
    # 현재 라인에 해당하는 물량만 추출
    view_db = db_full[db_full['라인'] == line_name]
    
    # 조립 라인의 경우 CELL 필터링을 거칩니다.
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_db = view_db[view_db['CELL'] == st.session_state.selected_cell]
        
    if view_db.empty:
        st.info(f"현재 {line_name}에 표시할 내역이 없습니다.")
        return
        
    # 헤더 출력
    col_h = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_list = ["기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "상태 변경 제어"]
    for i, title in enumerate(header_list):
        col_h[i].write(f"**{title}**")
        
    # 데이터 행 최신순으로 표시
    view_db_sorted = view_db.sort_values('시간', ascending=False)
    
    for idx_row, row_data in view_db_sorted.iterrows():
        # 구분선 행 처리
        if row_data['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f1f3f5; padding: 8px; text-align: center; border-radius: 8px; font-weight: bold; color: #495057; border: 1px dashed #ced4da;'>📦 {row_data['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        col_r = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        col_r[0].write(row_data['시간'])
        col_r[1].write(row_data['CELL'])
        col_r[2].write(row_data['모델'])
        col_r[3].write(row_data['품목코드'])
        col_r[4].write(row_data['시리얼'])
        
        with col_r[5]:
            status_val = row_data['상태']
            
            if status_val in ["진행 중", "수리 완료(재투입)"]:
                b_c1, b_c2 = st.columns(2)
                
                if b_c1.button(confirm_btn_text, key=f"ok_btn_{idx_row}"):
                    db_full.at[idx_row, '상태'] = "완료"
                    db_full.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_full):
                        st.rerun()
                        
                if b_c2.button("🚫 불량 발생", key=f"ng_btn_{idx_row}"):
                    db_full.at[idx_row, '상태'] = "불량 처리 중"
                    db_full.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_full):
                        st.rerun()
                        
            elif status_val == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 대기 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 공정 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 메뉴별 상세 렌더링 영역 (초기화 문제 수정 반영)
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 페이지 (Workflow 시작점)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 UI
    all_cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_btn_grid = st.columns(len(all_cells))
    
    for idx_c, cell_name_c in enumerate(all_cells):
        if c_btn_grid[idx_c].button(cell_name_c, type="primary" if st.session_state.selected_cell == cell_name_c else "secondary"):
            st.session_state.selected_cell = cell_name_c
            st.rerun()
            
    # 특정 셀 선택 시에만 신규 생산 등록 폼 노출
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 조립 등록")
            
            # 모델 선택
            input_model = st.selectbox("생산할 제품 모델 선택", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("assembly_registration_form"):
                row_1, row_2 = st.columns(2)
                
                # 모델에 따른 품목 리스트 자동 연동
                item_list_avail = st.session_state.master_items_dict.get(input_model, ["모델 정보 없음"])
                input_item = row_1.selectbox("품목코드 선택", item_list_avail)
                
                input_sn = row_2.text_input("시리얼 번호(S/N)")
                
                submit_btn = st.form_submit_button("▶️ 생산 기록 생성", use_container_width=True, type="primary")
                
                if submit_btn:
                    if input_model != "선택하세요." and input_sn != "":
                        current_db_ptr = st.session_state.production_db
                        
                        # [중복 방지 체크] 모델+시리얼 조합 확인
                        dup_find = current_db_ptr[
                            (current_db_ptr['모델'] == input_model) & 
                            (current_db_ptr['시리얼'] == input_sn) & 
                            (current_db_ptr['상태'] != "구분선")
                        ]
                        
                        if not dup_find.empty:
                            st.error(f"❌ 중복 등록 거부: '{input_sn}' 시리얼은 이미 시스템에 존재합니다.")
                        else:
                            # 신규 제품 행 생성
                            new_data_row = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': input_model, 
                                '품목코드': input_item, 
                                '시리얼': input_sn, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 병합 및 구분선 체크
                            df_updated = pd.concat([current_db_ptr, pd.DataFrame([new_data_row])], ignore_index=True)
                            df_updated = check_and_add_marker(df_updated, "조립 라인")
                            
                            st.session_state.production_db = df_updated
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 정확히 입력해주십시오.")
                        
    display_process_log_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 페이지 (행 업데이트 방식)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    this_line = st.session_state.current_line
    icon_this = "🔍" if this_line == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_this} {this_line} 공정 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(this_line)
    st.divider()
    
    # 이전 단계 공정명
    prev_line_name = "조립 라인" if this_line == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_line_name} 물량 입고 승인")
        
        # 필터링
        filter_col1, filter_col2 = st.columns(2)
        model_filter_val = filter_col1.selectbox("모델 필터링", ["전체"] + st.session_state.master_models, key=f"f_val_{this_line}")
        
        # 대기 데이터 필터링
        full_db_search = st.session_state.production_db
        
        # 이전 공정에서 완료되고 현재 공정 입고 대기 중인 제품
        waiting_rows = full_db_search[
            (full_db_search['라인'] == prev_line_name) & 
            (full_db_search['상태'] == "완료")
        ]
        
        if model_filter_val != "전체":
            waiting_rows = waiting_rows[waiting_rows['모델'] == model_filter_val]
            
        if not waiting_rows.empty:
            st.success(f"현재 {len(waiting_rows)}건의 제품이 입고를 기다리고 있습니다.")
            
            # 입고 버튼 그리드
            in_btn_cols = st.columns(4)
            for i, row_item in enumerate(waiting_rows.itertuples()):
                sn_target = row_item.시리얼
                md_target = row_item.모델
                
                if in_btn_cols[i % 4].button(f"📥 입고: {sn_target}", key=f"in_act_{sn_target}_{this_line}"):
                    st.session_state.confirm_target = sn_target
                    st.session_state.confirm_model = md_target
                    confirm_entry_dialog()
        else:
            st.info(f"현재 {prev_line_name}에서 대기 중인 물량이 없습니다.")
            
    display_process_log_table(this_line, "검사 통과" if this_line == "검사 라인" else "포장 및 출하 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 현황 통합 대시보드</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 최신 데이터 새로고침", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db_rpt = st.session_state.production_db
    
    if not db_rpt.empty:
        # 데이터 정제
        clean_db_rpt = db_rpt[db_rpt['상태'] != '구분선']
        
        # 주요 실적 산출
        # 최종 포장 완료 수량
        final_qty = len(clean_db_rpt[
            (clean_db_rpt['라인'] == '포장 라인') & 
            (clean_db_rpt['상태'] == '완료')
        ])
        
        ng_qty_total = len(clean_db_rpt[clean_db_rpt['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출
        ftt_rate_val = 0
        if (final_qty + ng_qty_total) > 0:
            ftt_rate_val = (final_qty / (final_qty + ng_qty_total)) * 100
        else:
            ftt_rate_val = 100
            
        # 메트릭 레이아웃
        m_r1, m_r2, m_r3, m_r4 = st.columns(4)
        m_r1.metric("최종 제품 출하", f"{final_qty} EA")
        m_r2.metric("공정 재공 수량", len(clean_db_rpt[clean_db_rpt['상태'] == '진행 중']))
        m_r3.metric("누적 불량 건수", f"{ng_qty_total} 건", delta=ng_qty_total, delta_color="inverse")
        m_r4.metric("직행률(FTT)", f"{ftt_rate_val:.1f}%")
        
        st.divider()
        
        # 차트 영역
        chart_col1, chart_col2 = st.columns([3, 2])
        
        with chart_col1:
            dist_df = clean_db_rpt.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(dist_df, x='라인', y='수량', color='라인', title="공정 단계별 실시간 제품 분포"), use_container_width=True)
            
        with chart_col2:
            pie_df = clean_db_rpt.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(pie_df, values='수량', names='모델', hole=0.3, title="생산 모델별 점유율"), use_container_width=True)
            
        st.markdown("##### 🔍 전 공정 통합 생산 이력 데이터")
        st.dataframe(db_rpt.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("표시할 생산 데이터가 부족합니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (line4 계정 권한 대응)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True)
    
    # 상단에 조립 현황 통계 배치 (참조용)
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중 상태인 행들 필터링
    repair_db_all = st.session_state.production_db
    bad_rows_list = repair_db_all[repair_db_all['상태'] == "불량 처리 중"]
    
    if bad_rows_list.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치가 완료된 상태입니다.")
    else:
        st.markdown(f"##### 수리 대기 건수: 총 {len(bad_rows_list)}건")
        
        for idx_b, row_b in bad_rows_list.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **S/N: {row_b['시리얼']}** | 모델: {row_b['모델']} | 발생공정: {row_b['라인']}")
                
                # 입력 필드 레이아웃
                input_col1, input_col2, input_col3 = st.columns([4, 4, 2])
                
                # 이전 입력값 캐시 로드
                cache_symptom = st.session_state.repair_cache.get(f"s_{idx_b}", "")
                cache_action = st.session_state.repair_cache.get(f"a_{idx_b}", "")
                
                in_symptom = input_col1.text_input("불량 원인(Symptom)", value=cache_symptom, key=f"is_{idx_b}")
                in_action = input_col2.text_input("수리 조치(Action)", value=cache_action, key=f"ia_{idx_b}")
                
                # 실시간 캐시 갱신
                st.session_state.repair_cache[f"s_{idx_b}"] = in_symptom
                st.session_state.repair_cache[f"a_{idx_b}"] = in_action
                
                # 사진 첨부
                photo_upload = st.file_uploader("수리 사진 첨부(JPG/PNG)", type=['jpg','png','jpeg'], key=f"ph_{idx_b}")
                
                if photo_upload:
                    st.image(photo_upload, width=300, caption="업로드 예정 사진")
                    
                if input_col3.button("🔧 수리 완료 등록", key=f"finish_act_{idx_b}", type="primary", use_container_width=True):
                    if in_symptom and in_action:
                        img_url_final = ""
                        
                        if photo_upload is not None:
                            with st.spinner("증빙 사진을 드라이브에 저장하고 있습니다..."):
                                ts_now = get_kst_now().strftime('%Y%m%d_%H%M')
                                fn_save = f"{row_b['시리얼']}_FIX_{ts_now}.jpg"
                                res_url = upload_image_to_drive(photo_upload, fn_save)
                                
                                if "http" in res_url:
                                    img_url_final = f" [사진링크: {res_url}]"
                        
                        # 행 데이터 업데이트 (상태 변경)
                        repair_db_all.at[idx_b, '상태'] = "수리 완료(재투입)"
                        repair_db_all.at[idx_b, '증상'] = in_symptom
                        repair_db_all.at[idx_b, '수리'] = in_action + img_url_final
                        repair_db_all.at[idx_b, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(repair_db_all):
                            # 성공 시 캐시 삭제
                            st.session_state.repair_cache.pop(f"s_{idx_b}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_b}", None)
                            st.success("수리 보고서가 정상 반영되었습니다.")
                            st.rerun()
                    else:
                        st.error("원인과 조치 사항을 모두 입력해야 합니다.")

# -----------------------------------------------------------------
# 6-5. 수리 결과 분석 리포트
# -----------------------------------------------------------------
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 이력 분석 리포트</h2>", unsafe_allow_html=True)
    
    db_full_rpt = st.session_state.production_db
    # 수리 완료 기록이 있는 데이터만 필터링
    repair_hist_df = db_full_rpt[
        (db_full_rpt['상태'].str.contains("재투입", na=False)) | 
        (db_full_rpt['수리'] != "")
    ]
    
    if not repair_hist_df.empty:
        sc1, sc2 = st.columns(2)
        
        with sc1:
            line_bad_rpt = repair_hist_df.groupby('라인').size().reset_index(name='건수')
            st.plotly_chart(px.bar(line_bad_rpt, x='라인', y='건수', title="공정 단계별 불량 발생 빈도"), use_container_width=True)
            
        with sc2:
            model_bad_rpt = repair_hist_df.groupby('모델').size().reset_index(name='건수')
            st.plotly_chart(px.pie(model_bad_rpt, values='건수', names='모델', hole=0.3, title="모델별 불량 구성 비율"), use_container_width=True)
            
        st.markdown("##### 📋 상세 수리 및 조치 이력 통합 데이터")
        st.dataframe(repair_hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("조회할 수리 데이터가 존재하지 않습니다.")

# -----------------------------------------------------------------
# 6-6. 마스터 데이터 관리 (초기화 오류 수정 반영)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리자 전용 마스터 센터</h2>", unsafe_allow_html=True)
    
    # 보안 인증
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            st.write("안전한 시스템 설정을 위해 관리자 비밀번호가 필요합니다.")
            input_pw_admin = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            
            if st.form_submit_button("관리자 인증"):
                if input_pw_admin in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 기능이 개방되었습니다.")
                    st.rerun()
                else:
                    st.error("비밀번호 불일치")
    else:
        if st.sidebar.button("🔓 마스터 모드 종료"):
            st.session_state.admin_authenticated = False
            navigate_to_page("생산 리포트")

        st.markdown("### 📋 1. 생산 기준 정보 설정")
        row_adm_1, row_adm_2 = st.columns(2)
        
        with row_adm_1:
            with st.container(border=True):
                st.write("**새 모델 등록**")
                new_m_nm = st.text_input("추가할 모델 명칭")
                
                if st.button("모델 등록", use_container_width=True):
                    if new_m_nm and new_m_nm not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m_nm)
                        st.session_state.master_items_dict[new_m_nm] = []
                        st.success(f"'{new_m_nm}' 모델이 등록되었습니다.")
                        st.rerun()

        with row_adm_2:
            with st.container(border=True):
                st.write("**품목코드 마스터 설정**")
                select_m = st.selectbox("대상 모델 선택", st.session_state.master_models)
                new_i_nm = st.text_input("새 품목코드")
                
                if st.button("품목코드 등록", use_container_width=True):
                    if new_i_nm and new_i_nm not in st.session_state.master_items_dict[select_m]:
                        st.session_state.master_items_dict[select_m].append(new_i_nm)
                        st.success(f"[{select_m}] 품목 코드가 등록되었습니다.")
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 관리 및 백업")
        row_bk_1, row_bk_2 = st.columns(2)
        
        with row_bk_1:
            st.write("현재 구글 시트의 전체 생산 데이터를 CSV로 내보냅니다.")
            csv_data_out = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            
            st.download_button(
                "📥 전체 실적 CSV 다운로드", 
                csv_data_out, 
                f"production_log_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with row_bk_2:
            st.write("백업된 CSV 파일을 로드하여 기존 데이터에 통합합니다.")
            csv_import_file = st.file_uploader("백업용 CSV 파일 선택", type="csv")
            
            if csv_import_file and st.button("📤 데이터 로드 반영", use_container_width=True):
                df_loaded = pd.read_csv(csv_import_file)
                # 시리얼 번호 타입 보정
                if '시리얼' in df_loaded.columns:
                    df_loaded['시리얼'] = df_loaded['시리얼'].astype(str)
                
                st.session_state.production_db = pd.concat([st.session_state.production_db, df_loaded], ignore_index=True)
                
                if save_to_gsheet(st.session_state.production_db):
                    st.success("데이터 로드 및 시트 업데이트 완료")
                    st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 권한 및 계정 관리")
        
        user_c1, user_c2, user_c3 = st.columns([3, 3, 2])
        new_u_id = user_c1.text_input("새 아이디")
        new_u_pw = user_c2.text_input("새 비밀번호", type="password")
        new_u_role = user_c3.selectbox("권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성/업데이트", use_container_width=True):
            if new_u_id and new_u_pw:
                st.session_state.user_db[new_u_id] = {"pw": new_u_pw, "role": new_u_role}
                st.success(f"계정 [{new_u_id}] 등록 완료")
                st.rerun()
        
        with st.expander("현재 시스템 등록 계정 일람"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("### ⚠️ 4. 위험 구역 (시트 데이터 완전 초기화)")
        # [수정] 초기화 시 force_reset=True 옵션을 주어 구글 시트를 물리적으로 비웁니다.
        if st.button("🚫 시스템 전체 생산 데이터 초기화", type="secondary", use_container_width=True):
             st.error("주의: 이 작업은 구글 시트의 모든 데이터를 삭제하며 되돌릴 수 없습니다.")
             if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                 # 빈 데이터프레임 생성
                 reset_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 st.session_state.production_db = reset_df
                 
                 # 강제 초기화 모드로 저장 실행
                 if save_to_gsheet(reset_df, force_reset=True):
                     st.success("구글 시트의 모든 데이터가 성공적으로 초기화되었습니다.")
                     st.rerun()
