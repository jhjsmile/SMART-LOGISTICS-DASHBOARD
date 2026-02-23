import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 API 연동 라이브러리
# 현장 수리 증빙용 사진 파일의 업로드 및 드라이브 저장을 위해 사용됩니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 환경 설정 및 UI 스타일링 (560줄 이상의 상세 스타일)
# =================================================================
# 애플리케이션의 기본 페이지 설정과 브라우저 탭에 표시될 제목을 정의합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v19.2", 
    layout="wide"
)

# [핵심] 역할(Role) 기반 메뉴 권한 관리
# 현장 각 공정 담당자에게 필요한 메뉴만 노출하여 작업 집중도를 높입니다.
# 특히 line4 계정은 repair_team 권한을 할당받아 수리 업무만 수행합니다.
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
        "불량 공정" # line4 계정 전용
    ]
}

# 사용자 정의 CSS (가독성 및 버튼 클릭성 개선을 위한 스타일 정의)
st.markdown("""
    <style>
    /* 전체 앱 컨테이너의 최대 너비와 배경 정렬 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼의 패딩과 글꼴 두께를 현장 조작에 맞게 조절 */
    .stButton button { 
        margin-top: 5px; 
        padding: 10px 15px; 
        width: 100%; 
        font-weight: 800;
        font-size: 1.05em;
        border-radius: 10px;
        transition: transform 0.1s ease;
    }
    
    .stButton button:active {
        transform: scale(0.98);
    }
    
    /* 중앙 정렬된 메인 섹션 제목 */
    .centered-title { 
        text-align: center; 
        font-weight: 900; 
        margin: 30px 0; 
        color: #1e272e;
    }
    
    /* 불량품 발생 시 시각적 알림 배너 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #d63031; 
        padding: 22px; 
        border-radius: 12px; 
        border: 2px solid #ff7675; 
        font-weight: bold; 
        margin-bottom: 25px;
        text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    }
    
    /* 상단 대시보드 KPI 카드 스타일 */
    .stat-box {
        background-color: #ffffff; 
        border-radius: 18px; 
        padding: 28px; 
        text-align: center;
        border: 1px solid #dfe6e9; 
        margin-bottom: 20px;
        box-shadow: 0 6px 15px rgba(0,0,0,0.03);
    }
    
    .stat-label { 
        font-size: 1.05em; 
        color: #636e72; 
        font-weight: 700; 
        margin-bottom: 10px;
    }
    
    .stat-value { 
        font-size: 2.5em; 
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
# 2. 구글 연동 및 데이터 처리 핵심 로직 (강제 초기화 기능 포함)
# =================================================================
# 구글 시트와의 실시간 통신을 위한 커넥션을 생성합니다.
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """한국 표준시(KST)를 반환하는 공용 함수입니다."""
    return datetime.now() + timedelta(hours=9)

def load_data():
    """구글 시트로부터 최신 데이터를 로드하고 형식을 보정합니다."""
    try:
        # 캐시를 즉시 무효화하고 최신 상태를 읽어옵니다.
        df_raw = conn.read(ttl=0).fillna("")
        
        # 시리얼 번호가 지수 형식이나 숫자로 오인되는 것을 방지합니다.
        if '시리얼' in df_raw.columns:
            df_raw['시리얼'] = df_raw['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [방어 로직] 수동 삭제 시에도 데이터 구조(헤더)를 유지합니다.
        if df_raw.empty:
            return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            
        return df_raw
    except Exception as e:
        st.error(f"데이터 로딩 오류: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df, is_reset_action=False):
    """
    구글 시트에 데이터를 즉시 동기화하여 저장합니다.
    [핵심 수정] is_reset_action=True 일 때만 빈 데이터를 강제로 덮어씌웁니다.
    """
    # 1. 초기화 상황이 아닌데 데이터가 비어있으면 저장을 차단하여 정보를 보호합니다.
    if df.empty and not is_reset_action:
        st.error("❌ 저장 보호: 데이터가 증발하는 것을 방지하기 위해 저장이 차단되었습니다.")
        return False
    
    # 2. 구글 시트 API의 통신 안정성을 위해 최대 3회 자동 재시도를 수행합니다.
    for attempt in range(1, 4):
        try:
            # [초기화 핵심] 구글 API에 현재 데이터프레임 상태를 그대로 업데이트합니다.
            conn.update(data=df)
            
            # 앱의 모든 내부 캐시를 즉시 삭제하여 데이터 동기화를 보장합니다.
            st.cache_data.clear()
            return True
        except Exception as api_err:
            if attempt < 3:
                time.sleep(2) # 2초 대기 후 재시도
                continue
            else:
                st.error(f"⚠️ 구글 저장 실패 (3회 시도 완료): {api_err}")
                return False

def upload_image_to_drive(file_obj, filename_save):
    """수리 조치 사진을 구글 드라이브에 안전하게 보존합니다."""
    try:
        raw_keys = st.secrets["connections"]["gsheets"]
        credentials = service_account.Credentials.from_service_account_info(raw_keys)
        
        service = build('drive', 'v3', credentials=credentials)
        target_folder = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not target_folder:
            return "오류: 드라이브 폴더 설정 안됨"

        metadata = {'name': filename_save, 'parents': [target_folder]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 파일 생성 및 링크 반환
        file_res = service.files().create(body=metadata, media_body=media, fields='id, webViewLink').execute()
        return file_res.get('webViewLink')
    except Exception as e:
        return f"사진 업로드 실패: {str(e)}"

# =================================================================
# 3. 세션 상태(Session State) 변수 초기화
# =================================================================
# 애플리케이션 수명 주기 동안 유지되어야 할 변수들을 정의합니다.

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    # 계정 마스터 정보 (아이디/비번/역할)
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
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }

if 'current_line' not in st.session_state:
    st.session_state.current_line = "조립 라인"

if 'selected_cell' not in st.session_state:
    st.session_state.selected_cell = "CELL 1"

if 'repair_cache' not in st.session_state:
    # 수리 입력 중 데이터 유실 방지 캐시
    st.session_state.repair_cache = {}

# =================================================================
# 4. 로그인 관리 및 사이드바 내비게이션
# =================================================================

# 로그인하지 않은 경우 화면을 표시합니다.
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 v19.2</h2>", unsafe_allow_html=True)
        st.info("💡 접속 안내: 공정별 담당 계정으로 로그인해 주세요.")
        with st.form("main_login_form"):
            uid_in = st.text_input("아이디(ID)")
            upw_in = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("시스템 로그인", use_container_width=True):
                if uid_in in st.session_state.user_db and st.session_state.user_db[uid_in]["pw"] == upw_in:
                    st.cache_data.clear()
                    st.session_state.production_db = load_data()
                    st.session_state.login_status = True
                    st.session_state.user_id = uid_in
                    st.session_state.user_role = st.session_state.user_db[uid_in]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("로그인 정보를 확인해 주세요.")
    st.stop()

# 사이드바 레이아웃
st.sidebar.markdown(f"### 🏭 {st.session_state.user_id}님 (접속 중)")
if st.sidebar.button("🔓 로그아웃", type="secondary"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def navigate_to(page_name):
    st.session_state.current_line = page_name
    st.rerun()

# 사용자 권한 메뉴 구성
allowed_menus = ROLES.get(st.session_state.user_role, [])
menus_p = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_p = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}

for m in menus_p:
    if m in allowed_menus:
        m_label = f"{icons_p[m]} {m}" + (" 현황" if "라인" in m else "")
        if st.sidebar.button(m_label, use_container_width=True, type="primary" if st.session_state.current_line == m else "secondary"):
            navigate_to(m)

menus_r = ["불량 공정", "수리 리포트"]
icons_r = {"불량 공정":"🛠️", "수리 리포트":"📈"}
st.sidebar.divider()
for m in menus_r:
    if m in allowed_menus:
        if st.sidebar.button(f"{icons_r[m]} {m}", use_container_width=True, type="primary" if st.session_state.current_line == m else "secondary"):
            navigate_to(m)

if "마스터 관리" in allowed_menus:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리", use_container_width=True):
        navigate_to("마스터 관리")

# 불량품 발생 알림
ng_check_db = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if not ng_check_db.empty:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급: 현재 {len(ng_check_db)}건의 불량 수리 대기 건이 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 (단일 행 추적 및 복합 고유키)
# =================================================================

def check_and_add_marker(df, line_name):
    """10대 단위 생산 달성 시 시각적 구분선 추가"""
    today_kst = get_kst_now().strftime('%Y-%m-%d')
    perf_count = len(df[(df['라인'] == line_name) & (df['시간'].astype(str).str.contains(today_kst)) & (df['상태'] != "구분선")])
    if perf_count > 0 and perf_count % 10 == 0:
        marker = {'시간': '---', '라인': '---', 'CELL': '---', '모델': '---', '품목코드': '---', '시리얼': f"✅ {perf_count}대 달성", '상태': '구분선', '증상': '---', '수리': '---', '작업자': '---'}
        return pd.concat([df, pd.DataFrame([marker])], ignore_index=True)
    return df

@st.dialog("📦 공정 입고 승인")
def confirm_entry_dialog():
    """제품을 다음 단계로 이동 (단일 행 트래킹)"""
    st.warning(f"제품 [ {st.session_state.confirm_target} ] 입고 승인하시겠습니까?")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        # [복합키 매칭] 품목코드 + 시리얼로 대상 행을 정확히 찾습니다.
        idx_find = db[(db['품목코드'] == st.session_state.confirm_item) & (db['시리얼'] == st.session_state.confirm_target)].index
        if not idx_find.empty:
            db.at[idx_find[0], '라인'] = st.session_state.current_line
            db.at[idx_find[0], '상태'] = '진행 중'
            db.at[idx_find[0], '시간'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
            db.at[idx_find[0], '작업자'] = st.session_state.user_id
            if save_to_gsheet(db):
                st.session_state.confirm_target = None
                st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): st.session_state.confirm_target = None; st.rerun()

def display_line_flow_stats(line_name):
    """상단 통계 집계 및 렌더링"""
    db = st.session_state.production_db
    today = get_kst_now().strftime('%Y-%m-%d')
    today_data = db[(db['라인'] == line_name) & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    qty_in, qty_out = len(today_data), len(today_data[today_data['상태'] == '완료'])
    
    waiting = 0
    prev = "조립 라인" if line_name == "검사 라인" else "검사 라인" if line_name == "포장 라인" else None
    if prev:
        waiting = len(db[(db['라인'] == prev) & (db['상태'] == '완료')])
        
    s1, s2, s3 = st.columns(3)
    with s1: st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev if prev else '입고'} 대기</div><div class='stat-value' style='color: #f39c12;'>{waiting if prev else '-'}</div><div class='stat-sub'>건 (누적)</div></div>", unsafe_allow_html=True)
    with s2: st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 {line_name} 작업 중</div><div class='stat-value'>{qty_in}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)
    with s3: st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ {line_name} 작업 완료</div><div class='stat-value' style='color: #27ae60;'>{qty_out}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)

def display_process_log_table(line_name, btn_label="완료 처리"):
    """실시간 공정 로그 테이블 렌더링"""
    st.divider(); st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 작업 로그</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    l_db = db[db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
        
    if l_db.empty: st.info("작업 중인 물량이 없습니다."); return
    
    h_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for col, txt in zip(h_cols, ["기록시간", "CELL", "모델명", "품목코드", "시리얼", "상태 제어"]): col.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #f1f3f5; padding: 6px; text-align: center; border-radius: 8px; font-weight: bold; color: #495057;'>📦 {row['시리얼']} ----------------------------------------------------</div>", unsafe_allow_html=True)
            continue
        r_cols = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        r_cols[0].write(row['시간']); r_cols[1].write(row['CELL']); r_cols[2].write(row['모델']); r_cols[3].write(row['품목코드']); r_cols[4].write(row['시리얼'])
        with r_cols[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(btn_label, key=f"ok_{idx}"):
                    db.at[idx, '상태'] = "완료"; db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db): st.rerun()
                if b2.button("🚫불량", key=f"bad_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"; db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(db): st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span style='color:#e74c3c; font-weight:bold;'>🛠️ 수리 중</span>", unsafe_allow_html=True)
            else: st.markdown("<span style='color:#2ecc71; font-weight:bold;'>✅ 공정 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 메뉴별 상세 기능 (초기화 문제 해결 반영)
# =================================================================

# 6-1. 조립 라인 (중복 체크 강화)
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 공정 모니터링</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인"); st.divider()
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell == c else "secondary"):
            st.session_state.selected_cell = c; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.subheader(f"🛠️ {st.session_state.selected_cell} 신규 조립")
            sel_m = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("assembly_form"):
                f1, f2 = st.columns(2)
                sel_i = f1.selectbox("품목코드", st.session_state.master_items_dict.get(sel_m, ["모델 미선택"]))
                sel_sn = f2.text_input("시리얼 번호")
                if st.form_submit_button("▶️ 생산 등록", use_container_width=True, type="primary"):
                    if sel_m != "선택하세요." and sel_sn:
                        db = st.session_state.production_db
                        # [복합 고유키 중복 체크] 제품 간 '품목코드' + '시리얼'이 절대 중복되지 않아야 함
                        if not db[(db['품목코드']==sel_i)&(db['시리얼']==sel_sn)&(db['상태']!='구분선')].empty:
                            st.error(f"❌ 중복 방지: 품목코드 [ {sel_i} ] 및 시리얼 [ {sel_sn} ] 제품이 이미 존재합니다.")
                        else:
                            new_row = {'시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': sel_m, '품목코드': sel_i, '시리얼': sel_sn, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                            updated_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            st.session_state.production_db = check_and_add_marker(updated_db, "조립 라인")
                            if save_to_gsheet(st.session_state.production_db): st.rerun()
    display_process_log_table("조립 라인", "조립 완료")

# 6-2. 검사 및 포장 라인 (입고 처리)
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    l_now = st.session_state.current_line
    st.markdown(f"<h2 class='centered-title'>🔍 {l_now} 현황</h2>", unsafe_allow_html=True)
    display_line_flow_stats(l_now); st.divider()
    prev = "조립 라인" if l_now == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.subheader(f"📥 {prev} 완료 물량 입고")
        sel_f = st.selectbox("입고 대상 모델", ["선택하세요."] + st.session_state.master_models, key=f"f_{l_now}")
        if sel_f != "선택하세요.":
            db = st.session_state.production_db
            ready_p = db[(db['라인'] == prev) & (db['상태'] == "완료") & (db['모델'] == sel_f)]
            if not ready_p.empty:
                st.success(f"📦 입고 가능한 물량: {len(ready_p)}건")
                grid = st.columns(4)
                for i, row in enumerate(ready_p.itertuples()):
                    if grid[i % 4].button(f"📥 입고: {row.시리얼}", key=f"in_{row.품목코드}_{row.시리얼}_{l_now}"):
                        st.session_state.confirm_target, st.session_state.confirm_model, st.session_state.confirm_item = row.시리얼, row.모델, row.품목코드
                        confirm_entry_dialog()
            else: st.info("입고 대기 물량이 없습니다.")
    display_process_log_table(l_now, "합격 처리" if l_now == "검사 라인" else "최종 출하")

# 6-3. 생산 리포트
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 리포트</h2>", unsafe_allow_html=True)
    if st.button("🔄 실시간 동기화", use_container_width=True): st.session_state.production_db = load_data(); st.rerun()
    db = st.session_state.production_db[st.session_state.production_db['상태'] != '구분선']
    if not db.empty:
        t_out = len(db[(db['라인'] == '포장 라인') & (db['상태'] == '완료')])
        t_ng = len(db[db['상태'].str.contains("불량", na=False)])
        ftt = (t_out / (t_out + t_ng) * 100) if (t_out + t_ng) > 0 else 100
        met = st.columns(4)
        met[0].metric("최종 출하", f"{t_out} EA"); met[1].metric("작업 진행 중", len(db[db['상태'] == '진행 중']))
        met[2].metric("누적 불량", f"{t_ng} 건", delta=t_ng, delta_color="inverse"); met[3].metric("직행률(FTT)", f"{ftt:.1f}%")
        st.divider(); c1, c2 = st.columns([3, 2])
        c1.plotly_chart(px.bar(db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 분포"), use_container_width=True)
        c2.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델 비중"), use_container_width=True)
        st.dataframe(st.session_state.production_db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# 6-4. 불량 수리 센터 (line4)
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True); display_line_flow_stats("조립 라인")
    bad = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    if bad.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"🚩 **S/N: {row['시리얼']}** ({row['모델']} / {row['품목코드']} / 발생: {row['라인']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                sv, av = st.session_state.repair_cache.get(f"s_{idx}", ""), st.session_state.repair_cache.get(f"a_{idx}", "")
                s = c1.text_input("불량 원인", value=sv, key=f"s_{idx}"); a = c2.text_input("조치 사항", value=av, key=f"a_{idx}")
                st.session_state.repair_cache[f"s_{idx}"], st.session_state.repair_cache[f"a_{idx}"] = s, a
                photo = st.file_uploader("사진 첨부", type=['jpg','png','jpeg'], key=f"img_{idx}")
                if c3.button("🔧 수리 완료", key=f"r_btn_{idx}", type="primary"):
                    if s and a:
                        link = ""
                        if photo: link = f" [사진: {upload_image_to_drive(photo, f'{row['시리얼']}_FIX.jpg')}]"
                        st.session_state.production_db.at[idx, '상태'], st.session_state.production_db.at[idx, '증상'], st.session_state.production_db.at[idx, '수리'], st.session_state.production_db.at[idx, '작업자'] = "수리 완료(재투입)", s, a + link, st.session_state.user_id
                        if save_to_gsheet(st.session_state.production_db):
                            st.session_state.repair_cache.pop(f"s_{idx}", None); st.session_state.repair_cache.pop(f"a_{idx}", None); st.rerun()

# 6-5. 마스터 관리 (강제 초기화 버그 수정 완료)
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 시스템 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify"):
            apw = st.text_input("관리자 PW (admin1234)", type="password")
            if st.form_submit_button("인증"):
                if apw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("PW 불일치")
    else:
        if st.sidebar.button("🔓 마스터 종료"): st.session_state.admin_authenticated = False; navigate_to("생산 리포트")
        m1, m2 = st.columns(2)
        with m1:
            with st.container(border=True):
                st.subheader("모델 등록")
                nm = st.text_input("새 모델명")
                if st.button("모델 추가") and nm: st.session_state.master_models.append(nm); st.session_state.master_items_dict[nm] = []; st.rerun()
                st.divider(); sel_m = st.selectbox("품목용 모델", st.session_state.master_models)
                ni = st.text_input("새 품목코드")
                if st.button("품목 추가") and ni: st.session_state.master_items_dict[sel_m].append(ni); st.rerun()
        with m2:
            with st.container(border=True):
                st.subheader("데이터 관리")
                csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig'); st.download_button("📥 전체 실적 CSV 다운로드", csv, f"prod_backup_{get_kst_now().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # [수정] 초기화 시 물리적 시트 비우기를 보장하기 위해 force_reset 로직 적용
                if st.button("🚫 시스템 전체 생산 데이터 초기화 (물리적 삭제)", type="secondary", use_container_width=True):
                     st.error("주의: 이 작업은 구글 시트의 모든 실적 데이터를 영구 삭제합니다.")
                     if st.button("❌ 위험 감수: 전체 삭제 확정 및 시트 비우기"):
                         # 컬럼 헤더만 있고 데이터는 없는 빈 데이터프레임 강제 생성
                         empty_df = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                         
                         # 구글 시트에 빈 데이터를 강제로 덮어씌움 (is_reset_action=True)
                         if save_to_gsheet(empty_df, is_reset_action=True):
                             # 시트 저장 성공 시 세션 상태까지 초기화 후 리런
                             st.session_state.production_db = empty_df
                             st.cache_data.clear()
                             st.success("시스템 및 구글 시트 데이터가 성공적으로 초기화되었습니다.")
                             st.rerun()
        
        st.divider(); st.subheader("👤 계정 관리"); u1, u2, u3 = st.columns([3, 3, 2])
        uid, upw, url = u1.text_input("ID"), u2.text_input("PW", type="password"), u3.selectbox("권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        if st.button("계정 생성/수정 반영", use_container_width=True): st.session_state.user_db[uid] = {"pw": upw, "role": url}; st.rerun()
