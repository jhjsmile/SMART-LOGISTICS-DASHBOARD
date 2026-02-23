import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [구글 서비스 연동을 위한 라이브러리]
# 서비스 계정 인증 및 드라이브 API 사용을 위한 설정
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# [1. 시스템 전역 설정 및 디자인 정의]
# =================================================================
# 앱의 타이틀과 레이아웃(와이드 모드)을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v16.9",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST) 설정: 서버 위치에 상관없이 한국 시간으로 기록하기 위함
KST = timezone(timedelta(hours=9))

# 사용자 그룹별 권한(Role) 정의
# 현장 라인별, 관리자별 접근 가능한 메뉴를 분리하여 보안 및 편의성 강화
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [CSS 스타일 커스텀] - v9.1 디자인 + 이전 격자 UI 선호도 반영
st.markdown("""
    <style>
    /* 메인 컨테이너 너비 제한 (v9.1 기준 1200px로 가독성 확보) */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 스타일: 패딩 및 정렬 최적화 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
        border-radius: 5px;
    }
    
    /* 제목 중앙 정렬 및 폰트 설정 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 20px 0; 
    }
    
    /* v9.1 전용 섹션 타이틀: 회색 배경에 파란색 왼쪽 굵은 테두리(8px) */
    .section-title { 
        background-color: #f8f9fa; 
        color: #000; 
        padding: 15px; 
        border-radius: 8px; 
        font-weight: bold; 
        margin-bottom: 20px; 
        border-left: 8px solid #007bff;
    }
    
    /* 상태 표시 색상 정의 (성공/불량 시인성 강화) */
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    
    /* 대시보드 상단 통계 박스 (Stat Box) */
    .stat-box {
        background-color: #f0f2f6; 
        border-radius: 10px; 
        padding: 15px; 
        text-align: center;
        border: 1px solid #e0e0e0; 
        margin-bottom: 10px;
    }
    .stat-label { font-size: 0.9em; color: #555; font-weight: bold; }
    .stat-value { font-size: 1.8em; color: #007bff; font-weight: bold; }
    .stat-sub { font-size: 0.8em; color: #888; }
    
    /* 긴급 알림 배너 스타일 */
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
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# [2. 핵심 유틸리티 함수 - 데이터 연동 및 기록]
# =================================================================

def get_now_kst():
    """현재 한국 표준시를 'YYYY-MM-DD HH:MM:SS' 형식으로 반환합니다."""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 커넥션 객체 초기화
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """구글 시트로부터 실시간 생산 데이터를 로드하고 전처리합니다."""
    try:
        # ttl=0 설정을 통해 캐시를 사용하지 않고 항상 시트의 최신 정보를 가져옵니다.
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 시리얼 번호가 숫자로 인식되어 소수점(.0)이 붙는 현상을 방지합니다.
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터 로드 실패 시 컬럼 구조만 갖춘 빈 데이터프레임을 생성하여 시스템 중단을 방지합니다.
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """업데이트된 데이터프레임을 구글 시트에 즉시 반영하고 캐시를 초기화합니다."""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """불량 수리 사진을 구글 드라이브의 지정 폴더에 업로드하고 웹 링크를 반환합니다."""
    try:
        # secrets에서 API 인증 정보를 로드합니다.
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 드라이브 API 서비스 구축
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 드라이브 폴더 ID가 설정되지 않았습니다."

        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 파일 생성 및 업로드 실행
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 사진 업로드 실패: {str(e)}"

# =================================================================
# [3. 세션 상태(Session State) 관리 및 데이터 초기화]
# =================================================================

# 1) 생산 실적 데이터베이스 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 2) 시스템 기본 계정 DB (초기 설정)
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

# 3) 로그인 및 권한 상태값
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 4) 생산 기준 정보 (모델 및 품목 매핑)
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }

# 5) 공정 내비게이션 상태값
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [4. 로그인 인터페이스 및 사이드바 내비게이션]
# =================================================================

# [로그인 화면 로직]
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 접속 정보를 입력하세요. (관리자 문의: admin)")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)", placeholder="아이디 입력")
            upw = st.text_input("비밀번호(PW)", type="password", placeholder="비밀번호 입력")
            if st.form_submit_button("시스템 접속", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    # 소속 그룹에 맞는 첫 페이지로 이동
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 아이디 또는 비밀번호를 확인해 주세요.")
    st.stop()

# [사이드바 구성]
st.sidebar.title(f"🏭 {st.session_state.user_id} 작업자")
if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def nav_to(page_name): 
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한에 따른 메뉴 렌더링
user_allowed_menus = ROLES.get(st.session_state.user_role, [])

# 그룹 1: 메인 공정 관리
if "조립 라인" in user_allowed_menus:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): nav_to("조립 라인")
if "검사 라인" in user_allowed_menus:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): nav_to("검사 라인")
if "포장 라인" in user_allowed_menus:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): nav_to("포장 라인")
if "리포트" in user_allowed_menus:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): nav_to("리포트")

# 그룹 2: 사후 및 품질 관리
st.sidebar.divider()
if "불량 공정" in user_allowed_menus:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): nav_to("불량 공정")
if "수리 리포트" in user_allowed_menus:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): nav_to("수리 리포트")

# 그룹 3: 관리자 전용 메뉴
if st.session_state.user_role == "admin" or "마스터 관리" in user_allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav_to("마스터 관리")

# [현장 공통] 하단 불량 발생 실시간 알림
bad_sum = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_sum > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 알림: 수리 대기 중인 제품이 {bad_sum}건 존재합니다.</div>", unsafe_allow_html=True)

# =================================================================
# [5. 공용 비즈니스 로직 - 1인 1행 업데이트 및 로그 출력]
# =================================================================

@st.dialog("📦 공정 단계 전환 확인")
def confirm_entry_dialog():
    """제품을 다음 단계로 입고할 때 행을 추가하지 않고 기존 정보를 업데이트하는 다이얼로그입니다."""
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ]")
    st.markdown(f"**이동 공정:** {st.session_state.current_line}")
    c1, c2 = st.columns(2)
    if c1.button("✅ 입고 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심] 시리얼 번호를 기준으로 기존 행을 찾아 업데이트 (Update)
        idx_find = db[db['시리얼'] == st.session_state.confirm_target].index
        if not idx_find.empty:
            target_idx = idx_find[0]
            db.at[target_idx, '시간'] = get_now_kst()
            db.at[target_idx, '라인'] = st.session_state.current_line
            db.at[target_idx, '상태'] = '진행 중'
            db.at[target_idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
        st.session_state.confirm_target = None
        st.rerun()
    if c2.button("❌ 입고 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def render_realtime_log(line_name, ok_label="완료 처리"):
    """각 라인별로 실시간 로그 및 작업 제어 버튼을 렌더링합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    l_db = db[db['라인'] == line_name]
    
    # 조립 라인의 경우 선택된 워크스테이션(CELL)별로 필터링
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty: 
        st.info("현재 처리 대기 중인 데이터가 없습니다.")
        return
    
    # v9.1 스타일의 컬럼 비중 [2.5, 1, 1.5, 1.5, 2, 3] 적용
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_labels = ["업데이트 시간", "구분", "모델명", "품목코드", "시리얼 번호", "공정 상태제어"]
    for col, txt in zip(lh, header_labels): 
        col.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간'])
        lr[1].write(row['CELL'])
        lr[2].write(row['모델'])
        lr[3].write(row['품목코드'])
        lr[4].write(f"`{row['시리얼']}`")
        
        with lr[5]:
            if row['상태'] in ["진 진행 중", "수리 완료(재투입)"]:
                b_ok, b_ng = st.columns(2)
                if b_ok.button(ok_label, key=f"ok_btn_{idx}", type="secondary"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
                if b_ng.button("🚫불량", key=f"ng_btn_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# [6. 페이지별 메인 비즈니스 로직]
# =================================================================

# --- 6-1. 조립 라인 현황 (신규 등록 및 중복 체크) ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 작업 현황</h2>", unsafe_allow_html=True)
    
    # CELL(작업대) 선택 버튼 UI
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell == c else "secondary", use_container_width=True): 
            st.session_state.selected_cell = c; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
            m_choice = st.selectbox("생산 모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
            with st.form("assembly_reg_form"):
                r1, r2 = st.columns(2)
                i_choice = r1.selectbox("품목코드 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델 먼저 선택"])
                s_input = r2.text_input("제품 시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 조립 등록 실행", use_container_width=True, type="primary"):
                    if m_choice != "선택하세요." and s_input:
                        db_p = st.session_state.production_db
                        # [규칙] 시리얼 중복 등록 방지 로직 (제품 1개당 고유 행 보장)
                        if s_input in db_p['시리얼'].values:
                            st.error(f"❌ 오류: 시리얼 '{s_input}'은(는) 이미 시스템에 등록되어 있는 제품입니다.")
                        else:
                            new_data = {
                                '시간': get_now_kst(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_p, pd.DataFrame([new_data])], ignore_index=True)
                            save_to_gsheet(st.session_state.production_db); st.rerun()
    render_realtime_log("조립 라인", "완료")

# --- 6-2. 품질/포장 라인 현황 (입고 승인 로직) ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_step = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 입고 승인 대기 리스트</div>", unsafe_allow_html=True)
        db_ref = st.session_state.production_db
        # 이전 단계가 완료된 제품만 필터링하여 입고 대기 리스트 구성
        wait_items = db_ref[(db_ref['라인'] == prev_step) & (db_ref['상태'] == "완료")]
        
        if not wait_items.empty:
            st.success(f"📦 현재 {len(wait_items)}개의 제품이 입고를 기다리고 있습니다.")
            grid_ui = st.columns(4)
            for i, (idx, row) in enumerate(wait_items.iterrows()):
                if grid_ui[i % 4].button(f"입고: {row['시리얼']}", key=f"btn_wait_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    confirm_entry_dialog()
        else: 
            st.info("이전 공정에서 입고 대기 중인 물량이 없습니다.")
            
    render_realtime_log(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "출고 완료")

# --- 6-3. 통합 리포트 (이전 격자 스타일 복구 버전) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 대시보드 리포트</h2>", unsafe_allow_html=True)
    db_rep = st.session_state.production_db
    
    if not db_rep.empty:
        # 주요 KPI 계산 (1인 1행 기준이므로 단순 카운팅)
        total_qty = len(db_rep)
        done_qty = len(db_rep[(db_rep['라인'] == '포장 라인') & (db_rep['상태'] == '완료')])
        wip_qty = len(db_rep[db_rep['상태'] == '진행 중'])
        ng_qty = len(db_rep[db_rep['상태'].str.contains("불량", na=False)])
        
        met = st.columns(4)
        met[0].metric("총 투입량", f"{total_qty} EA")
        met[1].metric("최종 포장 완료", f"{done_qty} EA")
        met[2].metric("공정 재공(WIP)", f"{wip_qty} EA")
        met[3].metric("누적 불량 발생", f"{ng_qty} 건", delta=ng_qty, delta_color="inverse")
        
        st.divider()
        # [복구] 이전 격자 UI 선호도를 반영한 그래프 디자인
        # 다크 테마를 제거하고, 정수 표기(dtick=1)를 적용한 밝은 격자형 차트입니다.
        rep_c1, rep_c2 = st.columns([1, 2])
        
        with rep_c1:
            loc_data = db_rep.groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(
                loc_data, x='라인', y='수량', color='라인', 
                title="<b>[공정별 제품 현재 위치]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"}
            )
            # 흰색 격자선 및 투명 배경 복구 설정
            fig_bar.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', 
                paper_bgcolor='rgba(0,0,0,0)',
                xaxis_title="공정 라인",
                yaxis_title="수량(EA)"
            )
            # [핵심] Y축 수량 정수 표기 강제 (dtick=1)
            fig_bar.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with rep_c2:
            model_data = db_rep.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(
                model_data, values='수량', names='모델', hole=0.3, 
                title="<b>[전체 생산 모델별 비중]</b>",
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 생산 데이터 통합 테이블</div>", unsafe_allow_html=True)
        st.dataframe(db_rep.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 존재하지 않습니다.")

# --- 6-4. 불량 수리 센터 (현장 수리 처리) ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 및 조치 센터</h2>", unsafe_allow_html=True)
    db_bad = st.session_state.production_db
    bad_items = db_bad[db_bad['상태'] == "불량 처리 중"]
    
    # 상단 요약 현황판
    today_p = datetime.now(KST).strftime('%Y-%m-%d')
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 현재 수리 대기</div><div class='stat-value' style='color:#f44336;'>{len(bad_items)}</div></div>", unsafe_allow_html=True)
    with sc2:
        done_rep = len(db_bad[(db_bad['상태'] == "수리 완료(재투입)") & (db_bad['시간'].astype(str).str.contains(today_p))])
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 수리 완료</div><div class='stat-value' style='color:#28a745;'>{done_rep}</div></div>", unsafe_allow_html=True)

    if bad_items.empty: 
        st.success("✅ 현재 조치 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_items.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']} / 발생: {row['라인']})")
                c_sv, c_av, c_img, c_btn = st.columns([3, 3, 2, 2])
                
                s_val = c_sv.text_input("불량 원인 상세", placeholder="예: 센서 접촉 불량", key=f"bad_s_{idx}")
                a_val = c_av.text_input("수리 조치 사항", placeholder="예: 케이블 재결합", key=f"bad_a_{idx}")
                up_file = c_img.file_uploader("사진 등록", type=['jpg','png','jpeg'], key=f"bad_img_{idx}")
                
                if c_btn.button("✅ 수리 완료", key=f"bad_r_{idx}", use_container_width=True, type="primary"):
                    if s_val and a_val:
                        img_path = ""
                        if up_file:
                            with st.spinner("이미지 업로드 중..."):
                                link = upload_image_to_drive(up_file, f"REPAIR_{row['시리얼']}.jpg")
                                if "http" in link: img_path = f" [사진 확인: {link}]"
                        
                        db_bad.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad.at[idx, '증상'], db_bad.at[idx, '수리'] = s_val, a_val + img_path
                        db_bad.at[idx, '작업자'] = st.session_state.user_id
                        save_to_gsheet(db_bad); st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 분석 및 수리 이력 리포트</h2>", unsafe_allow_html=True)
    db_hist = st.session_state.production_db
    hist_df = db_hist[db_hist['수리'] != ""]
    
    if not hist_df.empty:
        # [복구] 격자선이 강조된 밝은 스타일 그래프
        fig_hist = px.bar(hist_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 불량 수리 건수")
        fig_hist.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        fig_hist.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
        st.plotly_chart(fig_hist, use_container_width=True)
        
        st.markdown("<div class='section-title'>📜 상세 수리 조치 내역 원장</div>", unsafe_allow_html=True)
        st.dataframe(hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("수리 내역이 존재하지 않습니다.")

# --- 6-6. 마스터 관리 (v9.1 UI + v16.7 기능 100% 복구) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 계정 통합 관리</h2>", unsafe_allow_html=True)
    
    # 관리자 인증 필터
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            admin_pw = st.text_input("시스템 관리자 비밀번호 (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if admin_pw == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호가 올바르지 않습니다.")
    else:
        if st.button("🔓 관리 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False; nav_to("조립 라인")

        # [v9.1 디자인] 2열 레이아웃 기준정보 관리
        st.markdown("<div class='section-title'>📋 생산 기준정보 및 데이터 제어</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        
        with m_col1:
            with st.container(border=True):
                st.subheader("모델/품목 코드 등록")
                new_m_name = st.text_input("신규 생산 모델 추가")
                if st.button("모델 등록 실행", use_container_width=True):
                    if new_m_name and new_m_name not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m_name)
                        st.session_state.master_items_dict[new_m_name] = []; st.rerun()
                st.divider()
                sel_m_target = st.selectbox("품목을 등록할 모델 선택", st.session_state.master_models)
                new_item_code = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록 실행", use_container_width=True):
                    if new_item_code and new_item_code not in st.session_state.master_items_dict[sel_m_target]:
                        st.session_state.master_items_dict[sel_m_target].append(new_item_code); st.rerun()

        with m_col2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 마이그레이션")
                # CSV 백업 다운로드
                raw_csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 생산 데이터 CSV 다운로드", raw_csv, f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # CSV 데이터 복구 및 병합
                up_csv = st.file_uploader("복구용 CSV 파일 업로드", type="csv")
                if up_csv and st.button("📤 데이터 병합 업데이트", use_container_width=True):
                    try:
                        import_df = pd.read_csv(up_csv)
                        merged_db = pd.concat([st.session_state.production_db, import_df], ignore_index=True)
                        # 중복된 시리얼은 가장 최근 데이터만 남기고 제거
                        st.session_state.production_db = merged_db.drop_duplicates(subset=['시리얼'], keep='last')
                        save_to_gsheet(st.session_state.production_db); st.rerun()
                    except: st.error("파일 구조를 확인해 주세요.")

        # [v9.1 디자인] 사용자 계정 관리 섹션
        st.divider()
        st.markdown("<div class='section-title'>👤 시스템 사용자 계정 관리 (ID/PW 권한 설정)</div>", unsafe_allow_html=True)
        u_col1, u_col2, u_col3 = st.columns([3, 3, 2])
        reg_uid = u_col1.text_input("신규 생성 ID")
        reg_upw = u_col2.text_input("신규 생성 PW", type="password")
        reg_urole = u_col3.selectbox("권한 설정", ["user", "admin"])
        
        if st.button("계정 생성 및 정보 업데이트", use_container_width=True):
            if reg_uid and reg_upw:
                st.session_state.user_db[reg_uid] = {"pw": reg_upw, "role": reg_urole}
                st.success(f"사용자 '{reg_uid}' 정보가 업데이트되었습니다."); st.rerun()
        
        with st.expander("현재 시스템 등록 계정 목록 보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        # 시스템 초기화 도구
        if st.button("⚠️ 시스템 전체 실적 데이터 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v16.9 배포 버전 종료 ]
# =================================================================
