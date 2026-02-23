import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [구글 서비스 연동을 위한 라이브러리]
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# [기본 환경 설정] - 전역 설정 및 상수 정의
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v16.5",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST) 설정 (서버 위치에 관계없이 일관된 시간 기록)
KST = timezone(timedelta(hours=9))

# 사용자 그룹별 권한(Role) 정의
# 현장 라인별, 관리자별 접근 가능한 메뉴를 분리하여 보안 및 편의성 강화
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
}

# [CSS 스타일 시트] - UI 디자인 커스텀
# 두 번째 이미지의 다크한 느낌과 전문적인 대시보드 UI를 위해 설정
st.markdown("""
    <style>
    /* 메인 앱 레이아웃 및 여백 조절 */
    .stApp { 
        max-width: 1400px; 
        margin: 0 auto; 
    }
    
    /* 버튼 스타일 커스텀 */
    .stButton button { 
        margin-top: 0px; 
        padding: 5px 15px; 
        width: 100%; 
        border-radius: 5px;
    }
    
    /* 제목 중앙 정렬 및 폰트 설정 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 30px 0; 
        color: #f0f2f6;
    }
    
    /* 긴급 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #331111; 
        color: #ff4b4b; 
        padding: 20px; 
        border-radius: 12px; 
        border: 1px solid #ff4b4b; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(255, 75, 75, 0.2);
    }
    
    /* 통계 지표 박스 스타일 (대시보드 상단) */
    .stat-box {
        background-color: #1e2130; 
        border-radius: 12px; 
        padding: 20px; 
        text-align: center;
        border: 1px solid #3e445b; 
        margin-bottom: 15px;
        transition: transform 0.3s ease;
    }
    .stat-box:hover {
        transform: translateY(-5px);
        border-color: #007bff;
    }
    .stat-label { font-size: 1.0em; color: #aab0c6; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.2em; color: #00d4ff; font-weight: bold; }
    .stat-sub { font-size: 0.85em; color: #6c757d; margin-top: 5px; }
    
    /* 섹션 구분 제목 스타일 */
    .section-title { 
        font-size: 1.3em; 
        font-weight: bold; 
        margin: 35px 0 15px 0; 
        border-left: 6px solid #00d4ff; 
        padding-left: 15px; 
        color: #ffffff;
    }
    
    /* 사이드바 스타일 개선 */
    [data-testid="stSidebar"] {
        background-color: #11141d;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 함수 (데이터 로드/저장/업로드)
# =================================================================

def get_current_kst_time():
    """현재 대한민국 표준시를 문자열로 반환"""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 커넥션 초기화
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """구글 시트로부터 실시간 생산 데이터를 로드하고 전처리"""
    try:
        # ttl=0 설정을 통해 캐시 없이 매번 실시간 데이터를 가져옴
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 시리얼 번호가 숫자로 인식되어 .0이 붙는 현상 방지
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터가 아예 없는 초기 상태일 경우 빈 데이터프레임 생성
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """변경 정보를 구글 시트에 업데이트하고 로컬 캐시 초기화"""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """작업자가 업로드한 수리 사진을 구글 드라이브 지정 폴더에 저장"""
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 구글 드라이브 API 서비스 빌드
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 폴더 ID 설정이 누락되었습니다."

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 파일 업로드 실행 및 웹 링크 반환 필드 지정
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 업로드 실패: {str(e)}"

# =================================================================
# 3. 세션 상태(Session State) 초기화
# =================================================================

# 생산 DB 세션 초기화
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 사용자 계정 정보 (초기 설정값)
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }

# 앱 구동을 위한 제어 상태값들
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], 
        "EPS7133": ["7133-S", "7133-M"], 
        "T20i": ["T20i-P", "T20i-Basic"], 
        "T20C": ["T20C-S", "T20C-Custom"]
    }
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# 4. 로그인 시스템 및 사이드바 구성
# =================================================================

# [로그인 화면]
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.3, 1])
    with l_col:
        st.markdown("<h1 class='centered-title'>🛡️ 생산 관리 통합 시스템</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center; color:#6c757d;'>Production Management & Tracking System</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            uid = st.text_input("계정 ID", placeholder="아이디를 입력하세요")
            upw = st.text_input("계정 PW", type="password", placeholder="비밀번호를 입력하세요")
            
            login_btn = st.form_submit_button("시스템 접속", use_container_width=True)
            if login_btn:
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    # 초기 페이지 설정
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 로그인 정보가 올바르지 않습니다.")
    st.stop()

# [사이드바 메뉴 구성]
st.sidebar.markdown("<h2 style='color:#00d4ff;'>🏭 PMS v16.5</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"**접속자:** {st.session_state.user_id} 작업자")
if st.sidebar.button("🚪 시스템 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def handle_nav(menu_name): 
    st.session_state.current_line = menu_name
    st.rerun()

# 권한에 따른 메뉴 렌더링
available_menus = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 공정 및 대시보드
st.sidebar.caption("MAIN PROCESS")
menu_icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "리포트":"📊"}
for menu in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if menu in available_menus:
        btn_label = f"{menu_icons[menu]} {menu}"
        if menu == "리포트": btn_label = f"{menu_icons[menu]} 통합 대시보드"
        
        if st.sidebar.button(
            btn_label, 
            use_container_width=True, 
            type="primary" if st.session_state.current_line == menu else "secondary"
        ):
            handle_nav(menu)

# 그룹 2: 사후 관리
st.sidebar.divider()
st.sidebar.caption("POST-MANAGEMENT")
sub_icons = {"불량 공정":"🛠️", "수리 리포트":"📈"}
for menu in ["불량 공정", "수리 리포트"]:
    if menu in available_menus:
        if st.sidebar.button(
            f"{sub_icons[menu]} {menu}", 
            use_container_width=True,
            type="primary" if st.session_state.current_line == menu else "secondary"
        ):
            handle_nav(menu)

# 그룹 3: 시스템 관리
if "마스터 관리" in available_menus:
    st.sidebar.divider()
    st.sidebar.caption("SYSTEM ADMIN")
    if st.sidebar.button(
        "🔐 마스터 데이터 관리", 
        use_container_width=True,
        type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"
    ):
        handle_nav("마스터 관리")

# =================================================================
# 5. 공용 비즈니스 로직 (Update/Validate)
# =================================================================

@st.dialog("📋 공정 단계 전환 승인")
def confirm_process_update():
    """제품을 다음 공정으로 이동(Update)할 때 최종 확인 팝업"""
    st.warning(f"시리얼 번호 [ {st.session_state.confirm_target} ]")
    st.markdown(f"**대상 공정:** {st.session_state.current_line}")
    st.info("입고 승인 시 기존 공정 기록이 업데이트됩니다.")
    
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심 로직] 1인 1행 유지를 위해 시리얼 번호로 기존 행을 찾아 업데이트
        match_idx = db[db['시리얼'] == st.session_state.confirm_target].index
        if not match_idx.empty:
            target_idx = match_idx[0]
            db.at[target_idx, '시간'] = get_current_kst_time()
            db.at[target_idx, '라인'] = st.session_state.current_line
            db.at[target_idx, '상태'] = '진행 중'
            db.at[target_idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
            
        st.session_state.confirm_target = None
        st.rerun()
        
    if c2.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def display_summary_header(current_line_name):
    """모든 페이지 상단에 노출되는 생산 현황 요약 바"""
    db = st.session_state.production_db
    today_prefix = datetime.now(KST).strftime('%Y-%m-%d')
    
    # 현재 라인의 오늘 데이터 필터링
    line_today = db[(db['라인'] == current_line_name) & (db['시간'].astype(str).str.contains(today_prefix))]
    
    cnt_input = len(line_today)
    cnt_done = len(line_today[line_today['상태'] == '완료'])
    
    # 이전 라인에서의 대기 물량 계산
    wait_count = 0
    prev_line = None
    if current_line_name == "검사 라인": prev_line = "조립 라인"
    elif current_line_name == "포장 라인": prev_line = "검사 라인"
    
    if prev_line:
        # 이전 라인에서 '완료' 상태이지만 아직 현재 라인으로 업데이트되지 않은 제품들
        wait_count = len(db[(db['라인'] == prev_line) & (db['상태'] == '완료')])
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>⏳ {prev_line if prev_line else '신규'} 대기</div>
            <div class='stat-value' style='color:#ff9f43;'>{wait_count if prev_line else '-'}</div>
            <div class='stat-sub'>건 (Process Buffer)</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>📥 금일 투입</div>
            <div class='stat-value'>{cnt_input}</div>
            <div class='stat-sub'>건 (Today Input)</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>✅ 금일 완료</div>
            <div class='stat-value' style='color:#28c76f;'>{cnt_done}</div>
            <div class='stat-sub'>건 (Today Success)</div>
        </div>""", unsafe_allow_html=True)

