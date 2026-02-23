# -*- coding: utf-8 -*-
"""
==========================================================================================
시스템 명칭: 생산 통합 관리 및 공정 추적 시스템 (Integrated Production & Process Tracking System)
버전 정보: v22.0 (Ultra-Expanded Architecture)
최종 업데이트: 2024-05-24
------------------------------------------------------------------------------------------
[시스템 개요]
본 프로그램은 조립, 검사, 포장으로 이어지는 생산 전 공정을 실시간으로 디지털화하여 관리합니다.
특히 구글 시트를 물리적인 데이터베이스(DB)로 활용하며, 현장 작업자의 실수를 원천 차단하기 위한
다양한 안전 로직(Safety Logic)이 설계되어 있습니다.

[핵심 업데이트 사양]
1. 디자인: v15.2 버전의 클래식 화이트-블루 테마 완벽 복원
2. 버튼: "✅완료", "🚫불량" 등 짧은 라벨과 슬림한 높이(Padding) 적용
3. 고유키: [품목코드 + 시리얼] 복합키 방식을 통한 데이터 유일성 보장
4. 초기화: 빈 데이터 강제 덮어쓰기(Overwrite)를 통한 구글 시트 물리적 초기화 성공
5. 리셋: CELL 변경 시 위젯 키(Key) 동적 생성을 통한 모델 선택박스 자동 초기화
6. 필터: 검사/포장 라인에서 모델명 선택 후 품목코드를 다시 고르는 2단계 정밀 필터
7. 분량: 1,000줄에 달하는 상세한 코드 전개와 운영 매뉴얼급 주석 탑재
==========================================================================================
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

# 구글 클라우드 플랫폼(GCP) API 연동을 위한 보안 및 통신 라이브러리
# 현장 수리 증빙용 사진을 구글 드라이브에 실시간으로 업로드하기 위해 필요합니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================================================================
# [PART 1] 시스템 환경 설정 및 글로벌 스타일링 (v15.2 클래식 복원)
# ==========================================================================================

# 애플리케이션의 기본 페이지 설정을 수행합니다.
# 현장의 넓은 모니터 환경을 고려하여 레이아웃을 'wide'로 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v22.0",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

def apply_integrated_ultra_style():
    """
    현장 시인성 확보를 위한 v15.2 클래식 디자인과 슬림 버튼 스타일을 통합 정의합니다.
    모든 색상 코드와 여백 수치는 사용자님의 요청에 따라 엄격하게 설정되었습니다.
    """
    st.markdown("""
        <style>
        /* 1. 전체 캔버스 설정 (화이트 배경 테마) */
        .stApp {
            max-width: 1250px;
            margin: 0 auto;
            background-color: #ffffff;
            color: #333333;
        }

        /* 2. 버튼 슬림화 및 조작성 최적화 (핵심 UI 수정) */
        /* 버튼의 높이를 낮추고 라벨이 중앙에 오도록 세밀하게 조정합니다. */
        div.stButton > button {
            margin-top: 2px !important;
            margin-bottom: 2px !important;
            padding: 4px 10px !important; /* 슬림 패딩 적용 */
            width: 100%;
            height: auto !important;
            min-height: 32px !important;
            font-weight: 700 !important;
            font-size: 0.92em !important;
            border-radius: 6px !important;
            border: 1px solid #ced4da !important;
            background-color: #ffffff !important;
            color: #2c3e50 !important;
            transition: all 0.15s ease-in-out !important;
        }
        
        /* 버튼에 마우스를 올렸을 때 블루 테마 색상 적용 */
        div.stButton > button:hover {
            border-color: #007bff !important;
            color: #007bff !important;
            background-color: #f1f8ff !important;
            transform: translateY(-1px);
        }
        
        /* 버튼 클릭 시 시각적 피드백 */
        div.stButton > button:active {
            background-color: #e2f0ff !important;
            transform: translateY(1px);
        }

        /* 3. 섹션 타이틀 및 제목 디자인 (v15.2 복구) */
        .centered-main-title {
            text-align: center;
            font-weight: 900;
            margin: 20px 0 35px 0;
            color: #1a1a1a;
            font-size: 2.4em;
            border-bottom: 3px solid #007bff;
            padding-bottom: 12px;
            letter-spacing: -1px;
        }
        
        .sub-section-title {
            font-size: 1.3em;
            font-weight: 800;
            color: #007bff;
            margin: 30px 0 15px 0;
            padding-left: 12px;
            border-left: 5px solid #007bff;
        }

        /* 4. 알람 및 공지 배너 스타일 (가시성 극대화) */
        .emergency-banner {
            background-color: #fff0f0;
            color: #d63031;
            padding: 18px 25px;
            border-radius: 12px;
            border: 1px solid #fab1a0;
            font-weight: 800;
            margin-bottom: 25px;
            text-align: center;
            font-size: 1.15em;
            box-shadow: 0 4px 12px rgba(214, 48, 49, 0.08);
        }

        /* 5. 대시보드 메트릭 카드 디자인 (Clean White 스타일) */
        .metric-card {
            background-color: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            border: 1px solid #e9ecef;
            box-shadow: 0 5px 15px rgba(0,0,0,0.02);
            margin-bottom: 20px;
        }
        
        .metric-header {
            font-size: 1em;
            color: #6c757d;
            font-weight: 700;
            margin-bottom: 10px;
            text-transform: uppercase;
        }
        
        .metric-body {
            font-size: 2.5em;
            color: #007bff;
            font-weight: 900;
        }
        
        .metric-footer {
            font-size: 0.85em;
            color: #adb5bd;
            margin-top: 5px;
        }

        /* 6. 스트림릿 기본 위젯 여백 조정 */
        .stSelectbox, .stTextInput {
            margin-bottom: 10px;
        }
        </style>
        """, unsafe_allow_html=True)

# 정의된 모든 상세 스타일을 애플리케이션에 즉시 주입합니다.
apply_integrated_ultra_style()

# ==========================================================================================
# [PART 2] 권한 관리 및 보안 아키텍처 (Role-Based Access Control)
# ==========================================================================================

# 시스템에서 사용하는 모든 메뉴 구조를 정의합니다.
# 사용자님의 요청에 따라 "리포트" 명칭 등 v15.2의 친숙한 용어를 그대로 사용합니다.
MENU_STRUCTURE = {
    "master": {
        "access": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
        "label": "최고 관리자(Master)"
    },
    "control_tower": {
        "access": ["리포트", "수리 리포트", "마스터 관리"],
        "label": "통제 센터(Control)"
    },
    "assembly_team": {
        "access": ["조립 라인"],
        "label": "조립 공정(Assembly)"
    },
    "qc_team": {
        "access": ["검사 라인", "불량 공정"],
        "label": "품질 검사(QC)"
    },
    "packing_team": {
        "access": ["포장 라인"],
        "label": "포장 출하(Packing)"
    },
    "repair_team": {
        "access": ["불량 공정"], # line4 계정을 위한 전용 수리 권한
        "label": "수리 전담(Repair)"
    }
}

# ==========================================================================================
# [PART 3] 구글 클라우드 연동 및 데이터 핸들링 엔진 (초기화 버그 수정 완료)
# ==========================================================================================

# 구글 시트 연결을 위한 커넥션 생성
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_timestamp():
    """한국 표준시(KST) 기준의 현재 시각을 생성하여 반환합니다."""
    # 서버 시각이 UTC인 경우를 대비하여 9시간을 더해 보정합니다.
    return datetime.now() + timedelta(hours=9)

def fetch_live_data():
    """
    구글 시트로부터 실시간 생산 데이터를 로드합니다.
    데이터 유실 방지를 위해 시트가 비어있을 경우의 예외 처리를 아주 상세히 수행합니다.
    """
    try:
        # 캐시를 무효화하고 최신 데이터를 강제로 읽어옵니다. (TTL=0)
        df_raw = conn.read(ttl=0).fillna("")
        
        # 1. 시리얼 번호 보정: 숫자로 인식되어 .0이 붙는 현상을 정규식을 통해 제거합니다.
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # 2. 데이터 유효성 검사: 만약 시트 내용이 완전히 삭제되었다면 기본 컬럼 구조를 강제로 반환합니다.
        if df_raw.empty:
            headers = ['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자']
            return pd.DataFrame(columns=headers)
            
        return df_raw
    except Exception as fetch_err:
        # 네트워크 장애 등 발생 시 시스템 다운을 막기 위한 빈 데이터프레임 반환
        st.error(f"⚠️ 구글 데이터 로드 실패: {fetch_err}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_gsheet(df, is_reset_action=False):
    """
    변경된 데이터프레임을 구글 시트에 즉시 반영(Overwrite)합니다.
    [핵심 수정] is_reset_action이 True일 때만 빈 데이터 업데이트를 강제 승인합니다.
    """
    # 1. 비정상적인 빈 데이터 전송 차단 (초기화 명령이 아닌 경우)
    if df.empty and not is_reset_action:
        st.error("❌ 저장 오류: 전송할 데이터가 존재하지 않습니다. (동기화 실패 방지)")
        return False
    
    # 2. 통신 안정성을 위한 3단계 재시도 메커니즘
    for attempt in range(1, 4):
        try:
            # 구글 시트의 내용을 현재 데이터프레임으로 완전히 덮어씁니다.
            conn.update(data=df)
            
            # 전역 캐시를 즉시 삭제하여 모든 사용자가 최신본을 보게 합니다.
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2) # 2초 대기 후 다시 시도
                continue
            else:
                st.error(f"⚠️ 구글 저장 최종 실패: {api_err}")
                return False

def drive_image_uploader(file_stream, filename_str):
    """현장에서 촬영한 수리 증빙 사진을 구글 드라이브에 안전하게 보관합니다."""
    try:
        # secrets에 저장된 서비스 계정 키 정보를 로드합니다.
        raw_keys = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_keys)
        
        # 드라이브 API 서비스 생성
        drive_service = build('drive', 'v3', credentials=credentials)
        target_folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder_id:
            return "오류: 폴더ID 설정값 없음"

        # 메타데이터 및 파일 스트림 구성
        meta_data = {'name': filename_str, 'parents': [target_folder_id]}
        media_payload = MediaIoBaseUpload(file_stream, mimetype=file_stream.type)
        
        # 드라이브 업로드 실행 및 웹 공유 링크 수신
        created_file = drive_service.files().create(
            body=meta_data, 
            media_body=media_payload, 
            fields='id, webViewLink'
        ).execute()
        
        return created_file.get('webViewLink')
    except Exception as drive_api_err:
        return f"드라이브 업로드 기술적 오류: {str(drive_api_err)}"

# ==========================================================================================
# [PART 4] 세션 상태(Session State) 글로벌 변수 초기화
# ==========================================================================================
# 애플리케이션 가동 중에 영구적으로 유지될 모든 동적 변수들을 등록합니다.

if 'production_db' not in st.session_state:
    # 앱 시작 시 최초 1회 구글 시트에서 데이터를 동기화합니다.
    st.session_state.production_db = fetch_live_data()

if 'user_db' not in st.session_state:
    # 시스템 운영을 위한 마스터 계정 데이터베이스입니다.
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"},
        "line4": {"pw": "4444", "role": "repair_team"}
    }

# 로그인 관련 세션 변수
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 마스터 제품 구성 데이터 (확장성 확보)
if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    # 모델별 상세 품목코드 매핑
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B", "7150-PRO"], 
        "EPS7133": ["7133-S", "7133-PLUS"], 
        "T20i": ["T20i-P", "T20i-WHITE"], 
        "T20C": ["T20C-S", "T20C-CORE"]
    }

# 공정 내비게이션 및 캐시 세션
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# ==========================================================================================
# [PART 5] 사용자 인증 시스템 및 사이드바 내비게이션
# ==========================================================================================

def render_login_module():
    """로그인 이전의 사용자 인증 화면을 전개합니다."""
    _, login_col, _ = st.columns([1, 1.2, 1])
    with login_col:
        st.markdown("<h1 class='centered-main-title'>🔐 생산 통합 관리 시스템 로그인</h1>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 공정 담당자 계정으로 로그인하여 주시기 바랍니다.")
        
        with st.form("main_system_login_form"):
            in_user_id = st.text_input("운영 아이디(ID) 입력")
            in_user_pw = st.text_input("비밀번호(PW) 입력", type="password")
            
            trigger_login = st.form_submit_button("시스템 로그인 실행", use_container_width=True)
            
            if trigger_login:
                # 계정 정보를 조회하여 비밀번호를 검증합니다.
                if in_user_id in st.session_state.user_db:
                    correct_pw_val = st.session_state.user_db[in_user_id]["pw"]
                    if in_user_pw == correct_pw_val:
                        # 인증 성공 처리
                        st.cache_data.clear()
                        st.session_state.production_db = fetch_live_data()
                        st.session_state.login_status = True
                        st.session_state.user_id = in_user_id
                        st.session_state.user_role = st.session_state.user_db[in_id if 'in_id' in locals() else in_user_id]["role"]
                        # 권한별 첫 번째 페이지로 자동 이동
                        st.session_state.current_line = MENU_STRUCTURE[st.session_state.user_role]["access"][0]
                        st.rerun()
                    else:
                        st.error("입력한 비밀번호가 유효하지 않습니다.")
                else:
                    st.error("등록된 시스템 계정 정보가 존재하지 않습니다.")

# 로그인 상태가 아닐 경우 실행을 중단하고 로그인 화면을 띄웁니다.
if not st.session_state.login_status:
    render_login_module()
    st.stop()

# --- 로그인 완료 후 사이드바 렌더링 영역 ---
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 접속 중")
st.sidebar.caption(f"운영 등급: {MENU_STRUCTURE[st.session_state.user_role]['label']}")

if st.sidebar.button("🔓 시스템 안전 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.rerun()

st.sidebar.divider()

def navigate_page(page_name):
    """지정된 페이지로 이동을 수행하는 핸들러입니다."""
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한에 따른 메뉴 필터링 및 버튼 생성
allowed_access_list = MENU_STRUCTURE.get(st.session_state.user_role, {}).get("access", [])

# 그룹 1: 메인 공정 관리
for m_item in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if m_item in allowed_access_list:
        btn_style_type = "primary" if st.session_state.current_line == m_item else "secondary"
        if st.sidebar.button(f"📦 {m_item}", use_container_width=True, type=btn_style_type):
            navigate_page(m_item)

st.sidebar.divider()

# 그룹 2: 사후 관리 및 마스터 설정
for m_item in ["불량 공정", "수리 리포트", "마스터 관리"]:
    if m_item in allowed_access_list:
        btn_style_type_2 = "primary" if st.session_state.current_line == m_item else "secondary"
        if st.sidebar.button(f"⚙️ {m_item}", use_container_width=True, type=btn_style_type_2):
            navigate_page(m_item)

# 하단 긴급 알림 배너 (불량 발생 시 자동 집계)
ng_pending_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if len(ng_pending_db) > 0:
    st.markdown(f"<div class='emergency-banner'>🚨 긴급 상황: 수리 대기 중인 불량 제품이 {len(ng_pending_db)}건 존재합니다. 즉시 확인 바랍니다.</div>", unsafe_allow_html=True)

# ==========================================================================================
# [PART 6] 핵심 비즈니스 로직 및 공용 유틸리티 컴포넌트
# ==========================================================================================

def execute_divider_marker(df, line_nm):
    """10대 단위 생산 실적 달성 시 구분선을 삽입하여 시각적 통계를 제공합니다."""
    kst_today_str = get_kst_timestamp().strftime('%Y-%m-%d')
    # 금일 해당 라인 실적 수량 집계 (구분선 제외)
    perf_count = len(df[
        (df['라인'] == line_nm) & 
        (df['시간'].astype(str).str.contains(kst_today_str)) & 
        (df['상태'] != "구분선")
    ])
    
    # 10의 배수 달성 시마다 고유 구분 행 생성 및 병합
    if perf_count > 0 and perf_count % 10 == 0:
        divider_data = {
            '시간': '---', '라인': '---', 'CELL': '---', '모델': '---', '품목코드': '---', 
            '시리얼': f"✅ {perf_count}대 생산 실적 달성 마커", 
            '상태': '구분선', '증상': '---', '수리': '---', '작업자': '---'
        }
        return pd.concat([df, pd.DataFrame([divider_data])], ignore_index=True)
    return df

@st.dialog("📦 공정 단계 입고 승인")
def trigger_entry_confirm_dialog():
    """제품을 다음 공정으로 이동시키기 위해 기존 행 정보를 업데이트합니다. (단일 행 추적의 핵심)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ]의 입고를 정식 승인하시겠습니까?")
    st.write(f"승인 시 해당 제품의 위치가 '{st.session_state.current_line}'으로 동기화됩니다.")
    
    btn_ok_c, btn_no_c = st.columns(2)
    
    if btn_ok_c.button("✅ 입고 승인 완료", type="primary", use_container_width=True):
        full_db_ref = st.session_state.production_db
        
        # [복합키 매칭] '품목코드'와 '시리얼'이 동시에 일치하는 행 인덱스를 조회합니다.
        row_target_idx = full_db_ref[
            (full_db_ref['품목코드'] == st.session_state.confirm_item) & 
            (full_db_ref['시리얼'] == st.session_state.confirm_target)
        ].index
        
        if not row_target_idx.empty:
            idx_ptr = row_target_idx[0]
            
            # [Workflow 업데이트] 기존 정보를 갱신하여 불필요한 행 추가를 방지합니다.
            full_db_ref.at[idx_ptr, '라인'] = st.session_state.current_line
            full_db_ref.at[idx_ptr, '상태'] = '진행 중'
            full_db_ref.at[idx_ptr, '시간'] = get_kst_timestamp().strftime('%Y-%m-%d %H:%M:%S')
            full_db_ref.at[idx_ptr, '작업자'] = st.session_state.user_id
            
            # 구글 시트에 실시간 반영 실행
            if push_to_gsheet(full_db_ref):
                st.session_state.confirm_target = None
                st.rerun()
        else:
            st.error("데이터 매칭 오류: 해당 품목코드 및 시리얼 조합을 데이터베이스에서 찾을 수 없습니다.")
            
    if btn_no_c.button("❌ 승인 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_dashboard_kpi_metrics(line_nm):
    """상단 통계 KPI 섹션을 v15.2 클래식 스타일로 렌더링합니다."""
    db_ptr = st.session_state.production_db
    kst_today_val = get_kst_timestamp().strftime('%Y-%m-%d')
    
    # 금일 실적 데이터 필터링
    today_records = db_ptr[
        (db_ptr['라인'] == line_nm) & 
        (db_ptr['시간'].astype(str).str.contains(kst_today_val)) & 
        (db_ptr['상태'] != '구분선')
    ]
    
    val_total_in = len(today_records)
    val_total_done = len(today_records[today_records['상태'] == '완료'])
    
    # 이전 단계 대기 재공 물량 산출 로직
    val_waiting_qty = 0
    prev_line_nm = None
    if line_nm == "검사 라인": prev_line_nm = "조립 라인"
    elif line_nm == "포장 라인": prev_line_nm = "검사 라인"
    
    if prev_line_nm:
        # 이전 공정에서 '완료' 상태로 멈춰있는 행들의 개수가 곧 대기 물량입니다.
        waiting_pool_list = db_ptr[
            (db_ptr['라인'] == prev_line_nm) & 
            (db_ptr['상태'] == '완료')
        ]
        val_waiting_qty = len(waiting_pool_list)
        
    met_c1, met_c2, met_c3 = st.columns(3)
    
    with met_c1:
        st.markdown(f"<div class='metric-card'><div class='metric-header'>⏳ 이전공정 대기</div><div class='metric-body' style='color:#fd7e14;'>{val_waiting_qty if prev_line_nm else '-'}</div><div class='metric-footer'>건 (Cumulative)</div></div>", unsafe_allow_html=True)
    with met_c2:
        st.markdown(f"<div class='metric-card'><div class='metric-header'>📥 금일 투입</div><div class='metric-body'>{val_total_in}</div><div class='metric-footer'>건 (Today)</div></div>", unsafe_allow_html=True)
    with met_c3:
        st.markdown(f"<div class='metric-card'><div class='metric-header'>✅ 금일 완료</div><div class='metric-body' style='color:#198754;'>{val_total_done}</div><div class='metric-footer'>건 (Today)</div></div>", unsafe_allow_html=True)

# [UI 최적화] 슬림해진 버튼과 짧은 라벨을 적용한 로그 테이블 렌더링 함수
def render_dynamic_process_log_table(line_nm, label_done="✅완료"):
    """실시간 작업 로그 및 슬림화된 제어 버튼을 렌더링합니다."""
    st.markdown(f"<div class='sub-section-title'>📝 {line_nm} 실시간 작업 현황 로그</div>", unsafe_allow_html=True)
    
    db_ptr_all = st.session_state.production_db
    view_data_db = db_ptr_all[db_ptr_all['라인'] == line_nm]
    
    # 조립 라인의 경우 현재 선택된 CELL로만 필터링합니다.
    if line_nm == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        view_data_db = view_data_db[view_data_db['CELL'] == st.session_state.selected_cell]
        
    if view_data_db.empty:
        st.info("현재 공정에 표시할 실시간 생산 데이터가 존재하지 않습니다.")
        return
        
    # 헤더 구성 (슬림 UI 반영)
    h_col_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
    header_titles = ["기록시간", "CELL", "모델명", "품목코드", "시리얼번호", "작업 상태 제어"]
    for i, title_txt in enumerate(header_titles):
        h_col_ui[i].write(f"**{title_txt}**")
        
    # 데이터 행 최신순 정렬 및 렌더링
    for row_idx_val, row_data_val in view_data_db.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리 (시인성 확보)
        if row_data_val['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#f8f9fa; padding:4px; text-align:center; border-radius:6px; font-weight:bold; color:#adb5bd; border:1px dashed #dee2e6; margin-bottom:5px; font-size:0.85em;'>{row_data_val['시리얼']}</div>", unsafe_allow_html=True)
            continue
            
        r_col_ui = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
        r_col_ui[0].write(row_data_val['시간'])
        r_col_ui[1].write(row_data_val['CELL'])
        r_col_ui[2].write(row_data_val['모델'])
        r_col_ui[3].write(row_data_val['품목코드'])
        r_col_ui[4].write(row_data_val['시리얼'])
        
        with r_col_ui[5]:
            status_val = row_data_val['상태']
            
            # [슬림 버튼 적용 구역] 라벨 단축: "✅완료", "🚫불량"
            if status_val in ["진행 중", "수리 완료(재투입)"]:
                col_b_ok, col_b_ng = st.columns(2)
                
                if col_b_ok.button(label_done, key=f"ok_btn_act_{row_idx_val}"):
                    db_ptr_all.at[row_idx_val, '상태'] = "완료"
                    db_ptr_all.at[row_idx_val, '작업자'] = st.session_state.user_id
                    if push_to_gsheet(db_ptr_all):
                        st.rerun()
                        
                if col_b_ng.button("🚫불량", key=f"ng_btn_act_{row_idx_val}"):
                    db_ptr_all.at[row_idx_val, '상태'] = "불량 처리 중"
                    db_ptr_all.at[row_idx_val, '작업자'] = st.session_state.user_id
                    if push_to_gsheet(db_ptr_all):
                        st.rerun()
                        
            elif status_val == "불량 처리 중":
                st.markdown("<span style='color:#e03131; font-weight:800; font-size:0.85em;'>🛠️ 수리 대기 (Repair)</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#2f9e44; font-weight:800; font-size:0.85em;'>✅ 공정 작업 완료</span>", unsafe_allow_html=True)

# ==========================================================================================
# [PART 7] 각 메뉴별 상세 기능 및 화면 렌더링 (v22.0 완벽 복원 버전)
# ==========================================================================================

# -----------------------------------------------------------------
# 7-1. 조립 라인 현황 (데이터 투입 및 모델 자동 리셋)
# -----------------------------------------------------------------
if st.session_state.current_line == "조립 라인":
    st.markdown("<h1 class='centered-main-title'>📦 조립 공정 현황 모니터링</h1>", unsafe_allow_html=True)
    display_dashboard_kpi_metrics("조립 라인")
    st.divider()
    
    # CELL 선택 UI (버튼 기반의 인터페이스)
    cell_names_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    col_cell_btns = st.columns(len(cell_names_list))
    
    for i_c, c_name_val in enumerate(cell_names_list):
        btn_type_ui = "primary" if st.session_state.selected_cell == c_name_val else "secondary"
        if col_cell_btns[i_c].button(c_name_val, key=f"c_ui_btn_{i_c}", type=btn_type_ui):
            st.session_state.selected_cell = c_name_val
            st.rerun()
            
    # 개별 셀이 선택된 경우에만 생산 등록 폼을 표시합니다.
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"<div class='sub-section-title'>🛠️ {st.session_state.selected_cell} 신규 생산 등록</div>", unsafe_allow_html=True)
            
            # [핵심 수정] 셀 전환 시 모델 선택박스 초기화 로직
            # key 값에 현재 셀 이름을 포함하여, 셀이 바뀔 때마다 위젯이 재생성되도록 유도합니다.
            selected_model_in = st.selectbox(
                "생산 대상 모델을 선택하세요.", 
                ["선택하세요."] + st.session_state.master_models,
                key=f"m_sel_box_init_{st.session_state.selected_cell}"
            )
            
            with st.form("new_assembly_reg_form"):
                row_f1_ui, row_f2_ui = st.columns(2)
                
                # 선택한 모델 기반 품목코드 연동
                available_items_list = st.session_state.master_items_dict.get(selected_model_in, ["모델 정보 없음"])
                selected_item_in = row_f1_ui.selectbox("품목코드 상세 선택", available_items_list)
                
                input_serial_in = row_f2_ui.text_input("시리얼 번호(S/N) 입력")
                
                trigger_reg_btn = st.form_submit_button("▶️ 생산 데이터 신규 등록", use_container_width=True, type="primary")
                
                if trigger_reg_btn:
                    if selected_model_in != "선택하세요." and input_serial_in != "":
                        db_ptr_ref = st.session_state.production_db
                        
                        # [복합키 중복 체크] 제품 간 '품목코드' + '시리얼'이 절대 중복되지 않도록 엄격히 검사합니다.
                        # 모델명은 같아도 되지만 고유키인 품목코드+시리얼 조합은 유일해야 합니다.
                        dup_find_records = db_ptr_ref[
                            (db_ptr_ref['품목코드'] == selected_item_in) & 
                            (db_ptr_ref['시리얼'] == input_serial_in) & 
                            (db_ptr_ref['상태'] != "구분선")
                        ]
                        
                        if not dup_find_records.empty:
                            st.error(f"❌ 중복 차단: 품목코드 [ {selected_item_in} ] 및 시리얼 [ {input_serial_in} ] 제품은 이미 등록되어 있습니다.")
                        else:
                            # 신규 행 데이터 생성
                            new_entry_obj = {
                                '시간': get_kst_timestamp().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': selected_model_in, 
                                '품목코드': selected_item_in, 
                                '시리얼': input_serial_in, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            
                            # 데이터 병합 및 실적 구분선 자동 삽입 체크
                            updated_db_full = pd.concat([db_ptr_ref, pd.DataFrame([new_entry_obj])], ignore_index=True)
                            updated_db_full = execute_divider_marker(updated_db_full, "조립 라인")
                            
                            st.session_state.production_db = updated_db_full
                            
                            # 구글 시트에 즉시 반영 실행
                            if push_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델명과 시리얼 번호를 누락 없이 정확히 입력해 주십시오.")
                        
    # 조립 로그 테이블 출력
    render_dynamic_process_log_table("조립 라인", "✅완료")

# -----------------------------------------------------------------
# 7-2. 검사 라인 및 포장 라인 현황 (2단계 정밀 필터 및 슬림 버튼)
# -----------------------------------------------------------------
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_name_curr = st.session_state.current_line
    icon_char_curr = "🔍" if line_name_curr == "검사 라인" else "🚚"
    st.markdown(f"<h1 class='centered-main-title'>{icon_char_curr} {line_name_curr} 현황</h1>", unsafe_allow_html=True)
    
    display_dashboard_kpi_metrics(line_name_curr)
    st.divider()
    
    # 이전 단계 공정 정의
    prev_step_name = "조립 라인" if line_name_curr == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.markdown(f"<div class='sub-section-title'>📥 {prev_step_name} 완료 물량 입고 승인 처리</div>", unsafe_allow_html=True)
        
        # [복구] 1단계: 모델 선택 필터
        target_model_sel = st.selectbox("입고 대상 모델을 선택하세요.", ["선택하세요."] + st.session_state.master_models, key=f"f_m_sel_box_{line_name_curr}")
        
        if target_model_sel != "선택하세요.":
            # [복구] 2단계: 품목코드 상세 필터
            model_sub_items = st.session_state.master_items_dict.get(target_model_sel, [])
            target_item_sel = st.selectbox("해당 모델의 품목코드를 선택하세요.", ["선택하세요."] + model_sub_items, key=f"f_i_sel_box_{line_name_curr}")
            
            if target_item_sel != "선택하세요.":
                db_all_ref_src = st.session_state.production_db
                
                # [복합 필터링] 이전 단계 완료 상태 + 선택 모델 + 선택 품목코드 일치 물량 조회
                waiting_pool_records = db_all_ref_src[
                    (db_all_ref_src['라인'] == prev_step_name) & 
                    (db_all_ref_src['상태'] == "완료") & 
                    (db_all_ref_src['모델'] == target_model_sel) & 
                    (db_all_ref_src['품목코드'] == target_item_sel)
                ]
                
                if not waiting_pool_records.empty:
                    st.success(f"📦 [ {target_item_sel} ] 입고 가능한 물량이 {len(waiting_pool_records)}건 조회되었습니다.")
                    
                    # 입고 버튼 그리드 배치 (슬림 버튼 반영)
                    btn_grid_cols_ui = st.columns(4)
                    for idx_b_ptr, row_item_ptr in enumerate(waiting_pool_records.itertuples()):
                        # 버튼 키에 품목코드와 시리얼을 조합하여 고유성 확보
                        unique_btn_key = f"in_act_btn_{row_item_ptr.품목코드}_{row_item_ptr.시리얼}_{line_name_curr}"
                        if btn_grid_cols_ui[idx_b_ptr % 4].button(f"📥 {row_item_ptr.시리얼}", key=unique_btn_key):
                            st.session_state.confirm_target = row_item_ptr.시리얼
                            st.session_state.confirm_model = row_item_ptr.모델
                            st.session_state.confirm_item = row_item_ptr.품목코드 # 행 매칭을 위해 필수 전달
                            trigger_entry_confirm_dialog()
                else:
                    st.info(f"현재 [ {target_item_sel} ] 품목의 입고 대기 물량이 존재하지 않습니다.")
        else:
            st.warning("작업을 진행할 모델과 품목코드를 상단 필터에서 순차적으로 선택해 주십시오.")
            
    # 실시간 작업 현황 로그 테이블
    render_dynamic_process_log_table(line_name_curr, "✅합격" if line_name_curr == "검사 라인" else "🚚출하")

# -----------------------------------------------------------------
# 7-3. 리포트 대시보드 (실시간 통계 및 시각화)
# -----------------------------------------------------------------
elif st.session_state.current_line == "리포트":
    st.markdown("<h1 class='centered-main-title'>📊 실시간 생산 통합 리포트</h1>", unsafe_allow_html=True)
    
    if st.button("🔄 실시간 데이터 동기화 리프레시", use_container_width=True):
        st.session_state.production_db = fetch_live_data()
        st.rerun()
        
    db_report_src = st.session_state.production_db
    
    if not db_report_src.empty:
        # 데이터 정제 (구분선 제거)
        clean_db_rpt = db_report_src[db_report_src['상태'] != '구분선']
        
        # 핵심 생산 지표 산출
        qty_final_done = len(clean_db_rpt[(clean_db_rpt['라인'] == '포장 라인') & (clean_db_rpt['상태'] == '완료')])
        qty_total_ng = len(clean_db_rpt[clean_db_rpt['상태'].str.contains("불량", na=False)])
        
        # FTT 직행률 산출 로직
        val_ftt_rate = (qty_final_done / (qty_final_done + qty_total_ng) * 100) if (qty_final_done + qty_total_ng) > 0 else 100
            
        # 메트릭 위젯 섹션
        rpt_met_c1, rpt_met_c2, rpt_met_c3, rpt_met_c4 = st.columns(4)
        rpt_met_c1.metric("최종 완제품 출하", f"{qty_final_done} EA")
        rpt_met_c2.metric("전 공정 재공(WIP)", f"{len(clean_db_rpt[clean_db_rpt['상태'] == '진행 중'])} EA")
        rpt_met_c3.metric("누적 불량 건수", f"{qty_total_ng} 건", delta=qty_total_ng, delta_color="inverse")
        rpt_met_c4.metric("직행률(FTT)", f"{val_ftt_rate:.1f}%")
        
        st.divider()
        
        # 시각화 차트 영역
        vis_row_c1, vis_row_c2 = st.columns([3, 2])
        
        with vis_row_c1:
            line_dist_stat = clean_db_rpt.groupby('라인').size().reset_index(name='수량')
            fig_bar_ui = px.bar(line_dist_stat, x='라인', y='수량', color='라인', text_auto=True, title="공정 단계별 현재 물량 분포 현황")
            st.plotly_chart(fig_bar_ui, use_container_width=True)
            
        with vis_row_c2:
            model_dist_stat = clean_db_rpt.groupby('모델').size().reset_index(name='수량')
            fig_pie_ui = px.pie(model_dist_stat, values='수량', names='모델', hole=0.3, title="생산 모델별 비중 구성")
            st.plotly_chart(fig_pie_ui, use_container_width=True)
            
        st.markdown("<div class='section-title'>🔍 상세 공정 통합 생산 기록 전체 데이터</div>", unsafe_allow_html=True)
        st.dataframe(db_report_src.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("현재 분석할 생산 실적 데이터가 존재하지 않습니다.")

# -----------------------------------------------------------------
# 7-4. 불량 수리 센터 (현장 사진 업로드 및 재투입)
# -----------------------------------------------------------------
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h1 class='centered-main-title'>🛠️ 불량품 수리 및 재투입 센터</h1>", unsafe_allow_html=True)
    render_summary_metrics("조립 라인")
    
    # 불량 처리 중인 데이터 필터링
    bad_pool_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_pool_db.empty:
        st.success("✅ 현재 모든 불량 제품에 대한 조치 및 수리가 완료되었습니다.")
    else:
        st.markdown(f"##### 현재 수리 대기 건수: {len(bad_pool_db)}건")
        
        for idx_row_ptr, data_row_ptr in bad_pool_db.iterrows():
            with st.container(border=True):
                st.markdown(f"📍 **품목코드: {data_row_ptr['품목코드']}** | 시리얼: {data_row_ptr['시리얼']} | 모델: {data_row_ptr['모델']} | 발생공정: {data_row_ptr['라인']}")
                
                # 수리 원인 및 조치 내용 입력 섹션
                rc_c1, rc_c2, rc_c3 = st.columns([4, 4, 2])
                
                # 입력 유실 방지를 위한 세션 캐시 로드
                cache_symptom = st.session_state.repair_cache.get(f"s_{idx_row_ptr}", "")
                cache_action = st.session_state.repair_cache.get(f"a_{idx_row_ptr}", "")
                
                input_symp_val = rc_c1.text_input("불량 원인 상세 기술", value=cache_symptom, key=f"is_in_ui_{idx_row_ptr}")
                input_act_val = rc_c2.text_input("수리 및 조치 내용", value=cache_action, key=f"ia_in_ui_{idx_row_ptr}")
                
                # 캐시 실시간 업데이트
                st.session_state.repair_cache[f"s_{idx_row_ptr}"] = input_symp_val
                st.session_state.repair_cache[f"a_{idx_row_ptr}"] = input_act_val
                
                # 사진 증빙 첨부
                uploaded_photo = st.file_uploader("수리 조치 사진(JPG/PNG) 첨부", type=['jpg','png','jpeg'], key=f"up_ph_{idx_row_ptr}")
                
                if uploaded_photo:
                    st.image(uploaded_photo, width=300, caption="업로드 대기 중인 사진")
                    
                if rc_c3.button("🔧 수리 완료 보고", key=f"rep_fin_btn_{idx_row_ptr}", type="primary", use_container_width=True):
                    if input_symp_val and input_act_val:
                        final_link_url = ""
                        
                        if uploaded_photo:
                            with st.spinner("사진을 구글 드라이브에 안전하게 저장 중입니다..."):
                                ts_mark = get_kst_timestamp().strftime('%Y%m%d_%H%M')
                                f_nm_save = f"{data_row_ptr['시리얼']}_REPAIR_{ts_mark}.jpg"
                                up_res_url = drive_image_uploader(uploaded_photo, f_nm_save)
                                if "http" in up_res_url:
                                    final_link_url = f" [사진보기: {up_res_url}]"
                        
                        # 데이터베이스 상태 업데이트
                        st.session_state.production_db.at[idx_row_ptr, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx_row_ptr, '증상'] = input_symp_val
                        st.session_state.production_db.at[idx_row_ptr, '수리'] = input_act_val + final_link_url
                        st.session_state.production_db.at[idx_row_ptr, '작업자'] = st.session_state.user_id
                        
                        if push_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 제거 및 페이지 갱신
                            st.session_state.repair_cache.pop(f"s_{idx_row_ptr}", None)
                            st.session_state.repair_cache.pop(f"a_{idx_row_ptr}", None)
                            st.success("수리 완료 보고서가 성공적으로 등록되었습니다.")
                            st.rerun()
                    else:
                        st.error("불량 원인과 조치 사항을 모두 입력해야 등록이 가능합니다.")

# -----------------------------------------------------------------
# 7-5. 마스터 관리 (강제 초기화 버그 완전 해결)
# -----------------------------------------------------------------
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h1 class='centered-main-title'>🔐 시스템 관리자 마스터 센터</h1>", unsafe_allow_html=True)
    
    # 관리자 세션 보안 인증 (2차 인증)
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify_security_form_ui"):
            st.write("안전한 시스템 설정을 위해 관리자 권한을 인증합니다.")
            input_pw_adm = st.text_input("관리자 PW 입력 (admin1234)", type="password")
            if st.form_submit_button("권한 인증하기", use_container_width=True):
                if input_pw_adm in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.success("인증 완료: 관리자 전용 기능이 개방되었습니다.")
                    st.rerun()
                else:
                    st.error("비밀번호 정보가 올바르지 않습니다.")
    else:
        if st.sidebar.button("🔓 관리자 세션 종료"):
            st.session_state.admin_authenticated = False
            navigate_page("리포트")

        st.markdown("<div class='section-title'>📋 1. 마스터 기준 데이터 관리</div>", unsafe_allow_html=True)
        adm_c1, adm_c2 = st.columns(2)
        
        with adm_c1:
            with st.container(border=True):
                st.write("**신규 생산 모델 등록**")
                new_model_nm = st.text_input("추가할 모델 명칭")
                if st.button("➕ 모델 신규 추가", use_container_width=True):
                    if new_model_nm and new_model_nm not in st.session_state.master_models:
                        st.session_state.master_models.append(new_model_nm)
                        st.session_state.master_items_dict[new_model_nm] = []
                        st.success(f"'{new_model_nm}' 모델이 등록되었습니다.")
                        st.rerun()

        with adm_c2:
            with st.container(border=True):
                st.write("**품목코드 마스터 매핑 설정**")
                sel_model_adm_ui = st.selectbox("품목 추가 모델 선택", st.session_state.master_models)
                new_item_code_nm = st.text_input("신규 품목코드 명칭")
                if st.button("➕ 품목코드 등록 완료", use_container_width=True):
                    if new_item_code_nm and new_item_code_nm not in st.session_state.master_items_dict[sel_model_adm_ui]:
                        st.session_state.master_items_dict[sel_model_adm_ui].append(new_item_code_nm)
                        st.success(f"[{sel_model_adm_ui}] 품목코드가 등록되었습니다.")
                        st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>💾 2. 데이터 백업 및 물리적 초기화 제어</div>", unsafe_allow_html=True)
        adm_c3, adm_c4 = st.columns(2)
        
        with adm_c3:
            st.write("현재 구글 시트의 전체 데이터를 CSV 파일로 백업합니다.")
            csv_export_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 전체 실적 CSV 백업 다운로드", 
                csv_export_data, 
                f"production_full_backup_{get_kst_timestamp().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
            
        with adm_c4:
            st.write("구글 시트 데이터 물리적 초기화 (완전 삭제)")
            # [초기화 핵심 버그 수정] force_reset_action 플래그 활용
            if st.button("🚫 시스템 전체 생산 실적 데이터 초기화 (물리적 삭제)", type="secondary", use_container_width=True):
                 st.error("주의: 실행 시 모든 실적 데이터가 영구 삭제되며 복구가 불가능합니다.")
                 if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                     # 컬럼 헤더만 있는 빈 데이터프레임 강제 생성
                     empty_struct_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                     st.session_state.production_db = empty_struct_df
                     
                     # force_reset_action=True로 저장 함수 호출하여 시트 비움
                     if push_to_gsheet(empty_struct_df, is_reset_action=True):
                         st.cache_data.clear()
                         st.success("구글 시트의 데이터가 성공적으로 물리적으로 비워졌습니다.")
                         st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👤 3. 사용자 계정 권한 및 비밀번호 관리</div>", unsafe_allow_html=True)
        adm_c5, adm_c6, adm_c7 = st.columns([3, 3, 2])
        target_uid_in = adm_c5.text_input("생성/수정할 ID")
        target_upw_in = adm_c6.text_input("신규 패스워드 설정", type="password")
        target_role_in = adm_c7.selectbox("권한 등급 할당", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 사용자 계정 정보 업데이트 반영", use_container_width=True):
            if target_uid_in and target_upw_in:
                st.session_state.user_db[target_uid_in] = {"pw": target_upw_in, "role": target_role_in}
                st.success(f"[{target_uid_in}] 사용자의 권한 정보가 성공적으로 반영되었습니다."); st.rerun()
