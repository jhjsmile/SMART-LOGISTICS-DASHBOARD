import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리 (사진 업로드용)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
# 페이지의 제목과 레이아웃을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.1", 
    layout="wide"
)

# [핵심] 역할(Role) 정의
# 사용자 계정별로 접근 가능한 메뉴를 세밀하게 분리합니다.
# 특히 'line4'를 위해 'repair_team' 권한을 별도로 구성했습니다.
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
        "불량 공정"  # line4 전용: 수리 센터 메뉴만 노출
    ]
}

# CSS 스타일 정의: 화면 레이아웃과 버튼, 통계 박스의 디자인을 설정합니다.
st.markdown("""
    <style>
    /* 전체 앱 최대 너비 설정 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 상단 여백 및 크기 조정 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
    }
    
    /* 제목 중앙 정렬 스타일 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 20px 0; 
    }
    
    /* 불량 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 15px; 
        border-radius: 8px; 
        border: 1px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 20px;
        text-align: center;
    }
    
    /* 상단 통계 수치 박스 스타일 */
    .stat-box {
        background-color: #f0f2f6; 
        border-radius: 10px; 
        padding: 15px; 
        text-align: center;
        border: 1px solid #e0e0e0; 
        margin-bottom: 10px;
    }
    
    .stat-label { 
        font-size: 0.9em; 
        color: #555; 
        font-weight: bold; 
    }
    
    .stat-value { 
        font-size: 1.8em; 
        color: #007bff; 
        font-weight: bold; 
    }
    
    .stat-sub { 
        font-size: 0.8em; 
        color: #888; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 및 드라이브 연동 함수
# =================================================================
# Streamlit GSheets Connection을 사용하여 구글 시트와 연결합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """
    서버 시간이 아닌 한국 표준시(KST)를 반환합니다.
    서버 시간 대비 9시간을 더합니다.
    """
    kst_time = datetime.now() + timedelta(hours=9)
    return kst_time

def load_data():
    """
    구글 시트로부터 전체 생산 데이터를 읽어옵니다.
    데이터 손실을 방지하기 위해 로드 실패 시 세션 데이터를 보호합니다.
    """
    try:
        df = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 숫자로 인식될 경우를 대비해 문자열로 변환하고 소수점을 제거합니다.
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [중요] 시트 데이터가 비어있을 경우 세션에 이미 데이터가 있다면 세션 값을 유지합니다.
        if df.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
        return df
    except Exception as e:
        st.error(f"구글 시트 로드 중 오류 발생: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """
    변경된 데이터를 구글 시트에 업데이트합니다.
    빈 데이터가 저장되어 시트가 초기화되는 것을 방지하기 위한 안전장치를 포함합니다.
    """
    # 1. 빈 데이터 체크 (초기화 방지)
    if df.empty:
        st.error("❌ 시스템 보호: 저장하려는 데이터가 비어있어 작업을 중단했습니다.")
        return False
    
    # 2. API Quota 에러에 대비하여 최대 3회 재시도 로직을 적용합니다.
    for attempt in range(3):
        try:
            conn.update(data=df)
            # 캐시를 클리어하여 즉시 반영되도록 합니다.
            st.cache_data.clear()
            return True
        except Exception as e:
            if attempt < 2:
                # 1.5초 대기 후 재시도합니다.
                time.sleep(1.5)
                continue
            else:
                st.error(f"⚠️ 구글 시트 저장 실패 (3회 시도 모두 실패): {e}")
                return False

def upload_image_to_drive(file_obj, filename):
    """
    수리 완료 시 업로드한 사진을 구글 드라이브 지정 폴더에 저장합니다.
    성공 시 이미지의 웹 보기 링크를 반환합니다.
    """
    try:
        # secrets에서 API 정보를 가져옵니다.
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 드라이브 서비스 빌드
        service = build('drive', 'v3', credentials=creds)
        
        # 구글 드라이브의 폴더 ID를 가져옵니다.
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "폴더ID설정안됨"

        # 파일 메타데이터 및 미디어 객체 생성
        file_metadata = {
            'name': filename, 
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 드라이브 파일 생성 실행
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        return f"업로드실패({str(e)})"

# =================================================================
# 3. 세션 상태(Session State) 초기화
# =================================================================
# 애플리케이션 시작 시 한 번만 실행되는 초기화 설정입니다.

if 'production_db' not in st.session_state:
    # 최초 실행 시 데이터를 로드합니다.
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 시스템에서 사용하는 기본 계정 정보입니다.
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
# 4. 로그인 화면 및 메뉴 구성
# =================================================================

# 로그인하지 않은 상태일 때 로그인 폼을 표시합니다.
if not st.session_state.login_status:
    # 화면 중앙에 정렬하기 위해 컬럼을 나눕니다.
    _, l_col, _ = st.columns([1, 1.2, 1])
    
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 계정 안내: master(전체), admin(관제), line1~4(현장)")
        
        with st.form("login_form"):
            user_id_input = st.text_input("아이디(ID)")
            user_pw_input = st.text_input("비밀번호(PW)", type="password")
            
            submit_login = st.form_submit_button("로그인 진행", use_container_width=True)
            
            if submit_login:
                # 계정 정보 일치 여부를 확인합니다.
                if user_id_input in st.session_state.user_db:
                    db_pw = st.session_state.user_db[user_id_input]["pw"]
                    
                    if user_pw_input == db_pw:
                        # 로그인 성공 시 세션 상태를 업데이트합니다.
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = user_id_input
                        st.session_state.user_role = st.session_state.user_db[user_id_input]["role"]
                        
                        # 권한에 맞는 첫 번째 메뉴로 자동 이동합니다.
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("비밀번호가 올바르지 않습니다.")
                else:
                    st.error("존재하지 않는 사용자 계정입니다.")
    st.stop()

# 사이드바 설정 영역
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("시스템 전체 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 메뉴 이동 함수 정의
def nav(menu_name):
    st.session_state.current_line = menu_name
    st.rerun()

# 사용자 권한에 따른 메뉴 리스트 생성
user_allowed_menus = ROLES.get(st.session_state.user_role, [])

# 메뉴 그룹 1: 공정 현황 및 리포트
menus_main = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_main = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

group_1_displayed = False
for m in menus_main:
    if m in user_allowed_menus:
        group_1_displayed = True
        btn_label = f"{icons_main[m]} {m}" + (" 현황" if "라인" in m else "")
        
        # 현재 활성화된 메뉴는 파란색(primary)으로 표시합니다.
        btn_type = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(btn_label, use_container_width=True, type=btn_type):
            nav(m)

# 메뉴 그룹 2: 불량 관리 및 수리 결과
menus_repair = ["불량 공정", "수리 리포트"]
icons_repair = {"불량 공정":"🛠️", "수리 리포트":"📈"}

group_2_displayed = False
for m in menus_repair:
    if m in user_allowed_menus:
        group_2_displayed = True

if group_1_displayed and group_2_displayed:
    st.sidebar.divider()

for m in menus_repair:
    if m in user_allowed_menus:
        repair_btn_label = f"{icons_repair[m]} {m}"
        repair_btn_type = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(repair_btn_label, use_container_width=True, type=repair_btn_type):
            nav(m)

# 마스터 데이터 관리 전용 메뉴
if "마스터 관리" in user_allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        nav("마스터 관리")

# 하단 공용 알림창 (수리 대기 중인 항목 노출)
bad_rows = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not bad_rows.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 알림: 현재 {len(bad_rows)}건의 제품이 수리 대기 상태입니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 공용 컴포넌트 및 로직 (워크플로우 전이 핵심)
# =================================================================

def check_and_add_marker(df, line_name):
    """
    조립 라인에서 10대 단위로 구분선을 추가합니다. (시트 시인성 확보)
    """
    today_date = get_kst_now().strftime('%Y-%m-%d')
    
    # 해당 라인의 오늘 생산 실적(구분선 제외)을 계산합니다.
    today_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(today_date)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대마다 구분선 행을 추가합니다.
    if today_count > 0 and today_count % 10 == 0:
        marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {today_count}대 실적 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        df_marked = pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
        return df_marked
    return df

@st.dialog("📦 공정 상태 전환 승인")
def confirm_entry_dialog():
    """
    제품이 다음 공정으로 이동할 때, 기존 행의 정보를 업데이트합니다.
    (조립 -> 검사 -> 포장 단일 행 트래킹 로직)
    """
    st.warning(f"제품 [ {st.session_state.confirm_target} ]을(를) {st.session_state.current_line}에 입고하시겠습니까?")
    st.write("승인 시 해당 제품의 위치 정보가 업데이트됩니다.")
    
    c1, c2 = st.columns(2)
    
    if c1.button("✅ 입고 승인", type="primary", use_container_width=True):
        # 전체 데이터베이스를 가져옵니다.
        db = st.session_state.production_db
        
        # 모델과 시리얼 번호가 일치하는 유일한 행을 찾습니다.
        target_idx = db[
            (db['모델'] == st.session_state.confirm_model) & 
            (db['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not target_idx.empty:
            # 기존 데이터를 업데이트합니다. (행 추가가 아님)
            idx = target_idx[0]
            db.at[idx, '라인'] = st.session_state.current_line
            db.at[idx, '상태'] = '진행 중'
            db.at[idx, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db.at[idx, '작업자'] = st.session_state.user_id
            
            # 구글 시트에 즉시 동기화합니다.
            if save_to_gsheet(db):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("대상 제품의 정보를 데이터베이스에서 찾을 수 없습니다.")
            
    if c2.button("❌ 승인 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(current_line_name):
    """
    상단 통계 바를 생성합니다. (대기, 진행 중, 완료 물량 계산)
    수량 계산 오류(5->14)를 해결하기 위해 조합키 방식을 사용합니다.
    """
    db = st.session_state.production_db
    today_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 현재 라인의 오늘 데이터 필터링
    today_records = db[
        (db['라인'] == current_line_name) & 
        (db['시간'].astype(str).str.contains(today_str)) & 
        (db['상태'] != '구분선')
    ]
    
    count_input = len(today_records)
    count_done = len(today_records[today_records['상태'] == '완료'])
    
    # 이전 라인에서의 대기 물량 산출
    wait_count = 0
    prev_line_name = None
    
    if current_line_name == "검사 라인":
        prev_line_name = "조립 라인"
    elif current_line_name == "포장 라인":
        prev_line_name = "검사 라인"
    
    if prev_line_name:
        # 이전 공정에서 '완료' 상태로 대기 중인 행을 모두 가져옵니다.
        waiting_data = db[
            (db['라인'] == prev_line_name) & 
            (db['상태'] == '완료')
        ]
        wait_count = len(waiting_data)
    
    # 3개 컬럼으로 구성된 통계 레이아웃
    st_col1, st_col2, st_col3 = st.columns(3)
    
    with st_col1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {prev_line_name if prev_line_name else '입고'} 대기</div>
                <div class='stat-value' style='color: #ff9800;'>{wait_count if prev_line_name else '-'}</div>
                <div class='stat-sub'>건 (누적)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {current_line_name} 진행 중</div>
                <div class='stat-value'>{count_input}</div>
                <div class='stat-sub'>건 (Today)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {current_line_name} 완료</div>
                <div class='stat-value' style='color: #28a745;'>{count_done}</div>
                <div class='stat-sub'>건 (Today)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, confirm_btn_label="완료"):
    """
    현재 라인에서 작업 중인 제품들의 목록을 테이블 형식으로 표시하고 제어 버튼을 제공합니다.
    """
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    
    db = st.session_state.production_db
    # 현재 라인 물량 필터링
    line_view_db = db[db['라인'] == line_name]
    
    # 조립 라인일 경우 선택한 CELL 물량만 필터링합니다.
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        line_view_db = line_view_db[line_view_db['CELL'] == st.session_state.selected_cell]
    
    if line_view_db.empty:
        st.info(f"현재 {line_name}에 작업 중인 내역이 없습니다.")
        return
    
    # 컬럼 헤더 구성
    log_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    log_header = ["최종시간", "CELL", "모델명", "품목코드", "시리얼", "상태 제어"]
    
    for i, title in enumerate(log_header):
        log_cols[i].write(f"**{title}**")
        
    # 데이터 행 최신순으로 출력
    sorted_view = line_view_db.sort_values('시간', ascending=False)
    
    for idx, row in sorted_view.iterrows():
        # 구분선 행 처리
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #e9ecef; padding: 5px; text-align: center; border-radius: 5px; font-weight: bold; color: #495057;'>📦 {row['시리얼']} -----------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        row_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        row_cols[0].write(row['시간'])
        row_cols[1].write(row['CELL'])
        row_cols[2].write(row['모델'])
        row_cols[3].write(row['품목코드'])
        row_cols[4].write(row['시리얼'])
        
        with row_cols[5]:
            current_status = row['상태']
            
            if current_status in ["진행 중", "수리 완료(재투입)"]:
                b_pass, b_ng = st.columns(2)
                
                if b_pass.button(confirm_btn_label, key=f"btn_pass_{idx}"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db):
                        st.rerun()
                        
                if b_ng.button("🚫불량", key=f"btn_ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db):
                        st.rerun()
                        
            elif current_status == "불량 처리 중":
                st.markdown("<span style='color:red; font-weight:bold;'>🔴 불량 수리 대기 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:green; font-weight:bold;'>🟢 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 메인 렌더링 영역
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 현황 (Start Point)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 버튼 구성
    cell_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_cols = st.columns(len(cell_list))
    
    for i, cell_name in enumerate(cell_list):
        if btn_cols[i].button(cell_name, type="primary" if st.session_state.selected_cell == cell_name else "secondary"):
            st.session_state.selected_cell = cell_name
            st.rerun()
            
    # 개별 CELL 선택 시에만 신규 등록 폼을 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🔨 {st.session_state.selected_cell} 신규 조립 등록")
            
            model_sel = st.selectbox("모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("assembly_entry_form"):
                form_r1, form_r2 = st.columns(2)
                
                # 모델 선택에 따른 품목코드 목록 자동 변경
                item_list = st.session_state.master_items_dict.get(model_sel, ["모델을 먼저 선택하세요."])
                item_sel = form_r1.selectbox("품목코드 선택", item_list)
                
                sn_input = form_r2.text_input("시리얼 번호(S/N) 입력")
                
                submit_reg = st.form_submit_button("▶️ 신규 생산 등록", use_container_width=True, type="primary")
                
                if submit_reg:
                    if model_sel != "선택하세요." and sn_input != "":
                        current_db = st.session_state.production_db
                        
                        # [전수 중복 체크] 모델과 시리얼 번호가 이미 존재하는지 확인합니다.
                        duplicate_check = current_db[
                            (current_db['모델'] == model_sel) & 
                            (current_db['시리얼'] == sn_input) & 
                            (current_db['상태'] != "구분선")
                        ]
                        
                        if not duplicate_check.empty:
                            st.error(f"❌ 중복 등록 불가: '{sn_input}' 번호의 생산 기록이 이미 존재합니다.")
                        else:
                            # 신규 행 데이터 구성
                            new_entry = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': model_sel, 
                                '품목코드': item_sel, 
                                '시리얼': sn_input, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 추가 및 구분선 체크
                            updated_db = pd.concat([current_db, pd.DataFrame([new_entry])], ignore_index=True)
                            updated_db = check_and_add_marker(updated_db, "조립 라인")
                            
                            st.session_state.production_db = updated_db
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 모두 확인해주세요.")
                        
    display_process_log_table("조립 라인", "조립 완료")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 (Workflow Update)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_name = st.session_state.current_line
    title_icon = "🔍" if line_name == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{title_icon} {line_name} 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(line_name)
    st.divider()
    
    # 이전 단계 공정 정의
    previous_line = "조립 라인" if line_name == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {previous_line} 물량 입고 처리")
        
        sel_c1, sel_c2 = st.columns(2)
        model_f = sel_c1.selectbox("모델 필터", ["전체보기"] + st.session_state.master_models, key=f"f1_{line_name}")
        
        # 모델 필터링에 따른 물량 조회
        db_all = st.session_state.production_db
        
        # 이전 라인에서 '완료'된 상태인 물량만 입고 대상으로 간주합니다.
        waiting_pool = db_all[
            (db_all['라인'] == previous_line) & 
            (db_all['상태'] == "완료")
        ]
        
        if model_f != "전체보기":
            waiting_pool = waiting_pool[waiting_pool['모델'] == model_f]
            
        if not waiting_pool.empty:
            st.success(f"현재 입고 가능한 물량이 {len(waiting_pool)}건 검색되었습니다.")
            
            # 버튼 그리드 구성 (4열)
            btn_grid = st.columns(4)
            for idx_btn, row_btn in enumerate(waiting_pool.itertuples()):
                btn_sn = row_btn.시리얼
                btn_model = row_btn.모델
                btn_item = row_btn.품목코드
                
                if btn_grid[idx_btn % 4].button(f"📥 입고: {btn_sn}", key=f"in_{btn_sn}_{line_name}"):
                    st.session_state.confirm_target = btn_sn
                    st.session_state.confirm_model = btn_model
                    st.session_state.confirm_item = btn_item
                    confirm_entry_dialog()
        else:
            st.info(f"현재 {previous_line}에서 입고 대기 중인 물량이 없습니다.")
            
    display_process_log_table(line_name, "검사 합격" if line_name == "검사 라인" else "출하 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 통합 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 리포트 통합 대시보드</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 최신 데이터로 대시보드 새로고침", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db_report = st.session_state.production_db
    
    if not db_report.empty:
        # 구분선 행을 제외한 실제 작업 데이터만 추출
        clean_db = db_report[db_report['상태'] != '구분선']
        
        # 주요 생산 지표 산출
        # 최종 생산량은 포장 라인에서 '완료'된 행의 수입니다.
        total_out = len(clean_db[
            (clean_db['라인'] == '포장 라인') & 
            (clean_db['상태'] == '완료')
        ])
        
        total_ng_count = len(clean_db[clean_db['상태'].str.contains("불량", na=False)])
        
        # FTT(직행률) 계산
        ftt_val = 0
        if (total_out + total_ng_count) > 0:
            ftt_val = (total_out / (total_out + total_ng_count)) * 100
        else:
            ftt_val = 100
            
        # 메트릭 레이아웃
        met_c1, met_c2, met_c3, met_c4 = st.columns(4)
        met_c1.metric("최종 제품 출하", f"{total_out} EA")
        met_c2.metric("전체 공정 재공", len(clean_db[clean_db['상태'] == '진행 중']))
        met_c3.metric("누적 불량 건수", f"{total_ng_count} 건", delta=total_ng_count, delta_color="inverse")
        met_c4.metric("직행률(FTT)", f"{ftt_val:.1f}%")
        
        st.divider()
        
        # 시각화 차트 영역
        chart_c1, chart_c2 = st.columns([3, 2])
        
        with chart_c1:
            # 라인별 제품 위치 분포
            pos_df = clean_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(pos_df, x='라인', y='수량', color='라인', title="현재 라인별 제품 분포 현황"), use_container_width=True)
            
        with chart_c2:
            # 모델별 비중 파이 차트
            model_pie = clean_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie, values='수량', names='모델', hole=0.3, title="전체 생산 모델 비중"), use_container_width=True)
            
        st.divider()
        st.markdown("##### 👷 현장 작업자별 처리 건수")
        worker_stat = clean_db.groupby('작업자').size().reset_index(name='처리건수')
        st.plotly_chart(px.bar(worker_stat, x='작업자', y='처리건수', color='작업자'), use_container_width=True)
        
        st.markdown("##### 🔍 상세 생산 이력 데이터 (전체)")
        st.dataframe(db_report.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("리포트를 구성할 데이터가 충분하지 않습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (Repair Center)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 및 관리 센터</h2>", unsafe_allow_html=True)
    
    # 조립 라인 기준의 현재 대기 물량을 표시하여 수리 속도를 조절할 수 있게 합니다.
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중인 제품들만 필터링합니다.
    repair_db = st.session_state.production_db
    bad_list = repair_db[repair_db['상태'] == "불량 처리 중"]
    
    if bad_list.empty:
        st.success("✅ 현재 모든 제품의 수리 작업이 완료되어 대기 중인 불량품이 없습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 물량: {len(bad_list)}건")
        
        for idx_r, row_r in bad_list.iterrows():
            with st.container(border=True):
                st.markdown(f"🚩 **S/N: {row_r['시리얼']}** | 모델: {row_r['모델']} | 발생 공정: {row_r['라인']}")
                
                # 입력 영역 구성
                rep_c1, rep_c2, rep_c3 = st.columns([4, 4, 2])
                
                # 캐시된 수리 내역 로드
                cache_s_val = st.session_state.repair_cache.get(f"s_{idx_r}", "")
                cache_a_val = st.session_state.repair_cache.get(f"a_{idx_r}", "")
                
                s_cause = rep_c1.text_input("불량 원인 상세 기술", value=cache_s_val, key=f"s_in_{idx_r}")
                a_action = rep_c2.text_input("수리 조치 내용", value=cache_a_val, key=f"a_in_{idx_r}")
                
                # 캐시 즉시 업데이트
                st.session_state.repair_cache[f"s_{idx_r}"] = s_cause
                st.session_state.repair_cache[f"a_{idx_r}"] = a_action
                
                # 사진 첨부 (드라이브 저장용)
                repair_photo = st.file_uploader("수리 조치 사진 첨부 (JPG/PNG)", type=['jpg','png','jpeg'], key=f"img_up_{idx_r}")
                
                if repair_photo:
                    st.image(repair_photo, width=300, caption="첨부된 수리 사진")
                    
                if rep_c3.button("🛠️ 수리 완료 승인", key=f"btn_rep_done_{idx_r}", type="primary", use_container_width=True):
                    if s_cause and a_action:
                        final_img_link = ""
                        
                        if repair_photo is not None:
                            with st.spinner("증빙 사진을 구글 드라이브에 안전하게 업로드 중..."):
                                ts = get_kst_now().strftime('%Y%m%d_%H%M')
                                f_name = f"{row_r['시리얼']}_REPAIR_{ts}.jpg"
                                upload_res = upload_image_to_drive(repair_photo, f_name)
                                
                                if "http" in upload_res:
                                    final_img_link = f" [사진링크: {upload_res}]"
                        
                        # 데이터베이스 업데이트: 상태를 '재투입'으로 변경합니다.
                        repair_db.at[idx_r, '상태'] = "수리 완료(재투입)"
                        repair_db.at[idx_r, '증상'] = s_cause
                        repair_db.at[idx_r, '수리'] = a_action + final_img_link
                        repair_db.at[idx_r, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(repair_db):
                            # 성공 시 입력 캐시 제거
                            st.session_state.repair_cache.pop(f"s_{idx_r}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_r}", None)
                            st.success("수리 완료 보고가 시트에 정상 반영되었습니다.")
                            st.rerun()
                    else:
                        st.error("수리 원인과 조치 사항을 반드시 입력해야 합니다.")

# -----------------------------------------------------------------
# 6-5. 수리 결과 분석 리포트
# -----------------------------------------------------------------
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 분석 리포트</h2>", unsafe_allow_html=True)
    
    total_db = st.session_state.production_db
    # 수리 내역이 존재하는 행만 필터링합니다.
    repair_summary = total_db[
        (total_db['상태'].str.contains("재투입", na=False)) | 
        (total_db['수리'] != "")
    ]
    
    if not repair_summary.empty:
        r_col1, r_col2 = st.columns(2)
        
        with r_col1:
            # 공정별 불량 빈도 분석
            bad_freq = repair_summary.groupby('라인').size().reset_index(name='건수')
            st.plotly_chart(px.bar(bad_freq, x='라인', y='건수', title="공정별 불량 발생 빈도"), use_container_width=True)
            
        with r_col2:
            # 모델별 불량 분포 분석
            bad_model = repair_summary.groupby('모델').size().reset_index(name='건수')
            st.plotly_chart(px.pie(bad_model, values='건수', names='모델', hole=0.3, title="불량 모델별 분포 비중"), use_container_width=True)
            
        st.markdown("##### 📋 상세 수리 조치 이력")
        st.dataframe(repair_summary[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재 시스템에 누적된 수리 이력 데이터가 없습니다.")

# -----------------------------------------------------------------
# 6-6. 마스터 데이터 관리 (Admin Only)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리자 전용 메뉴</h2>", unsafe_allow_html=True)
    
    # 관리자 인증 상태 확인
    if not st.session_state.admin_authenticated:
        with st.form("admin_security_form"):
            st.write("중요 설정 변경을 위해 관리자 인증이 필요합니다.")
            input_apw = st.text_input("관리자 비밀번호 입력 (admin1234)", type="password")
            
            if st.form_submit_button("관리자 권한 인증"):
                if input_apw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 성공: 관리자 세션이 활성화되었습니다.")
                    st.rerun()
                else:
                    st.error("비밀번호 인증 실패")
    else:
        if st.button("🔓 관리자 세션 종료 및 메뉴 잠금", use_container_width=True):
            st.session_state.admin_authenticated = False
            nav("생산 리포트")

        st.markdown("### 📋 1. 제품 마스터 관리")
        admin_c1, admin_c2 = st.columns(2)
        
        with admin_c1:
            with st.container(border=True):
                st.write("**새로운 모델 등록**")
                n_model_name = st.text_input("신규 모델명 입력")
                
                if st.button("➕ 모델 추가", use_container_width=True):
                    if n_model_name and n_model_name not in st.session_state.master_models:
                        st.session_state.master_models.append(n_model_name)
                        st.session_state.master_items_dict[n_model_name] = []
                        st.success(f"'{n_model_name}' 모델 등록 완료")
                        st.rerun()

        with admin_c2:
            with st.container(border=True):
                st.write("**모델별 품목코드 등록**")
                sel_model_m = st.selectbox("대상 모델 선택", st.session_state.master_models)
                n_item_code = st.text_input("신규 품목코드 입력")
                
                if st.button("➕ 품목코드 추가", use_container_width=True):
                    if n_item_code and n_item_code not in st.session_state.master_items_dict[sel_model_m]:
                        st.session_state.master_items_dict[sel_model_m].append(n_item_code)
                        st.success(f"[{sel_model_m}] 품목코드 등록 완료")
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 외부 로드")
        backup_c1, backup_c2 = st.columns(2)
        
        with backup_c1:
            st.write("현재 구글 시트의 전체 데이터를 CSV로 백업합니다.")
            csv_export = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            
            st.download_button(
                "📥 전체 데이터 CSV 다운로드", 
                csv_export, 
                f"backup_production_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with backup_c2:
            st.write("CSV 백업 파일을 업로드하여 데이터를 일괄 병합합니다.")
            csv_upload = st.file_uploader("백업 CSV 파일 선택", type="csv")
            
            if csv_upload and st.button("📤 데이터 로드 및 시트 업데이트", use_container_width=True):
                new_loaded_df = pd.read_csv(csv_upload)
                # 시리얼 번호 타입 보정
                if '시리얼' in new_loaded_df.columns:
                    new_loaded_df['시리얼'] = new_loaded_df['시리얼'].astype(str)
                
                st.session_state.production_db = pd.concat([st.session_state.production_db, new_loaded_df], ignore_index=True)
                
                if save_to_gsheet(st.session_state.production_db):
                    st.success("데이터 로드 및 시트 업데이트 성공!")
                    st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 계정 및 권한 관리")
        
        user_add_c1, user_add_c2, user_add_c3 = st.columns([3, 3, 2])
        target_uid = user_add_c1.text_input("아이디(ID) 설정")
        target_upw = user_add_c2.text_input("비밀번호(PW) 설정", type="password")
        target_role = user_add_c3.selectbox("부여 권한 선택", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 사용자 계정 생성 및 업데이트", use_container_width=True):
            if target_uid and target_upw:
                st.session_state.user_db[target_uid] = {"pw": target_upw, "role": target_role}
                st.success(f"계정 [{target_uid}] 등록/업데이트 완료")
                st.rerun()
        
        with st.expander("현재 시스템 계정 정보 테이블 확인"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("### ⚠️ 4. 위험 구역 (전체 초기화)")
        if st.button("🚫 시스템 전체 생산 DB 초기화", type="secondary", use_container_width=True):
             st.warning("경고: 초기화 시 복구가 절대 불가능합니다. 신중하게 선택하세요.")
             if st.button("❌ 위험 감수: 전체 삭제 확정"):
                 st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 if save_to_gsheet(st.session_state.production_db):
                     st.success("시스템 데이터가 완전히 초기화되었습니다.")
                     st.rerun()