def render_realtime_log(line_filter, ok_text="완료 처리"):
    """각 라인 하단에 위치하는 실시간 작업 리스트 및 제어부"""
    st.markdown(f"<div class='section-title'>📋 {line_filter} 실시간 작업 리스트</div>", unsafe_allow_html=True)
    
    full_db = st.session_state.production_db
    display_df = full_db[full_db['라인'] == line_filter]
    
    # 조립 라인의 경우 선택된 CELL 데이터만 필터링하여 복잡도 감소
    if line_filter == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        display_df = display_df[display_df['CELL'] == st.session_state.selected_cell]
    
    if display_df.empty:
        st.info("현재 처리 대기 중인 항목이 없습니다.")
        return
    
    # 테이블 헤더 구성
    cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    headers = ["업데이트 시간", "구분", "모델명", "품목코드", "시리얼 번호", "상태 제어"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")
    
    # 데이터 행 렌더링 (최신순)
    for idx, row in display_df.sort_values('시간', ascending=False).iterrows():
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        r_cols[0].write(row['시간'])
        r_cols[1].write(row['CELL'])
        r_cols[2].write(row['모델'])
        r_cols[3].write(row['품목코드'])
        r_cols[4].write(f"`{row['시리얼']}`")
        
        with r_cols[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                btn_ok, btn_ng = st.columns(2)
                if btn_ok.button(ok_text, key=f"btn_ok_{idx}", type="secondary"):
                    full_db.at[idx, '상태'] = "완료"
                    full_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(full_db)
                    st.rerun()
                if btn_ng.button("🚫 불량", key=f"btn_ng_{idx}"):
                    full_db.at[idx, '상태'] = "불량 처리 중"
                    full_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(full_db)
                    st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span style='color:#ff4b4b;'>🔴 불량 분석 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#28c76f;'>🟢 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 세부 페이지별 렌더링 로직
# =================================================================

# --- [6-1. 조립 라인] ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 관리</h2>", unsafe_allow_html=True)
    display_summary_header("조립 라인")
    
    st.divider()
    # 셀 선택 인터페이스
    cells = ["CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_tabs = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_tabs[i].button(c, type="primary" if st.session_state.selected_cell == c else "secondary", use_container_width=True):
            st.session_state.selected_cell = c
            st.rerun()
            
    # 제품 등록 폼
    with st.container(border=True):
        st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 제품 등록")
        # 셀 이동 시 이전 입력값 간섭 방지를 위해 고유 Key 사용
        m_sel = st.selectbox("생산 모델", ["선택하세요."] + st.session_state.master_models, key=f"sel_m_{st.session_state.selected_cell}")
        
        with st.form(f"asm_entry_form_{st.session_state.selected_cell}"):
            f_c1, f_c2 = st.columns(2)
            i_list = st.session_state.master_items_dict.get(m_sel, ["모델을 먼저 선택하세요"])
            i_sel = f_c1.selectbox("품목 코드", i_list)
            sn_input = f_c2.text_input("시리얼 번호(S/N)", placeholder="제품 스캔 또는 입력")
            
            submit_reg = st.form_submit_button("생산 시작 (DB 등록)", type="primary", use_container_width=True)
            if submit_reg:
                if m_sel == "선택하세요." or not sn_input:
                    st.error("필수 정보를 모두 입력해주세요.")
                else:
                    db = st.session_state.production_db
                    # [규칙] 시리얼 중복 체크 로직
                    if sn_input in db['시리얼'].values:
                        st.error(f"❌ 중복 오류: '{sn_input}'은 이미 생산 진행 중이거나 완료된 번호입니다.")
                    else:
                        new_data = {
                            '시간': get_current_kst_time(),
                            '라인': "조립 라인",
                            'CELL': st.session_state.selected_cell,
                            '모델': m_sel,
                            '품목코드': i_sel,
                            '시리얼': sn_input,
                            '상태': '진행 중',
                            '증상': '', '수리': '',
                            '작업자': st.session_state.user_id
                        }
                        st.session_state.production_db = pd.concat([db, pd.DataFrame([new_data])], ignore_index=True)
                        save_to_gsheet(st.session_state.production_db)
                        st.success(f"성공: {sn_input} 등록 완료")
                        st.rerun()
    
    render_realtime_log("조립 라인")

# --- [6-2. 검사 / 포장 라인] ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    page_type = st.session_state.current_line
    icon = "🔍" if page_type == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon} {page_type} 관리</h2>", unsafe_allow_html=True)
    display_summary_header(page_type)
    
    st.divider()
    st.markdown("<div class='section-title'>📥 입고 승인 대기 목록</div>", unsafe_allow_html=True)
    
    # 이전 라인 완료 제품 조회
    prev_map = {"검사 라인": "조립 라인", "포장 라인": "검사 라인"}
    p_line = prev_map[page_type]
    
    db = st.session_state.production_db
    waiting_df = db[(db['라인'] == p_line) & (db['상태'] == "완료")]
    
    if not waiting_df.empty:
        st.info(f"이전 공정({p_line})에서 완료된 제품 {len(waiting_df)}건이 대기 중입니다.")
        # 카드형 입고 인터페이스
        grid_cols = st.columns(4)
        for i, (idx, row) in enumerate(waiting_df.iterrows()):
            with grid_cols[i % 4]:
                with st.container(border=True):
                    st.markdown(f"**S/N: {row['시리얼']}**")
                    st.caption(f"{row['모델']} | {row['품목코드']}")
                    if st.button(f"입고 승인", key=f"move_{idx}", use_container_width=True, type="primary"):
                        st.session_state.confirm_target = row['시리얼']
                        st.session_state.confirm_model = row['모델']
                        st.session_state.confirm_item = row['품목코드']
                        confirm_process_update()
    else:
        st.info("이전 라인에서 넘어온 대기 물량이 없습니다.")
        
    render_realtime_log(page_type, ok_text="합격 처리" if page_type == "검사 라인" else "출고 완료")

# --- [6-3. 통합 대시보드 (디자인 강화 버전)] ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 통합 생산 대시보드</h2>", unsafe_allow_html=True)
    
    # 최신 데이터 동기화 버튼
    if st.button("🔄 데이터 강제 새로고침", use_container_width=True):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db = st.session_state.production_db
    if not db.empty:
        # 주요 KPI 계산
        final_done = len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])
        in_process = len(db[db['상태'] == '진행 중'])
        ng_total = len(db[db['상태'].str.contains("불량", na=False)])
        ftr_rate = (final_done / len(db) * 100) if not db.empty else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("최종 생산 실적", f"{final_done} EA", help="포장 라인까지 완료된 총 수량")
        m2.metric("전 공정 재공(WIP)", f"{in_process} EA", help="현재 각 라인에서 진행 중인 제품")
        m3.metric("누적 불량 발생", f"{ng_total} 건", delta=ng_total, delta_color="inverse")
        m4.metric("공정 직행률", f"{ftr_rate:.1f}%")
        
        st.divider()
        
        # [ Image_e2eb1e.png 스타일 차트 구현 ]
        c_left, c_right = st.columns([1, 2])
        
        with c_left:
            # 공정별 제품 위치 바 차트
            # 색상 매핑: 검사(LightBlue), 조립(Blue), 포장(Pink/Peach)
            loc_data = db.groupby('라인').size().reset_index(name='수량')
            # 강제 순서 지정
            loc_data['sort_idx'] = loc_data['라인'].map({"조립 라인":0, "검사 라인":1, "포장 라인":2})
            loc_data = loc_data.sort_values('sort_idx')
            
            fig_loc = px.bar(
                loc_data, 
                x='라인', 
                y='수량', 
                color='라인',
                title="<b>공정별 제품 위치</b>",
                color_discrete_map={
                    "검사 라인": "#A0D1FB", # 라이트 블루
                    "조립 라인": "#0068C9", # 블루
                    "포장 라인": "#FFABAB"  # 핑크/피치
                },
                template="plotly_dark"
            )
            # 디자인 세밀 조정 (이미지와 유사하게)
            fig_loc.update_traces(width=0.4) # 막대 너비 조절
            fig_loc.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                showlegend=True,
                legend_title_text="라인"
            )
            # [수량 표기 짝수 방지 - 정수 고정]
            fig_loc.update_yaxes(dtick=1, rangemode='tozero', gridcolor='#333')
            st.plotly_chart(fig_loc, use_container_width=True)
            
        with c_right:
            # 모델별 비중 파이 차트 (이미지 스타일)
            model_data = db.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(
                model_data, 
                values='수량', 
                names='모델', 
                hole=0.45,
                title="<b>모델별 비중</b>",
                color_discrete_sequence=px.colors.qualitative.Pastel,
                template="plotly_dark"
            )
            fig_pie.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        st.markdown("<div class='section-title'>📋 실시간 생산 현황 데이터 보드</div>", unsafe_allow_html=True)
        st.dataframe(
            db.sort_values('시간', ascending=False), 
            use_container_width=True, 
            hide_index=True
        )

