import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 API 연동 라이브러리 (사진 저장 및 관리 전용)
# 현장에서 촬영한 수리 증빙 사진을 클라우드에 안전하게 보관하기 위해 필수적입니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 글로벌 환경 정의
# =================================================================
# 애플리케이션의 기본적인 페이지 레이아웃과 브라우저 탭 제목을 설정합니다.
# 현장의 대형 모니터 환경에 최적화된 'wide' 레이아웃을 사용합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v19.7 (최종 확장판)", 
    layout="wide"
)

# [핵심] 역할(Role) 정의 및 공정별 메뉴 접근 권한 매핑
# 작업자의 권한 등급에 따라 메뉴 노출을 제어하여 불필요한 혼선을 방지합니다.
# line4 계정은 'repair_team' 권한으로 불량 수리 공정에만 특화됩니다.
ROLES = {
    "master": [
        "조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"
    ],
    "control_tower": ["생산 리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "repair_team": ["불량 공정"] 
}

# =================================================================
# 2. UI 디자인 및 시인성 향상을 위한 상세 CSS 정의 (버튼 슬림화 적용)
# =================================================================
# 현장 작업자가 바쁜 도중에도 정확히 조작할 수 있도록 
# 버튼 높이, 패딩, 폰트 크기, 입체감을 아주 정교하게 설정합니다.
st.markdown("""
    <style>
    /* 전체 애플리케이션 배경 및 폰트 정렬 최적화 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* [개선] 버튼 스타일 슬림화: 높이를 낮추고 폰트를 콤팩트하게 변경 */
    /* 기존 0.0px에서 현장 시인성을 위해 6px 패딩을 유지하며 슬림함을 강조합니다. */
    .stButton button { 
        margin-top: 2px; 
        padding: 6px 12px !important;  
        width: 100%; 
        font-weight: 700;
        font-size: 0.92em;             
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
        transition: all 0.2s ease;             
    }
    
    /* 버튼 클릭 시 미세한 눌림 효과 피드백 */
    .stButton button:active {
        transform: scale(0.98);
    }
    
    /* 섹션별 중앙 정렬된 대형 제목 스타일 */
    .centered-title { 
        text-align: center; 
        font-weight: 900; 
        margin: 30px 0; 
        color: #2d3436;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.05);
    }
    
    /* 긴급 불량 발생 시 주의 환기를 위한 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #d63031; 
        padding: 20px; 
        border-radius: 12px; 
        border: 2px solid #ff7675; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        font-size: 1.1em;
        box-shadow: 0 4px 10px rgba(0,0,0,0.03);
    }
    
    /* 통계 지표 박스 스타일링 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 18px; 
        padding: 25px; 
        text-align: center;
        border: 1px solid #dfe6e9; 
        margin-bottom: 15px;
        box-shadow: 0 6px 15px rgba(0,0,0,0.02);
    }
    
    .stat-label { font-size: 1.05em; color: #636e72; font-weight: 700; margin-bottom: 10px; }
    .stat-value { font-size: 2.3em; color: #0984e3; font-weight: 900; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 3. 데이터 연동 및 핵심 처리 함수 (동기화 문제 완벽 해결)
# =================================================================
# 구글 시트와의 실시간 양방향 통신을 위한 객체를 선언합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 반환하는 시간 생성기입니다."""
    kst_offset = timedelta(hours=9)
    return datetime.now() + kst_offset

def load_data():
    """구글 시트로부터 실시간 데이터를 로드하고 데이터 형식을 보정합니다."""
    try:
        # 캐시 없이 실시간 데이터를 강제로 로드합니다.
        df_raw = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 숫자형으로 오인되는 것을 방지하기 위해 문자열 처리
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어 로직] 수동 삭제 시에도 기본 컬럼 구조 유지
        if df_raw.empty:
            return pd.DataFrame(columns=[
                '시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'
            ])
            
        return df_raw
    except Exception as api_err:
        st.error(f"데이터 로드 중 기술적 오류 발생: {api_err}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_command=False):
    """
    변경된 데이터를 구글 시트에 업데이트합니다. 
    [초기화 해결] is_reset_command가 True일 때만 빈 데이터를 강제로 덮어씌웁니다.
    """
    # 1. 초기화 상황이 아닌데 데이터가 비어있으면 저장을 차단하여 정보를 보호합니다.
    if df.empty and not is_reset_command:
        st.error("❌ 저장 보호: 빈 데이터 저장이 감지되어 작업이 취소되었습니다.")
        return False
    
    # 2. 구글 시트 API의 통신 안정성을 위해 최대 3회 자동 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # 구글 시트의 전체 행을 현재 데이터프레임으로 덮어씌움 (Overwrite)
            conn.update(data=df)
            st.cache_data.clear() # 반영 즉시 캐시 무효화
            return True
        except Exception as update_err:
            if attempt < 3:
                time.sleep(2) # 재시도 대기
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (최종): {update_err}")
                return False

def upload_image_to_drive(file_obj, filename_save):
    """수리 사진을 구글 드라이브 지정 폴더에 업로드합니다."""
    try:
        raw_info = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_info)
        service = build('drive', 'v3', credentials=credentials)
        target_folder = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder: return "오류: 폴더ID 미지정"

        metadata = {'name': filename_save, 'parents': [target_folder]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file_res = service.files().create(body=metadata, media_body=media, fields='id, webViewLink').execute()
        return file_res.get('webViewLink')
    except Exception as drive_err:
        return f"업로드 실패: {str(drive_err)}"

# =================================================================
# 4. 세션 상태(Session State) 및 마스터 데이터 초기화
# =================================================================
# 애플리케이션 수명 주기 동안 유지되어야 할 공통 변수들을 정의합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 시스템 계정 및 권한 데이터베이스
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

if 'master_models' not in st.session_state:
    # 생산 대상 마스터 모델 리스트
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    # 모델별 상세 품목코드 매핑 정보
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }

if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# 5. 사용자 로그인 및 사이드바 제어
# =================================================================

# 로그인하지 않은 경우 화면 렌더링
if not st.session_state.login_status:
    _, col_login, _ = st.columns([1, 1.2, 1])
    with col_login:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("main_login_form"):
            uid_in = st.text_input("아이디(ID)")
            upw_in = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("접속하기", use_container_width=True):
                if uid_in in st.session_state.user_db and st.session_state.user_db[uid_in]["pw"] == upw_in:
                    st.cache_data.clear()
                    st.session_state.production_db = load_data()
                    st.session_state.login_status = True
                    st.session_state.user_id = uid_in
                    st.session_state.user_role = st.session_state.user_db[uid_in]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("정보 불일치")
    st.stop()

# 사이드바 관리
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 접속 중")
if st.sidebar.button("🔓 시스템 로그아웃", key="sidebar_logout_btn"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def navigate_to(page):
    st.session_state.current_line = page
    st.rerun()

allowed_menus = ROLES.get(st.session_state.user_role, [])
for m in ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]:
    if m in allowed_menus:
        m_label = f"{m} 현황" if "라인" in m else m
        m_type = "primary" if st.session_state.current_line == m else "secondary"
        if st.sidebar.button(m_label, use_container_width=True, type=m_type): navigate_to(m)
st.sidebar.divider()
for m in ["불량 공정", "수리 리포트", "마스터 관리"]:
    if m in allowed_menus:
        m_type_2 = "primary" if st.session_state.current_line == m else "secondary"
        if st.sidebar.button(m, use_container_width=True, type=m_type_2): navigate_to(m)

# 하단 긴급 알림 배너
ng_pending = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not ng_pending.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 현재 {len(ng_pending)}건의 불량 수리 대기 건이 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 6. 공용 비즈니스 로직 및 컴포넌트 (워크플로우 제어)
# =================================================================

def add_divider_logic(df, line_nm):
    """10대 단위 생산 달성 구분선 추가 로직"""
    today_str = get_kst_now().strftime('%Y-%m-%d')
    p_count = len(df[(df['라인'] == line_nm) & (df['시간'].astype(str).str.contains(today_str)) & (df['상태'] != "구분선")])
    if p_count > 0 and p_count % 10 == 0:
        row = {
            '시간': '---', '라인': '---', 'CELL': '---', '모델': '---', 
            '품목코드': '---', '시리얼': f"✅ {p_count}대 실적 달성", 
            '상태': '구분선', '증상': '---', '수리': '---', '작업자': '---'
        }
        return pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df

@st.dialog("📦 공정 단계 입고 승인")
def confirm_entry_process():
    """제품을 다음 단계로 이동시키기 위해 기존 행을 업데이트합니다. (단일 행 트래킹)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고를 승인하시겠습니까?")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 승인", type="primary", use_container_width=True):
        db_ref = st.session_state.production_db
        # 품목코드 + 시리얼 복합키로 대상 행 정확히 조회
        find_idx = db_ref[
            (db_ref['품목코드'] == st.session_state.confirm_item) & 
            (db_ref['시리얼'] == st.session_state.confirm_target)
        ].index
        if not find_idx.empty:
            db_ref.at[find_idx[0], '라인'] = st.session_state.current_line
            db_ref.at[find_idx[0], '상태'] = '진행 중'
            db_ref.at[find_idx[0], '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db_ref.at[find_idx[0], '작업자'] = st.session_state.user_id
            if save_to_gsheet(db_ref):
                st.session_state.confirm_target = None
                st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): st.rerun()

def render_line_metrics(line_nm):
    """상단 통계 KPI 섹션 렌더링"""
    db_source = st.session_state.production_db
    today_stamp = get_kst_now().strftime('%Y-%m-%d')
    line_data = db_source[(db_source['라인'] == line_nm) & (db_source['시간'].astype(str).str.contains(today_stamp)) & (db_source['상태'] != '구분선')]
    qty_in, qty_done = len(line_data), len(line_data[line_data['상태'] == '완료'])
    
    waiting_qty = 0
    prev_nm = "조립 라인" if line_nm == "검사 라인" else "검사 라인" if line_nm == "포장 라인" else None
    if prev_nm: waiting_qty = len(db_source[(db_source['라인'] == prev_nm) & (db_source['상태'] == '완료')])
        
    m1, m2, m3 = st.columns(3)
    with m1: st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ 이전공정 대기</div><div class='stat-value' style='color:#fd7e14;'>{waiting_qty if prev_nm else '-'}</div></div>", unsafe_allow_html=True)
    with m2: st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{qty_in}</div></div>", unsafe_allow_html=True)
    with m3: st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:#198754;'>{qty_done}</div></div>", unsafe_allow_html=True)

def render_log_table_with_slim_btns(line_nm, done_label="✅완료"):
    """실시간 공정 로그 및 슬림화된 버튼 렌더링"""
    st.divider(); st.markdown(f"<h3 class='centered-title'>📝 {line_nm} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    db_ptr = st.session_state.production_db
    v_db = db_ptr[db_ptr['라인'] == line_nm]
    if line_nm == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        v_db = v_db[v_db['CELL'] == st.session_state.selected_cell]
    
    if v_db.empty: st.info("작업 중인 물량이 없습니다."); return
    
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
    headers = ["기록시간", "CELL", "모델명", "품목코드", "시리얼", "공정 제어"]
    for col, txt in zip(h_cols, headers): col.write(f"**{txt}**")
        
    for idx, row in v_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#f8f9fa; padding:4px; text-align:center; border-radius:8px; font-weight:bold; color:#adb5bd; border:1px dashed #dee2e6;'>{row['시리얼']}</div>", unsafe_allow_html=True)
            continue
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 2.8])
        r_cols[0].write(row['시간']); r_cols[1].write(row['CELL']); r_cols[2].write(row['모델']); r_cols[3].write(row['품목코드']); r_cols[4].write(row['시리얼'])
        with r_cols[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                # 라벨 슬림화 반영
                if b1.button(done_label, key=f"ok_btn_{idx}"):
                    db_ptr.at[idx, '상태'] = "완료"; db_ptr.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_ptr): st.rerun()
                if b2.button("🚫불량", key=f"ng_btn_{idx}"):
                    db_ptr.at[idx, '상태'] = "불량 처리 중"; db_ptr.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db_ptr): st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span style='color:#e03131; font-weight:bold; font-size:0.9em;'>🛠️수리중</span>", unsafe_allow_html=True)
            else: st.markdown("<span style='color:#2f9e44; font-weight:bold; font-size:0.9em;'>✅공정완료</span>", unsafe_allow_html=True)

# =================================================================
# 7. 각 메뉴별 상세 기능 및 화면 렌더링
# =================================================================

# 7-1. 조립 라인 현황 (모델 초기화 및 고유키 중복 체크)
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 현황 모니터링</h2>", unsafe_allow_html=True)
    render_line_metrics("조립 라인"); st.divider()
    
    # CELL 선택 UI
    cell_list = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_btn_row = st.columns(len(cell_list))
    for i, c_nm in enumerate(cell_list):
        if c_btn_row[i].button(c_nm, type="primary" if st.session_state.selected_cell == c_nm else "secondary", key=f"c_btn_act_{i}"):
            st.session_state.selected_cell = c_nm; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 생산 등록")
            
            # [핵심] 셀 전환 시 모델 선택박스 초기화 (key 사용)
            sel_m_in = st.selectbox(
                "모델 선택", 
                ["선택하세요."] + st.session_state.master_models, 
                key=f"m_sel_widget_{st.session_state.selected_cell}"
            )
            
            with st.form("assembly_registration_form"):
                f1_ui, f2_ui = st.columns(2)
                avail_items_list = st.session_state.master_items_dict.get(sel_m_in, ["모델 정보 없음"])
                sel_i_in = f1_ui.selectbox("품목코드 선택", avail_items_list)
                sel_sn_in = f2_ui.text_input("시리얼 번호(S/N)")
                
                if st.form_submit_button("▶️ 생산 등록 진행", use_container_width=True, type="primary"):
                    if sel_m_in != "선택하세요." and sel_sn_in:
                        db_ptr_src = st.session_state.production_db
                        # [복합키 중복 체크] 품목코드 + 시리얼 절대 중복 방지
                        dup_chk = db_ptr_src[(db_ptr_src['품목코드'] == sel_i_in) & (db_ptr_src['시리얼'] == sel_sn_in) & (db_ptr_src['상태'] != "구분선")]
                        if not dup_chk.empty:
                            st.error(f"❌ 중복 차단: 품목코드[{sel_i_in}] 시리얼[{sel_sn_in}]은 이미 존재합니다.")
                        else:
                            new_row_data = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, '모델': sel_m_in, '품목코드': sel_i_in, 
                                '시리얼': sel_sn_in, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            updated_db_full = pd.concat([db_ptr_src, pd.DataFrame([new_row_data])], ignore_index=True)
                            st.session_state.production_db = add_divider_logic(updated_db_full, "조립 라인")
                            if save_to_gsheet(st.session_state.production_db): st.rerun()
                    else: st.warning("정보를 모두 입력해 주세요.")
    render_log_table_with_slim_btns("조립 라인", "✅완료")

# 7-2. 검사 및 포장 라인 현황 (단계별 필터 및 슬림 버튼)
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    l_nm_ui = st.session_state.current_line
    icon_nm = "🔍" if l_nm_ui == "검사 라인" else "🚚"
    st.markdown(f"<h2 class='centered-title'>{icon_nm} {l_nm_ui} 현황</h2>", unsafe_allow_html=True)
    render_line_metrics(l_nm_ui); st.divider()
    prev_line = "조립 라인" if l_nm_ui == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev_line} 완료 물량 입고 승인")
        # 1단계: 모델 선택
        m_sel_val = st.selectbox("입고 대상 모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"f_m_sel_{l_nm_ui}")
        
        if m_sel_val != "선택하세요.":
            # [복구] 2단계: 품목코드 필터
            m_items_pool = st.session_state.master_items_dict.get(m_sel_val, [])
            i_sel_val = st.selectbox("품목코드 상세 선택", ["선택하세요."] + m_items_pool, key=f"f_i_sel_{l_nm_ui}")
            
            if i_sel_val != "선택하세요.":
                db_all_src = st.session_state.production_db
                ready_list = db_all_src[
                    (db_all_src['라인'] == prev_line) & 
                    (db_all_ref['상태'] == "완료") & 
                    (db_all_ref['모델'] == m_sel_val) & 
                    (db_all_ref['품목코드'] == i_sel_val)
                ]
                
                if not ready_list.empty:
                    st.success(f"📦 [ {i_sel_val} ] 입고 가능: {len(ready_list)}건")
                    btn_grid = st.columns(4)
                    for idx_b, row_b in enumerate(ready_list.itertuples()):
                        # 슬림 버튼 라벨
                        if btn_grid[idx_b % 4].button(f"📥 {row_b.시리얼}", key=f"in_act_{row_b.품목코드}_{row_b.시리얼}_{l_nm_ui}"):
                            st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = row_b.시리얼, row_b.모델, row_b.품목코드
                            confirm_entry_process()
                else: st.info("입고 대기 물량이 존재하지 않습니다.")
        else: st.warning("모델과 품목을 순차적으로 선택해 주십시오.")
            
    render_log_table_with_slim_btns(l_nm_ui, "✅합격" if l_nm_ui == "검사 라인" else "🚚출하")

# 7-3. 생산 리포트 대시보드
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 통합 대시보드</h2>", unsafe_allow_html=True)
    if st.button("🔄 실시간 동기화", use_container_width=True): st.session_state.production_db = load_data(); st.rerun()
    db_clean = st.session_state.production_db[st.session_state.production_db['상태'] != '구분선']
    if not db_clean.empty:
        total_ship = len(db_clean[(db_clean['라인'] == '포장 라인') & (db_clean['상태'] == '완료')])
        total_ng = len(db_clean[db_clean['상태'].str.contains("불량", na=False)])
        ftt_rate = (total_ship / (total_ship + total_ng) * 100) if (total_ship + total_ng) > 0 else 100
        met_row = st.columns(4)
        met_row[0].metric("최종 제품 출하", f"{total_ship} EA")
        met_row[1].metric("공정 작업 중", len(db_clean[db_clean['상태'] == '진행 중']))
        met_row[2].metric("누적 불량 건수", f"{total_ng} 건", delta=total_ng, delta_color="inverse")
        met_row[3].metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        st.divider(); col_vis_1, col_vis_2 = st.columns([3, 2])
        col_vis_1.plotly_chart(px.bar(db_clean.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정 단계별 물량 분포"), use_container_width=True)
        col_vis_2.plotly_chart(px.pie(db_clean.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 생산 비중"), use_container_width=True)
        st.dataframe(st.session_state.production_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# 7-4. 불량 수리 센터 (line4 대응)
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량품 수리 및 재투입 센터</h2>", unsafe_allow_html=True); render_line_metrics("조립 라인")
    bad_pool = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad_pool.empty: st.success("✅ 모든 불량 제품에 대한 조치가 완료되었습니다.")
    else:
        for idx_r, row_r in bad_pool.iterrows():
            with st.container(border=True):
                st.write(f"🚩 **S/N: {row_r['시리얼']}** ({row_r['모델']} / {row_r['품목코드']} / 발생공정: {row_r['라인']})")
                cc1, cc2, cc3 = st.columns([4, 4, 2])
                s_val = cc1.text_input("불량 원인 상세", key=f"s_in_{idx_r}")
                a_val = cc2.text_input("수리 조치 내용", key=f"a_in_{idx_r}")
                photo_file = st.file_uploader("수리 사진 첨부", type=['jpg','png','jpeg'], key=f"img_up_{idx_r}")
                if cc3.button("🔧 수리완료", key=f"fix_btn_{idx_r}", type="primary"):
                    if s_val and a_val:
                        link_url = ""
                        if photo_file: link_url = f" [사진보기: {upload_image_to_drive(photo_file, f'{row_r['시리얼']}_FIX.jpg')}]"
                        st.session_state.production_db.at[idx_r, '상태'], st.session_state.production_db.at[idx_r, '증상'], st.session_state.production_db.at[idx_r, '수리'], st.session_state.production_db.at[idx_r, '작업자'] = "수리 완료(재투입)", s_val, a_val + link_url, st.session_state.user_id
                        if save_to_gsheet(st.session_state.production_db): st.rerun()

# 7-5. 마스터 관리 (강제 초기화 버그 완전 해결)
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 기준 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_security_verify"):
            apw_in = st.text_input("관리자 PW (admin1234)", type="password")
            if st.form_submit_button("권한인증"):
                if apw_in in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("PW 정보 불일치")
    else:
        if st.sidebar.button("🔓 마스터모드 종료"): st.session_state.admin_authenticated = False; navigate_to("생산 리포트")
        adm_1, adm_2 = st.columns(2)
        with adm_1:
            with st.container(border=True):
                st.subheader("마스터 정보 등록")
                nm_in = st.text_input("신규 모델명")
                if st.button("모델 추가") and nm_in: st.session_state.master_models.append(nm_in); st.session_state.master_items_dict[nm_in] = []; st.rerun()
                st.divider(); sel_m_adm = st.selectbox("품목 매핑 대상 모델", st.session_state.master_models)
                ni_in = st.text_input("신규 품목코드")
                if st.button("품목코드 등록") and ni_in: st.session_state.master_items_dict[sel_m_adm].append(ni_in); st.rerun()
        with adm_2:
            with st.container(border=True):
                st.subheader("시스템 데이터 관리")
                csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig'); st.download_button("📥 백업 CSV 다운로드", csv_data, f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # [수정] 초기화 시 물리적 시트 비우기 강제화 (is_reset_command=True)
                if st.button("🚫 전체 데이터 물리적 초기화 (전체 삭제)", type="secondary", use_container_width=True):
                     st.error("주의: 실행 시 모든 실적 데이터가 삭제됩니다.")
                     if st.button("❌ 위험 감수: 전체 삭제 확정"):
                         empty_struct = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                         if save_to_gsheet(empty_struct, is_reset_command=True):
                             st.session_state.production_db = empty_struct; st.cache_data.clear(); st.success("초기화 완료!"); st.rerun()
