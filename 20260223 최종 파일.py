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
    page_title="생산 통합 관리 시스템 v17.1",
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

# [CSS 스타일 커스텀] - v9.1 UI 기반 설정 유지
st.markdown("""
    <style>
    /* 메인 컨테이너 너비 제한 (v9.1 스타일 1200px로 안정감 확보) */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 스타일: 현장 작업 편의를 위해 패딩 및 너비 조절 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
        border-radius: 5px;
    }
    
    /* 제목 중앙 정렬 및 굵게 */
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
    
    /* 상태 표시 텍스트 강조 색상 */
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    
    /* 대시보드 상단 요약 통계 박스 */
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
    
    /* 긴급 불량 알림 배너 스타일 */
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
# [2. 핵심 유틸리티 함수 - 데이터 연동 및 관리]
# =================================================================

def get_now_kst():
    """현재 한국 표준시를 'YYYY-MM-DD HH:MM:SS' 형식으로 반환합니다."""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 커넥션 객체 초기화
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """구글 시트로부터 실시간 생산 데이터를 로드하고 전처리합니다."""
    try:
        # ttl=0 설정을 통해 캐시 없이 매번 시트의 실제 데이터를 가져옵니다.
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 시리얼 번호가 숫자로 인식되어 소수점(.0)이 붙는 현상 방지
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터가 없는 초기 상태이거나 로드 실패 시 빈 프레임 반환
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """업데이트된 데이터를 구글 시트에 저장하고 Streamlit 캐시를 비웁니다."""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """수리 조치 사진을 구글 드라이브의 지정된 폴더에 업로드하고 링크를 반환합니다."""
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 드라이브 API 서비스 구축
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 폴더 설정이 누락되었습니다."

        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 드라이브 파일 생성 실행
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 이미지 업로드 실패: {str(e)}"

# =================================================================
# [3. 세션 상태(Session State) 관리]
# =================================================================

# 1) 생산 실적 DB 초기 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 2) 계정 정보 세션 관리
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

# 3) UI 제어용 상태값
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 4) 생산 마스터 기준 정보 설정
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }

# 5) 공정 내비게이션 및 캐시
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [4. 로그인 인터페이스 및 사이드바 내비게이션]
# =================================================================

if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)", placeholder="아이디를 입력하세요")
            upw = st.text_input("비밀번호(PW)", type="password", placeholder="비밀번호를 입력하세요")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    # 소속 그룹의 첫 번째 메뉴로 이동
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 로그인 정보가 정확하지 않습니다.")
    st.stop()

# 사이드바 구성
st.sidebar.title(f"🏭 {st.session_state.user_id} 작업자")
if st.sidebar.button("🚪 시스템 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def navigate_to(page_name): 
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한별 노출 메뉴
allowed_menus = ROLES.get(st.session_state.user_role, [])

# v9.1 스타일 내비게이션 버튼 (조립/검사/포장/리포트)
if "조립 라인" in allowed_menus:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): navigate_to("조립 라인")
if "검사 라인" in allowed_menus:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): navigate_to("검사 라인")
if "포장 라인" in allowed_menus:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): navigate_to("포장 라인")
if "리포트" in allowed_menus:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): navigate_to("리포트")

st.sidebar.divider()
# 사후 관리 메뉴 (수리 센터/리포트)
if "불량 공정" in allowed_menus:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): navigate_to("불량 공정")
if "수리 리포트" in allowed_menus:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): navigate_to("수리 리포트")

if st.session_state.user_role == "admin" or "마스터 관리" in allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): navigate_to("마스터 관리")

# 불량 알림 실시간 표시
realtime_bad = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if realtime_bad > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 불량 제품이 {realtime_bad}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# [5. 공용 비즈니스 로직 - 1인 1행 데이터 업데이트]
# =================================================================

@st.dialog("📦 공정 단계 전환 확인")
def confirm_update_dialog():
    """시리얼 번호 기준으로 기존 데이터를 업데이트(Update)하는 로직입니다."""
    st.warning(f"시리얼 번호 [ {st.session_state.confirm_target} ]")
    st.markdown(f"**이동 대상 공정:** {st.session_state.current_line}")
    c1, c2 = st.columns(2)
    if c1.button("✅ 입고 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심] 1인 1행 유지를 위해 기존 기록을 찾아 업데이트
        idx_match = db[db['시리얼'] == st.session_state.confirm_target].index
        if not idx_match.empty:
            target_idx = idx_match[0]
            db.at[target_idx, '시간'] = get_now_kst()
            db.at[target_idx, '라인'] = st.session_state.current_line
            db.at[target_idx, '상태'] = '진행 중'
            db.at[target_idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
        st.session_state.confirm_target = None
        st.rerun()
    if c2.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def render_realtime_log_v9(line_name, ok_label="완료 처리"):
    """v9.1 디자인의 가독성 좋은 로그 렌더링 함수입니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그 현황</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    display_df = db[db['라인'] == line_name]
    
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        display_df = display_df[display_df['CELL'] == st.session_state.selected_cell]
    
    if display_df.empty: 
        st.info("현재 처리 중인 제품 데이터가 존재하지 않습니다.")
        return
    
    # v9.1 기준 컬럼 비중: [2.5, 1, 1.5, 1.5, 2, 3]
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    labels = ["업데이트 시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]
    for col, txt in zip(h_cols, labels): 
        col.write(f"**{txt}**")
    
    for idx, row in display_df.sort_values('시간', ascending=False).iterrows():
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        r_cols[0].write(row['시간'])
        r_cols[1].write(row['CELL'])
        r_cols[2].write(row['모델'])
        r_cols[3].write(row['품목코드'])
        r_cols[4].write(f"`{row['시리얼']}`")
        
        with r_cols[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_ok, b_ng = st.columns(2)
                if b_ok.button(ok_label, key=f"ok_{idx}", type="secondary"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
                if b_ng.button("🚫불량", key=f"ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 불량 분석 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# [6. 세부 페이지별 메인 비즈니스 로직]
# =================================================================

# --- 6-1. 조립 라인 현황 (신규 등록 및 중복 체크) ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    
    # CELL 선택 인터페이스 (v9.1 스타일)
    cell_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_btn_cols = st.columns(len(cell_list))
    for i, c_name in enumerate(cell_list):
        if c_btn_cols[i].button(c_name, type="primary" if st.session_state.selected_cell == c_name else "secondary"): 
            st.session_state.selected_cell = c_name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
            choice_m = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
            with st.form("assembly_form_v17_1"):
                form_c1, form_c2 = st.columns(2)
                choice_i = form_c1.selectbox("품목 선택", st.session_state.master_items_dict.get(choice_m, []) if choice_m!="선택하세요." else ["모델 선택 필요"])
                form_sn = form_c2.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 조립 등록 실행", use_container_width=True, type="primary"):
                    if choice_m != "선택하세요." and form_sn:
                        db_p = st.session_state.production_db
                        # [규칙] 시리얼 중복 체크
                        if form_sn in db_p['시리얼'].values:
                            st.error(f"❌ 이미 등록된 시리얼 번호({form_sn})입니다.")
                        else:
                            new_row = {
                                '시간': get_now_kst(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': choice_m, '품목코드': choice_i, '시리얼': form_sn, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_p, pd.DataFrame([new_row])], ignore_index=True)
                            save_to_gsheet(st.session_state.production_db); st.rerun()
    render_realtime_log_v9("조립 라인", "완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    lt_text = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    ps_name = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{lt_text}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 공정 입고 대기 목록</div>", unsafe_allow_html=True)
        db_ref = st.session_state.production_db
        # 이전 단계가 '완료'된 항목만 노출
        wait_df = db_ref[(db_ref['라인'] == ps_name) & (db_ref['상태'] == "완료")]
        
        if not wait_df.empty:
            st.success(f"현재 {len(wait_df)}개의 제품이 입고 대기 중입니다.")
            grid_c = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if grid_c[i % 4].button(f"입고: {row['시리얼']}", key=f"btn_wait_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    confirm_update_dialog()
        else: 
            st.info("이전 공정에서 입고 대기 중인 물량이 없습니다.")
            
    render_realtime_log_v9(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "포장 완료")

# --- 6-3. 통합 리포트 (막대 확장 / 도넛 축소 레이아웃) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 통합 생산 리포트</h2>", unsafe_allow_html=True)
    db_rep = st.session_state.production_db
    
    if not db_rep.empty:
        # 생산 핵심 지표
        t_tot = len(db_rep)
        t_fin = len(db_rep[(db_rep['라인'] == '포장 라인') & (db_rep['상태'] == '완료')])
        t_wip = len(db_rep[db_rep['상태'] == '진행 중'])
        
        m_cols = st.columns(4)
        m_cols[0].metric("총 투입량", f"{t_tot} EA")
        m_cols[1].metric("최종 생산 실적", f"{t_fin} EA")
        m_cols[2].metric("현재 재공(WIP)", f"{t_wip} EA")
        m_cols[3].metric("운영 상태", "정상")
        
        st.divider()
        # [레이아웃] 막대 그래프 넓게(1.8), 도넛 그래프 작게(1.2)
        cl_left, cl_right = st.columns([1.8, 1.2])
        
        with cl_left:
            # 1) 공정별 위치 바 차트 (색상 지정 및 정수 표기)
            df_pos = db_rep.groupby('라인').size().reset_index(name='수량')
            fig_b = px.bar(
                df_pos, x='라인', y='수량', color='라인', 
                title="<b>[공정별 제품 분포]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_white"
            )
            fig_b.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            # Y축 정수 고정
            fig_b.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_b, use_container_width=True)
            
        with cl_right:
            # 2) 모델별 파이 차트 (물리적 크기 축소)
            df_mod = db_rep.groupby('모델').size().reset_index(name='수량')
            fig_p = px.pie(df_mod, values='수량', names='모델', hole=0.45, title="<b>[모델별 생산 비중]</b>")
            fig_p.update_layout(height=350, margin=dict(l=40, r=40, t=60, b=40))
            st.plotly_chart(fig_p, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 생산 데이터 통합 원장</div>", unsafe_allow_html=True)
        st.dataframe(db_rep.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 없습니다.")

# --- 6-4. 불량 수리 센터 [요청하신 레이아웃 개편] ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 및 조치 관리</h2>", unsafe_allow_html=True)
    db_bad_p = st.session_state.production_db
    list_bad = db_bad_p[db_bad_p['상태'] == "불량 처리 중"]
    
    # 상단 수리 현황
    sb1, sb2 = st.columns(2)
    with sb1: st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 현재 수리 대기</div><div class='stat-value' style='color:#f44336;'>{len(list_bad)}</div></div>", unsafe_allow_html=True)
    with sb2:
        today_rep_pre = datetime.now(KST).strftime('%Y-%m-%d')
        rep_count_today = len(db_bad_p[(db_bad_p['상태'] == "수리 완료(재투입)") & (db_bad_p['시간'].astype(str).str.contains(today_rep_pre))])
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 수리 완료</div><div class='stat-value' style='color:#28a745;'>{rep_count_today}</div></div>", unsafe_allow_html=True)

    if list_bad.empty: 
        st.success("✅ 현재 조치 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in list_bad.iterrows():
            with st.container(border=True):
                st.markdown(f"**제품 시리얼: `{row['시리얼']}`** ({row['모델']} / 발생공정: {row['라인']})")
                
                # [개편된 레이아웃]
                # 1행: 원인과 조치 내용
                r1_c1, r1_c2 = st.columns(2)
                val_cause = r1_c1.text_input("⚠️ 불량 원인", placeholder="불량 발생 원인 입력", key=f"cs_{idx}")
                val_action = r1_c2.text_input("🛠️ 수리 조치", placeholder="수리 및 조치 내용 입력", key=f"ac_{idx}")
                
                # 2행: 이미지 등록 및 확정 버튼 (원인/조치 바로 밑)
                r2_c1, r2_c2 = st.columns([3, 1])
                val_img = r2_c1.file_uploader("📸 수리 증빙 사진 등록", type=['jpg','png','jpeg'], key=f"ui_{idx}")
                
                # 버튼을 수직 중앙 정렬하기 위한 여백
                r2_c2.write("") 
                if r2_c2.button("✅ 수리 확정", key=f"bf_{idx}", type="primary", use_container_width=True):
                    if val_cause and val_action:
                        p_path = ""
                        if val_img:
                            with st.spinner("이미지 업로드 중..."):
                                d_res = upload_image_to_drive(val_img, f"REP_{row['시리얼']}.jpg")
                                if "http" in d_res: p_path = f" [사진: {d_res}]"
                        
                        db_bad_p.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad_p.at[idx, '증상'], db_bad_p.at[idx, '수리'] = val_cause, val_action + p_path
                        db_bad_p.at[idx, '작업자'] = st.session_state.user_id
                        save_to_gsheet(db_bad_p); st.rerun()
                    else:
                        st.error("불량 원인과 수리 내용을 모두 입력해야 확정이 가능합니다.")

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 분석 데이터 리포트</h2>", unsafe_allow_html=True)
    db_hist = st.session_state.production_db
    df_h = db_hist[db_hist['수리'] != ""]
    
    if not df_h.empty:
        # 리포트 차트 (1.8:1.2 비율 적용)
        hl_c, hr_c = st.columns([1.8, 1.2])
        with hl_c:
            fig_h_b = px.bar(df_h.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 불량 수리 빈도", template="plotly_white")
            fig_h_b.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_h_b, use_container_width=True)
        with hr_c:
            fig_h_p = px.pie(df_h.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 불량 비중")
            fig_h_p.update_layout(height=350)
            st.plotly_chart(fig_h_p, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 불량 수리 조치 데이터</div>", unsafe_allow_html=True)
        st.dataframe(df_h[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("기록된 수리 내역이 존재하지 않습니다.")

# --- 6-6. 마스터 관리 ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 기준 데이터 및 계정 관리</h2>", unsafe_allow_html=True)
    
    # 관리자 인증 필터
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth_v17_1"):
            p_master = st.text_input("마스터 비밀번호 (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if p_master == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호 불일치")
    else:
        if st.button("🔓 관리자 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False; navigate_to("조립 라인")

        st.markdown("<div class='section-title'>📋 생산 기준정보 및 DB 연동 제어</div>", unsafe_allow_html=True)
        m_col1, m_col2 = st.columns(2)
        
        with m_col1:
            with st.container(border=True):
                st.subheader("모델/품목 신규 등록")
                in_new_m = st.text_input("신규 모델명 추가")
                if st.button("모델 등록 확정", use_container_width=True):
                    if in_new_m and in_new_m not in st.session_state.master_models:
                        st.session_state.master_models.append(in_new_m)
                        st.session_state.master_items_dict[in_new_m] = []; st.rerun()
                st.divider()
                in_sel_m = st.selectbox("품목용 모델 선택", st.session_state.master_models)
                in_new_i = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록 확정", use_container_width=True):
                    if in_new_i and in_new_i not in st.session_state.master_items_dict[in_sel_m]:
                        st.session_state.master_items_dict[in_sel_m].append(in_new_i); st.rerun()

        with m_col2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 복구")
                csv_b = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 생산 데이터 CSV 백업", csv_b, f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                f_load = st.file_uploader("복구용 CSV 선택", type="csv")
                if f_load and st.button("📤 데이터 병합 업데이트 실행", use_container_width=True):
                    try:
                        df_imp = pd.read_csv(f_load)
                        df_merged = pd.concat([st.session_state.production_db, df_imp], ignore_index=True)
                        st.session_state.production_db = df_merged.drop_duplicates(subset=['시리얼'], keep='last')
                        save_to_gsheet(st.session_state.production_db); st.rerun()
                    except: st.error("파일 구조를 확인하세요.")

        st.divider()
        st.markdown("<div class='section-title'>👤 사용자 계정 및 권한 관리</div>", unsafe_allow_html=True)
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        id_reg = u_c1.text_input("ID")
        pw_reg = u_c2.text_input("PW", type="password")
        rl_reg = u_c3.selectbox("권한", ["user", "admin"])
        
        if st.button("계정 생성/정보 수정", use_container_width=True):
            if id_reg and pw_reg:
                st.session_state.user_db[id_reg] = {"pw": pw_reg, "role": rl_reg}
                st.success(f"사용자 '{id_reg}' 정보 반영 완료"); st.rerun()
        
        with st.expander("현재 계정 리스트 확인"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        if st.button("⚠️ 시스템 전체 실적 데이터 삭제", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v17.1 배포 버전 종료 ]
# =================================================================