# --- [6-4. 불량 수리 센터] ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 센터</h2>", unsafe_allow_html=True)
    
    db = st.session_state.production_db
    bad_items = db[db['상태'] == "불량 처리 중"]
    
    # 요약 통계
    today_prefix = datetime.now(KST).strftime('%Y-%m-%d')
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>🛠️ 현재 수리 대기</div>
            <div class='stat-value' style='color:#ff4b4b;'>{len(bad_items)}</div>
        </div>""", unsafe_allow_html=True)
    with sc2:
        done_today = len(db[(db['상태'] == "수리 완료(재투입)") & (db['시간'].astype(str).str.contains(today_prefix))])
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>✅ 금일 수리 완료</div>
            <div class='stat-value' style='color:#28c76f;'>{done_today}</div>
        </div>""", unsafe_allow_html=True)
        
    if bad_items.empty:
        st.success("현재 분석이 필요한 불량 항목이 없습니다. 생산 라인이 원활합니다.")
    else:
        for idx, row in bad_items.iterrows():
            with st.container(border=True):
                st.markdown(f"### 🚨 불량 발생: {row['시리얼']}")
                st.write(f"**발생 공정:** {row['라인']} | **모델:** {row['모델']}")
                
                c_input, c_img, c_btn = st.columns([4, 4, 2])
                with c_input:
                    sv = st.text_input("불량 원인 분석", placeholder="원인을 입력하세요", key=f"sv_{idx}")
                    av = st.text_input("수리 및 조치 내용", placeholder="조치 사항을 입력하세요", key=f"av_{idx}")
                with c_img:
                    up_img = st.file_uploader("수리 증빙 사진", type=['jpg','png','jpeg'], key=f"img_{idx}")
                    if up_img: st.image(up_img, width=150)
                with c_btn:
                    st.write("") # 간격 조절
                    if st.button("수리 완료 및 재투입", key=f"repair_ok_{idx}", type="primary", use_container_width=True):
                        if not sv or not av:
                            st.error("분석 및 조치 내용을 입력해야 합니다.")
                        else:
                            drive_link = ""
                            if up_img:
                                with st.spinner("사진 저장 중..."):
                                    res = upload_image_to_drive(up_img, f"Repair_{row['시리얼']}_{datetime.now(KST).strftime('%H%M')}.jpg")
                                    if "http" in res: drive_link = f" [사진: {res}]"
                            
                            db.at[idx, '상태'] = "수리 완료(재투입)"
                            db.at[idx, '증상'] = sv
                            db.at[idx, '수리'] = av + drive_link
                            db.at[idx, '작업자'] = st.session_state.user_id
                            save_to_gsheet(db)
                            st.rerun()

