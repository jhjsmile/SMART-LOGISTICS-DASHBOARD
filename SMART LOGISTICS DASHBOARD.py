# -*- coding: utf-8 -*-
"""
=================================================================
프로그램명: 생산 통합 관리 시스템 (Integrated Manufacturing Execution System)
버전: v20.0 (Ultra-Expanded Edition)
최종 수정일: 2024-05-22
개발 목적: 
  1. 조립-검사-포장 전 공정의 실시간 데이터 트래킹
  2. 구글 시트 및 드라이브 연동을 통한 데이터 영구 보존
  3. 품목코드 및 시리얼 기반의 유일성(Uniqueness) 보장
  4. 현장 작업 편의를 위한 슬림 UI 및 자동 초기화 로직 구현
=================================================================
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import io
import time
import os

# 구글 API 인증 및 드라이브 연동을 위한 라이브러리군
# 수리 공정에서 촬영한 증빙 사진을 클라우드에 업로드하기 위해 필수적으로 사용됩니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# [PART 1] 시스템 전역 설정 및 스타일 정의 (Detailed CSS)
# =================================================================

# 애플리케이션의 기본 페이지 구성을 수행합니다.
# 현장의 넓은 모니터 환경을 고려하여 wide 레이아웃을 채택합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v20.0",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

def apply_custom_style():
    """
    현장 시인성 및 버튼 슬림화를 위한 초정밀 CSS 스타일을 정의합니다.
    버튼이 과도하게 커보이는 문제를 해결하기 위해 패딩과 폰트 크기를 조절합니다.
    """
    st.markdown("""
        <style>
        /* 1. 기본 폰트 및 앱 컨테이너 설정 */
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700;900&display=swap');
        
        html, body, [class*="css"]  {
            font-family: 'Noto Sans KR', sans-serif;
        }
        
        .stApp {
            max-width: 1300px;
            margin: 0 auto;
            background-color: #fcfcfc;
        }

        /* 2. 버튼 슬림화 및 조작성 강화 (핵심 수정) */
        /* 패딩을 줄여 높이를 낮추고, 폰트 크기를 최적화하여 버튼이 콤팩트하게 보이도록 합니다. */
        div.stButton > button {
            margin-top: 2px !important;
            margin-bottom: 2px !important;
            padding: 4px 8px !important;
            width: 100%;
            height: auto !important;
            min-height: 32px !important;
            font-weight: 700 !important;
            font-size: 0.9em !important;
            border-radius: 6px !important;
            border: 1px solid #dfe6e9 !important;
            background-color: #ffffff !important;
            color: #2d3436 !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
            transition: all 0.2s ease-in-out !important;
        }
        
        div.stButton > button:hover {
            border-color: #0984e3 !important;
            color: #0984e3 !important;
            background-color: #f1f9ff !important;
        }
        
        div.stButton > button:active {
            transform: translateY(1px);
            background-color: #e1f0ff !important;
        }

        /* 3. 섹션 및 텍스트 스타일 정의 */
        .centered-title {
            text-align: center;
            font-weight: 900;
            margin: 20px 0 30px 0;
            color: #1e272e;
            font-size: 2.2em;
            letter-spacing: -1px;
        }
        
        .section-header {
            font-size: 1.3em;
            font-weight: 800;
            color: #2d3436;
            margin-bottom: 15px;
            padding-left: 10px;
            border-left: 5px solid #0984e3;
        }

        /* 4. 긴급 알림 배너 스타일 */
        .alarm-banner {
            background-color: #fff5f5;
            color: #d63031;
            padding: 15px 20px;
            border-radius: 10px;
            border: 1px solid #ff7675;
            font-weight: 700;
            margin-bottom: 20px;
            text-align: center;
            font-size: 1.1em;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }

        /* 5. 대시보드 KPI 카드 스타일 */
        .stat-card {
            background-color: #ffffff;
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            border: 1px solid #f1f2f6;
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
            margin-bottom: 15px;
        }
        
        .stat-label {
            font-size: 0.95em;
            color: #636e72;
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        .stat-value {
            font-size: 2.4em;
            color: #0984e3;
            font-weight: 900;
        }
        
        .stat-unit {
            font-size: 0.4em;
            color: #b2bec3;
            margin-left: 5px;
        }

        /* 6. 데이터프레임 및 테이블 가독성 개선 */
        .stDataFrame {
            border: 1px solid #f1f2f6;
            border-radius: 10px;
        }
        
        /* 사이드바 메뉴 간격 조정 */
        [data-testid="stSidebarNav"] {
            padding-top: 20px;
        }
        </style>
        """, unsafe_allow_html=True)

# 스타일 즉시 적용
apply_custom_style()

# =================================================================
# [PART 2] 권한(Role) 및 계정 보안 설정
# =================================================================

# 시스템에서 사용하는 모든 메뉴와 역할별 접근 권한을 정의합니다.
# 권한이 없는 작업자에게는 해당 메뉴가 사이드바에서 노출되지 않습니다.
# line4 작업자는 'repair_team' 권한을 사용합니다.
ROLE_CONFIG = {
    "master": {
        "menus": ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"],
        "desc": "시스템 전체 관리자"
    },
    "control_tower": {
        "menus": ["생산 리포트", "수리 리포트", "마스터 관리"],
        "desc": "생산 관리자"
    },
    "assembly_team": {
        "menus": ["조립 라인"],
        "desc": "조립 현장 담당자"
    },
    "qc_team": {
        "menus": ["검사 라인", "불량 공정"],
        "desc": "품질 검사 및 수리 담당"
    },
    "packing_team": {
        "menus": ["포장 라인"],
        "desc": "출하 및 포장 담당"
    },
    "repair_team": {
        "menus": ["불량 공정"], # line4용 권한
        "desc": "불량 수리 전담반"
    }
}

# =================================================================
# [PART 3] 데이터 연동 핵심 함수 (초기화 문제 해결 전용 로직 포함)
# =================================================================

# 구글 시트 연결을 위한 커넥션 객체
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 반환하는 타임스탬프 생성 함수입니다."""
    return datetime.now() + timedelta(hours=9)

def load_sheet_data():
    """
    구글 시트로부터 실시간 데이터를 로드하고 데이터 형식을 정제합니다.
    사용자가 수동으로 시트를 비웠을 경우를 대비한 방어 로직이 포함되어 있습니다.
    """
    try:
        # TTL=0 설정을 통해 캐시를 우회하고 매번 실제 시트의 데이터를 읽어옵니다.
        df_raw = conn.read(ttl=0).fillna("")
        
        # 1. 시리얼 번호가 숫자나 지수 형태로 변환되는 현상 방지 (문자열 강제 변환)
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # 2. 데이터가 완전히 비어있는 경우 (수동 삭제 등) 컬럼 구조를 강제로 생성합니다.
        if df_raw.empty:
            cols = ['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자']
            return pd.DataFrame(columns=cols)
            
        return df_raw
    except Exception as e:
        # 통신 장애 발생 시 빈 데이터프레임을 반환하여 시스템 중단을 막습니다.
        st.error(f"⚠️ 데이터 동기화 오류: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def commit_to_gsheet(df, force_reset=False):
    """
    변경된 데이터를 구글 시트에 업데이트합니다.
    [핵심 수정] force_reset=True 일 때만 빈 데이터프레임을 허용하여 시트를 물리적으로 초기화합니다.
    """
    # 1. 데이터가 비어있는데 초기화 모드가 아니라면 저장을 차단하여 데이터를 보호합니다.
    if df.empty and not force_reset:
        st.error("❌ 데이터 보호: 저장할 데이터가 비어있습니다. 새로고침을 시도하세요.")
        return False
    
    # 2. 구글 시트 API의 통신 불안정을 극복하기 위해 최대 3회 자동 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # Overwrite 방식으로 시트의 전체 내용을 현재 데이터프레임으로 교환합니다.
            conn.update(data=df)
            
            # 반영 즉시 스트림릿의 캐시를 삭제하여 최신 데이터를 모든 작업자에게 노출합니다.
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2) # 2초 대기 후 다시 시도
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (최종): {api_err}")
                return False

def push_image_to_drive(file_obj, file_name_str):
    """수리 현장 사진을 구글 드라이브 지정 폴더에 업로드하고 링크를 반환합니다."""
    try:
        # secrets에서 보안 키 정보를 로드합니다.
        raw_info = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_info)
        
        # 구글 드라이브 서비스 구축
        service = build('drive', 'v3', credentials=creds)
        
        # 타겟 폴더 ID (미리 설정되어 있어야 함)
        target_folder = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder:
            return "오류: 드라이브 폴더 설정 미비"

        # 파일 메타데이터 및 스트림 설정
        file_meta = {'name': file_name_str, 'parents': [target_folder]}
        media_body = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 실제 업로드 명령 실행
        file_res = service.files().create(
            body=file_meta, 
            media_body=media_body, 
            fields='id, webViewLink'
        ).execute()
        
        return file_res.get('webViewLink')
    except Exception as drive_err:
        return f"업로드 실패: {str(drive_err)}"

