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
    page_title="생산 통합 관리 시스템 v17.0",
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

# [CSS 스타일 커스텀] - v9.1 UI 기반 설정
st.markdown("""
    <style>
    /* 메인 컨테이너 너비 제한 (v9.1 스타일 1200px) */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 스타일: 현장 작업 편의를 위한 패딩 설정 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
        border-radius: 5px;
    }
    
    /* 제목 중앙 정렬 및 폰트 */
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
    
    /* 상태 표시 텍스트 색상 */
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    
    /* 대시보드 상단 통계 지표 박스 */
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
    
    /* 긴급 알림 배너 */
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
        # ttl=0 설정을 통해 캐시 없이 항상 시트의 최신 정보를 가져옵니다.
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 시리얼 번호가 숫자로 인식되어 소수점(.0)이 붙는 현상을 방지합니다.
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터 로드 실패 시 컬럼 구조만 갖춘 빈 데이터프레임 반환
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """업데이트된 데이터프레임을 구글 시트에 저장하고 캐시를 초기화합니다."""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """불량 수리 사진을 구글 드라이브 지정 폴더에 업로드하고 링크를 반환합니다."""
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "❌ 폴더 ID 설정이 누락되었습니다."

        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 사진 업로드 실패: {str(e)}"

# =================================================================
# [3. 세션 상태(Session State) 관리]
# =================================================================

# 1) 생산 DB 세션 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 2) 사용자 계정 정보 정의
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

# 3) UI 제어 상태
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 4) 생산 마스터 기준 정보
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }

# 5) 내비게이션 상태
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [4. 로그인 및 사이드바 내비게이션] - v9.1 스타일
# =================================================================

if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)", placeholder="아이디 입력")
            upw = st.text_input("비밀번호(PW)", type="password", placeholder="비밀번호 입력")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: 
                    st.error("❌ 로그인 정보가 올바르지 않습니다.")
    st.stop()

# 사이드바 구성
st.sidebar.title(f"🏭 {st.session_state.user_id} 작업자")
if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def navigate_to(page_name): 
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한 필터링
allowed_menus = ROLES.get(st.session_state.user_role, [])

# v9.1 스타일 메뉴 배치
if "조립 라인" in allowed_menus:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): navigate_to("조립 라인")
if "검사 라인" in allowed_menus:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): navigate_to("검사 라인")
if "포장 라인" in allowed_menus:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): navigate_to("포장 라인")
if "리포트" in allowed_menus:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): navigate_to("리포트")

st.sidebar.divider()
if "불량 공정" in allowed_menus:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): navigate_to("불량 공정")
if "수리 리포트" in allowed_menus:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): navigate_to("수리 리포트")

if st.session_state.user_role == "admin" or "마스터 관리" in allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): navigate_to("마스터 관리")

# 불량 알림 배너 (상시 노출)
bad_count_realtime = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_count_realtime > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 알림: 수리 대기 중인 불량 제품이 {bad_count_realtime}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# [5. 공용 데이터 로직 - 1제품 1행 업데이트]
# =================================================================

@st.dialog("📦 공정 단계 전환 확인")
def confirm_update_dialog():
    """시리얼 번호 기준으로 기존 데이터를 업데이트(Update)하는 로직입니다."""
    st.warning(f"시리얼 번호 [ {st.session_state.confirm_target} ]")
    st.markdown(f"**이동 대상 공정:** {st.session_state.current_line}")
    c1, c2 = st.columns(2)
    if c1.button("✅ 입고 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [핵심] 1인 1행 유지를 위해 기존 행을 찾아 업데이트
        found_idx = db[db['시리얼'] == st.session_state.confirm_target].index
        if not found_idx.empty:
            target_idx = found_idx[0]
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
    """v9.1 디자인의 컬럼 비중을 유지한 실시간 로그 렌더링 함수입니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그 현황</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    display_df = db[db['라인'] == line_name]
    
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        display_df = display_df[display_df['CELL'] == st.session_state.selected_cell]
    
    if display_df.empty: 
        st.info("현재 처리 중인 데이터가 없습니다.")
        return
    
    # v9.1 컬럼 비중 [2.5, 1, 1.5, 1.5, 2, 3]
    header_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_labels = ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]
    for col, txt in zip(header_cols, header_labels): 
        col.write(f"**{txt}**")
    
    for idx, row in display_df.sort_values('시간', ascending=False).iterrows():
        row_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        row_cols[0].write(row['시간'])
        row_cols[1].write(row['CELL'])
        row_cols[2].write(row['모델'])
        row_cols[3].write(row['품목코드'])
        row_cols[4].write(f"`{row['시리얼']}`")
        
        with row_cols[5]:
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
# [6. 페이지별 메인 렌더링 로직]
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    
    # CELL 선택 버튼 (v9.1 스타일)
    cell_names = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_cols = st.columns(len(cell_names))
    for i, name in enumerate(cell_names):
        if btn_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 생산 등록")
            sel_m = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"asm_m_{st.session_state.selected_cell}")
            with st.form("assembly_form_v17"):
                c1, c2 = st.columns(2)
                sel_i = c1.selectbox("품목 선택", st.session_state.master_items_dict.get(sel_m, []) if sel_m!="선택하세요." else ["모델 먼저 선택"])
                input_sn = c2.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 조립 등록 실행", use_container_width=True, type="primary"):
                    if sel_m != "선택하세요." and input_sn:
                        db_p = st.session_state.production_db
                        # [규칙] 시리얼 중복 체크
                        if input_sn in db_p['시리얼'].values:
                            st.error(f"❌ 이미 등록된 시리얼 번호({input_sn})입니다.")
                        else:
                            new_data = {
                                '시간': get_now_kst(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': sel_m, '품목코드': sel_i, '시리얼': input_sn, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_p, pd.DataFrame([new_data])], ignore_index=True)
                            save_to_gsheet(st.session_state.production_db); st.rerun()
    render_realtime_log_v9("조립 라인", "완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title_text = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_step_name = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title_text}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 공정 입고 대기 목록</div>", unsafe_allow_html=True)
        db_ref = st.session_state.production_db
        # 이전 단계가 완료된 제품만 필터링
        wait_items_df = db_ref[(db_ref['라인'] == prev_step_name) & (db_ref['상태'] == "완료")]
        
        if not wait_items_df.empty:
            st.success(f"현재 {len(wait_items_df)}개의 제품이 입고 대기 중입니다.")
            grid_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_items_df.iterrows()):
                if grid_cols[i % 4].button(f"입고: {row['시리얼']}", key=f"btn_in_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    confirm_update_dialog()
        else: 
            st.info("이전 공정에서 입고 대기 중인 물량이 없습니다.")
            
    render_realtime_log_v9(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "출하 포장")

# --- 6-3. 통합 리포트 (막대 그래프 넓게, 도넛 그래프 작게 조정) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 통합 생산 리포트</h2>", unsafe_allow_html=True)
    db_report = st.session_state.production_db
    
    if not db_report.empty:
        # 주요 생산 지표
        t_q, d_q, w_q = len(db_report), len(db_report[(db_report['라인'] == '포장 라인') & (db_report['상태'] == '완료')]), len(db_report[db_report['상태'] == '진행 중'])
        
        met_cols = st.columns(4)
        met_cols[0].metric("총 투입량", f"{t_q} EA")
        met_cols[1].metric("최종 생산 완료", f"{d_q} EA")
        met_cols[2].metric("현재 재공(WIP)", f"{w_q} EA")
        met_cols[3].metric("가동 상태", "정상 운영 중")
        
        st.divider()
        # [레이아웃 수정] 막대 그래프를 좌우로 넓게(1.8), 도넛 그래프를 아담하게(1.2)
        chart_l, chart_r = st.columns([1.8, 1.2])
        
        with chart_l:
            # 1) 공정별 제품 위치 바 차트 (색상 매핑 및 정수 표기)
            pos_df = db_report.groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(
                pos_df, x='라인', y='수량', color='라인', 
                title="<b>[공정별 제품 분포 현황]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_white"
            )
            fig_bar.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', 
                paper_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=50, b=20)
            )
            # Y축 정수 표기 강제
            fig_bar.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with chart_r:
            # 2) 모델별 비중 파이 차트 (크기 축소: height 350)
            model_df = db_report.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(
                model_df, values='수량', names='모델', hole=0.45, 
                title="<b>[모델별 생산 비중]</b>",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            # [축소 설정] height를 350으로 낮추고 마진을 늘려 작게 보이게 함
            fig_pie.update_layout(
                height=350, 
                margin=dict(l=40, r=40, t=60, b=40),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 생산 데이터 통합 원장</div>", unsafe_allow_html=True)
        st.dataframe(db_report.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 없습니다.")

# --- 6-4. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 및 조치 관리</h2>", unsafe_allow_html=True)
    db_bad_process = st.session_state.production_db
    bad_items_list = db_bad_process[db_bad_process['상태'] == "불량 처리 중"]
    
    # 수리 현황 바
    s_c1, s_c2 = st.columns(2)
    with s_c1: st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 현재 수리 대기</div><div class='stat-value' style='color:#f44336;'>{len(bad_items_list)}</div></div>", unsafe_allow_html=True)
    with s_c2:
        d_today_prefix = datetime.now(KST).strftime('%Y-%m-%d')
        rep_done_today = len(db_bad_process[(db_bad_process['상태'] == "수리 완료(재투입)") & (db_bad_process['시간'].astype(str).str.contains(d_today_prefix))])
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 수리 완료</div><div class='stat-value' style='color:#28a745;'>{rep_done_today}</div></div>", unsafe_allow_html=True)

    if bad_items_list.empty: 
        st.success("✅ 조치 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_items_list.iterrows():
            with st.container(border=True):
                st.write(f"**제품 시리얼: {row['시리얼']}** ({row['모델']} / 발생공정: {row['라인']})")
                c_s, c_a, c_i, c_b = st.columns([3, 3, 2, 2])
                
                bad_cause = c_s.text_input("불량 원인", placeholder="예: 조립 누락", key=f"cs_{idx}")
                bad_action = c_a.text_input("수리 내용", placeholder="예: 재체결 실시", key=f"ac_{idx}")
                up_img_file = c_i.file_uploader("이미지", type=['jpg','png','jpeg'], key=f"ui_{idx}")
                
                if c_b.button("✅ 수리 확정", key=f"bf_{idx}", use_container_width=True, type="primary"):
                    if bad_cause and bad_action:
                        drive_path = ""
                        if up_img_file:
                            with st.spinner("이미지 저장 중..."):
                                drive_res = upload_image_to_drive(up_img_file, f"REP_{row['시리얼']}.jpg")
                                if "http" in drive_res: drive_path = f" [사진 확인: {drive_res}]"
                        
                        db_bad_process.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad_process.at[idx, '증상'], db_bad_process.at[idx, '수리'] = bad_cause, bad_action + drive_path
                        db_bad_process.at[idx, '작업자'] = st.session_state.user_id
                        save_to_gsheet(db_bad_process); st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 분석 데이터 리포트</h2>", unsafe_allow_html=True)
    db_h = st.session_state.production_db
    h_df = db_h[db_h['수리'] != ""]
    
    if not h_df.empty:
        # 수리 이력 대시보드 (레이아웃 동일하게 [1.8, 1.2])
        rh_l, rh_r = st.columns([1.8, 1.2])
        with rh_l:
            fig_h_bar = px.bar(h_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 불량 발생 건수", template="plotly_white")
            fig_h_bar.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_h_bar, use_container_width=True)
        with rh_r:
            fig_h_pie = px.pie(h_df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 불량 비중")
            fig_h_pie.update_layout(height=350)
            st.plotly_chart(fig_h_pie, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 불량 수리 조치 데이터</div>", unsafe_allow_html=True)
        st.dataframe(h_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("기록된 수리 내역이 존재하지 않습니다.")

# --- 6-6. 마스터 관리 ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 기준 데이터 및 계정 관리</h2>", unsafe_allow_html=True)
    
    # 관리자 인증
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth_form_v17"):
            master_pw = st.text_input("시스템 마스터 PW (admin1234)", type="password")
            if st.form_submit_button("마스터 인증하기"):
                if master_pw == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호 불일치")
    else:
        if st.button("🔓 관리자 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False; navigate_to("조립 라인")

        # 섹션 1: 기준정보 관리
        st.markdown("<div class='section-title'>📋 생산 기준정보 및 DB 연동 제어</div>", unsafe_allow_html=True)
        m_c1, m_c2 = st.columns(2)
        
        with m_c1:
            with st.container(border=True):
                st.subheader("모델/품목 신규 등록")
                new_m_input = st.text_input("신규 생산 모델 추가")
                if st.button("모델 등록 확정", use_container_width=True):
                    if new_m_input and new_m_input not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m_input)
                        st.session_state.master_items_dict[new_m_input] = []; st.rerun()
                st.divider()
                sel_m_reg = st.selectbox("품목 등록용 모델 선택", st.session_state.master_models)
                new_i_input = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록 확정", use_container_width=True):
                    if new_i_input and new_i_input not in st.session_state.master_items_dict[sel_m_reg]:
                        st.session_state.master_items_dict[sel_m_reg].append(new_i_input); st.rerun()

        with m_c2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 복구 로드")
                # CSV 백업
                raw_data_csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 생산 데이터 CSV 백업", raw_data_csv, f"PMS_Backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # 데이터 복구
                load_file = st.file_uploader("복구용 CSV 업로드", type="csv")
                if load_file and st.button("📤 데이터 로드(병합) 실행", use_container_width=True):
                    try:
                        imp_df = pd.read_csv(load_file)
                        merged_df_res = pd.concat([st.session_state.production_db, imp_df], ignore_index=True)
                        st.session_state.production_db = merged_df_res.drop_duplicates(subset=['시리얼'], keep='last')
                        save_to_gsheet(st.session_state.production_db); st.rerun()
                    except: st.error("파일 데이터 구조를 확인하세요.")

        # 섹션 2: 계정 관리
        st.divider()
        st.markdown("<div class='section-title'>👤 시스템 계정 및 작업자 권한 관리</div>", unsafe_allow_html=True)
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        reg_id = u_c1.text_input("작업자 ID")
        reg_pw = u_c2.text_input("비밀번호", type="password")
        reg_rl = u_c3.selectbox("권한 그룹", ["user", "admin"])
        
        if st.button("계정 생성/정보 업데이트", use_container_width=True):
            if reg_id and reg_pw:
                st.session_state.user_db[reg_id] = {"pw": reg_pw, "role": reg_rl}
                st.success(f"사용자 '{reg_id}' 정보가 성공적으로 반영되었습니다."); st.rerun()
        
        with st.expander("현재 시스템 등록 계정 전체보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        # 공장 초기화
        if st.button("⚠️ 시스템 전체 데이터 초기화 (영구 삭제)", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v17.0 배포 버전 종료 ]
# =================================================================
