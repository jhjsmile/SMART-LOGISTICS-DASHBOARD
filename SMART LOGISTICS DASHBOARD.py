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
# 1. 시스템 전역 설정 및 디자인 (Global Configurations)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 전역 타임존 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동 새로고침
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 사용자 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],
    "packing_team": ["포장 라인"]
}

# CSS 스타일 정의
st.markdown("""
<style>
.stApp { max-width: 1200px; margin: 0 auto; }
.stButton button {
    display: flex; justify-content: center; align-items: center;
    margin-top: 1px; padding: 6px 10px; width: 100%; border-radius: 8px;
    font-weight: 600; white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis;
}
.centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
.section-title {
    background-color: #f8f9fa; color: #111; padding: 16px 20px; border-radius: 10px;
    font-weight: bold; margin: 10px 0 25px 0; border-left: 10px solid #007bff;
}
.stat-box {
    display: flex; flex-direction: column; justify-content: center; align-items: center;
    background-color: #ffffff; border-radius: 12px; padding: 22px; border: 1px solid #e9ecef;
    margin-bottom: 15px; min-height: 130px; box-shadow: 0 4px 6px rgba(0,0,0,0.02);
}
.stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
.stat-value { font-size: 2.4rem; color: #007bff; font-weight: bold; line-height: 1; }
.button-spacer { margin-top: 28px; }
.status-red { color: #fa5252; font-weight: bold; }
.status-green { color: #40c057; font-weight: bold; }
.alarm-banner {
    background-color: #fff5f5; color: #c92a2a; padding: 18px; border-radius: 12px;
    border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 25px; text-align: center;
}
</style>
""", unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 함수 (Core Utilities)
# =================================================================

def get_now_kst_str():
    """현재 한국 표준시(KST) 문자열 반환"""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_realtime_ledger():
    """구글 시트 데이터 로드"""
    try:
        df = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.warning(f"데이터 연동 중 오류 발생: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    """구글 시트 데이터 업데이트"""
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as error:
        st.error(f"클라우드 저장 실패: {error}")

def upload_img_to_drive(file_obj, serial_no):
    """구글 드라이브 이미지 업로드"""
    try:
        gcp_info = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        if not folder_id:
            return "❌ 클라우드 폴더 ID가 설정되지 않았습니다."
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded_file = drive_svc.files().create(
            body=meta_data, media_body=media, fields='id, webViewLink'
        ).execute()
        return uploaded_file.get('webViewLink')
    except Exception as err:
        return f"⚠️ 업로드 중단: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (Session State Initialization)
# =================================================================
if 'production_db' not in st.session_state:
    st.session_state.production_db = load_realtime_ledger()

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
        if df is None or df.empty:
            return default_acc
        acc_dict = {}
        for _, row in df.iterrows():
            uid = str(row['id']).strip() if pd.notna(row['id']) else ""
            if uid:
                acc_dict[uid] = {
                    "pw": str(row['pw']).strip() if pd.notna(row['pw']) else "",
                    "role": str(row['role']).strip() if pd.notna(row['role']) else "user"
                }
        return acc_dict if acc_dict else default_acc
    except:
        return default_acc

if 'user_db' not in st.session_state:
    st.session_state.user_db = load_accounts()

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"],
        "EPS7133": ["7133-S", "7133-Standard"],
        "T20i": ["T20i-P", "T20i-Premium"],
        "T20C": ["T20C-S", "T20C-Standard"]
    }

if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 및 사이드바 (v18.0 계층형 메뉴)
# =================================================================
if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("main_gate_login"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 및 접속 시작", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else:
                    st.error("❌ 정보가 올바르지 않습니다.")
    st.stop()

# 사이드바 구성
st.sidebar.markdown("### 🏭 생산 관리 시스템 v18.0")
st.sidebar.markdown(f"**{st.session_state.user_id} 작업자**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True):
    st.session_state.login_status = False
    st.rerun()

st.sidebar.divider()

if 'selected_dept' not in st.session_state:
    st.session_state.selected_dept = "제조 1반"

selected_dept = st.sidebar.selectbox(
    "🏢 소속 부서 선택",
    ["제조 1반", "제조 2반", "제조 3반"],
    index=["제조 1반", "제조 2반", "제조 3반"].index(st.session_state.selected_dept)
)

if selected_dept != st.session_state.selected_dept:
    st.session_state.selected_dept = selected_dept
    st.rerun()

def handle_nav(p_name):
    st.session_state.current_line = p_name
    st.rerun()

my_allowed = ROLES.get(st.session_state.user_role, [])

for p in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if p in my_allowed:
        if st.sidebar.button(f"▶ {p} 현황", use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            handle_nav(p)

st.sidebar.divider()

for p in ["불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(f"🛠 {p}", use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"):
            handle_nav(p)

if st.session_state.user_role == "master" or "마스터 관리" in my_allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"):
        handle_nav("마스터 관리")

# 알림 배너
repair_wait_cnt = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if repair_wait_cnt > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 긴급 통지: 분석 대기 중인 품질 이슈가 {repair_wait_cnt}건 발생했습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 핵심 비즈니스 로직 및 컴포넌트
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    st.warning(f"승인 대상 S/N: [ {st.session_state.confirm_target} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_full = st.session_state.production_db
        idx_match = db_full[db_full['시리얼'] == st.session_state.confirm_target].index
        if not idx_match.empty:
            idx = idx_match[0]
            db_full.at[idx, '시간'] = get_now_kst_str()
            db_full.at[idx, '라인'] = st.session_state.current_line
            db_full.at[idx, '상태'] = '진행 중'
            db_full.at[idx, '작업자'] = st.session_state.user_id
            push_to_cloud(db_full)
            st.session_state.confirm_target = None
            st.success("공정 입고 완료")
            st.rerun()
    if c_no.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def draw_v17_optimized_log(line_key, ok_btn_txt="완료 처리"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_source = st.session_state.production_db
    f_df = db_source[db_source['라인'] == line_key]
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    if f_df.empty:
        st.info("데이터가 없습니다.")
        return
    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    header_labels = ["기록 시간", "CELL", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]
    for col, txt in zip(h_row, header_labels):
        col.write(f"**{txt}**")
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r_row[0].write(row['시간'])
        r_row[1].write(row['CELL'] if row['CELL'] != "-" else "N/A")
        r_row[2].write(row['모델'])
        r_row[3].write(row['품목코드'])
        r_row[4].write(f"`{row['시리얼']}`")
        with r_row[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_grid1, b_grid2 = st.columns(2)
                if b_grid1.button(ok_btn_txt, key=f"ok_idx_{idx}", type="secondary"):
                    db_source.at[idx, '상태'] = "완료"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
                if b_grid2.button("🚫불량", key=f"ng_idx_{idx}"):
                    db_source.at[idx, '상태'] = "불량 처리 중"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 품질 이슈 분석 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 렌더링 (Page Views)
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 조립 생산 라인 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    station_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if station_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"):
            st.session_state.selected_cell = name; st.rerun()
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"am_{st.session_state.selected_cell}")
            with st.form("assembly_entry_gate"):
                fc1, fc2 = st.columns(2)
                target_item = fc1.selectbox("세부 품목 코드", st.session_state.master_items_dict.get(target_model, []) if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("제품 시리얼(S/N) 입력")
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        full_db = st.session_state.production_db
                        if target_sn in full_db['시리얼'].values:
                            st.error(f"❌ 중복 시리얼: {target_sn}")
                        else:
                            new_entry = {
                                '시간': get_now_kst_str(),
                                '라인': "조립 라인",
                                'CELL': st.session_state.selected_cell,
                                '모델': target_model,
                                '품목코드': target_item,
                                '시리얼': target_sn,
                                '상태': '진행 중',
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new_entry])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    draw_v17_optimized_log("조립 라인", "조립 완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    pg_title_txt = "🔍 품질 검사 공정 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    pv_line_name = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{pg_title_txt}</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 입고 승인 대기</div>", unsafe_allow_html=True)
        db_raw_ref = st.session_state.production_db
        wait_list_df = db_raw_ref[(db_raw_ref['라인'] == pv_line_name) & (db_raw_ref['상태'] == "완료")]
        if not wait_list_df.empty:
            st.success(f"대기 물량: {len(wait_list_df)}개")
            wait_grid = st.columns(4)
            for i, (idx, row) in enumerate(wait_list_df.iterrows()):
                if wait_grid[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_in_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    trigger_entry_dialog()
        else:
            st.info("입고 대기 물량이 없습니다.")
    draw_v17_optimized_log(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "포장 완료")

# --- 6-3. 통합 리포트 ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 모니터링</h2>", unsafe_allow_html=True)
    db_rep_source = st.session_state.production_db
    if not db_rep_source.empty:
        q_tot = len(db_rep_source)
        q_fin = len(db_rep_source[(db_rep_source['라인'] == '포장 라인') & (db_rep_source['상태'] == '완료')])
        q_wip = len(db_rep_source[db_rep_source['상태'] == '진행 중'])
        q_bad = len(db_rep_source[db_rep_source['상태'].str.contains("불량", na=False)])
        m_cols = st.columns(4)
        m_cols[0].metric("총 투입", f"{q_tot} EA")
        m_cols[1].metric("생산 실적", f"{q_fin} EA")
        m_cols[2].metric("재공(WIP)", f"{q_wip} EA")
        m_cols[3].metric("품질 이슈", f"{q_bad} 건", delta=q_bad, delta_color="inverse")
        st.divider()
        chart_l, chart_r = st.columns([1.8, 1.2])
        with chart_l:
            pos_sum_df = db_rep_source.groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(pos_sum_df, x='라인', y='수량', color='라인', title="공정별 분포")
            fig_bar.update_yaxes(dtick=1)
            st.plotly_chart(fig_bar, use_container_width=True)
        with chart_r:
            mod_sum_df = db_rep_source.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(mod_sum_df, values='수량', names='모델', hole=0.5, title="모델별 비중")
            st.plotly_chart(fig_pie, use_container_width=True)
        st.dataframe(db_rep_source.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리</h2>", unsafe_allow_html=True)
    db_bad_target = st.session_state.production_db
    wait_list = db_bad_target[db_bad_target['상태'] == "불량 처리 중"]
    today_dt = datetime.now(KST).date()
    def check_today_match(v):
        try: return pd.to_datetime(v).date() == today_dt
        except: return False
    rep_done_today = len(db_bad_target[(db_bad_target['상태'] == "수리 완료(재투입)") & (db_bad_target['시간'].apply(check_today_match))])
    stat1, stat2 = st.columns(2)
    with stat1: st.markdown(f"<div class='stat-box'><div class='stat-label'>분석 대기</div><div class='stat-value' style='color:#fa5252;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    with stat2: st.markdown(f"<div class='stat-box'><div class='stat-label'>금일 조치</div><div class='stat-value' style='color:#40c057;'>{rep_done_today}</div></div>", unsafe_allow_html=True)
    if not wait_list.empty:
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.markdown(f"**S/N: `{row['시리얼']}`**")
                r1c1, r1c2 = st.columns(2)
                v_cause = r1c1.text_input("원인 분석", key=f"rc_{idx}")
                v_action = r1c2.text_input("조치 사항", key=f"ra_{idx}")
                r2c1, r2c2 = st.columns([3, 1])
                v_img_f = r2c1.file_uploader("사진 등록", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                if r2c2.button("수리 확정", key=f"rb_{idx}", type="primary"):
                    if v_cause and v_action:
                        web_url = ""
                        if v_img_f:
                            res_url = upload_img_to_drive(v_img_f, row['시리얼'])
                            if "http" in res_url: web_url = f" [사진: {res_url}]"
                        db_bad_target.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad_target.at[idx, '시간'] = get_now_kst_str()
                        db_bad_target.at[idx, '증상'], db_bad_target.at[idx, '수리'] = v_cause, v_action + web_url
                        db_bad_target.at[idx, '작업자'] = st.session_state.user_id
                        push_to_cloud(db_bad_target); st.rerun()

# --- 6-5. 수리 이력 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 이력 리포트</h2>", unsafe_allow_html=True)
    hist_df = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    if not hist_df.empty:
        st.dataframe(hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# --- 6-6. 마스터 정보 관리 ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("master_verify"):
            m_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("인증"):
                if m_pw == "master1234":
                    st.session_state.admin_authenticated = True; st.rerun()
    else:
        if st.sidebar.button("🔓 세션 잠금"):
            st.session_state.admin_authenticated = False; handle_nav("조립 라인")
        st.markdown("<div class='section-title'>계정 및 데이터 관리</div>", unsafe_allow_html=True)
        # 계정 관리 시트 업데이트
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        r_uid = u_c1.text_input("ID 생성")
        r_upw = u_c2.text_input("PW 설정", type="password")
        r_url = u_c3.selectbox("권한 부여", list(ROLES.keys()))
        if st.button("계정 저장", use_container_width=True):
            if r_uid and r_upw:
                st.session_state.user_db[r_uid] = {"pw": r_upw, "role": r_url}
                acc_df = pd.DataFrame.from_dict(st.session_state.user_db, orient='index').reset_index()
                acc_df.columns = ['id', 'pw', 'role']
                gs_conn.update(worksheet="accounts", data=acc_df)
                st.success("저장 완료"); st.rerun()
        if st.button("⚠️ 데이터 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# [ PMS v18.0 최종 소스코드 종료 ]
