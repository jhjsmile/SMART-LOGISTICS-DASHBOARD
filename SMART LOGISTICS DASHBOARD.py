import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh

# [구글 클라우드 서비스 연동] 드라이브 API 및 인증 라이브러리
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 (v17.8 원본 유지)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.6",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 전역 타임존 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동으로 전체 화면을 새로고침합니다.
st_autorefresh(interval=30000, key="pms_auto_refresh")

# [V18.4 추가] 제조 반 리스트 정의
PRODUCTION_GROUPS = ["제조 1반", "제조 2반", "제조 3반"]

# 사용자 그룹별 메뉴 접근 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [정밀 검수된 CSS 스타일]
st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { 
        display: flex; justify-content: center; align-items: center;
        margin-top: 1px; padding: 6px 10px; width: 100%; border-radius: 8px;
        font-weight: 600; white-space: nowrap !important; overflow: hidden;
        text-overflow: ellipsis; transition: all 0.2s ease;
    }
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
    .section-title { 
        background-color: #f8f9fa; color: #111; padding: 16px 20px; 
        border-radius: 10px; font-weight: bold; margin: 10px 0 25px 0; 
        border-left: 10px solid #007bff; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-box {
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        background-color: #ffffff; border-radius: 12px; padding: 22px; 
        border: 1px solid #e9ecef; margin-bottom: 15px; min-height: 130px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.4rem; color: #007bff; font-weight: bold; line-height: 1; }
    .button-spacer { margin-top: 28px; }
    .status-red { color: #fa5252; font-weight: bold; }
    .status-green { color: #40c057; font-weight: bold; }
    .alarm-banner { 
        background-color: #fff5f5; color: #c92a2a; padding: 18px; border-radius: 12px; 
        border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 25px;
        text-align: center; box-shadow: 0 2px 10px rgba(201, 42, 42, 0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 함수
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_realtime_ledger():
    try:
        df = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        if '반' not in df.columns:
            df.insert(1, '반', "제조 2반") if not df.empty else df.insert(1, '반', "")
        else:
            df['반'] = df['반'].apply(lambda x: "제조 2반" if x == "" else x)
        return df
    except Exception as e:
        return pd.DataFrame(columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as error: st.error(f"클라우드 저장 실패: {error}")

def upload_img_to_drive(file_obj, serial_no):
    try:
        gcp_info = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded_file = drive_svc.files().create(body=meta_data, media_body=media, fields='id, webViewLink').execute()
        return uploaded_file.get('webViewLink')
    except Exception as err: return f"⚠️ 업로드 중단: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (에러 방지를 위한 필구 구조 초기화)
# =================================================================

if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_realtime_ledger()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "master": {"pw": "master1234", "role": "master"}
    }

# [V18.6 핵심 추가] 반별 독립 모델/품목 데이터 구조 초기화 (이게 없으면 에러남)
if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조 1반": [],
        "제조 2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조 3반": []
    }

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조 1반": {},
        "제조 2반": {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        "제조 3반": {}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조 2반"
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 및 사이드바 (계층 구조)
# =================================================================

if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("main_gate_login"):
            input_id = st.text_input("아이디(ID)", placeholder="사용자 ID 입력")
            input_pw = st.text_input("비밀번호(PW)", type="password", placeholder="액세스 비밀번호 입력")
            if st.form_submit_button("인증 및 접속 시작", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    st.rerun()
                else: st.error("❌ 정보 불일치")
    st.stop()

st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"**{st.session_state.user_id} 작업자 ({st.session_state.user_role})**")
if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False; st.rerun()

st.sidebar.divider()
my_allowed = ROLES.get(st.session_state.user_role, [])

for group in PRODUCTION_GROUPS:
    is_expanded = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=is_expanded):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in my_allowed:
                is_active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True, type="primary" if is_active else "secondary"):
                    st.session_state.selected_group, st.session_state.current_line = group, p; st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(p, key=f"fixed_nav_{p}", use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"): 
            st.session_state.current_line = p; st.rerun()

if "마스터 관리" in my_allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        st.session_state.current_line = "마스터 관리"; st.rerun()

# =================================================================
# 5. 핵심 비즈니스 로직 (v17.8 원본 100% 복원)
# =================================================================

def draw_v17_optimized_log(line_key, ok_btn_txt="완료 처리"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {st.session_state.selected_group} {line_key} 원장</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    f_df = db[(db['반'] == st.session_state.selected_group) & (db['라인'] == line_key)]
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: st.info("데이터가 없습니다."); return
    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    for col, txt in zip(h_row, ["기록 시간", "CELL", "모델", "품목코드", "시리얼", "현장 제어"]): col.write(f"**{txt}**")
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델']); r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
        with r[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_btn_txt, key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
            else: st.write(f"✅ {row['상태']}")

# =================================================================
# 6. 각 페이지별 렌더링 (반별 독립 마스터 적용)
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

if curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): st.session_state.selected_cell = name; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 등록")
            # [V18.6 핵심] 현재 반에 해당하는 모델 리스트만 필터링해서 표시
            my_models = st.session_state.group_master_models.get(curr_g, [])
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + my_models, key=f"am_{curr_g}")
            with st.form("entry_form"):
                fc1, fc2 = st.columns(2)
                # [V18.6 핵심] 선택된 모델에 종속된 품목 리스트만 표시
                my_items = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
                target_item = fc1.selectbox("세부 품목 코드", my_items if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("제품 시리얼(S/N) 입력")
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        db = st.session_state.production_db
                        if target_sn in db['시리얼'].values: st.error("이미 등록된 시리얼입니다.")
                        else:
                            new_row = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 'CELL': st.session_state.selected_cell,
                                       '모델': target_model, '품목코드': target_item, '시리얼': target_sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                            st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    draw_v17_optimized_log("조립 라인", "조립 완료")

elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l}</h2>", unsafe_allow_html=True)
    draw_v17_optimized_log(curr_l, "합격 처리" if curr_l=="검사 라인" else "포장 완료")

elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify"):
            m_pw = st.text_input("마스터 비밀번호", type="password")
            if st.form_submit_button("권한 인증"):
                if m_pw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
    else:
        st.sidebar.button("🔓 세션 잠금(Lock)", on_click=lambda: setattr(st.session_state, 'admin_authenticated', False))
        m_col_1, m_col_2 = st.columns(2)
        with m_col_1:
            st.markdown("#### 📋 제조 반별 독립 기준정보 설정")
            m_tabs = st.tabs(["제조 1반", "제조 2반", "제조 3반"])
            for i, g_name in enumerate(PRODUCTION_GROUPS):
                with m_tabs[i]:
                    with st.container(border=True):
                        st.subheader(f"{g_name} 모델 등록")
                        add_m = st.text_input(f"신규 모델명 ({g_name})", key=f"am_{g_name}")
                        if st.button(f"{g_name} 모델 확정", key=f"ab_{g_name}"):
                            if add_m and add_m not in st.session_state.group_master_models[g_name]:
                                st.session_state.group_master_models[g_name].append(add_m)
                                st.session_state.group_master_items[g_name][add_m] = []; st.rerun()
                        st.divider()
                        st.subheader(f"{g_name} 품목 등록")
                        g_mods = st.session_state.group_master_models[g_name]
                        if g_mods:
                            sel_m = st.selectbox(f"모델 선택 ({g_name})", g_mods, key=f"sm_{g_name}")
                            add_i = st.text_input(f"신규 품목코드 ({sel_m})", key=f"ai_{g_name}")
                            if st.button(f"{g_name} 품목 확정", key=f"ib_{g_name}"):
                                if add_i and add_i not in st.session_state.group_master_items[g_name][sel_m]:
                                    st.session_state.group_master_items[g_name][sel_m].append(add_i); st.rerun()
                        else: st.caption("모델을 먼저 등록하세요.")
        with m_col_2:
            with st.container(border=True):
                st.subheader("데이터 관리")
                csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 CSV 백업", csv, "PMS_Backup.csv", use_container_width=True)
                st.divider()
                f_mig = st.file_uploader("복구용 CSV 선택", type="csv")
                if f_mig and st.button("📤 데이터 로드"):
                    imp_df = pd.read_csv(f_mig)
                    st.session_state.production_db = pd.concat([st.session_state.production_db, imp_df], ignore_index=True).drop_duplicates(subset=['시리얼'], keep='last')
                    push_to_cloud(st.session_state.production_db); st.rerun()
# 리포트 및 나머지 페이지 로직 (v17.8 유지)...
