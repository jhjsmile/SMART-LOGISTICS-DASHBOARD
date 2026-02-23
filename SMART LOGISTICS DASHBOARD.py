import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리 (사진 저장 및 관리용)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 UI 스타일 정의 (상세 전개 스타일)
# =================================================================
# 애플리케이션의 기본 페이지 설정을 수행합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.8", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 메뉴 권한 설정
# 각 현장 작업자와 관리자의 권한을 엄격히 분리합니다.
# line4 계정은 'repair_team' 권한을 사용하여 불량 공정만 전담합니다.
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

# 현장 시인성을 높이기 위한 상세 CSS 정의
st.markdown("""
    <style>
    /* 메인 컨테이너 최대 너비 및 중앙 정렬 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 크기, 패딩, 글꼴 두께 설정 */
    .stButton button { 
        margin-top: 5px; 
        padding: 10px 12px; 
        width: 100%; 
        font-weight: 800;
        border-radius: 8px;
    }
    
    /* 중앙 정렬 대형 제목 스타일 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 30px 0; 
        color: #1e272e;
    }
    
    /* 긴급 불량 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #eb4d4b; 
        padding: 22px; 
        border-radius: 12px; 
        border: 2px solid #ff7675; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        font-size: 1.15em;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* 상단 통계 지표 박스 스타일 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 15px; 
        padding: 25px; 
        text-align: center;
        border: 1px solid #dfe6e9; 
        margin-bottom: 20px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    }
    
    .stat-label { 
        font-size: 1em; 
        color: #636e72; 
        font-weight: 700; 
        margin-bottom: 8px;
    }
    
    .stat-value { 
        font-size: 2.3em; 
        color: #0984e3; 
        font-weight: 900; 
    }
    
    .stat-sub { 
        font-size: 0.9em; 
        color: #b2bec3; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 데이터 연동 함수 (초기화 문제 해결 핵심)
# =================================================================
# 구글 시트 연결 객체를 선언합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """서버 시간이 아닌 한국 표준시(KST)를 생성합니다."""
    return datetime.now() + timedelta(hours=9)

def load_data():
    """시트로부터 실시간 데이터를 로드하며 시리얼 형식을 보정합니다."""
    try:
        # 캐시 없이 실시간 데이터를 읽어옵니다.
        df_raw = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 지수 형태나 소수점으로 표시되는 것을 방지합니다.
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [데이터 보호 로직]
        # 로드 실패로 데이터가 비어있어도 세션에 데이터가 있다면 기존 데이터를 반환하여
        # 의도치 않은 삭제를 방지합니다.
        if df_raw.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
                
        return df_raw
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_mode=False):
    """
    변경된 데이터를 구글 시트에 업데이트합니다.
    [핵심 수정] is_reset_mode=True일 경우, 빈 데이터프레임을 강제로 덮어씌워 시트를 비웁니다.
    """
    # 1. 초기화가 아닌 일반 저장 중 빈 데이터가 감지되면 저장을 거부합니다.
    if df.empty and not is_reset_mode:
        st.error("❌ 저장 오류: 데이터가 비어있어 저장이 차단되었습니다. (새로고침 하세요)")
        return False
    
    # 2. 구글 시트 API의 네트워크 불안정을 대비하여 3회 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # [초기화 해결책] 구글 시트의 내용을 완전히 지우기 위해 Overwrite 방식을 사용합니다.
            conn.update(data=df)
            
            # 캐시를 즉시 삭제하여 데이터가 즉각 반영되도록 유도합니다.
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2) # 2초 대기 후 재시도
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (최종): {api_err}")
                return False

def upload_image_to_drive(file_data, file_name):
    """불량 수리 사진을 구글 드라이브에 저장합니다."""
    try:
        # 인증 정보 구성
        raw_info = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_info)
        
        # 드라이브 API 서비스 생성
        service = build('drive', 'v3', credentials=credentials)
        
        # 업로드 대상 폴더 조회
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "오류: 폴더ID 미지정"

        file_metadata = {
            'name': file_name, 
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_data, mimetype=file_data.type)
        
        # 업로드 실행 및 링크 획득
        file_obj = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file_obj.get('webViewLink')
    except Exception as upload_err:
        return f"업로드실패: {str(upload_err)}"

# =================================================================
# 3. 세션 상태(Session State) 초기화 관리
# =================================================================
# 시스템 부팅 시 필요한 초기 변수들을 설정합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 계정 마스터 정보 (아이디/비번/권한)
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
# 4. 로그인 화면 및 메뉴 내비게이션 (상세 전개)
# =================================================================

# 미로그인 상태일 때의 화면 구성
if not st.session_state.login_status:
    # 화면을 3분할하여 중앙에 로그인 폼 배치
    _, l_col, _ = st.columns([1, 1.2, 1])
    
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 현장 담당 계정 또는 관리자 계정으로 로그인해 주세요.")
        
        with st.form("main_login_form"):
            user_id_in = st.text_input("아이디(ID)")
            user_pw_in = st.text_input("비밀번호(PW)", type="password")
            
            btn_login = st.form_submit_button("시스템 로그인", use_container_width=True)
            
            if btn_login:
                # 계정 정보가 유효한지 검증합니다.
                if user_id_in in st.session_state.user_db:
                    correct_pw = st.session_state.user_db[user_id_in]["pw"]
                    
                    if user_pw_in == correct_pw:
                        # 로그인 성공 및 데이터 로드
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = user_id_in
                        st.session_state.user_role = st.session_state.user_db[user_id_in]["role"]
                        
                        # 권한에 따른 초기 진입 메뉴 설정
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("입력한 비밀번호가 올바르지 않습니다.")
                else:
                    st.error("등록된 아이디 정보가 없습니다.")
    st.stop()

# 사이드바 레이아웃
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("🔓 시스템 로그아웃", type="secondary"): 
    st.session_status = False
    st.rerun()
st.sidebar.divider()

# 페이지 전환 전용 함수
def navigate_to(page_name):
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한 메뉴 리스트 추출
allowed_list = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 생산 공정 현황
menus_1 = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_1 = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for m in menus_1:
    if m in allowed_list:
        m_label = f"{icons_1[m]} {m}" + (" 현황" if "라인" in m else "")
        m_style = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(m_label, use_container_width=True, type=m_style):
            navigate_to(m)

# 그룹 2: 사후 관리 및 분석
menus_2 = ["불량 공정", "수리 리포트"]
icons_2 = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for m in menus_2:
    if m in allowed_list:
        m_label_2 = f"{icons_2[m]} {m}"
        m_style_2 = "primary" if st.session_state.current_line == m else "secondary"
        
        if st.sidebar.button(m_label_2, use_container_width=True, type=m_style_2):
            navigate_to(m)

# 그룹 3: 마스터 관리
if "마스터 관리" in allowed_list:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_to("마스터 관리")

# 시스템 공용 불량 발생 알림
bad_found = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not bad_found.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 공정 내 수리가 필요한 제품이 {len(bad_found)}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 및 공용 UI (워크플로우 방식)
# =================================================================

def check_and_add_marker(df, line_name):
    """지정된 생산 실적(10대) 달성 시 구분선 행을 시트에 추가합니다."""
    today_kst = get_kst_now().strftime('%Y-%m-%d')
    
    # 오늘 해당 라인의 순수 생산 실적 개수를 파악합니다.
    line_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(today_kst)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대마다 구분선 행을 생성하여 병합합니다.
    if line_count > 0 and line_count % 10 == 0:
        marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {line_count}대 생산 실적 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        return pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
    return df

@st.dialog("📦 공정 단계 전환 승인")
def confirm_entry_dialog():
    """제품을 다음 공정으로 이동시키기 위해 기존 행을 업데이트합니다. (단일 행 추적 핵심)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    st.write(f"승인 시 해당 제품의 위치가 '{st.session_state.current_line}'으로 변경됩니다.")
    
    c_ok, c_no = st.columns(2)
    
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
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
            
    if c_no.button("❌ 취소", use_container_width=True):
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
    st_col1, st_col2, st_col3 = st.columns(3)
    
    with st_col1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {prev_step_name if prev_step_name else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{val_waiting if prev_step_name else '-'}</div>
                <div class='stat-sub'>건 (누적 대기 수량)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{val_in}</div>
                <div class='stat-sub'>건 (금일 투입)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with st_col3:
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
    head_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_titles = ["기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "공정 상태 제어"]
    
    for i, title in enumerate(header_titles):
        head_cols[i].write(f"**{title}**")
        
    # 데이터 행 렌더링 (최신순)
    for idx_row, data_row in view_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리
        if data_row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f8f9fa; padding: 7px; text-align: center; border-radius: 8px; font-weight: bold; color: #636e72; border: 1px dashed #ced4da;'>📦 {data_row['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        row_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        row_cols[0].write(data_row['시간'])
        row_cols[1].write(data_row['CELL'])
        row_cols[2].write(data_row['모델'])
        row_cols[3].write(data_row['품목코드'])
        row_cols[4].write(data_row['시리얼'])
        
        with row_cols[5]:
            status_now = data_row['상태']
            
            if status_now in ["진행 중", "수리 완료(재투입)"]:
                b_pass, b_bad = st.columns(2)
                
                # 중복 키 에러 방지를 위한 인덱스 기반 키 할당
                if b_pass.button(confirm_label, key=f"ok_btn_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "완료"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
                if b_bad.button("🚫불량", key=f"ng_btn_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "불량 처리 중"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
            elif status_now == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 수리 센터 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 작업 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 메뉴별 상세 렌더링 로직 (v18.8 수정 사항 반영)
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 페이지 (Workflow 시작점)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 UI 구성
    cell_options = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_grid = st.columns(len(cell_options))
    
    for i, c_name in enumerate(cell_options):
        # 현재 선택된 CELL은 파란색으로 표시합니다.
        if btn_grid[i].button(c_name, type="primary" if st.session_state.selected_cell == c_name else "secondary"):
            st.session_state.selected_cell = c_name
            st.rerun()
            
    # 개별 셀이 선택되었을 때만 생산 등록 폼을 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 생산 등록")
            
            # 모델 선택박스
            input_model = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("new_assembly_form"):
                row_f1, row_f2 = st.columns(2)
                
                # 모델 기반 품목 리스트 자동 연동
                items_avail = st.session_state.master_items_dict.get(input_model, ["모델 정보 없음"])
                input_item = row_f1.selectbox("품목코드 선택", items_avail)
                
                input_sn = row_f2.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 신규 생산 등록", use_container_width=True, type="primary"):
                    if input_model != "선택하세요." and input_sn != "":
                        db_ptr = st.session_state.production_db
                        
                        # [전수 중복 생산 체크] 모델+시리얼 조합 확인
                        dup_find = db_ptr[
                            (db_ptr['모델'] == input_model) & 
                            (db_ptr['시리얼'] == input_sn) & 
                            (db_ptr['상태'] != "구분선")
                        ]
                        
                        if not dup_find.empty:
                            st.error(f"❌ 중복 등록 불가: '{input_sn}' 번호는 이미 시스템에 존재합니다.")
                        else:
                            # 신규 행 데이터 객체 생성
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
                            
                            # 데이터 추가 및 구분선 자동 체크
                            df_updated = pd.concat([db_ptr, pd.DataFrame([new_data_row])], ignore_index=True)
                            df_updated = check_and_add_marker(df_updated, "조립 라인")
                            
                            st.session_state.production_db = df_updated
                            
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
        st.subheader(f"📥 {prev_step_name} 물량 입고 승인")
        
        # [수정 사항] 작업자 혼선을 방지하기 위해 '전체보기'를 삭제하고 모델을 반드시 선택하게 합니다.
        model_f_val = st.selectbox("입고 대상 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"filt_{line_name}")
        
        if model_f_val != "선택하세요.":
            db_all = st.session_state.production_db
            
            # 이전 공정에서 '완료' 상태로 대기 중인 특정 모델 물량 조회
            ready_pool = db_all[
                (db_all['라인'] == prev_step_name) & 
                (db_all['상태'] == "완료") & 
                (db_all['모델'] == model_f_val)
            ]
            
            if not ready_pool.empty:
                st.success(f"📦 현재 입고 가능한 [ {model_f_val} ] 물량이 {len(ready_pool)}건 있습니다.")
                
                # 버튼 그리드 구성 (DuplicateKey 에러 방지 위해 모델명 포함 키 생성)
                btn_cols = st.columns(4)
                for i, row in enumerate(ready_pool.itertuples()):
                    sn_val = row.시리얼
                    md_val = row.모델
                    
                    # 키 값에 모델명과 시리얼을 조합하여 고유성을 확보합니다.
                    if btn_cols[i % 4].button(f"📥 입고: {sn_val}", key=f"in_{md_val}_{sn_val}_{line_name}"):
                        st.session_state.confirm_target = sn_val
                        st.session_state.confirm_model = md_val
                        confirm_entry_dialog()
            else:
                st.info(f"현재 [ {model_f_val} ] 모델의 입고 대기 물량이 없습니다.")
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
        
        # 주요 KPI 지표 산출
        # 최종 포장 라인까지 완료된 수량이 실제 생산량입니다.
        done_qty = len(clean_db[(clean_db['라인'] == '포장 라인') & (clean_db['상태'] == '완료')])
        ng_qty = len(clean_db[clean_db['상태'].str.contains("불량", na=False)])
        
        ftt_rate = 0
        if (done_qty + ng_qty) > 0:
            ftt_rate = (done_qty / (done_qty + ng_qty)) * 100
        else:
            ftt_rate = 100
            
        # 대시보드 메트릭 표시
        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        m_c1.metric("최종 제품 출하", f"{done_qty} EA")
        m_c2.metric("공정 작업 중", len(clean_db[clean_db['상태'] == '진행 중']))
        m_c3.metric("누적 불량 건수", f"{ng_qty} 건", delta=ng_qty, delta_color="inverse")
        m_c4.metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        
        # 시각화 차트 레이아웃
        vis_col1, vis_col2 = st.columns([3, 2])
        
        with vis_col1:
            line_dist = clean_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_dist, x='라인', y='수량', color='라인', title="공정 단계별 실시간 제품 분포"), use_container_width=True)
            
        with vis_col2:
            model_pie = clean_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성"), use_container_width=True)
            
        st.markdown("##### 🔍 상세 공정 생산 기록 전체 보기")
        st.dataframe(rpt_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("조회할 생산 실적 데이터가 없습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (Repair Center)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중인 행들 필터링
    bad_items = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_items.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 수리 조치가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_items)}건")
        
        for idx, row in bad_items.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **시리얼: {row['시리얼']}** | 모델: {row['모델']} | 발생공정: {row['라인']}")
                
                # 수리 원인 및 조치 입력부
                rep_c1, rep_c2, rep_c3 = st.columns([4, 4, 2])
                
                # 세션 캐시값 로드
                cache_s = st.session_state.repair_cache.get(f"s_{idx}", "")
                cache_a = st.session_state.repair_cache.get(f"a_{idx}", "")
                
                i_cause = rep_c1.text_input("불량 원인 상세", value=cache_s, key=f"is_{idx}")
                i_action = rep_c2.text_input("수리 조치 내용", value=cache_a, key=f"ia_{idx}")
                
                # 실시간 캐시 업데이트
                st.session_state.repair_cache[f"s_{idx}"] = i_cause
                st.session_state.repair_cache[f"a_{idx}"] = i_action
                
                # 사진 첨부 업로더
                up_photo = st.file_uploader("수리 증빙 사진(JPG/PNG)", type=['jpg','png','jpeg'], key=f"ph_{idx}")
                
                if up_photo:
                    st.image(up_photo, width=300, caption="업로드 예정 사진")
                    
                if rep_c3.button("🔧 수리 완료 보고", key=f"rep_btn_{idx}", type="primary", use_container_width=True):
                    if i_cause and i_action:
                        web_link = ""
                        
                        if up_photo is not None:
                            with st.spinner("증빙 사진을 드라이브에 안전하게 저장 중..."):
                                ts_m = get_kst_now().strftime('%Y%m%d_%H%M')
                                f_nm = f"{row['시리얼']}_FIX_{ts_m}.jpg"
                                res_url = upload_image_to_drive(up_photo, f_nm)
                                
                                if "http" in res_url:
                                    web_link = f" [사진보기: {res_url}]"
                        
                        # 데이터베이스 상태 업데이트
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = i_cause
                        st.session_state.production_db.at[idx, '수리'] = i_action + web_link
                        st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 제거 및 페이지 리프레시
                            st.session_state.repair_cache.pop(f"s_{idx}", None)
                            st.session_state.repair_cache.pop(f"a_{idx}", None)
                            st.success("수리 보고서가 정상 등록되었습니다.")
                            st.rerun()
                    else:
                        st.error("불량 원인과 조치 사항을 모두 입력해야 완료할 수 있습니다.")

# -----------------------------------------------------------------
# 6-5. 마스터 관리 (초기화 문제 완벽 해결 영역)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리 및 데이터 설정</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_security_form"):
            st.write("안전한 설정을 위해 관리자 권한 인증이 필요합니다.")
            input_pw = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            
            if st.form_submit_button("인증하기"):
                if input_pw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
    else:
        if st.sidebar.button("🔓 관리자 세션 종료"):
            st.session_state.admin_authenticated = False
            navigate_to("생산 리포트")

        st.markdown("### 📋 1. 마스터 기준 데이터 관리")
        row1_c1, row1_c2 = st.columns(2)
        
        with row1_c1:
            with st.container(border=True):
                st.write("**제품 모델 등록**")
                n_m = st.text_input("새 모델 명칭")
                if st.button("➕ 모델 추가", use_container_width=True):
                    if n_m and n_m not in st.session_state.master_models:
                        st.session_state.master_models.append(n_m)
                        st.session_state.master_items_dict[n_m] = []
                        st.rerun()

        with row1_c2:
            with st.container(border=True):
                st.write("**품목코드 마스터 설정**")
                target_m = st.selectbox("품목 추가 모델 선택", st.session_state.master_models)
                n_i = st.text_input("새 품목코드")
                if st.button("➕ 품목코드 추가", use_container_width=True):
                    if n_i and n_i not in st.session_state.master_items_dict[target_m]:
                        st.session_state.master_items_dict[target_m].append(n_i)
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 물리적 초기화")
        row2_c1, row2_c2 = st.columns(2)
        
        with row2_c1:
            st.write("현재 시트 데이터를 CSV로 백업합니다.")
            csv_blob = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 전체 실적 CSV 다운로드", csv_blob, f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
            
        with row2_c2:
            st.write("시스템 데이터 물리적 초기화")
            # [수정] 초기화 시 빈 데이터프레임 구조를 생성하여 Overwrite 방식으로 업데이트합니다.
            if st.button("🚫 전체 실적 데이터 초기화", type="secondary", use_container_width=True):
                 st.error("경고: 실행 시 구글 시트의 모든 실적 데이터가 영구 삭제됩니다.")
                 if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                     # 컬럼 구조만 남긴 빈 데이터프레임 생성
                     empty_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                     st.session_state.production_db = empty_df
                     
                     # 초기화 모드로 저장 실행 (구글 시트 덮어쓰기 강제 수행)
                     if save_to_gsheet(empty_df, is_reset_mode=True):
                         st.success("시스템 및 구글 시트 데이터가 완전히 초기화되었습니다.")
                         st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 계정 권한 관리")
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        target_uid = u_c1.text_input("새 계정 ID")
        target_upw = u_c2.text_input("새 계정 PW", type="password")
        target_role = u_c3.selectbox("권한 등급", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성 및 업데이트", use_container_width=True):
            if target_uid and target_upw:
                st.session_state.user_db[target_uid] = {"pw": target_upw, "role": target_role}
                st.success(f"[{target_uid}] 계정 권한 정보가 업데이트되었습니다.")
                st.rerun()