# =================================================================
# [PART 4] 세션 상태(Session State) 변수 초기화
# =================================================================
# 애플리케이션 가동 중에 실시간으로 변하는 모든 상태값을 메모리에 등록합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_sheet_data()

if 'user_db' not in st.session_state:
    # 시스템 계정 및 초기 권한 설정
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"},
        "line4": {"pw": "4444", "role": "repair_team"}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 마스터 제품 기준 데이터
if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], 
        "EPS7133": ["7133-S", "7133-PRO"], 
        "T20i": ["T20i-P", "T20i-WHITE"], 
        "T20C": ["T20C-S", "T20C-CORE"]
    }

if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [PART 5] 로그인 UI 및 사이드바 내비게이션
# =================================================================

def render_login_screen():
    """로그인 이전의 화면 구성을 담당합니다."""
    _, col_l, _ = st.columns([1, 1.2, 1])
    with col_l:
        st.markdown("<h1 class='centered-title'>🔐 생산 통합 관리 시스템</h1>", unsafe_allow_html=True)
        st.info("💡 공정별 부여된 ID와 비밀번호를 사용하여 시스템에 접속해 주세요.")
        
        with st.form("main_login_form"):
            in_id = st.text_input("아이디(ID)")
            in_pw = st.text_input("비밀번호(PW)", type="password")
            
            if st.form_submit_button("시스템 접속하기", use_container_width=True):
                if in_id in st.session_state.user_db:
                    correct_pw = st.session_state.user_db[in_id]["pw"]
                    if in_pw == correct_pw:
                        # 로그인 처리 및 데이터 초기 동기화
                        st.cache_data.clear()
                        st.session_state.production_db = load_sheet_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = in_id
                        st.session_state.user_role = st.session_state.user_db[in_id]["role"]
                        # 초기 메뉴 설정
                        st.session_state.current_line = ROLE_CONFIG[st.session_state.user_role]["menus"][0]
                        st.rerun()
                    else:
                        st.error("비밀번호가 일치하지 않습니다.")
                else:
                    st.error("등록되지 않은 아이디 정보입니다.")

