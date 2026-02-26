import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh

# [구글 클라우드 서비스 연동] 드라이브 API 및 인증 라이브러리
# 서비스 계정 키를 통해 이미지 업로드 및 권한 관리를 수행합니다.
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 (Global Configurations)
# =================================================================
# 애플리케이션의 타이틀과 와이드 레이아웃 설정
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 전역 타임존 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동으로 전체 화면을 새로고침합니다.
# 생산 현황판(대시보드)의 실시간성을 보장합니다.
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 사용자 그룹별 메뉴 접근 권한 정의 (Role-Based Access Control)
# 각 사용자의 등급에 따라 사이드바 내비게이션 항목이 동적으로 제어됩니다.
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"], # 중앙 관제
    "assembly_team": ["조립 라인"],                         # 조립 라인
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],     # 검사 라인
    "packing_team": ["포장 라인"]                            # 포장 라인
}

# [정밀 검수된 CSS 스타일] - v17.7 스타일 완벽 복구 및 반 선택 디자인 추가
st.markdown("""
    <style>
    /* 메인 컨테이너 최대 너비 제한 */
    .stApp { max-width: 1200px; margin: 0 auto; }
    
    /* 버튼 텍스트 줄바꿈 방지 및 중앙 정렬 */
    .stButton button { 
        display: flex; justify-content: center; align-items: center;
        margin-top: 1px; padding: 6px 10px; width: 100%; 
        border-radius: 8px; font-weight: 600;
        white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis;
        transition: all 0.2s ease;
    }
    
    /* 타이틀 중앙 정렬 */
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
    
    /* 섹션 타이틀: 파란색 테두리 포인트 */
    .section-title { 
        background-color: #f8f9fa; color: #111; padding: 16px 20px; 
        border-radius: 10px; font-weight: bold; margin: 10px 0 25px 0; 
        border-left: 10px solid #007bff; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    
    /* 대시보드 KPI 카드 디자인 */
    .stat-box {
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        background-color: #ffffff; border-radius: 12px; padding: 22px; 
        border: 1px solid #e9ecef; margin-bottom: 15px; min-height: 130px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.4rem; color: #007bff; font-weight: bold; line-height: 1; }
    
    /* 상태 표시 색상 */
    .status-red { color: #fa5252; font-weight: bold; }
    .status-green { color: #40c057; font-weight: bold; }
    
    /* 알림 배너 스타일 */
    .alarm-banner { 
        background-color: #fff5f5; color: #c92a2a; padding: 18px; 
        border-radius: 12px; border: 1px solid #ffa8a8; font-weight: bold; 
        margin-bottom: 25px; text-align: center; box-shadow: 0 2px 10px rgba(201, 42, 42, 0.1);
    }

    /* v18.0 제조 반 표시 배지 */
    .team-badge {
        background-color: #e7f5ff; color: #1971c2; padding: 8px 15px;
        border-radius: 10px; font-weight: bold; text-align: center;
        margin-bottom: 15px; border: 1px solid #a5d8ff;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 함수 (Core Utilities)
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 연동 객체 초기화
gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_realtime_ledger():
    try:
        df = gs_conn.read(ttl=0).fillna("")
        # [v18.0 패치] '반' 컬럼이 없으면 자동으로 생성해줍니다.
        if '반' not in df.columns:
            df.insert(0, '반', '제조1반')
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.warning(f"데이터 연동 중 오류 발생: {e}")
        return pd.DataFrame(columns=['반', '시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as error:
        st.error(f"클라우드 저장 실패: {error}")

def upload_img_to_drive(file_obj, serial_no):
    try:
        gcp_info = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        if not folder_id: return "❌ 폴더 ID 미설정"
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded_file = drive_svc.files().create(body=meta_data, media_body=media, fields='id, webViewLink').execute()
        return uploaded_file.get('webViewLink')
    except Exception as err:
        return f"⚠️ 업로드 중단: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (Session State Initialization)
# =================================================================

# 1) 생산 반 선택 상태 (v18.0 핵심)
if 'selected_team' not in st.session_state: st.session_state.selected_team = "제조1반"

# 2) 생산 실적 원장 세션 로드
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_realtime_ledger()

# [중요] 필터링된 데이터셋 생성: 화면에는 선택된 '반'의 데이터만 노출
db_full = st.session_state.production_db
db_team = db_full[db_full['반'] == st.session_state.selected_team]

# 3) 시스템 계정 DB
def load_accounts():
    default_acc = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }
    try:
        df = gs_conn.read(worksheet="accounts", ttl=0)
        if df is None or df.empty: return default_acc
        acc_dict = {}
        for _, row in df.iterrows():
            uid = str(row['id']).strip() if pd.notna(row['id']) else ""
            if uid:
                acc_dict[uid] = {
                    "pw": str(row['pw']).strip() if pd.notna(row['pw']) else "",
                    "role": str(row['role']).strip() if pd.notna(row['role']) else "user"
                }
        return acc_dict if acc_dict else default_acc
    except: return default_acc

if 'user_db' not in st.session_state: st.session_state.user_db = load_accounts()

# 4) 로그인 및 세션 상태
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 5) 마스터 데이터
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"], 
        "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
    }
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 화면 및 사이드바 내비게이션
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
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("❌ 아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

# [사이드바 구성]
st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"<div class='team-badge'>📍 {st.session_state.selected_team} 접속 중</div>", unsafe_allow_html=True)
st.sidebar.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{st.session_state.user_id} 작업자**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False; st.rerun()

# [v18.0 핵심] 제조 반 전환 UI (마스터 권한 시 노출)
if st.session_state.user_role == "master":
    st.sidebar.divider()
    st.sidebar.markdown("#### 🔄 제조 반 전환")
    t_col1, t_col2, t_col3 = st.sidebar.columns(3)
    if t_col1.button("1반", type="primary" if st.session_state.selected_team=="제조1반" else "secondary"):
        st.session_state.selected_team = "제조1반"; st.rerun()
    if t_col2.button("2반", type="primary" if st.session_state.selected_team=="제조2반" else "secondary"):
        st.session_state.selected_team = "제조2반"; st.rerun()
    if t_col3.button("3반", type="primary" if st.session_state.selected_team=="제조3반" else "secondary"):
        st.session_state.selected_team = "제조3반"; st.rerun()

st.sidebar.divider()
my_allowed = ROLES.get(st.session_state.user_role, [])

# 공정 메뉴 버튼
for p in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if p in my_allowed:
        if st.sidebar.button(f"{p} 현황", use_container_width=True, type="primary" if st.session_state.current_line==p else "secondary"):
            st.session_state.current_line = p; st.rerun()

st.sidebar.divider()
for p in ["불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(f"{p}", use_container_width=True, type="primary" if st.session_state.current_line==p else "secondary"):
            st.session_state.current_line = p; st.rerun()

if "마스터 관리" in my_allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"):
        st.session_state.current_line = "마스터 관리"; st.rerun()

# 상황 전파 배너 (현재 선택된 반의 불량만 감지)
repair_wait_cnt = len(db_team[db_team['상태'] == "불량 처리 중"])
if repair_wait_cnt > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ {st.session_state.selected_team} 통지: 품질 이슈가 {repair_wait_cnt}건 발생했습니다. 즉시 수리 센터를 확인하세요.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 및 공용 함수 (Team Filtered)
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    st.warning(f"승인 대상 S/N: [ {st.session_state.confirm_target} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        idx = db_full[db_full['시리얼'] == st.session_state.confirm_target].index[0]
        db_full.at[idx, '시간'] = get_now_kst_str()
        db_full.at[idx, '라인'] = st.session_state.current_line
        db_full.at[idx, '상태'] = '진행 중'
        db_full.at[idx, '작업자'] = st.session_state.user_id
        push_to_cloud(db_full)
        st.session_state.confirm_target = None; st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None; st.rerun()

def draw_v18_optimized_log(line_key, ok_btn_txt="완료 처리"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {st.session_state.selected_team} - {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    # [v18.0] 현재 반 데이터만 사용
    f_df = db_team[db_team['라인'] == line_key]
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty:
        st.info("현재 해당 공정에 할당된 데이터가 없습니다."); return

    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    for col, txt in zip(h_row, ["기록 시간", "CELL", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]): col.write(f"**{txt}**")
    
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델'])
        r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
        with r[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_btn_txt, key=f"ok_{idx}"):
                    db_full.at[idx, '상태'] = "완료"; push_to_cloud(db_full); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    db_full.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db_full); st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span class='status-red'>🔴 품질 이슈 분석 대기</span>", unsafe_allow_html=True)
            else: st.markdown("<span class='status-green'>🟢 공정 정상 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 렌더링 (Page Views)
# =================================================================

curr = st.session_state.current_line

# --- 6-1. 조립 라인 현황 ---
if curr == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {st.session_state.selected_team} 신규 조립 생산 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"):
            st.session_state.selected_cell = name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_team} {st.session_state.selected_cell} 신규 생산 등록")
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("assembly_entry_gate"):
                fc1, fc2 = st.columns(2)
                target_item = fc1.selectbox("세부 품목 코드", st.session_state.master_items_dict.get(target_model, []) if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("제품 시리얼(S/N) 입력")
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        if target_sn in db_full['시리얼'].values: st.error(f"❌ 중복 오류: 시리얼 '{target_sn}'은 이미 존재합니다.")
                        else:
                            new_entry = {
                                '반': st.session_state.selected_team, '시간': get_now_kst_str(), '라인': "조립 라인",
                                'CELL': st.session_state.selected_cell, '모델': target_model, '품목코드': target_item,
                                '시리얼': target_sn, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db_full, pd.DataFrame([new_entry])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    draw_v18_optimized_log("조립 라인", "조립 완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif curr in ["검사 라인", "포장 라인"]:
    pg_title = "🔍 품질 검사 공정 현황" if curr == "검사 라인" else "🚚 출하 포장 현황"
    pv_line = "조립 라인" if curr == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{st.session_state.selected_team} {pg_title}</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 이전 공정 완료 물량 (입고 승인 대기)</div>", unsafe_allow_html=True)
        wait_df = db_team[(db_team['라인'] == pv_line) & (db_team['상태'] == "완료")]
        if not wait_df.empty:
            st.success(f"현재 총 {len(wait_df)}건의 제품이 입고 승인을 기다리고 있습니다.")
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if w_cols[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_in_{idx}"):
                    st.session_state.confirm_target = row['시리얼']; trigger_entry_dialog()
        else: st.info("입고 가능한 대기 물량이 없습니다.")
    draw_v18_optimized_log(curr, "합격 처리" if curr=="검사 라인" else "포장 완료")

# --- 6-3. 통합 리포트 (디자인 최적화) ---
elif curr == "리포트":
    st.markdown(f"<h2 class='centered-title'>📊 {st.session_state.selected_team} 생산 통합 리포트</h2>", unsafe_allow_html=True)
    if not db_team.empty:
        q_tot, q_fin = len(db_team), len(db_team[(db_team['라인']=='포장 라인')&(db_team['상태']=='완료')])
        m_cols = st.columns(4)
        m_cols[0].metric("총 투입 실적", f"{q_tot} EA")
        m_cols[1].metric("최종 생산 수량", f"{q_fin} EA")
        m_cols[2].metric("현재 재공(WIP)", f"{len(db_team[db_team['상태']=='진행 중'])} EA")
        m_cols[3].metric("품질 이슈 발생", f"{len(db_team[db_team['상태'].str.contains('불량', na=False)])} 건", delta_color="inverse")
        
        st.divider()
        cl, cr = st.columns([1.8, 1.2])
        with cl:
            fig_bar = px.bar(db_team.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정 단계별 분포")
            fig_bar.update_yaxes(dtick=1); st.plotly_chart(fig_bar, use_container_width=True)
        with cr:
            fig_pie = px.pie(db_team.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.5, title="모델별 비중")
            st.plotly_chart(fig_pie, use_container_width=True)
        st.dataframe(db_team.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else: st.warning("분석할 데이터가 없습니다.")

# --- 6-4. 불량 수리 센터 (v17.5 판독 강화) ---
elif curr == "불량 공정":
    st.markdown(f"<h2 class='centered-title'>🛠️ {st.session_state.selected_team} 불량 분석 및 수리</h2>", unsafe_allow_html=True)
    wait_list = db_team[db_team['상태'] == "불량 처리 중"]
    if wait_list.empty: st.success("✅ 조치가 필요한 품질 이슈 사항이 없습니다.")
    else:
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.markdown(f"**이슈 시리얼: `{row['시리얼']}`** ({row['모델']} / {row['라인']})")
                r1c1, r1c2 = st.columns(2)
                v_cause = r1c1.text_input("⚠️ 불량 원인 분석", placeholder="원인 상세 입력", key=f"rc_{idx}")
                v_action = r1c2.text_input("🛠️ 수리 조치 사항", placeholder="조치 내용 입력", key=f"ra_{idx}")
                v_img = st.file_uploader("📸 증빙 사진 등록", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                if st.button("✅ 수리 확정", key=f"rb_{idx}", type="primary", use_container_width=True):
                    if v_cause and v_action:
                        with st.spinner("이미지 업로드 중..."):
                            url = upload_img_to_drive(v_img, row['시리얼']) if v_img else ""
                        db_full.at[idx, '상태'] = "수리 완료(재투입)"
                        db_full.at[idx, '시간'] = get_now_kst_str()
                        db_full.at[idx, '증상'], db_full.at[idx, '수리'] = v_cause, v_action + (f" [사진: {url}]" if "http" in url else "")
                        push_to_cloud(db_full); st.rerun()
                    else: st.error("원인과 조치 사항을 모두 입력하세요.")

# --- 6-5. 수리 이력 리포트 ---
elif curr == "수리 리포트":
    st.markdown(f"<h2 class='centered-title'>📈 {st.session_state.selected_team} 품질 수리 이력</h2>", unsafe_allow_html=True)
    hist_df = db_team[db_team['수리'] != ""]
    if not hist_df.empty:
        st.plotly_chart(px.bar(hist_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 이슈 발생 빈도"), use_container_width=True)
        st.dataframe(hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else: st.info("기록된 수리 내역이 없습니다.")

# --- 6-6. 마스터 데이터 관리 (계정/모델/초기화 포함) ---
elif curr == "마스터 관리":
    st.markdown(f"<h2 class='centered-title'>🔐 시스템 마스터 관리 ({st.session_state.selected_team})</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("master_verify"):
            m_pw = st.text_input("마스터 비밀번호 입력", type="password")
            if st.form_submit_button("권한 인증"):
                if m_pw == "master1234": st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호 불일치")
    else:
        st.markdown("<div class='section-title'>📋 생산 기준 정보 및 시스템 설정</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("모델 등록")
            new_m = st.text_input("신규 모델명")
            if st.button("모델 추가"):
                if new_m and new_m not in st.session_state.master_models:
                    st.session_state.master_models.append(new_m); st.session_state.master_items_dict[new_m] = []; st.rerun()
        with c2:
            st.subheader("계정 생성")
            r_id, r_pw = st.text_input("아이디"), st.text_input("비밀번호", type="password")
            r_role = st.selectbox("권한", list(ROLES.keys()))
            if st.button("계정 저장"):
                if r_id and r_pw:
                    st.session_state.user_db[r_id] = {"pw": r_pw, "role": r_role}
                    acc_df = pd.DataFrame.from_dict(st.session_state.user_db, orient='index').reset_index()
                    acc_df.columns = ['id', 'pw', 'role']
                    gs_conn.update(worksheet="accounts", data=acc_df); st.success("사용자 저장 완료!"); st.rerun()

        st.divider()
        # 데이터 백업 및 복구
        st.download_button("📥 전체 실적 CSV 백업", db_full.to_csv(index=False).encode('utf-8-sig'), f"PMS_Backup_{get_now_kst_str()}.csv", "text/csv", use_container_width=True)
        if st.button("⚠️ 시스템 데이터 전체 초기화 (영구 삭제)", type="secondary", use_container_width=True):
            empty_df = pd.DataFrame(columns=['반', '시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_to_cloud(empty_df); st.rerun()

# [ PMS v18.0 소스코드 종료 ]
