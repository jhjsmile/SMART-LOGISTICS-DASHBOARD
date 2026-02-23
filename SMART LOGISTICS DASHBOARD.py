import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [이미지/비디오 생성을 위한 핵심 API]
# 구글 GCP 서비스 계정 인증 및 드라이브 파일 제어를 위한 라이브러리 로드
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 검수 (Global CSS & Config)
# =================================================================
# 앱 브라우저 탭 설정 및 와이드 레이아웃 활성화
st.set_page_config(
    page_title="생산 통합 관리 시스템 v17.6",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 타임존 정의
# 서버의 물리적 위치와 관계없이 한국 시간을 기준으로 실적을 집계하고 기록합니다.
KST = timezone(timedelta(hours=9))

# 사용자 권한 체계 (Role-Based Access Control)
# 계정의 Role 등급에 따라 대시보드 및 공정 제어 권한을 차등 부여합니다.
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [정밀 검수된 CSS 스타일] - 정렬 및 밸런스 최적화
st.markdown("""
    <style>
    /* 전체 레이아웃 너비 1200px 고정 (가독성 최적화) */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 정렬 및 스타일: 텍스트가 중앙에 오도록 강제 */
    .stButton button { 
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: 1px; 
        padding: 6px 12px; 
        width: 100%; 
        border-radius: 8px;
        font-weight: 600;
        letter-spacing: -0.5px;
    }
    
    /* 섹션 타이틀: 파란색 테두리와 배경 정렬 */
    .section-title { 
        background-color: #f1f3f5; 
        color: #111; 
        padding: 16px 20px; 
        border-radius: 10px; 
        font-weight: bold; 
        margin: 10px 0 25px 0; 
        border-left: 10px solid #007bff;
        line-height: 1.5;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* 통계 박스 (Stat Box): 내부 요소 중앙 정렬 강화 */
    .stat-box {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        background-color: #f8f9fa; 
        border-radius: 12px; 
        padding: 20px; 
        border: 1px solid #dee2e6; 
        margin-bottom: 15px;
        min-height: 120px;
    }
    .stat-label { font-size: 0.95rem; color: #495057; font-weight: bold; margin-bottom: 10px; }
    .stat-value { font-size: 2.3rem; color: #007bff; font-weight: bold; line-height: 1; }
    .stat-sub { font-size: 0.85rem; color: #adb5bd; margin-top: 8px; }
    
    /* 수리 센터 입력칸/버튼 수평 정렬용 여백 */
    .button-spacer {
        margin-top: 28px;
    }
    
    /* 상태 표시 텍스트 강조 */
    .status-red { color: #e03131; font-weight: bold; }
    .status-green { color: #2f9e44; font-weight: bold; }
    
    /* 긴급 전파 배너: 시인성 극대화 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 18px; 
        border-radius: 12px; 
        border: 1px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(201, 42, 42, 0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 데이터 연동 유틸리티 (Data Connectivity)
# =================================================================

def get_now_timestamp():
    """현재 한국 시간을 표준 문자열 형식으로 생성합니다."""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 연동 객체 초기화
gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_live_data():
    """
    클라우드 구글 시트에서 최신 생산 실적을 로드합니다.
    ttl=0 설정을 통해 캐시 간섭 없는 실시간 동기화를 수행합니다.
    """
    try:
        df = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 엑셀 형식에서 숫자로 인식되어 붙는 소수점(.0)을 문자열 처리로 제거
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 시트 로드 실패 시 컬럼 구조만 정의하여 시스템 가동 유지
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_data_to_cloud(df):
    """
    수정된 데이터를 구글 시트에 즉시 반영합니다.
    작업 직후 캐시를 비워 대시보드 통계의 정합성을 보장합니다.
    """
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as error:
        st.error(f"클라우드 저장 실패: {error}")

def upload_proof_to_drive(file_stream, serial_no):
    """
    불량 조치 증빙 사진을 구글 드라이브 지정 폴더에 업로드합니다.
    파일명은 시리얼 번호와 조합하여 생성합니다.
    """
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 구글 드라이브 API 서비스 객체 생성
        svc = build('drive', 'v3', credentials=creds)
        f_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not f_id:
            return "❌ 폴더 ID 설정이 존재하지 않습니다."

        f_name = f"REP_{serial_no}_{datetime.now(KST).strftime('%H%M')}.jpg"
        meta = {'name': f_name, 'parents': [f_id]}
        media = MediaIoBaseUpload(file_stream, mimetype=file_stream.type)
        
        # 파일 업로드 실행 및 웹 링크 반환
        res = svc.files().create(body=meta, media_body=media, fields='id, webViewLink').execute()
        return res.get('webViewLink')
    except Exception as e:
        return f"⚠️ 사진 업로드 실패: {str(e)}"

# =================================================================
# 3. 세션 상태 관리 (Session Management)
# =================================================================

# 생산 실적 DB 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_live_data()

# 시스템 계정 (admin 포함)
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

# 인증 및 권한 상태
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 마스터 기준 정보 (모델 및 품목 매핑)
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], 
        "EPS7133": ["7133-S", "7133-Standard"], 
        "T20i": ["T20i-P", "T20i-BASIC"], 
        "T20C": ["T20C-S", "T20C-CORE"]
    }

# 앱 구동 위치 제어
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 화면 및 사이드바 (v17.2 디자인 준수)
# =================================================================

# [로그인 프로세스]
if not st.session_state.login_status:
    _, login_c, _ = st.columns([1, 1.2, 1])
    with login_c:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("sys_login_form"):
            uid = st.text_input("아이디(ID)", placeholder="사용자 ID")
            upw = st.text_input("비밀번호(PW)", type="password", placeholder="액세스 비밀번호")
            
            if st.form_submit_button("인증 및 접속 시작", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    # 권한별 초기 페이지 이동
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 아이디 또는 비밀번호를 확인해 주세요.")
    st.stop()

# [사이드바 구성 - 사용자 요청 v17.2 정렬 적용]
st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{st.session_state.user_id} 작업자**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def nav_to(page_name): 
    """사이드바 이동 기능을 수행합니다."""
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한 필터링
access_menus = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 공정 관리
if "조립 라인" in access_menus:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): 
        nav_to("조립 라인")
if "검사 라인" in access_menus:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): 
        nav_to("검사 라인")
if "포장 라인" in access_menus:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): 
        nav_to("포장 라인")
if "리포트" in access_menus:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): 
        nav_to("리포트")

st.sidebar.divider()
# 그룹 2: 사후 관리 및 분석
if "불량 공정" in access_menus:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): 
        nav_to("불량 공정")
if "수리 리포트" in access_menus:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): 
        nav_to("수리 리포트")

# 그룹 3: 마스터 어드민 전용
if st.session_state.user_role == "admin" or "마스터 관리" in access_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        nav_to("마스터 관리")

# [긴급 전파 모니터링] - 실시간 불량 대기 발생 시 경고 배너
active_ng = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if active_ng > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 공지: 현재 수리 대기 중인 불량 제품이 {active_ng}건 있습니다. 조속한 조치 바랍니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 (Core Business Logic)
# =================================================================

@st.dialog("📦 공정 단계 입고 승인")
def popup_entry_confirm():
    """
    공정 간 이동 시 호출되는 확인 다이얼로그입니다.
    기존의 시리얼 행을 검색하여 정보만 업데이트(Update)함으로써 1인 1행 원칙을 지킵니다.
    """
    st.warning(f"입고 시리얼: [ {st.session_state.confirm_target} ]")
    st.info(f"현재 이동 공정: {st.session_state.current_line}")
    st.write("승인 시 시간 및 작업자 정보가 갱신됩니다.")
    
    col_ok, col_no = st.columns(2)
    if col_ok.button("✅ 입고 확정", type="primary", use_container_width=True):
        db_main = st.session_state.production_db
        # 시리얼 번호를 기준으로 기존 실적 인덱스 검색
        target_rows = db_main[db_main['시리얼'] == st.session_state.confirm_target].index
        if not target_rows.empty:
            idx = target_rows[0]
            db_main.at[idx, '시간'] = get_now_timestamp()
            db_main.at[idx, '라인'] = st.session_state.current_line
            db_main.at[idx, '상태'] = '진행 중'
            db_main.at[idx, '작업자'] = st.session_state.user_id
            # 클라우드 동기화
            push_data_to_cloud(db_main)
            
        st.session_state.confirm_target = None
        st.success("입고 완료!"); st.rerun()
        
    if col_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def draw_v9_aligned_log(line_key, done_btn="완료 처리"):
    """
    v9.1 스타일의 정렬 비율을 준수하여 실시간 작업 로그를 렌더링합니다.
    컬럼 비율: [2.5, 1, 1.5, 1.5, 2, 3] 고정.
    """
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_raw = st.session_state.production_db
    f_df = db_raw[db_raw['라인'] == line_key]
    
    # 조립 라인의 경우 각 작업대(CELL)별 필터링 기능 강화
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: 
        st.info("현재 해당 공정에 투입된 항목이 없습니다.")
        return
    
    # [v9.1 디자인] 헤더 정렬
    hc = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    labels = ["기록 시간", "공정구분", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]
    for col, txt in zip(hc, labels): 
        col.write(f"**{txt}**")
    
    # 최신 시간 순으로 정렬하여 출력
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        rc = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        rc[0].write(row['시간'])
        rc[1].write(row['CELL'])
        rc[2].write(row['모델'])
        rc[3].write(row['품목코드'])
        rc[4].write(f"`{row['시리얼']}`")
        
        with rc[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                act_col1, act_col2 = st.columns(2)
                if act_col1.button(done_btn, key=f"btn_ok_{idx}", type="secondary"):
                    db_raw.at[idx, '상태'] = "완료"
                    db_raw.at[idx, '작업자'] = st.session_state.user_id
                    push_data_to_cloud(db_raw); st.rerun()
                if act_col2.button("🚫불량", key=f"btn_ng_{idx}"):
                    db_raw.at[idx, '상태'] = "불량 처리 중"
                    db_raw.at[idx, '작업자'] = st.session_state.user_id
                    push_data_to_cloud(db_raw); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 불량 분석 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 공정별 세부 페이지 (Page Rendering)
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 조립 생산 라인 현황</h2>", unsafe_allow_html=True)
    
    # 작업대(CELL) 선택 인터페이스 (v9.1 스타일 복구)
    c_names = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_grid = st.columns(len(c_names))
    for i, name in enumerate(c_names):
        if c_grid[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
            
    # 특정 CELL 선택 시에만 제품 등록 폼 노출
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 투입 등록")
            sel_model = st.selectbox("생산 대상 모델", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
            with st.form("assembly_entry_form"):
                fc1, fc2 = st.columns(2)
                sel_item = fc1.selectbox("품목 코드", st.session_state.master_items_dict.get(sel_model, []) if sel_model!="선택하세요." else ["모델 선택 대기"])
                sel_sn = fc2.text_input("제품 시리얼(S/N)")
                
                if st.form_submit_button("▶️ 생산 등록 실행", use_container_width=True, type="primary"):
                    if sel_model != "선택하세요." and sel_sn:
                        db_p = st.session_state.production_db
                        # [핵심] 시리얼 중복 등록 방지 로직 (제품 무결성 보장)
                        if sel_sn in db_p['시리얼'].values:
                            st.error(f"❌ 중복 오류: 시리얼 '{sel_sn}'은 이미 등록된 제품입니다.")
                        else:
                            new_data = {
                                '시간': get_now_timestamp(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': sel_model, '품목코드': sel_item, '시리얼': sel_sn, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_p, pd.DataFrame([new_data])], ignore_index=True)
                            push_data_to_cloud(st.session_state.production_db); st.rerun()
    
    draw_v9_aligned_log("조립 라인", "조립 완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    pg_title = "🔍 품질 검사 공정 현황" if st.session_state.current_line == "검사 라인" else "🚚 제품 출하 포장 현황"
    pv_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{pg_title}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 이전 공정 완료 물량 (입고 대기)</div>", unsafe_allow_html=True)
        db_ref = st.session_state.production_db
        # 이전 단계 '완료' 항목 필터링
        wait_df = db_ref[(db_ref['라인'] == pv_line) & (db_ref['상태'] == "완료")]
        
        if not wait_df.empty:
            st.success(f"현재 총 {len(wait_df)}건의 제품이 입고 승인을 기다리고 있습니다.")
            grid = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if grid[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_btn_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    popup_entry_confirm()
        else: 
            st.info("현재 대기 중인 입고 물량이 없습니다. 이전 공정 흐름을 확인하세요.")
            
    draw_v9_aligned_log(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "포장 완료")

# --- 6-3. 통합 리포트 (디자인 최적화 버전) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 리포트</h2>", unsafe_allow_html=True)
    db_rep = st.session_state.production_db
    
    if not db_rep.empty:
        # 생산 핵심 지표 산출
        tot_in = len(db_rep)
        tot_fin = len(db_rep[(db_rep['라인'] == '포장 라인') & (db_rep['상태'] == '완료')])
        tot_wip = len(db_rep[db_rep['상태'] == '진행 중'])
        tot_bad = len(db_rep[db_rep['상태'].str.contains("불량", na=False)])
        
        k_cols = st.columns(4)
        k_cols[0].metric("누적 총 투입", f"{tot_in} EA")
        k_cols[1].metric("최종 생산 완료", f"{tot_fin} EA")
        k_cols[2].metric("현재 공정 재공(WIP)", f"{tot_wip} EA")
        k_cols[3].metric("불량 발생 누적", f"{tot_bad} 건", delta=tot_bad, delta_color="inverse")
        
        st.divider()
        # [레이아웃 정밀 조정] 막대 그래프 넓게(1.8), 도넛 차트 아담하게(1.2)
        lo_l, lo_r = st.columns([1.8, 1.2])
        
        with lo_l:
            # 1) 공정별 위치 바 차트 (정수 표기 dtick=1 고정 및 격자 UI)
            pos_df = db_rep.groupby('라인').size().reset_index(name='수량')
            fig_b = px.bar(
                pos_df, x='라인', y='수량', color='라인', 
                title="<b>[공정 단계별 제품 분포 현황]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_white"
            )
            fig_b.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            # [핵심] Y축 수량을 1, 2, 3... 정수 단위로 강제
            fig_b.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_b, use_container_width=True)
            
        with lo_r:
            # 2) 모델별 비중 도넛 차트 (물리적 크기 축소 설정 유지)
            mod_df = db_rep.groupby('모델').size().reset_index(name='수량')
            fig_p = px.pie(mod_df, values='수량', names='모델', hole=0.5, title="<b>[생산 모델별 비중]</b>")
            # 높이를 350으로 축소하여 불필요한 공백 제거
            fig_p.update_layout(height=350, margin=dict(l=30, r=30, t=60, b=30))
            st.plotly_chart(fig_p, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 통합 생산 관리 원장 (Master Ledger)</div>", unsafe_allow_html=True)
        st.dataframe(db_rep.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 아직 입력되지 않았습니다.")

# --- 6-4. 불량 수리 센터 [v17.5 날짜 판독 강화 + v17.6 정렬 보정] ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치 관리</h2>", unsafe_allow_html=True)
    db_bad = st.session_state.production_db
    bad_wait = db_bad[db_bad['상태'] == "불량 처리 중"]
    
    # [v17.5 판독 엔진] 금일 조치 완료 카운트
    today_val = datetime.now(KST).date()
    def is_today(t_val):
        try: return pd.to_datetime(t_val).date() == today_val
        except: return False

    rep_today = len(db_bad[(db_bad['상태'] == "수리 완료(재투입)") & (db_bad['시간'].apply(is_today))])
    
    # 상단 수리 현황판 (중앙 정렬 강화)
    sc1, sc2 = st.columns(2)
    with sc1: 
        st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 분석 대기 건수</div><div class='stat-value' style='color:#e03131;'>{len(bad_wait)}</div><div class='stat-sub'>품질 이슈 분석 대기</div></div>", unsafe_allow_html=True)
    with sc2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 조치 완료</div><div class='stat-value' style='color:#2f9e44;'>{rep_today}</div><div class='stat-sub'>당일 수리 완료 실적</div></div>", unsafe_allow_html=True)

    if bad_wait.empty: 
        st.success("✅ 현재 조치 및 분석이 필요한 품질 이슈가 없습니다.")
    else:
        # 불량 제품별 조치 카드 렌더링
        for idx, row in bad_wait.iterrows():
            with st.container(border=True):
                st.markdown(f"**대상 S/N: `{row['시리얼']}`** (모델: {row['모델']} / 발생공정: {row['라인']})")
                
                # [v17.6 정렬 보정] 1행: 입력 필드
                r1c1, r1c2 = st.columns(2)
                bad_v = r1c1.text_input("⚠️ 불량 발생 원인", placeholder="원인 상세 입력", key=f"rc_{idx}")
                act_v = r1c2.text_input("🛠️ 수리 및 조치 사항", placeholder="조치 상세 입력", key=f"ra_{idx}")
                
                # [v17.6 정렬 보정] 2행: 업로더와 버튼 수평 높이 맞춤
                r2c1, r2c2 = st.columns([3, 1])
                proof_f = r2c1.file_uploader("📸 조치 증빙 사진 등록 (클라우드 전송)", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                
                # 수직 정렬을 위한 스페이서 주입
                r2c2.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if r2c2.button("✅ 수리 확정", key=f"rb_{idx}", type="primary", use_container_width=True):
                    if bad_v and act_v:
                        p_url = ""
                        if proof_f:
                            with st.spinner("증빙 사진 업로드 중..."):
                                up_res = upload_proof_to_drive(proof_f, row['시리얼'])
                                if "http" in up_res: p_url = f" [사진 확인: {up_res}]"
                        
                        # 데이터 업데이트 처리
                        db_bad.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad.at[idx, '시간'] = get_now_timestamp() # 수리 완료 시점으로 시간 갱신
                        db_bad.at[idx, '증상'], db_bad.at[idx, '수리'] = bad_v, act_v + p_url
                        db_bad.at[idx, '작업자'] = st.session_state.user_id
                        push_data_to_cloud(db_bad); st.rerun()
                    else:
                        st.error("불량 원인과 조치 사항을 반드시 입력해야 합니다.")

# --- 6-5. 수리 분석 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 품질 이슈 및 수리 분석 리포트</h2>", unsafe_allow_html=True)
    db_h = st.session_state.production_db
    rep_ledger = db_h[db_h['수리'] != ""]
    
    if not rep_ledger.empty:
        # 리포트 대시보드 (1.8:1.2 비율 적용)
        h_col_l, h_col_r = st.columns([1.8, 1.2])
        with h_col_l:
            fig_h_b = px.bar(rep_ledger.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 품질 이슈 빈도", template="plotly_white")
            fig_h_b.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_h_b, use_container_width=True)
        with h_col_r:
            fig_h_p = px.pie(rep_ledger.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 불량 비중")
            fig_h_p.update_layout(height=350)
            st.plotly_chart(fig_h_p, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 품질 이슈 및 조치 내역 원장</div>", unsafe_allow_html=True)
        st.dataframe(rep_ledger[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재까지 기록된 품질 이슈 및 수리 조치 내역이 없습니다.")

# --- 6-6. 마스터 정보 관리 (어드민) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    
    # 관리자 2단계 보안 인증 필터
    if not st.session_state.admin_authenticated:
        with st.form("admin_security_form"):
            m_pass = st.text_input("마스터 비밀번호 입력 (admin1234)", type="password")
            if st.form_submit_button("마스터 권한 인증"):
                if m_pass == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호 불일치: 권한이 없습니다.")
    else:
        # 인증 성공 시 관리자 전용 도구 노출
        if st.sidebar.button("🔓 관리자 세션 잠금(Lock)", use_container_width=True):
            st.session_state.admin_authenticated = False; nav_to("조립 라인")

        # [기준정보 관리 섹션]
        st.markdown("<div class='section-title'>📋 생산 기준정보 및 마스터 데이터 제어</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        
        with m_col1:
            with st.container(border=True):
                st.subheader("모델/품목 신규 등록")
                nm = st.text_input("신규 생산 모델 추가")
                if st.button("모델 등록 확정", use_container_width=True):
                    if nm and nm not in st.session_state.master_models:
                        st.session_state.master_models.append(nm)
                        st.session_state.master_items_dict[nm] = []; st.rerun()
                st.divider()
                sm = st.selectbox("품목 연결용 모델", st.session_state.master_models)
                ni = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록 확정", use_container_width=True):
                    if ni and ni not in st.session_state.master_items_dict[sm]:
                        st.session_state.master_items_dict[sm].append(ni); st.rerun()

        with m_col2:
            with st.container(border=True):
                st.subheader("시스템 데이터 백업 및 마이그레이션")
                # 전체 실적 데이터 CSV 백업
                raw_csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 실적 데이터 다운로드 (CSV)", raw_csv, f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # 백업 파일 업로드 및 실적 병합 도구
                csv_in = st.file_uploader("복구용 CSV 파일 업로드", type="csv")
                if csv_in and st.button("📤 실적 마이그레이션 실행", use_container_width=True):
                    try:
                        imp_df = pd.read_csv(csv_in)
                        combined = pd.concat([st.session_state.production_db, imp_df], ignore_index=True)
                        # 시리얼 번호 기준 중복 제거 (최신 실적 유지)
                        st.session_state.production_db = combined.drop_duplicates(subset=['시리얼'], keep='last')
                        push_data_to_cloud(st.session_state.production_db); st.rerun()
                    except: st.error("파일 구조 오류: 유효한 PMS 데이터 백업 형식이 아닙니다.")

        # [사용자 계정 보안 관리]
        st.divider()
        st.markdown("<div class='section-title'>👤 시스템 계정 및 작업자 권한 관리</div>", unsafe_allow_html=True)
        uc1, uc2, uc3 = st.columns([3, 3, 2])
        reg_id = uc1.text_input("신규 생성 ID")
        reg_pw = uc2.text_input("비밀번호 설정", type="password")
        reg_rl = uc3.selectbox("부여할 권한 등급", ["user", "admin"])
        
        if st.button("사용자 계정 생성/수정", use_container_width=True):
            if reg_id and reg_pw:
                st.session_state.user_db[reg_id] = {"pw": reg_pw, "role": reg_rl}
                st.success(f"사용자 '{reg_id}' 정보 반영 완료"); st.rerun()
        
        with st.expander("현재 시스템 등록 계정 전체 리스트"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        # [위험 도구] 전체 실적 초기화
        if st.button("⚠️ 시스템 전체 실적 데이터 영구 삭제 (초기화)", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_data_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v17.6 배포용 통합 코드 종료 ]
# =================================================================