if not st.session_state.login_status:
    render_login_screen()
    st.stop()

# --- 로그인 이후 사이드바 렌더링 ---
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 접속 중")
st.sidebar.caption(f"권한 등급: {ROLE_CONFIG[st.session_state.user_role]['desc']}")

if st.sidebar.button("🔓 시스템 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.rerun()

st.sidebar.divider()

def navigate(menu_nm):
    """메뉴 이동 처리 함수입니다."""
    st.session_state.current_line = menu_nm
    st.rerun()

# 사용자 권한에 맞는 메뉴만 생성합니다.
allowed_menus = ROLE_CONFIG[st.session_state.user_role]["menus"]

for menu_item in ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]:
    if menu_item in allowed_menus:
        btn_type = "primary" if st.session_state.current_line == menu_item else "secondary"
        if st.sidebar.button(f"📦 {menu_item}", use_container_width=True, type=btn_type):
            navigate(menu_item)

st.sidebar.divider()

for menu_item in ["불량 공정", "수리 리포트", "마스터 관리"]:
    if menu_item in allowed_menus:
        btn_type = "primary" if st.session_state.current_line == menu_item else "secondary"
        if st.sidebar.button(f"⚙️ {menu_item}", use_container_width=True, type=btn_type):
            navigate(menu_item)

# 알림 배너 자동 노출 (불량 발생 시)
ng_pending_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if len(ng_pending_list) > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 전체 공정에 {len(ng_pending_list)}건의 불량 수리가 대기 중입니다.</div>", unsafe_allow_html=True)

# =================================================================
# [PART 6] 핵심 비즈니스 로직 및 공용 컴포넌트
# =================================================================

