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
# 1. 시스템 설정 및 스타일 정의 (상세 전개 스타일)
# =================================================================
# 앱의 기본 설정을 수행합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.5", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 계정별 메뉴 권한
# line4는 오직 불량 공정 수리 업무만 수행합니다.
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

# UI 가독성을 위한 CSS 정의 (상세 스타일링)
st.markdown("""
    <style>
    /* 메인 앱의 레이아웃 너비 조절 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼의 높이와 시인성 개선 */
    .stButton button { 
        margin-top: 5px; 
        padding: 8px 10px; 
        width: 100%; 
        font-weight: bold;
    }
    
    /* 섹션 제목 중앙 정렬 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 30px 0; 
        color: #2c3e50;
    }
    
    /* 상단 실시간 경고 배너 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #e03131; 
        padding: 18px; 
        border-radius: 10px; 
        border: 2px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        font-size: 1.1em;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* 통계 카드 디자인 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 12px; 
        padding: 22px; 
        text-align: center;
        border: 1px solid #e9ecef; 
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    .stat-label { 
        font-size: 0.95em; 
        color: #868e96; 
        font-weight: 600; 
        margin-bottom: 5px;
    }
    
    .stat-value { 
        font-size: 2.1em; 
        color: #1c7ed6; 
        font-weight: 800; 
    }
    
    .stat-sub { 
        font-size: 0.85em; 
        color: #adb5bd; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 및 데이터 연동 핵심 함수
# =================================================================
# 연결 객체를 선언합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시를 반환합니다."""
    kst_now = datetime.now() + timedelta(hours=9)
    return kst_now

def load_data():
    """데이터를 로드하고 세션 데이터 유실을 방지합니다."""
    try:
        # TTL을 0으로 설정하여 캐시 없이 실시간 데이터를 읽습니다.
        df_sheet = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호 컬럼 데이터 타입 보정
        if '시리얼' in df_sheet.columns:
            df_sheet['시리얼'] = df_sheet['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어] 로드 시 에러로 데이터가 비어있을 경우 세션 내의 데이터를 유지합니다.
        if df_sheet.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
                
        return df_sheet
    except Exception as e:
        st.error(f"데이터 연동 중 오류 발생: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_mode=False):
    """
    데이터를 구글 시트에 업데이트합니다.
    [핵심 수정] 초기화 모드(is_reset_mode)일 때는 빈 데이터 업데이트를 강제 허용합니다.
    """
    # 일반 저장 중 데이터 증발 방지
    if df.empty and not is_reset_mode:
        st.error("❌ 저장 오류: 데이터가 비어있습니다. 새로고침을 시도하세요.")
        return False
    
    # [초기화 핵심] 구글 시트에서 빈 데이터프레임 업데이트를 거부하는 경우를 대비해
    # 초기화 시에는 컬럼명만 있고 행은 없는 데이터프레임을 명시적으로 전달합니다.
    if is_reset_mode:
        target_data = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
    else:
        target_data = df

    # API 지연 대응 재시도 (최대 3회)
    for attempt in range(1, 4):
        try:
            conn.update(data=target_data)
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2)
                continue
            else:
                st.error(f"⚠️ 구글 서버 동기화 실패: {api_err}")
                return False

def upload_image_to_drive(file_obj, filename):
    """불량 수리 사진을 드라이브에 저장합니다."""
    try:
        raw_info = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_info)
        
        drive_service = build('drive', 'v3', credentials=credentials)
        folder_target = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_target:
            return "오류: 드라이브 폴더 설정 안됨"

        metadata = {
            'name': filename, 
            'parents': [folder_target]
        }
        
        media_file = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        uploaded_res = drive_service.files().create(
            body=metadata, 
            media_body=media_file, 
            fields='id, webViewLink'
        ).execute()
        
        return uploaded_res.get('webViewLink')
    except Exception as e:
        return f"업로드실패: {str(e)}"

# =================================================================
# 3. 세션 상태 및 초기 변수 설정
# =================================================================
# 애플리케이션 수명 주기 동안 유지될 데이터를 초기화합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 계정별 PW 및 역할 매핑
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
# 4. 로그인 및 사이드바 구성 (상세 전개 스타일)
# =================================================================

# 로그인하지 않은 경우 화면을 표시합니다.
if not st.session_state.login_status:
    # 가운데 정렬
    _, login_col, _ = st.columns([1, 1.2, 1])
    
    with login_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 지정된 담당자 계정으로 로그인해 주세요.")
        
        with st.form("main_login"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            
            submit_btn = st.form_submit_button("시스템 로그인", use_container_width=True)
            
            if submit_btn:
                # 계정 정보 대조
                if input_id in st.session_state.user_db:
                    correct_pw = st.session_state.user_db[input_id]["pw"]
                    
                    if input_pw == correct_pw:
                        # 로그인 성공 처리
                        st.cache_data.clear()
                        st.session_state.production_db = load_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = input_id
                        st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                        
                        # 권한별 첫 메뉴로 자동 전환
                        st.session_state.current_line = ROLES[st.session_state.user_role][0]
                        st.rerun()
                    else:
                        st.error("비밀번호를 다시 확인해 주십시오.")
                else:
                    st.error("존재하지 않는 아이디입니다.")
    st.stop()

# 사이드바 레이아웃 (사용자 표시 및 메뉴)
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님")
if st.sidebar.button("🔓 전체 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

# 메뉴 전환 함수
def navigate_to(target_name):
    st.session_state.current_line = target_name
    st.rerun()

# 사용자 권한 메뉴 추출
my_menus = ROLES.get(st.session_state.user_role, [])

# 메뉴 그룹 1: 생산 공정
p_group = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
p_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for m_name in p_group:
    if m_name in my_menus:
        m_label = f"{p_icons[m_name]} {m_name}" + (" 현황" if "라인" in m_name else "")
        m_style = "primary" if st.session_state.current_line == m_name else "secondary"
        
        if st.sidebar.button(m_label, use_container_width=True, type=m_style):
            navigate_to(m_name)

# 메뉴 그룹 2: 불량/수리 센터
r_group = ["불량 공정", "수리 리포트"]
r_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}

st.sidebar.divider()

for m_name in r_group:
    if m_name in my_menus:
        r_label = f"{r_icons[m_name]} {m_name}"
        r_style = "primary" if st.session_state.current_line == m_name else "secondary"
        
        if st.sidebar.button(r_label, use_container_width=True, type=r_style):
            navigate_to(m_name)

# 그룹 3: 마스터 관리
if "마스터 관리" in my_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        navigate_to("마스터 관리")

# 하단 긴급 알림 배너
bad_items_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not bad_items_db.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 {len(bad_items_db)}건의 불량 수리 대기 건이 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 및 공용 UI 컴포넌트
# =================================================================

def check_and_add_marker(df, line_name):
    """실적 10대 달성 시 구분선 행을 시트에 추가합니다."""
    today_kst = get_kst_now().strftime('%Y-%m-%d')
    
    # 해당 라인의 오늘 생산량 파악
    line_total = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(today_kst)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대마다 달성 마커 삽입
    if line_total > 0 and line_total % 10 == 0:
        marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {line_total}대 생산 완료", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        df_updated = pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
        return df_updated
    return df

@st.dialog("📦 공정 입고 최종 확인")
def confirm_entry_dialog():
    """다음 단계로 공정 위치를 업데이트합니다. (단일 행 추적 핵심)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ]을(를) '{st.session_state.current_line}'에 입고 승인하시겠습니까?")
    
    c_ok, c_no = st.columns(2)
    
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_main = st.session_state.production_db
        
        # 모델과 시리얼 번호가 일치하는 단일 행 인덱스 조회
        idx_find = db_main[
            (db_main['모델'] == st.session_state.confirm_model) & 
            (db_main['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not idx_find.empty:
            target_idx = idx_find[0]
            
            # [Workflow 업데이트] 기존 행의 공정 위치와 상태 정보만 갱신
            db_main.at[target_idx, '라인'] = st.session_state.current_line
            db_main.at[target_idx, '상태'] = '진행 중'
            db_main.at[target_idx, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db_main.at[target_idx, '작업자'] = st.session_state.user_id
            
            if save_to_gsheet(db_main):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 오류: 해당 시리얼 번호를 시트에서 찾을 수 없습니다.")
            
    if c_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(line_name):
    """상단 대시보드 통계 카드 렌더링"""
    full_db = st.session_state.production_db
    kst_today_str = get_kst_now().strftime('%Y-%m-%d')
    
    # 금일 해당 라인의 투입/완료 데이터 집계
    today_line_db = full_db[
        (full_db['라인'] == line_name) & 
        (full_db['시간'].astype(str).str.contains(kst_today_str)) & 
        (full_db['상태'] != '구분선')
    ]
    
    val_input = len(today_line_db)
    val_done = len(today_line_db[today_line_db['상태'] == '완료'])
    
    # 이전 단계로부터의 대기 물량 산출
    val_wait = 0
    prev_step_nm = None
    
    if line_name == "검사 라인": prev_step_nm = "조립 라인"
    elif line_name == "포장 라인": prev_step_nm = "검사 라인"
    
    if prev_step_nm:
        # 이전 공정에서 '완료'되어 입고를 대기 중인 제품 개수 (단일 행 방식)
        wait_db = full_db[
            (full_db['라인'] == prev_step_nm) & 
            (full_db['상태'] == '완료')
        ]
        val_wait = len(wait_db)
        
    # 통계 레이아웃 렌더링
    s_col1, s_col2, s_col3 = st.columns(3)
    
    with s_col1:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>⏳ {prev_step_nm if prev_step_nm else '입고'} 대기</div>
                <div class='stat-value' style='color: #fd7e14;'>{val_wait if prev_step_nm else '-'}</div>
                <div class='stat-sub'>건 (누적 대기 수량)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with s_col2:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>📥 {line_name} 작업 중</div>
                <div class='stat-value'>{val_input}</div>
                <div class='stat-sub'>건 (금일 투입)</div>
            </div>
            """, unsafe_allow_html=True)
            
    with s_col3:
        st.markdown(f"""
            <div class='stat-box'>
                <div class='stat-label'>✅ {line_name} 작업 완료</div>
                <div class='stat-value' style='color: #198754;'>{val_done}</div>
                <div class='stat-sub'>건 (금일 완료)</div>
            </div>
            """, unsafe_allow_html=True)

def display_process_log_table(line_name, btn_label="완료 처리"):
    """실시간 공정 로그 및 상태 제어 테이블"""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    
    db_all = st.session_state.production_db
    # 해당 라인 제품만 필터링
    view_db = db_all[db_all['라인'] == line_name]
    
    # 조립 라인일 경우 CELL 필터 적용
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_db = view_db[view_db['CELL'] == st.session_state.selected_cell]
        
    if view_db.empty:
        st.info(f"현재 {line_name}에 등록된 데이터가 없습니다.")
        return
        
    # 테이블 헤더
    header_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_list = ["작업시간", "CELL", "제품모델", "품목코드", "시리얼번호", "공정 상태 제어"]
    for i, title in enumerate(header_list):
        header_cols[i].write(f"**{title}**")
        
    # 데이터 행 렌더링
    for idx_r, row_r in view_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리
        if row_r['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f8f9fa; padding: 7px; text-align: center; border-radius: 8px; font-weight: bold; color: #6c757d; border: 1px dashed #dee2e6;'>📦 {row_r['시리얼']} ----------------------------------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        row_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        row_cols[0].write(row_r['시간'])
        row_cols[1].write(row_r['CELL'])
        row_cols[2].write(row_r['모델'])
        row_cols[3].write(row_r['품목코드'])
        row_cols[4].write(row_r['시리얼'])
        
        with row_cols[5]:
            status_now = row_r['상태']
            
            if status_now in ["진행 중", "수리 완료(재투입)"]:
                b_pass, b_ng = st.columns(2)
                
                if b_pass.button(btn_label, key=f"btn_p_{idx_r}"):
                    db_all.at[idx_r, '상태'] = "완료"
                    db_all.at[idx_r, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
                if b_ng.button("🚫불량", key=f"btn_n_{idx_r}"):
                    db_all.at[idx_r, '상태'] = "불량 처리 중"
                    db_all.at[idx_r, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_all):
                        st.rerun()
                        
            elif status_now == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:bold;'>🛠️ 불량 수리 센터 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:bold;'>✅ 작업 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 메뉴별 상세 기능 로직
# =================================================================

# -----------------------------------------------------------------
# 6-1. 조립 라인 페이지 (Start Point)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인")
    st.divider()
    
    # CELL 선택 버튼 세트
    cell_opt = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_btn_row = st.columns(len(cell_opt))
    
    for i, c_nm in enumerate(cell_opt):
        if c_btn_row[i].button(c_nm, type="primary" if st.session_state.selected_cell == c_nm else "secondary"):
            st.session_state.selected_cell = c_nm
            st.rerun()
            
    # 개별 CELL 선택 시 생산 등록 폼 표시
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🔨 {st.session_state.selected_cell} 신규 생산 등록")
            
            # 모델 선택
            sel_m = st.selectbox("생산 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models)
            
            with st.form("assembly_form"):
                f_c1, f_c2 = st.columns(2)
                
                # 모델별 품목 코드 매핑
                item_list = st.session_state.master_items_dict.get(sel_m, ["모델 미선택"])
                sel_i = f_c1.selectbox("품목코드 선택", item_list)
                
                sn_in = f_c2.text_input("시리얼 번호(S/N) 입력")
                
                reg_btn = st.form_submit_button("▶️ 신규 생산 등록", use_container_width=True, type="primary")
                
                if reg_btn:
                    if sel_m != "선택하세요." and sn_in != "":
                        full_db_p = st.session_state.production_db
                        
                        # [전수 중복 방지] 모델+시리얼 조합 체크
                        dup_check = full_db_p[
                            (full_db_p['모델'] == sel_m) & 
                            (full_db_p['시리얼'] == sn_in) & 
                            (full_db_p['상태'] != "구분선")
                        ]
                        
                        if not dup_check.empty:
                            st.error(f"❌ 중복 생산 오류: '{sn_in}' 시리얼 제품이 이미 존재합니다.")
                        else:
                            # 새 데이터 행 추가
                            new_row_data = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': sel_m, 
                                '품목코드': sel_i, 
                                '시리얼': sn_in, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            updated_df_p = pd.concat([full_db_p, pd.DataFrame([new_row_data])], ignore_index=True)
                            updated_df_p = check_and_add_marker(updated_df_p, "조립 라인")
                            
                            st.session_state.production_db = updated_df_p
                            
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델과 시리얼 번호는 필수 입력 사항입니다.")
                        
    display_process_log_table("조립 라인", "조립 완료 보고")

# -----------------------------------------------------------------
# 6-2. 검사 및 포장 라인 페이지 (행 업데이트 - DuplicateKey 에러 수정)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_now_nm = st.session_state.current_line
    icon_now_nm = "🔍" if line_now_nm == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_now_nm} {line_now_nm} 공정 현황</h2>", unsafe_allow_html=True)
    
    display_line_flow_stats(line_now_nm)
    st.divider()
    
    # 이전 단계 공정명 정의
    prev_step_nm_str = "조립 라인" if line_now_nm == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_step_nm_str} 완료 물량 입고 승인")
        
        # 모델별 필터링
        filter_col_1, filter_col_2 = st.columns(2)
        m_filter = filter_col_1.selectbox("모델 필터링", ["전체보기"] + st.session_state.master_models, key=f"filter_m_{line_now_nm}")
        
        # 입고 대상 데이터 필터링
        db_all_search = st.session_state.production_db
        
        # 이전 공정에서 '완료' 상태가 된 행만 표시
        waiting_pool_df = db_all_search[
            (db_all_search['라인'] == prev_step_nm_str) & 
            (db_all_search['상태'] == "완료")
        ]
        
        if m_filter != "전체보기":
            waiting_pool_df = waiting_pool_df[waiting_pool_df['모델'] == m_filter]
            
        if not waiting_pool_df.empty:
            st.success(f"현재 총 {len(waiting_pool_df)}건의 입고 가능한 대기 물량이 조회되었습니다.")
            
            # [수정] 입고 버튼 그리드 생성
            # 동일 시리얼의 모델 중복 문제를 해결하기 위해 key에 모델명을 포함합니다.
            in_cols_grid = st.columns(4)
            for i, row_item_p in enumerate(waiting_pool_df.itertuples()):
                sn_target_p = row_item_p.시리얼
                md_target_p = row_item_p.모델
                
                # 키 값에 모델명을 추가하여 DuplicateKeyError를 방지합니다.
                btn_key_str = f"in_act_{md_target_p}_{sn_target_p}_{line_now_nm}"
                
                if in_cols_grid[i % 4].button(f"📥 입고: {sn_target_p}", key=btn_key_str):
                    st.session_state.confirm_target = sn_target_p
                    st.session_state.confirm_model = md_target_p
                    confirm_entry_dialog()
        else:
            st.info(f"현재 {prev_step_nm_str}에서 입고를 기다리는 물량이 없습니다.")
            
    display_process_log_table(line_now_nm, "검사 통과" if line_now_nm == "검사 라인" else "출하 준비 완료")

# -----------------------------------------------------------------
# 6-3. 생산 리포트 통합 대시보드
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 리포트 대시보드</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 최신 생산 데이터 새로고침", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db_rpt_view = st.session_state.production_db
    
    if not db_rpt_view.empty:
        # 데이터 정제 (구분선 제거)
        clean_rpt_db = db_rpt_view[db_rpt_view['상태'] != '구분선']
        
        # 주요 실적 지표 계산
        final_out_qty = len(clean_rpt_db[
            (clean_rpt_db['라인'] == '포장 라인') & 
            (clean_rpt_db['상태'] == '완료')
        ])
        
        total_bad_qty = len(clean_rpt_db[clean_rpt_db['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출
        ftt_rate_calc = 0
        if (final_out_qty + total_bad_qty) > 0:
            ftt_rate_calc = (final_out_qty / (final_out_qty + total_bad_qty)) * 100
        else:
            ftt_rate_calc = 100
            
        # 상단 메트릭 박스
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("최종 생산 실적", f"{final_out_qty} EA")
        m_col2.metric("공정 재공 상태", len(clean_rpt_db[clean_rpt_db['상태'] == '진행 중']))
        m_col3.metric("누적 불량 건수", f"{total_bad_qty} 건", delta=total_bad_qty, delta_color="inverse")
        m_col4.metric("직행률(FTT)", f"{ftt_rate_calc:.1f}%")
        
        st.divider()
        
        # 시각화 그래프
        chart_col1, chart_col2 = st.columns([3, 2])
        
        with chart_col1:
            line_dist_df = clean_rpt_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_dist_df, x='라인', y='수량', color='라인', title="공정 단계별 제품 분포 현황"), use_container_width=True)
            
        with chart_col2:
            model_pie_df = clean_rpt_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_pie_df, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성"), use_container_width=True)
            
        st.markdown("##### 🔍 전 공정 통합 생산 이력 데이터 (최신순)")
        st.dataframe(db_rpt_view.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("시트에 표시할 생산 데이터가 아직 존재하지 않습니다.")

# -----------------------------------------------------------------
# 6-4. 불량 수리 센터 (line4 권한 대응)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 관리 센터</h2>", unsafe_allow_html=True)
    
    # 조립 라인 기준의 현재 대기 물량을 표시하여 수리 속도를 조절할 수 있게 합니다.
    display_line_flow_stats("조립 라인")
    
    # 불량 처리 중 상태인 행 필터링
    repair_db_full = st.session_state.production_db
    bad_list_df = repair_db_full[repair_db_full['상태'] == "불량 처리 중"]
    
    if bad_list_df.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 조치가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_list_df)}건")
        
        for idx_br, row_br in bad_list_df.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **S/N: {row_br['시리얼']}** | 모델: {row_br['모델']} | 발생 공정: {row_br['라인']}")
                
                # 입력 필드 레이아웃
                in_c1, in_c2, in_c3 = st.columns([4, 4, 2])
                
                # 입력값 캐시 로드
                cache_s_str = st.session_state.repair_cache.get(f"s_{idx_br}", "")
                cache_a_str = st.session_state.repair_cache.get(f"a_{idx_br}", "")
                
                in_cause = in_c1.text_input("불량 원인 상세 기술", value=cache_s_str, key=f"in_s_{idx_br}")
                in_action = in_c2.text_input("수리 및 조치 사항", value=cache_a_str, key=f"in_a_{idx_br}")
                
                # 캐시 즉시 업데이트
                st.session_state.repair_cache[f"s_{idx_br}"] = in_cause
                st.session_state.repair_cache[f"a_{idx_br}"] = in_action
                
                # 사진 첨부
                rep_photo = st.file_uploader("수리 증빙 사진 업로드", type=['jpg','png','jpeg'], key=f"img_u_{idx_br}")
                
                if rep_photo:
                    st.image(rep_photo, width=300, caption="업로드 예정 사진")
                    
                if in_c3.button("🔧 수리 완료 보고", key=f"btn_r_done_{idx_br}", type="primary", use_container_width=True):
                    if in_cause and in_action:
                        web_link_f = ""
                        
                        if rep_photo is not None:
                            with st.spinner("사진을 드라이브에 저장하고 있습니다..."):
                                ts_mark = get_kst_now().strftime('%Y%m%d_%H%M')
                                fn_save = f"{row_br['시리얼']}_FIX_{ts_mark}.jpg"
                                up_url = upload_image_to_drive(rep_photo, fn_save)
                                
                                if "http" in up_url:
                                    web_link_f = f" [사진링크: {up_url}]"
                        
                        # 행 데이터 업데이트
                        repair_db_full.at[idx_br, '상태'] = "수리 완료(재투입)"
                        repair_db_full.at[idx_br, '증상'] = in_cause
                        repair_db_full.at[idx_br, '수리'] = in_action + web_link_f
                        repair_db_full.at[idx_br, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(repair_db_full):
                            # 성공 시 입력값 캐시 제거
                            st.session_state.repair_cache.pop(f"s_{idx_br}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_br}", None)
                            st.success("수리 보고서가 시트에 반영되었습니다.")
                            st.rerun()
                    else:
                        st.error("원인 분석과 조치 내용을 모두 입력해야 합니다.")

# -----------------------------------------------------------------
# 6-5. 수리 결과 분석 리포트
# -----------------------------------------------------------------
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 이력 분석 리포트</h2>", unsafe_allow_html=True)
    
    db_full_rep = st.session_state.production_db
    # 수리 완료 기록이 남은 행 필터링
    repair_hist_df = db_full_rep[
        (db_full_rep['상태'].str.contains("재투입", na=False)) | 
        (db_full_rep['수리'] != "")
    ]
    
    if not repair_hist_df.empty:
        stat_rc1, stat_rc2 = st.columns(2)
        
        with stat_rc1:
            line_bad_rpt = repair_hist_df.groupby('라인').size().reset_index(name='건수')
            st.plotly_chart(px.bar(line_bad_rpt, x='라인', y='건수', title="공정 단계별 불량 발생 건수"), use_container_width=True)
            
        with stat_rc2:
            model_bad_rpt = repair_hist_df.groupby('모델').size().reset_index(name='건수')
            st.plotly_chart(px.pie(model_bad_rpt, values='건수', names='모델', hole=0.3, title="불량 발생 모델 구성 비율"), use_container_width=True)
            
        st.markdown("##### 📋 상세 수리 및 조치 완료 이력 데이터")
        st.dataframe(repair_hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재 분석할 수리 데이터가 존재하지 않습니다.")

# -----------------------------------------------------------------
# 6-6. 마스터 관리 (초기화 오류 수정 반영)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리자 전용 마스터 센터</h2>", unsafe_allow_html=True)
    
    # 관리자 비밀번호 인증 절차
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            st.write("안전한 시스템 관리를 위해 관리자 인증이 필요합니다.")
            admin_pw_in = st.text_input("관리자 비밀번호 입력 (admin1234)", type="password")
            
            if st.form_submit_button("권한 인증"):
                if admin_pw_in in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 기능이 활성화되었습니다.")
                    st.rerun()
                else:
                    st.error("비밀번호 인증 실패")
    else:
        if st.sidebar.button("🔓 마스터 모드 종료"):
            st.session_state.admin_authenticated = False
            navigate_to("생산 리포트")

        st.markdown("### 📋 1. 마스터 정보 및 기준데이터 설정")
        adm_c1, adm_c2 = st.columns(2)
        
        with adm_c1:
            with st.container(border=True):
                st.subheader("모델 등록 관리")
                new_m_input = st.text_input("신규 추가 모델명")
                
                if st.button("➕ 모델 등록", use_container_width=True):
                    if new_m_input and new_m_input not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m_input)
                        st.session_state.master_items_dict[new_m_input] = []
                        st.success(f"'{new_m_input}' 모델이 신규 등록되었습니다.")
                        st.rerun()

        with adm_c2:
            with st.container(border=True):
                st.subheader("품목코드 마스터 설정")
                sel_model_adm = st.selectbox("대상 모델 선택", st.session_state.master_models)
                new_i_input = st.text_input("새로운 품목코드")
                
                if st.button("➕ 품목코드 등록", use_container_width=True):
                    if new_i_input and new_i_input not in st.session_state.master_items_dict[sel_model_adm]:
                        st.session_state.master_items_dict[sel_model_adm].append(new_i_input)
                        st.success(f"[{sel_model_adm}] 품목 등록 완료")
                        st.rerun()

        st.divider()
        st.markdown("### 💾 2. 데이터 백업 및 외부 로드 관리")
        bk_c1, bk_c2 = st.columns(2)
        
        with bk_c1:
            st.write("현재 구글 시트의 전체 실적 데이터를 CSV로 내려받습니다.")
            csv_export_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            
            st.download_button(
                "📥 전체 실적 CSV 다운로드", 
                csv_export_data, 
                f"production_backup_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with bk_c2:
            st.write("백업된 CSV 파일을 불러와 현재 시스템 데이터에 통합합니다.")
            csv_in_file = st.file_uploader("백업용 CSV 파일 선택", type="csv")
            
            if csv_in_file and st.button("📤 데이터 로드 반영", use_container_width=True):
                loaded_df_p = pd.read_csv(csv_in_file)
                # 시리얼 타입 보정
                if '시리얼' in loaded_df_p.columns:
                    loaded_df_p['시리얼'] = loaded_df_p['시리얼'].astype(str)
                
                st.session_state.production_db = pd.concat([st.session_state.production_db, loaded_df_p], ignore_index=True)
                
                if save_to_gsheet(st.session_state.production_db):
                    st.success("외부 데이터가 정상 반영되었습니다.")
                    st.rerun()

        st.divider()
        st.markdown("### 👤 3. 사용자 권한 및 계정 제어 센터")
        
        uc1, uc2, uc3 = st.columns([3, 3, 2])
        new_uid_p = uc1.text_input("생성할 ID 입력")
        new_upw_p = uc2.text_input("비밀번호 설정", type="password")
        new_url_p = uc3.selectbox("부여할 권한 선택", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성 및 업데이트", use_container_width=True):
            if new_uid_p and new_upw_p:
                st.session_state.user_db[new_uid_p] = {"pw": new_upw_p, "role": new_url_p}
                st.success(f"계정 [{new_uid_p}] 등록/업데이트 완료")
                st.rerun()
        
        with st.expander("현재 시스템 등록 계정 상세 목록"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        st.markdown("### ⚠️ 4. 위험 구역 (시트 데이터 물리적 초기화)")
        # [핵심 수정] 초기화 시 is_reset_mode=True 인자를 명시적으로 전달합니다.
        if st.button("🚫 시스템 전체 생산 데이터 초기화", type="secondary", use_container_width=True):
             st.error("주의: 초기화 시 구글 시트의 모든 실적 데이터가 물리적으로 삭제됩니다.")
             if st.button("❌ 위험 감수: 전체 삭제 확정"):
                 # 빈 데이터프레임 구조 생성
                 empty_struct = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 st.session_state.production_db = empty_struct
                 
                 # 강제 초기화 모드로 저장 수행
                 if save_to_gsheet(empty_struct, is_reset_mode=True):
                     st.success("구글 시트의 모든 데이터가 성공적으로 초기화되었습니다.")
                     st.rerun()
