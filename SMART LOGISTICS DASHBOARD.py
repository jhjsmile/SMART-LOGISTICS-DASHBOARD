import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리 (사진 저장용)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의 (상세 전개)
# =================================================================
# 앱의 기본적인 페이지 설정을 수행합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.7", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 계정별 메뉴 권한
# 현장의 요구사항에 맞춰 line4 전용 'repair_team' 권한을 포함했습니다.
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
        "불량 공정"  # line4 계정 전용 권한
    ]
}

# UI 디자인 설정을 위한 상세 CSS 정의
st.markdown("""
    <style>
    /* 메인 앱 컨테이너의 최대 너비와 중앙 정렬을 설정합니다. */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 모든 버튼의 높이, 여백, 글꼴 두께를 현장 작업에 최적화합니다. */
    .stButton button { 
        margin-top: 5px; 
        padding: 8px 10px; 
        width: 100%; 
        font-weight: bold;
    }
    
    /* 제목을 중앙에 배치하고 가독성을 높입니다. */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 25px 0; 
        color: #2d3436;
    }
    
    /* 불량 발생 시 작업자에게 경고를 주는 배너 스타일입니다. */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #d63031; 
        padding: 20px; 
        border-radius: 12px; 
        border: 2px solid #ff8787; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        font-size: 1.1em;
    }
    
    /* 상단 통계 지표 박스의 스타일을 정의합니다. */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 15px; 
        padding: 22px; 
        text-align: center;
        border: 1px solid #dfe6e9; 
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    .stat-label { 
        font-size: 1em; 
        color: #636e72; 
        font-weight: 700; 
        margin-bottom: 5px;
    }
    
    .stat-value { 
        font-size: 2.3em; 
        color: #0984e3; 
        font-weight: 800; 
    }
    
    .stat-sub { 
        font-size: 0.9em; 
        color: #b2bec3; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 및 드라이브 연동 함수 (초기화 및 데이터 보호 로직)
# =================================================================
# 구글 시트 연결을 위한 객체를 생성합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 생성하여 반환합니다."""
    kst_offset = timedelta(hours=9)
    kst_now = datetime.now() + kst_offset
    return kst_now

def load_data():
    """구글 시트에서 데이터를 로드하고 시리얼 번호 형식을 보정합니다."""
    try:
        # 캐시를 무시하고 실시간 데이터를 가져옵니다.
        df_sheet = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 숫자로 인식되어 소수점이 생기는 현상을 방지합니다.
        if '시리얼' in df_sheet.columns:
            df_sheet['시리얼'] = df_sheet['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [데이터 보호] 로드된 데이터가 비어있을 경우 세션 내의 데이터를 유지합니다.
        if df_sheet.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
                
        return df_sheet
    except Exception as e:
        st.error(f"데이터 연동 중 오류가 발생했습니다: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_mode=False):
    """
    구글 시트에 데이터를 업데이트합니다. 
    is_reset_mode가 True일 때만 빈 데이터를 시트에 반영하여 초기화를 수행합니다.
    """
    # 1. 평상시 작업 중 데이터가 증발하는 것을 방지합니다.
    if df.empty and not is_reset_mode:
        st.error("❌ 저장 보호: 빈 데이터 저장이 차단되었습니다. 페이지를 새로고침 하세요.")
        return False
    
    # 2. 구글 시트 API의 안정성을 위해 최대 3회 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # 시트 업데이트 실행
            conn.update(data=df)
            
            # 캐시를 즉시 삭제하여 데이터 동기화를 보장합니다.
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                # 2초 대기 후 재시도합니다.
                time.sleep(2)
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (최종): {api_err}")
                return False

def upload_image_to_drive(file_data, file_name):
    """수리 사진을 구글 드라이브 지정 폴더에 업로드합니다."""
    try:
        # 인증 정보 로드
        creds_raw = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(creds_raw)
        
        # 드라이브 API 서비스 구축
        service = build('drive', 'v3', credentials=credentials)
        
        # 드라이브 폴더 아이디 조회
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "오류: 폴더 ID 미지정"

        file_metadata = {
            'name': file_name, 
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_data, mimetype=file_data.type)
        
        # 업로드 실행 및 보기 링크 반환
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        return f"업로드실패: {str(e)}"

# =================================================================
# 3. 세션 상태 및 사용자 계정 초기화
# =================================================================
# 앱이 구동되는 동안 유지될 데이터를 설정합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 각 현장 및 관리자 계정 정보입니다.
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
# 4. 로그인 화면 및 사이드바 내비게이션
# =================================================================

# 로그인하지 않은 경우 화면을 렌더링합니다.
if not st.session_state.login_status:
    # 중앙 정렬을 위해 컬럼을 나눕니다.
    _, center_col, _ = st.columns([1, 1.2, 1])
    
    with center_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 할당받은 아이디와 비밀번호로 접속해 주세요.")
        
        with st.form("main_login_form"):
            user_id_in = st.text_input("아이디(ID)")
            user_pw_in = st.text_input("비밀번호(PW)", type="password")
            
            login_trigger = st.form_submit_button("시스템 접속", use_container_width=True)
            
            if login_trigger:
                # 계정 정보를 검증합니다.
                if user_id_in in st.session_state.user_db:
                    correct_pw = st.session_state.user_db[user_id_in]["pw"]
                    
                    if user_pw_in == correct_pw:
                        # 로그인 성공 시 세션 활성화
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = user_id_in
                        st.session_state.user_role = st.session_state.user_db[user_id_in]["role"]
                        
                        # 권한별 첫 번째 메뉴로 자동 이동합니다.
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("비밀번호가 올바르지 않습니다.")
                else:
                    st.error("등록되지 않은 아이디입니다.")
    st.stop()

# 사이드바 레이아웃 구성
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("🔓 전체 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환 함수 정의
def navigate_page(target_name):
    st.session_state.current_line = target_name
    st.rerun()

# 사용자 권한 메뉴 리스트 추출
allowed_menus = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 생산 공정
menus_p = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_p = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for m in menus_p:
    if m in allowed_menus:
        m_label = f"{icons_p[m]} {m}" + (" 현황" if "라인" in m else "")
        m_style = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(m_label, use_container_width=True, type=m_style):
            navigate_page(m)

# 그룹 2: 사후 관리 및 분석
menus_r = ["불량 공정", "수리 리포트"]
icons_r = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for m in menus_r:
    if m in allowed_menus:
        r_label = f"{icons_r[m]} {m}"
        r_style = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(r_label, use_container_width=True, type=r_style):
            navigate_page(m)

# 그룹 3: 마스터 관리 기능
if "마스터 관리" in allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_page("마스터 관리")

# 하단 공용 알림 (수리 대기 물량 체크)
bad_count_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not bad_count_db.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 공지: 현재 {len(bad_count_db)}건의 불량 수리 대기 제품이 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 로직 및 공용 UI 컴포넌트 (워크플로우 전이 방식)
# =================================================================

def check_and_add_marker(df, line_name):
    """지정된 생산 실적(10대) 달성 시 시각적 구분선을 시트에 추가합니다."""
    today_kst_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 오늘 해당 라인의 순수 생산 실적 개수를 파악합니다.
    current_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(today_kst_str)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대마다 구분선 행을 생성하여 데이터프레임에 병합합니다.
    if current_count > 0 and current_count % 10 == 0:
        marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {current_count}대 실적 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        df_new = pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
        return df_new
    return df

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    """제품의 공정 단계를 이동시키기 위해 기존 행을 업데이트합니다. (단일 행 추적 핵심)"""
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    st.write(f"현재 제품의 위치가 '{st.session_state.current_line}'으로 변경됩니다.")
    
    ok_col, no_col = st.columns(2)
    
    if ok_col.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_main = st.session_state.production_db
        
        # 모델명과 시리얼 번호가 일치하는 단일 행의 인덱스를 조회합니다.
        row_find = db_main[
            (db_main['모델'] == st.session_state.confirm_model) & 
            (db_main['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not row_find.empty:
            idx_target = row_find[0]
            
            # [단일 행 추적 로직] 행을 추가하지 않고 기존 정보만 갱신합니다.
            db_main.at[idx_target, '라인'] = st.session_state.current_line
            db_main.at[idx_target, '상태'] = '진행 중'
            db_main.at[idx_target, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db_main.at[idx_target, '작업자'] = st.session_state.user_id
            
            # 구글 시트에 즉시 반영합니다.
            if save_to_gsheet(db_main):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 실패: 해당 시리얼 번호를 찾을 수 없습니다.")
            
    if no_col.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(line_name):
    """상단 통계 영역 렌더링 (대기 물량 및 금일 실적 집계)"""
    db_ref = st.session_state.production_db
    today_stamp = get_kst_now().strftime('%Y-%m-%d')
    
    # 금일 해당 공정의 투입 및 완료 수량을 집계합니다.
    today_line_data = db_ref[
        (db_ref['라인'] == line_name) & 
        (db_ref['시간'].astype(str).str.contains(today_stamp)) & 
        (db_ref['상태'] != '구분선')
    ]
    
    val_in = len(today_line_data)
    val_out = len(today_line_data[today_line_data['상태'] == '완료'])
    
    # 이전 단계 공정에서의 대기 물량을 산출합니다.
    val_waiting = 0
    prev_step_name = None
    
    if line_name == "검사 라인": prev_step_name = "조립 라인"
    elif line_name == "포장 라인": prev_step_name = "검사 라인"
    
    if prev_step_name:
        # 단일 행 방식이므로 이전 라인 완료 상태인 행의 개수가 대기 물량이 됩니다.
        waiting_df = db_ref[
            (db_ref['라인'] == prev_step_name) & 
            (db_ref['상태'] == '완료')
        ]
        val_waiting = len(waiting_df)
        
    # 통계 레이아웃 렌더링
    s_col1, s_col2, s_col3 = st.columns(3)
    
    with s_col1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {prev_step_name if prev_step_name else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{val_waiting if prev_step_name else '-'}</div>
                <div class='stat-sub'>건 (누적 대기 물량)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with s_col2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{val_in}</div>
                <div class='stat-sub'>건 (금일 투입)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with s_col3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{val_out}</div>
                <div class='stat-sub'>건 (금일 완료)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, confirm_label="완료 처리"):
    """실시간 공정 로그 및 상태 제어 테이블을 표시합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 공정 로그</h3>", unsafe_allow_html=True)
    
    db_all = st.session_state.production_db
    # 해당 라인의 물량만 필터링합니다.
    view_db = db_all[db_all['라인'] == line_name]
    
    # 조립 라인일 경우 선택된 CELL 필터를 적용합니다.
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_db = view_db[view_db['CELL'] == st.session_state.selected_cell]
        
    if view_db.empty:
        st.info(f"현재 {line_name}에 등록된 데이터가 없습니다.")
        return
        
    # 테이블 헤더 구성
    col_h = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_titles = ["최종기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "상태 제어"]
    
    for i, title in enumerate(header_titles):
        col_h[i].write(f"**{title}**")
        
    # 데이터 행 렌더링 (최신순)
    for idx_row, data_row in view_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리
        if data_row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f8f9fa; padding: 7px; text-align: center; border-radius: 8px; font-weight: bold; color: #636e72; border: 1px dashed #ced4da;'>📦 {data_row['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        col_d = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        col_d[0].write(data_row['시간'])
        col_d[1].write(data_row['CELL'])
        col_d[2].write(data_row['모델'])
        col_d[3].write(data_row['품목코드'])
        col_d[4].write(data_row['시리얼'])
        
        with col_d[5]:
            current_status = data_row['상태']
            
            if current_status in ["진행 중", "수리 완료(재투입)"]:
                b_pass, b_bad = st.columns(2)
                
                if b_pass.button(confirm_label, key=f"ok_act_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "완료"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
                if b_bad.button("🚫불량", key=f"ng_act_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "불량 처리 중"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
            elif current_status == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 대기 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 메뉴별 상세 렌더링 로직 (v18.7 수정 사항 반영)
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 현황 (Start Point)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 UI
    cell_options = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_btn_grid = st.columns(len(cell_options))
    
    for i, c_name in enumerate(cell_options):
        if c_btn_grid[i].button(c_name, type="primary" if st.session_state.selected_cell == c_name else "secondary"):
            st.session_state.selected_cell = c_name
            st.rerun()
            
    # 개별 셀이 선택되었을 때만 생산 등록 폼을 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 생산 등록")
            
            # 모델 선택
            sel_model = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("new_assembly_form"):
                row_f1, row_f2 = st.columns(2)
                
                # 모델 기반 품목 리스트 로드
                items_avail = st.session_state.master_items_dict.get(sel_model, ["모델 정보 없음"])
                sel_item = row_f1.selectbox("품목코드 선택", items_avail)
                
                sel_sn = row_f2.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 신규 생산 등록", use_container_width=True, type="primary"):
                    if sel_model != "선택하세요." and sel_sn != "":
                        db_ptr = st.session_state.production_db
                        
                        # [전수 중복 생산 체크] 모델+시리얼 조합 확인
                        dup_find = db_ptr[
                            (db_ptr['모델'] == sel_model) & 
                            (db_ptr['시리얼'] == sel_sn) & 
                            (db_ptr['상태'] != "구분선")
                        ]
                        
                        if not dup_find.empty:
                            st.error(f"❌ 중복 등록 불가: '{sel_sn}' 번호는 이미 시스템에 존재합니다.")
                        else:
                            # 신규 행 생성
                            new_data = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': sel_model, 
                                '품목코드': sel_item, 
                                '시리얼': sel_sn, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 추가 및 구분선 체크
                            df_new_full = pd.concat([db_ptr, pd.DataFrame([new_data])], ignore_index=True)
                            df_new_full = check_and_add_marker(df_new_full, "조립 라인")
                            
                            st.session_state.production_db = df_new_full
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 정확히 입력해주세요.")
                        
    display_process_log_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 (입고 시 상태 전이 로직)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_name = st.session_state.current_line
    icon_name = "🔍" if line_name == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_name} {line_name} 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(line_name)
    st.divider()
    
    # 이전 단계 공정명 정의
    prev_step_name = "조립 라인" if line_name == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_step_name} 물량 입고 처리")
        
        # [수정] 작업자 혼선을 방지하기 위해 '전체보기'를 삭제하고 반드시 모델을 선택하게 합니다.
        model_f_val = st.selectbox("입고 대상 모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"filt_{line_name}")
        
        if model_f_val != "선택하세요.":
            db_all = st.session_state.production_db
            
            # 이전 공정 완료 물량 중 특정 모델 필터링
            ready_pool = db_all[
                (db_all['라인'] == prev_step_name) & 
                (db_all['상태'] == "완료") & 
                (db_all['모델'] == model_f_val)
            ]
            
            if not ready_pool.empty:
                st.success(f"📦 현재 입고 가능한 '{model_f_val}' 물량이 {len(ready_pool)}건 있습니다.")
                
                # [수정] 중복 키 에러 방지를 위해 버튼 키에 모델명 포함
                btn_cols = st.columns(4)
                for i, row in enumerate(ready_pool.itertuples()):
                    sn_val = row.시리얼
                    md_val = row.모델
                    
                    if btn_cols[i % 4].button(f"📥 입고: {sn_val}", key=f"btn_in_{md_val}_{sn_val}_{line_name}"):
                        st.session_state.confirm_target = sn_val
                        st.session_state.confirm_model = md_val
                        confirm_entry_dialog()
            else:
                st.info(f"현재 '{model_f_val}' 모델의 입고 대기 물량이 없습니다.")
        else:
            st.warning("작업을 진행할 모델을 먼저 선택해 주세요.")
            
    display_process_log_table(line_name, "검사 통과" if line_name == "검사 라인" else "출하 준비 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 통합 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 통합 리포트</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    rpt_db = st.session_state.production_db
    
    if not rpt_db.empty:
        # 데이터 정제 (구분선 제거)
        clean_db = rpt_db[rpt_db['상태'] != '구분선']
        
        # 주요 KPI 산출
        done_qty = len(clean_db[(clean_db['라인'] == '포장 라인') & (clean_db['상태'] == '완료')])
        ng_qty = len(clean_db[clean_db['상태'].str.contains("불량", na=False)])
        
        ftt_rate = 0
        if (done_qty + ng_qty) > 0:
            ftt_rate = (done_qty / (done_qty + ng_qty)) * 100
        else:
            ftt_rate = 100
            
        # 메트릭 레이아웃
        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        m_c1.metric("최종 제품 출하", f"{done_qty} EA")
        m_c2.metric("공정 작업 중", len(clean_db[clean_db['상태'] == '진행 중']))
        m_c3.metric("누적 불량 건수", f"{ng_qty} 건", delta=ng_qty, delta_color="inverse")
        m_c4.metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        
        # 시각화 그래프
        c_col1, c_col2 = st.columns([3, 2])
        
        with c_col1:
            line_dist = clean_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_dist, x='라인', y='수량', color='라인', title="공정 단계별 실시간 제품 분포"), use_container_width=True)
            
        with c_col2:
            model_pie = clean_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성"), use_container_width=True)
            
        st.markdown("##### 🔍 상세 생산 및 공정 기록 전체 보기")
        st.dataframe(rpt_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회할 생산 기록 데이터가 없습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (line4 대응 영역)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 관리 센터</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 상태인 행들 필터링
    db_full = st.session_state.production_db
    bad_list = db_full[db_full['상태'] == "불량 처리 중"]
    
    if bad_list.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_list)}건")
        
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **시리얼: {row['시리얼']}** | 모델: {row['모델']} | 발생공정: {row['라인']}")
                
                # 수리 입력 필드
                rep_c1, rep_c2, rep_c3 = st.columns([4, 4, 2])
                
                # 입력값 캐시 로드
                c_s = st.session_state.repair_cache.get(f"s_{idx}", "")
                c_a = st.session_state.repair_cache.get(f"a_{idx}", "")
                
                i_cause = rep_c1.text_input("불량 원인 상세", value=c_s, key=f"is_{idx}")
                i_action = rep_c2.text_input("수리 조치 내용", value=c_a, key=f"ia_{idx}")
                
                # 캐시 즉시 업데이트
                st.session_state.repair_cache[f"s_{idx}"] = i_cause
                st.session_state.repair_cache[f"a_{idx}"] = i_action
                
                up_photo = st.file_uploader("수리 증빙 사진(JPG/PNG)", type=['jpg','png','jpeg'], key=f"ph_{idx}")
                
                if up_photo:
                    st.image(up_photo, width=300, caption="업로드 예정 사진")
                    
                if rep_c3.button("🔧 수리 완료 등록", key=f"btn_f_{idx}", type="primary", use_container_width=True):
                    if i_cause and i_action:
                        web_link = ""
                        
                        if up_photo is not None:
                            with st.spinner("증빙 사진을 드라이브에 저장 중..."):
                                ts_m = get_kst_now().strftime('%Y%m%d_%H%M')
                                f_nm = f"{row['시리얼']}_FIX_{ts_m}.jpg"
                                res_url = upload_image_to_drive(up_photo, f_nm)
                                
                                if "http" in res_url:
                                    web_link = f" [사진링크: {res_url}]"
                        
                        # 상태 업데이트 로직
                        db_full.at[idx, '상태'] = "수리 완료(재투입)"
                        db_full.at[idx, '증상'] = i_cause
                        db_full.at[idx, '수리'] = i_action + web_link
                        db_full.at[idx, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(db_full):
                            # 성공 시 캐시 제거
                            st.session_state.repair_cache.pop(f"s_{idx}", None)
                            st.session_state.repair_cache.pop(f"a_{idx}", None)
                            st.success("수리 보고 완료!")
                            st.rerun()
                    else:
                        st.error("원인과 조치 사항을 모두 입력해 주세요.")

# -----------------------------------------------------------------
# 6-5. 수리 리포트 분석
# -----------------------------------------------------------------
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 분석 리포트</h2>", unsafe_allow_html=True)
    
    source_df = st.session_state.production_db
    # 수리 완료 기록 필터링
    repair_df = source_df[
        (source_df['상태'].str.contains("재투입", na=False)) | 
        (source_df['수리'] != "")
    ]
    
    if not repair_df.empty:
        r_col1, r_col2 = st.columns(2)
        
        with r_col1:
            line_bad = repair_df.groupby('라인').size().reset_index(name='건수')
            st.plotly_chart(px.bar(line_bad, x='라인', y='건수', title="공정별 불량 빈도"), use_container_width=True)
            
        with r_col2:
            model_bad = repair_df.groupby('모델').size().reset_index(name='건수')
            st.plotly_chart(px.pie(model_bad, values='건수', names='모델', hole=0.3, title="불량 모델 구성 비율"), use_container_width=True)
            
        st.markdown("##### 📋 상세 수리 조치 이력 통합 데이터")
        st.dataframe(repair_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("분석할 수리 데이터가 아직 없습니다.")

# -----------------------------------------------------------------
# 6-6. 마스터 관리 (초기화 문제 완벽 해결)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리 및 데이터 설정</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_security_form"):
            st.write("관리자 권한 인증이 필요합니다.")
            input_apw = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            
            if st.form_submit_button("인증하기"):
                if input_apw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("비밀번호 불일치")
    else:
        if st.sidebar.button("🔓 관리자 메뉴 잠금"):
            st.session_state.admin_authenticated = False
            navigate_page("생산 리포트")

        st.markdown("### 📋 1. 마스터 기준 데이터 관리")
        a_row1_c1, a_row1_c2 = st.columns(2)
        
        with a_row1_c1:
            with st.container(border=True):
                st.write("**모델 등록**")
                n_m = st.text_input("신규 모델명")
                if st.button("➕ 모델 추가", use_container_width=True):
                    if n_m and n_m not in st.session_state.master_models:
                        st.session_state.master_models.append(n_m)
                        st.session_state.master_items_dict[n_m] = []
                        st.rerun()

        with a_row1_c2:
            with st.container(border=True):
                st.write("**품목코드 등록**")
                sel_m_a = st.selectbox("대상 모델", st.session_state.master_models)
                n_i = st.text_input("신규 품목코드")
                if st.button("➕ 품목코드 추가", use_container_width=True):
                    if n_i and n_i not in st.session_state.master_items_dict[sel_m_a]:
                        st.session_state.master_items_dict[sel_m_a].append(n_i)
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 물리적 초기화")
        a_row2_c1, a_row2_c2 = st.columns(2)
        
        with a_row2_c1:
            st.write("현재 데이터를 CSV로 백업합니다.")
            csv_blob = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 전체 실적 다운로드", csv_blob, f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
            
        with a_row2_c2:
            st.write("데이터 물리적 초기화 (구글 시트 삭제 포함)")
            # [수정] 초기화 시 빈 데이터프레임을 생성하여 시트를 확실하게 비웁니다.
            if st.button("🚫 시스템 전체 데이터 초기화", type="secondary", use_container_width=True):
                 st.error("경고: 초기화 실행 시 구글 시트의 모든 실적 데이터가 삭제됩니다.")
                 if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                     empty_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                     st.session_state.production_db = empty_df
                     
                     # 초기화 모드로 저장 실행
                     if save_to_gsheet(empty_df, is_reset_mode=True):
                         st.success("시스템 및 구글 시트 초기화 완료!")
                         st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 계정 제어")
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        u_id = u_c1.text_input("계정 ID")
        u_pw = u_c2.text_input("계정 PW", type="password")
        u_rl = u_c3.selectbox("부여 권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성/업데이트", use_container_width=True):
            if u_id and u_pw:
                st.session_state.user_db[u_id] = {"pw": u_pw, "role": u_rl}
                st.success(f"[{u_id}] 계정 등록 완료")
                st.rerun()