# --- [6-5. 수리 리포트] ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 및 분석 이력 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    repair_df = db[db['수리'] != ""]
    
    if repair_df.empty:
        st.info("기록된 수리 이력이 없습니다.")
    else:
        # 이력 분석 차트
        rc1, rc2 = st.columns([1, 2])
        with rc1:
            fig_r1 = px.bar(repair_df.groupby('라인').size().reset_index(name='건수'), x='라인', y='건수', title="공정별 불량 발생 빈도", template="plotly_dark")
            fig_r1.update_yaxes(dtick=1)
            st.plotly_chart(fig_r1, use_container_width=True)
        with rc2:
            st.plotly_chart(px.pie(repair_df.groupby('모델').size().reset_index(name='건수'), values='건수', names='모델', title="모델별 불량 비중", template="plotly_dark"), use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 수리 이력 데이터</div>", unsafe_allow_html=True)
        st.dataframe(
            repair_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']].sort_values('시간', ascending=False),
            use_container_width=True,
            hide_index=True
        )

# --- [6-6. 마스터 관리 (풀버전)] ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 관리 및 기준 정보</h2>", unsafe_allow_html=True)
    
    # 2차 관리자 인증
    if not st.session_state.admin_authenticated:
        _, auth_c, _ = st.columns([1, 1, 1])
        with auth_c:
            with st.form("admin_verify"):
                apw = st.text_input("관리자 액세스 PW", type="password")
                if st.form_submit_button("인증 실행"):
                    if apw in ["admin1234", "master1234"]:
                        st.session_state.admin_authenticated = True
                        st.rerun()
                    else: st.error("접근 권한이 없습니다.")
    else:
        # 관리자 인증 완료 시
        if st.sidebar.button("🔓 관리 세션 종료"):
            st.session_state.admin_authenticated = False
            st.rerun()
            
        t1, t2, t3 = st.tabs(["📋 기준정보 관리", "👤 계정 관리", "💾 데이터 관리"])
        
        with t1:
            st.markdown("<div class='section-title'>📍 생산 모델 및 품목코드 설정</div>", unsafe_allow_html=True)
            mc1, mc2 = st.columns(2)
            with mc1:
                with st.container(border=True):
                    st.write("**신규 모델 등록**")
                    new_m = st.text_input("모델 명칭", placeholder="예: EPS7500")
                    if st.button("모델 추가", use_container_width=True):
                        if new_m and new_m not in st.session_state.master_models:
                            st.session_state.master_models.append(new_m)
                            st.session_state.master_items_dict[new_m] = []
                            st.success(f"모델 '{new_m}' 등록 완료")
                            st.rerun()
            with mc2:
                with st.container(border=True):
                    st.write("**품목코드 연결**")
                    sel_m = st.selectbox("대상 모델 선택", st.session_state.master_models)
                    new_i = st.text_input("신규 품목코드", placeholder="예: 7500-Standard")
                    if st.button("품목 추가", use_container_width=True):
                        if new_i and new_i not in st.session_state.master_items_dict[sel_m]:
                            st.session_state.master_items_dict[sel_m].append(new_i)
                            st.success(f"'{sel_m}'에 품목 '{new_i}' 추가 완료")
                            st.rerun()
                            
        with t2:
            st.markdown("<div class='section-title'>👥 시스템 사용자 계정 관리</div>", unsafe_allow_html=True)
            with st.container(border=True):
                uc1, uc2, uc3 = st.columns([3, 3, 2])
                nu_id = uc1.text_input("사용자 ID")
                nu_pw = uc2.text_input("임시 PW", type="password")
                nu_ro = uc3.selectbox("부여 권한", list(ROLES.keys()))
                
                if st.button("계정 생성 및 정보 업데이트", use_container_width=True):
                    if nu_id and nu_pw:
                        st.session_state.user_db[nu_id] = {"pw": nu_pw, "role": nu_ro}
                        st.success(f"사용자 '{nu_id}' 설정이 업데이트되었습니다.")
                        st.rerun()
            
            st.write("**현재 등록된 계정 리스트**")
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
            
        with t3:
            st.markdown("<div class='section-title'>📊 생산 데이터 관리 및 백업</div>", unsafe_allow_html=True)
            with st.container(border=True):
                st.write("**데이터 백업(Export)**")
                cur_db = st.session_state.production_db
                csv_export = cur_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 전체 생산 데이터 다운로드 (CSV)",
                    data=csv_export,
                    file_name=f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d_%H%M')}.csv",
                    mime='text/csv',
                    use_container_width=True
                )
                
                st.divider()
                st.write("**데이터 복구/병합(Import)**")
                up_csv = st.file_uploader("복구할 CSV 파일을 선택하세요.", type="csv")
                if up_csv and st.button("📤 데이터 병합 실행", use_container_width=True):
                    try:
                        imp_df = pd.read_csv(up_csv)
                        # 시리얼 기준 중복 제거하며 병합
                        merged = pd.concat([st.session_state.production_db, imp_df], ignore_index=True)
                        st.session_state.production_db = merged.drop_duplicates(subset=['시리얼'], keep='last')
                        save_to_gsheet(st.session_state.production_db)
                        st.success("데이터 병합 및 시트 동기화가 성공적으로 완료되었습니다.")
                        st.rerun()
                    except:
                        st.error("파일 형식이 올바르지 않습니다.")
                        
                st.divider()
                st.write("**시스템 초기화**")
                if st.button("⚠️ 시스템 전체 데이터 초기화 (주의)", type="secondary", use_container_width=True):
                    # 보안 확인을 위한 추가 절차 권장되나 요청에 따라 즉시 초기화 로직 배치
                    st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()

# =================================================================
# [ PMS v16.5 종료 ] - 시스템 안정성을 위해 루프 종료 시마다 로그 처리
# =================================================================