def insert_divider_logic(df, current_line):
    """생산 실적 10대 달성 시 시각적 구분선을 시트에 삽입합니다."""
    today_str = get_kst_now().strftime('%Y-%m-%d')
    # 오늘 해당 라인의 순수 생산 실적(구분선 제외)을 집계합니다.
    line_perf = len(df[
        (df['라인'] == current_line) & 
        (df['시간'].astype(str).str.contains(today_str)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10대 단위로 구분선 행을 생성하여 병합합니다.
    if line_perf > 0 and line_perf % 10 == 0:
        divider_row = {
            '시간': '---', '라인': '---', 'CELL': '---', '모델': '---', '품목코드': '---', 
            '시리얼': f"✅ {line_perf}대 생산 달성 구분선", 
            '상태': '구분선', '증상': '---', '수리': '---', '작업자': '---'
        }
        return pd.concat([df, pd.DataFrame([divider_row])], ignore_index=True)
    return df

@st.dialog("📦 공정 단계 입고 확인")
def confirm_entry_dialog():
    """제품을 다음 단계로 이동시키기 위해 기존 행 정보를 업데이트합니다. (단일 행 추적)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    st.write(f"현재 위치가 '{st.session_state.current_line}'으로 업데이트됩니다.")
    
    col_ok, col_no = st.columns(2)
    
    if col_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        full_db = st.session_state.production_db
        
        # [복합키 매칭] 품목코드와 시리얼 번호가 일치하는 단일 행의 인덱스를 조회합니다.
        match_idx = full_db[
            (full_db['품목코드'] == st.session_state.confirm_item) & 
            (full_db['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not match_idx.empty:
            target_idx = match_idx[0]
            
            # 기존 행 정보를 갱신 (단일 행 워크플로우의 핵심)
            full_db.at[target_idx, '라인'] = st.session_state.current_line
            full_db.at[target_idx, '상태'] = '진행 중'
            full_db.at[target_idx, '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            full_db.at[target_idx, '작업자'] = st.session_state.user_id
            
            # 시트에 즉시 동기화
            if commit_to_gsheet(full_db):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 실패: 시트에서 해당 품목코드 및 시리얼 조합을 찾을 수 없습니다.")
            
    if col_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def render_line_metrics(line_name):
    """페이지 상단에 해당 라인의 금일 실적 KPI 카드를 렌더링합니다."""
    db_source = st.session_state.production_db
    today_kst = get_kst_now().strftime('%Y-%m-%d')
    
    # 금일 실적 집계
    line_data = db_source[
        (db_source['라인'] == line_name) & 
        (db_source['시간'].astype(str).str.contains(today_kst)) & 
        (db_source['상태'] != '구분선')
    ]
    
    total_in = len(line_data)
    total_done = len(line_data[line_data['상태'] == '완료'])
    
    # 이전 공정에서의 대기 물량 산출
    waiting_qty = 0
    prev_line = None
    if line_name == "검사 라인": prev_line = "조립 라인"
    elif line_name == "포장 라인": prev_line = "검사 라인"
    
    if prev_line:
        # 이전 라인에서 '완료' 상태로 멈춰있는 물량 조회
        waiting_pool = db_source[
            (db_source['라인'] == prev_line) & 
            (db_source['상태'] == '완료')
        ]
        waiting_qty = len(waiting_pool)
        
    m1, m2, m3 = st.columns(3)
    
    with m1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>⏳ 이전공정 대기</div><div class='stat-value' style='color:#fd7e14;'>{waiting_qty if prev_line else '-'}</div><div class='stat-unit'>건</div></div>", unsafe_allow_html=True)
    with m2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{total_in}</div><div class='stat-unit'>건</div></div>", unsafe_allow_html=True)
    with m3:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:#198754;'>{total_done}</div><div class='stat-unit'>건</div></div>", unsafe_allow_html=True)

# [UI 최적화] 로그 테이블의 버튼을 슬림하게 구현한 공용 렌더링 함수
def render_process_log_table(line_name, btn_label_ok="✅완료"):
    """실시간 공정 로그 및 슬림 버튼 제어 영역을 표시합니다."""
    st.divider()
    st.markdown(f"<div class='section-header'>📝 {line_name} 실시간 작업 현황 로그</div>", unsafe_allow_html=True)
    
    db_all = st.session_state.production_db
    view_db = db_all[db_all['라인'] == line_name]
    
    # 조립 라인의 경우 CELL별 필터 적용
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_db = view_db[view_db['CELL'] == st.session_state.selected_cell]
        
    if view_db.empty:
        st.info("현재 표시할 작업 데이터가 존재하지 않습니다.")
        return
        
    # 헤더 정의 (슬림 UI 반영)
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
    header_titles = ["기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "작업 상태 제어"]
    
    for i, title in enumerate(header_titles):
        h_cols[i].write(f"**{title}**")
        
    # 데이터 행 최신순 정렬 및 렌더링
    for idx_row, data_row in view_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리
        if data_row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#f8f9fa; padding:5px; text-align:center; border-radius:8px; font-weight:bold; color:#adb5bd; border:1px dashed #dee2e6; margin-bottom:5px; font-size:0.85em;'>{data_row['시리얼']}</div>", unsafe_allow_html=True)
            continue
            
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
        r_cols[0].write(data_row['시간'])
        r_cols[1].write(data_row['CELL'])
        r_cols[2].write(data_row['모델'])
        r_cols[3].write(data_row['품목코드'])
        r_cols[4].write(data_row['시리얼'])
        
        with r_cols[5]:
            curr_status = data_row['상태']
            
            # [슬림 버튼] 완료 보고와 불량 발생 버튼을 콤팩트하게 배치
            if curr_status in ["진행 중", "수리 완료(재투입)"]:
                col_btn_ok, col_btn_ng = st.columns(2)
                
                # 버튼 라벨 슬림화: "✅완료", "🚫불량"
                if col_btn_ok.button(btn_label_ok, key=f"btn_ok_act_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "완료"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if commit_to_gsheet(db_all):
                        st.rerun()
                        
                if col_btn_ng.button("🚫불량", key=f"btn_ng_act_{idx_row}"):
                    db_all.at[idx_row, '상태'] = "불량 처리 중"
                    db_all.at[idx_row, '작업자'] = st.session_state.user_id
                    if commit_to_gsheet(db_all):
                        st.rerun()
                        
            elif curr_status == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:800; font-size:0.85em;'>🛠️ 수리 센터 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:800; font-size:0.85em;'>✅ 공정 작업 완료</span>", unsafe_allow_html=True)

# =================================================================
# [PART 7] 각 메뉴별 상세 기능 및 화면 렌더링 (v20.0 완성판)
# =================================================================

# -----------------------------------------------------------------
# 7-1. 조립 라인 페이지 (Workflow의 시작)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h1 class='centered-title'>📦 조립 공정 현황 모니터링</h1>", unsafe_allow_html=True)
    render_line_metrics("조립 라인")
    st.divider()
    
    # CELL 선택 UI (작업 구역 필터)
    cell_names = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    col_cells = st.columns(len(cell_names))
    
    for i, c_nm in enumerate(cell_names):
        btn_type = "primary" if st.session_state.selected_cell == c_nm else "secondary"
        if col_cells[i].button(c_nm, key=f"cell_btn_{i}", type=btn_type):
            st.session_state.selected_cell = c_nm
            st.rerun()
            
    # 개별 셀이 선택되었을 때만 생산 등록 폼을 노출합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"<div class='section-header'>🛠️ {st.session_state.selected_cell} 신규 생산 제품 등록</div>", unsafe_allow_html=True)
            
            # [핵심 수정] 셀 전환 시 모델 선택박스 초기화 (key에 cell 이름 포함)
            sel_model = st.selectbox(
                "생산 모델을 선택해 주세요.", 
                ["선택하세요."] + st.session_state.master_models,
                key=f"m_sel_box_{st.session_state.selected_cell}"
            )
            
            with st.form("new_production_reg_form"):
                f_col1, f_col2 = st.columns(2)
                
                # 모델 기반 품목 리스트 연동
                avail_items = st.session_state.master_items_dict.get(sel_model, ["모델 정보 없음"])
                sel_item = f_col1.selectbox("품목코드 선택", avail_items)
                
                sel_sn = f_col2.text_input("시리얼 번호(S/N) 입력")
                
                submit_btn = st.form_submit_button("▶️ 생산 데이터 신규 등록", use_container_width=True, type="primary")
                
                if submit_btn:
                    if sel_model != "선택하세요." and sel_sn != "":
                        db_ptr = st.session_state.production_db
                        
                        # [복합키 중복 체크] 제품 간 '품목코드' + '시리얼'이 절대 중복되지 않아야 합니다.
                        # 모델명은 중복될 수 있지만, 제품 식별키는 품목코드+시리얼 조합입니다.
                        dup_find = db_ptr[
                            (db_ptr['품목코드'] == sel_item) & 
                            (db_ptr['시리얼'] == sel_sn) & 
                            (db_ptr['상태'] != "구분선")
                        ]
                        
                        if not dup_find.empty:
                            st.error(f"❌ 중복 등록 거부: 품목코드 [ {sel_item} ] 및 시리얼 [ {sel_sn} ]은 이미 등록된 데이터입니다.")
                        else:
                            # 신규 행 생성
                            new_row = {
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
                            
                            # 데이터 병합 및 실적 마커 자동 삽입
                            updated_db = pd.concat([db_ptr, pd.DataFrame([new_row])], ignore_index=True)
                            updated_db = insert_divider_logic(updated_db, "조립 라인")
                            
                            st.session_state.production_db = updated_db
                            
                            # 구글 시트에 즉시 반영
                            if commit_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 누락 없이 입력해 주십시오.")
                        
    # 조립 로그 테이블 출력
    render_process_log_table("조립 라인", "✅완료")

# -----------------------------------------------------------------
# 7-2. 검사 라인 및 포장 라인 (단계별 필터 및 슬림 버튼)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_nm = st.session_state.current_line
    icon_nm = "🔍" if line_nm == "검사 라인" else "🚚"
    st.markdown(f"<h1 class='centered-title'>{icon_nm} {line_nm} 공정 현황</h1>", unsafe_allow_html=True)
    
    render_line_metrics(line_nm)
    st.divider()
    
    prev_nm = "조립 라인" if line_nm == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.markdown(f"<div class='section-header'>📥 {prev_nm} 완료 물량 입고 승인 처리</div>", unsafe_allow_html=True)
        
        # [복구] 1단계: 모델 선택 (반드시 하나를 선택해야 함)
        f_model = st.selectbox("입고할 제품 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"f_m_sel_{line_nm}")
        
        if f_model != "선택하세요.":
            # [복구] 2단계: 품목코드 상세 필터
            model_items = st.session_state.master_items_dict.get(f_model, [])
            f_item = st.selectbox("해당 모델의 품목코드를 선택하세요.", ["선택하세요."] + model_items, key=f"f_i_sel_{line_nm}")
            
            if f_item != "선택하세요.":
                db_all = st.session_state.production_db
                
                # [복합 필터링] 이전 라인 완료 + 선택 모델 + 선택 품목코드
                waiting_pool = db_all[
                    (db_all['라인'] == prev_nm) & 
                    (db_all['상태'] == "완료") & 
                    (db_all['모델'] == f_model) & 
                    (db_all['품목코드'] == f_item)
                ]
                
                if not waiting_pool.empty:
                    st.success(f"📦 [ {f_item} ] 입고 가능한 물량이 {len(waiting_pool)}건 조회되었습니다.")
                    
                    # 입고 승인 버튼을 4열 그리드로 배치 (슬림 버튼 적용)
                    btn_grid = st.columns(4)
                    for i, row in enumerate(waiting_pool.itertuples()):
                        # 버튼 라벨에 시리얼 번호만 짧게 노출
                        btn_key = f"in_btn_{row.품목코드}_{row.시리얼}_{line_nm}"
                        if btn_grid[i % 4].button(f"📥 {row.시리얼}", key=btn_key):
                            st.session_state.confirm_target = row.시리얼
                            st.session_state.confirm_model = row.모델
                            st.session_state.confirm_item = row.품목코드 # 품목코드를 같이 넘겨야 함
                            confirm_entry_dialog()
                else:
                    st.info(f"현재 [ {f_item} ] 품목의 입고 대기 물량이 존재하지 않습니다.")
        else:
            st.warning("작업을 진행할 모델과 품목을 순차적으로 상단 필터에서 선택해 주세요.")
            
    # 실시간 작업 로그 테이블
    render_process_log_table(line_nm, "✅합격" if line_nm == "검사 라인" else "🚚출하")

# -----------------------------------------------------------------
# 7-3. 생산 통합 리포트 (통계 대시보드)
# -----------------------------------------------------------------
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h1 class='centered-title'>📊 실시간 생산 통합 대시보드</h1>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화 리프레시", use_container_width=True):
        st.session_state.production_db = load_sheet_data()
        st.rerun()
        
    db_report = st.session_state.production_db
    
    if not db_report.empty:
        # 데이터 정제 (구분선 제거)
        clean_db = db_report[db_report['상태'] != '구분선']
        
        # 주요 KPI 지표 산출
        # 최종 포장 라인에서 '완료'된 수량이 완제품 수량입니다.
        qty_done = len(clean_db[(clean_db['라인'] == '포장 라인') & (clean_db['상태'] == '완료')])
        qty_ng = len(clean_db[clean_db['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출
        ftt_rate = 0
        if (qty_done + qty_ng) > 0:
            ftt_rate = (qty_done / (qty_done + qty_ng)) * 100
        else:
            ftt_rate = 100
            
        # 메트릭 위젯 배치
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        kpi_c1.metric("최종 완제품 출하", f"{qty_done} EA")
        kpi_c2.metric("전 공정 재공(WIP)", f"{len(clean_db[clean_db['상태'] == '진행 중'])} EA")
        kpi_c3.metric("누적 불량 건수", f"{qty_ng} 건", delta=qty_ng, delta_color="inverse")
        kpi_c4.metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        
        # 시각화 영역
        vis_c1, vis_c2 = st.columns([3, 2])
        
        with vis_c1:
            line_dist = clean_db.groupby('라인').size().reset_index(name='수량')
            fig_line = px.bar(line_dist, x='라인', y='수량', color='라인', text_auto=True, title="공정 단계별 현재 제품 분포 현황")
            st.plotly_chart(fig_line, use_container_width=True)
            
        with vis_c2:
            model_dist = clean_db.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(model_dist, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성")
            st.plotly_chart(fig_pie, use_container_width=True)
            
        st.markdown("<div class='section-header'>🔍 상세 공정 통합 생산 기록 전체 보기</div>", unsafe_allow_html=True)
        st.dataframe(db_report.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("현재 분석할 생산 실적 데이터가 존재하지 않습니다.")

# -----------------------------------------------------------------
# 7-4. 불량 수리 센터 (line4 권한 대응 및 사진 업로드)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h1 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h1>", unsafe_allow_html=True)
    render_line_metrics("조립 라인") # 참고용 실적 노출
    
    # 불량 처리 중인 데이터만 필터링
    bad_items = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_items.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 조치 및 수리가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_items)}건")
        
        for idx_r, row_r in bad_items.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **품목코드: {row_r['품목코드']}** | 시리얼: {row_r['시리얼']} | 모델: {row_r['모델']} | 발생: {row_r['라인']}")
                
                # 수리 원인 및 조치 내용 입력
                rc1, rc2, rc3 = st.columns([4, 4, 2])
                
                # 캐시 로드
                cache_sym = st.session_state.repair_cache.get(f"sym_{idx_r}", "")
                cache_act = st.session_state.repair_cache.get(f"act_{idx_r}", "")
                
                i_sym = rc1.text_input("불량 원인 상세", value=cache_sym, key=f"is_{idx_r}")
                i_act = rc2.text_input("수리 및 조치 사항", value=cache_act, key=f"ia_{idx_r}")
                
                # 캐시 실시간 업데이트
                st.session_state.repair_cache[f"sym_{idx_r}"] = i_sym
                st.session_state.repair_cache[f"act_{idx_r}"] = i_act
                
                # 사진 첨부 업로더
                up_file = st.file_uploader("수리 조치 사진(JPG/PNG) 첨부", type=['jpg','png','jpeg'], key=f"up_{idx_r}")
                
                if up_file:
                    st.image(up_file, width=300, caption="업로드 예정 사진")
                    
                if rc3.button("🔧 수리 완료 보고", key=f"rep_btn_{idx_r}", type="primary", use_container_width=True):
                    if i_sym and i_act:
                        final_photo_link = ""
                        
                        if up_file:
                            with st.spinner("증빙 사진을 드라이브에 저장 중입니다..."):
                                ts_m = get_kst_now().strftime('%Y%m%d_%H%M')
                                f_name = f"{row_r['시리얼']}_FIX_{ts_m}.jpg"
                                up_url = push_image_to_drive(up_file, f_name)
                                if "http" in up_url:
                                    final_photo_link = f" [사진보기: {up_url}]"
                        
                        # 데이터베이스 업데이트 로직
                        st.session_state.production_db.at[idx_r, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx_r, '증상'] = i_sym
                        st.session_state.production_db.at[idx_r, '수리'] = i_act + final_photo_link
                        st.session_state.production_db.at[idx_r, '작업자'] = st.session_state.user_id
                        
                        if commit_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 비우기 및 리프레시
                            st.session_state.repair_cache.pop(f"sym_{idx_r}", None)
                            st.session_state.repair_cache.pop(f"act_{idx_r}", None)
                            st.success("수리 완료 보고가 시트에 등록되었습니다.")
                            st.rerun()
                    else:
                        st.error("원인과 조치 사항을 모두 입력해야 등록이 가능합니다.")

# -----------------------------------------------------------------
# 7-5. 마스터 관리 (강제 초기화 버그 해결 영역)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h1 class='centered-title'>🔐 시스템 관리자 마스터 센터</h1>", unsafe_allow_html=True)
    
    # 관리자 세션 보안 인증
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_form"):
            st.write("안전한 시스템 설정을 위해 관리자 비밀번호를 확인합니다.")
            pw_in = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            if st.form_submit_button("권한 인증하기", use_container_width=True):
                if pw_in in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 기능이 활성화되었습니다.")
                    st.rerun()
                else:
                    st.error("비밀번호 정보가 올바르지 않습니다.")
    else:
        if st.sidebar.button("🔓 관리자 세션 종료"):
            st.session_state.admin_authenticated = False
            navigate("생산 리포트")

        st.markdown("<div class='section-header'>📋 1. 마스터 기준 데이터 관리</div>", unsafe_allow_html=True)
        ac1, ac2 = st.columns(2)
        
        with ac1:
            with st.container(border=True):
                st.write("**신규 모델 명칭 등록**")
                n_m = st.text_input("추가할 모델명")
                if st.button("➕ 모델 신규 추가", use_container_width=True):
                    if n_m and n_m not in st.session_state.master_models:
                        st.session_state.master_models.append(n_m)
                        st.session_state.master_items_dict[n_m] = []
                        st.rerun()

        with ac2:
            with st.container(border=True):
                st.write("**품목코드 마스터 매핑**")
                sel_m_a = st.selectbox("품목 추가 모델 선택", st.session_state.master_models)
                n_i = st.text_input("신규 품목코드 명칭")
                if st.button("➕ 품목코드 매핑 추가", use_container_width=True):
                    if n_i and n_i not in st.session_state.master_items_dict[sel_m_a]:
                        st.session_state.master_items_dict[sel_m_a].append(n_i)
                        st.rerun()

        st.divider()
        st.markdown("<div class='section-header'>💾 2. 데이터 백업 및 물리적 초기화 제어</div>", unsafe_allow_html=True)
        arc1, arc2 = st.columns(2)
        
        with arc1:
            st.write("현재 구글 시트의 전체 생산 실적 데이터를 CSV로 백업 다운로드합니다.")
            csv_blob = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 전체 실적 CSV 백업 다운로드", 
                csv_blob, 
                f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with arc2:
            st.write("구글 시트 데이터 물리적 초기화 (전체 삭제)")
            # [초기화 핵심 버그 수정] 
            # 버튼 클릭 시 빈 데이터프레임 구조를 생성하여 구글 API로 강제 전송(Overwrite)을 시도합니다.
            if st.button("🚫 시스템 전체 생산 실적 데이터 초기화", type="secondary", use_container_width=True):
                 st.error("주의: 실행 시 구글 시트의 모든 실적 데이터가 삭제되며 복구가 불가능합니다.")
                 if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                     # 컬럼 헤더만 있고 데이터는 없는 빈 데이터프레임 강제 생성
                     empty_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                     st.session_state.production_db = empty_df
                     
                     # force_reset 모드(is_reset_command=True)로 저장 함수 호출하여 시트 비움
                     if commit_to_gsheet(empty_df, force_reset=True):
                         st.cache_data.clear()
                         st.success("구글 시트의 데이터가 성공적으로 물리적으로 비워졌습니다.")
                         st.rerun()

        st.divider()
        st.markdown("<div class='section-header'>👤 3. 사용자 계정 권한 및 비밀번호 관리</div>", unsafe_allow_html=True)
        uc1, uc2, uc3 = st.columns([3, 3, 2])
        t_uid = uc1.text_input("생성/수정할 ID")
        t_upw = uc2.text_input("신규 패스워드 설정", type="password")
        t_role = uc3.selectbox("권한 등급 할당", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 사용자 계정 정보 업데이트 반영", use_container_width=True):
            if t_uid and t_upw:
                st.session_state.user_db[t_uid] = {"pw": t_upw, "role": t_role}
                st.success(f"[{t_uid}] 사용자의 권한 정보가 성공적으로 반영되었습니다."); st.rerun()
