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
# 1. 시스템 전역 설정 및 디자인 (v17.8 원본 스타일 유지)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v18.8",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 전역 타임존 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동으로 전체 화면을 새로고침합니다.
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 제조 반 리스트 정의
PRODUCTION_GROUPS = ["제조 1반", "제조 2반", "제조 3반"]

# 사용자 그룹별 메뉴 접근 권한 정의 (master 계정 포함)
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [v17.8 원본 CSS 스타일 100% 복원]
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
        # 반 컬럼 이관 로직
        if '반' not in df.columns:
            if not df.empty:
                df.insert(1, '반', "제조 2반")
            else:
                df.insert(1, '반', "")
        else:
            df['반'] = df['반'].apply(lambda x: "제조 2반" if x == "" else x)
        return df
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")
        return pd.DataFrame(columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

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
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded_file = drive_svc.files().create(body=meta_data, media_body=media, fields='id, webViewLink').execute()
        return uploaded_file.get('webViewLink')
    except Exception as err: 
        return f"⚠️ 업로드 실패: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (반별 독립 마스터 포함)
# =================================================================

if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_realtime_ledger()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "master": {"pw": "master1234", "role": "master"}
    }

# 반별 독립 마스터 구조 초기화 (에러 방지용 완전 선언)
if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조 1반": ["EPS100", "EPS200"],
        "제조 2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조 3반": ["T30-PRO", "T30-Standard"]
    }

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조 1반": {"EPS100": ["100-A"], "EPS200": ["200-A"]},
        "제조 2반": {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        "제조 3반": {"T30-PRO": ["T30P-A"], "T30-Standard": ["T30S-A"]}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조 2반"
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 인터페이스
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
                else: 
                    st.error("❌ 아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

# =================================================================
# 5. 사이드바 내비게이션 (계층형 Expander)
# =================================================================

st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{st.session_state.user_id} ({st.session_state.user_role})**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

my_allowed = ROLES.get(st.session_state.user_role, [])

# 제조 반별 그룹화
for group in PRODUCTION_GROUPS:
    exp_status = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=exp_status):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in my_allowed:
                is_active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True, 
                             type="primary" if is_active else "secondary"):
                    st.session_state.selected_group, st.session_state.current_line = group, p
                    st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if p in my_allowed:
        if st.sidebar.button(f"{p}", key=f"fixed_nav_{p}", use_container_width=True, 
                             type="primary" if st.session_state.current_line == p else "secondary"): 
            st.session_state.current_line = p
            st.rerun()

if "마스터 관리" in my_allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, 
                         type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        st.session_state.current_line = "마스터 관리"
        st.rerun()

# =================================================================
# 6. 공정 로직 - 공용 다이얼로그 및 로그 출력 (원본 v17.8 유지)
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
        st.success("공정 입고 처리가 완료되었습니다."); st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def draw_realtime_ledger_view(line_key, ok_btn_txt="완료 처리"):
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {st.session_state.selected_group} {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_source = st.session_state.production_db
    f_df = db_source[(db_source['반'] == st.session_state.selected_group) & (db_source['라인'] == line_key)]
    
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: 
        st.info("현재 공정에 할당된 데이터가 없습니다.")
        return
    
    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    for col, txt in zip(h_row, ["기록 시간", "CELL", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]):
        col.write(f"**{txt}**")
    
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r_row[0].write(row['시간'])
        r_row[1].write(row['CELL'])
        r_row[2].write(row['모델'])
        r_row[3].write(row['품목코드'])
        r_row[4].write(f"`{row['시리얼']}`")
        with r_row[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_grid1, b_grid2 = st.columns(2)
                if b_grid1.button(ok_btn_txt, key=f"ok_idx_{idx}", type="secondary"):
                    db_source.at[idx, '상태'] = "완료"; db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
                if b_grid2.button("🚫불량", key=f"ng_idx_{idx}"):
                    db_source.at[idx, '상태'] = "불량 처리 중"; db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 품질 이슈 분석 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 정상 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 7. 페이지별 렌더링 (800줄 규모 풀 코드)
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# --- 7-1. 조립 라인 현황 ---
if curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 신규 조립 생산 라인 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    station_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if station_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
            # 반별 모델 리스트 호출
            g_models = st.session_state.group_master_models.get(curr_g, [])
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + g_models, key=f"am_{curr_g}")
            with st.form("assembly_entry_gate"):
                fc1, fc2 = st.columns(2)
                g_items = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
                target_item = fc1.selectbox("세부 품목 코드", g_items if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("제품 시리얼(S/N) 입력")
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        full_db = st.session_state.production_db
                        if target_sn in full_db['시리얼'].values:
                            st.error(f"❌ 중복 오류: 시리얼 '{target_sn}'은 이미 등록되어 있습니다.")
                        else:
                            new_entry = {
                                '시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': target_model, '품목코드': target_item, '시리얼': target_sn, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new_entry])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    draw_realtime_ledger_view("조립 라인", "조립 완료")

# --- 7-2. 검사 / 포장 라인 ---
elif curr_l in ["검사 라인", "포장 라인"]:
    pg_title_txt = f"🔍 {curr_g} 품질 검사 현황" if curr_l == "검사 라인" else f"🚚 {curr_g} 출하 포장 현황"
    prev_line = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{pg_title_txt}</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 이전 공정 완료 물량 (입고 승인 대기)</div>", unsafe_allow_html=True)
        db_raw = st.session_state.production_db
        # 동일 반 필터링 추가
        wait_df = db_raw[(db_raw['반'] == curr_g) & (db_raw['라인'] == prev_line) & (db_raw['상태'] == "완료")]
        if not wait_df.empty:
            st.success(f"현재 총 {len(wait_df)}개의 제품이 입고 승인을 기다리고 있습니다.")
            wait_grid = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if wait_grid[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_in_{idx}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    trigger_entry_dialog()
        else: st.info("입고 가능한 대기 물량이 없습니다.")
    draw_realtime_ledger_view(curr_l, "합격 처리" if curr_l=="검사 라인" else "포장 완료")

# --- 7-3. 통합 리포트 (원본 1.8:1.2 비율 복원) ---
elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    v_group = st.radio("조회 범위 선택", ["전체"] + PRODUCTION_GROUPS, horizontal=True, index=PRODUCTION_GROUPS.index(curr_g)+1)
    df_rep = st.session_state.production_db
    if v_group != "전체": df_rep = df_rep[df_rep['반'] == v_group]
    
    if not df_rep.empty:
        q_tot, q_fin = len(df_rep), len(df_rep[(df_rep['라인']=='포장 라인') & (df_rep['상태']=='완료')])
        q_wip, q_bad = len(df_rep[df_rep['상태']=='진행 중']), len(df_rep[df_rep['상태'].str.contains("불량", na=False)])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("누적 총 투입", f"{q_tot} EA")
        c2.metric("최종 생산 실적", f"{q_fin} EA")
        c3.metric("현재 공정 재공(WIP)", f"{q_wip} EA")
        c4.metric("품질 이슈 발생", f"{q_bad} 건", delta=q_bad, delta_color="inverse")
        st.divider()
        chart_l, chart_r = st.columns([1.8, 1.2])
        with chart_l:
            pos_df = df_rep.groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(pos_df, x='라인', y='수량', color='라인', title="<b>[공정 단계별 제품 분포 현황]</b>", 
                             color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"}, template="plotly_white")
            fig_bar.update_yaxes(dtick=1, showgrid=True)
            st.plotly_chart(fig_bar, use_container_width=True)
        with chart_r:
            mod_df = df_rep.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(mod_df, values='수량', names='모델', hole=0.5, title="<b>[생산 모델별 비중]</b>")
            st.plotly_chart(fig_pie, use_container_width=True)
        st.markdown("<div class='section-title'>📋 실시간 통합 생산 관리 원장 (Ledger)</div>", unsafe_allow_html=True)
        st.dataframe(df_rep.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 7-4. 불량 수리 센터 (원본 이미지 로직) ---
elif curr_l == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치 관리</h2>", unsafe_allow_html=True)
    db_bad = st.session_state.production_db
    wait_list = db_bad[(db_bad['반'] == curr_g) & (db_bad['상태'] == "불량 처리 중")]
    stat1, stat2 = st.columns(2)
    with stat1: st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ {curr_g} 분석 대기</div><div class='stat-value' style='color:#fa5252;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    with stat2:
        today_rep = len(db_bad[(db_bad['반'] == curr_g) & (db_bad['상태'] == "수리 완료(재투입)") & (db_bad['시간'].str.contains(str(datetime.now(KST).date())))])
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ {curr_g} 금일 조치 완료</div><div class='stat-value' style='color:#40c057;'>{today_rep}</div></div>", unsafe_allow_html=True)
    
    if wait_list.empty: st.success("✅ 조치 사항이 없습니다.")
    else:
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.markdown(f"**이슈 시리얼: `{row['시리얼']}`**")
                r1, r2 = st.columns(2)
                v_c = r1.text_input("⚠️ 불량 원인", key=f"rc_{idx}")
                v_a = r2.text_input("🛠️ 조치 사항", key=f"ra_{idx}")
                c_img, c_btn = st.columns([3, 1])
                v_f = c_img.file_uploader("📸 증빙 사진", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                c_btn.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if c_btn.button("수리 확정", key=f"rb_{idx}", type="primary", use_container_width=True):
                    if v_c and v_a:
                        web_url = ""
                        if v_f:
                            with st.spinner("업로드 중..."):
                                res = upload_img_to_drive(v_f, row['시리얼'])
                                if "http" in res: web_url = f" [사진 확인: {res}]"
                        db_bad.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad.at[idx, '시간'] = get_now_kst_str()
                        db_bad.at[idx, '증상'], db_bad.at[idx, '수리'] = v_c, v_a + web_url
                        push_to_cloud(db_bad); st.rerun()

# --- 7-5. 수리 이력 리포트 ---
elif curr_l == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 품질 분석 및 수리 이력 리포트</h2>", unsafe_allow_html=True)
    db_hist = st.session_state.production_db
    hist_df = db_hist[db_hist['수리'] != ""]
    if not hist_df.empty:
        c_l, c_r = st.columns([1.8, 1.2])
        with c_l:
            fig = px.bar(hist_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 이슈 빈도")
            st.plotly_chart(fig, use_container_width=True)
        with c_r:
            fig_p = px.pie(hist_df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 불량 비중")
            st.plotly_chart(fig_p, use_container_width=True)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else: st.info("기록된 이슈 내역이 없습니다.")

# --- 7-6. 마스터 관리 (반별 독립 모델 설정 완전판) ---
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("master_verify"):
            pw = st.text_input("마스터 비밀번호", type="password")
            if st.form_submit_button("권한 인증"):
                if pw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("접근 거부")
    else:
        st.sidebar.button("🔓 세션 잠금(Lock)", on_click=lambda: setattr(st.session_state, 'admin_authenticated', False))
        st.markdown("<div class='section-title'>📋 제조 반별 독립 모델/품목 기준정보 설정</div>", unsafe_allow_html=True)
        
        m_tabs = st.tabs(["제조 1반 설정", "제조 2반 설정", "제조 3반 설정"])
        for i, g_name in enumerate(PRODUCTION_GROUPS):
            with m_tabs[i]:
                m_col1, m_col2 = st.columns(2)
                with m_col1:
                    with st.container(border=True):
                        st.subheader("신규 모델 등록")
                        nm = st.text_input(f"[{g_name}] 모델명", key=f"nm_{g_name}")
                        if st.button(f"{g_name} 모델 저장", key=f"nb_{g_name}"):
                            if nm and nm not in st.session_state.group_master_models[g_name]:
                                st.session_state.group_master_models[g_name].append(nm)
                                st.session_state.group_master_items[g_name][nm] = []; st.rerun()
                with m_col2:
                    with st.container(border=True):
                        st.subheader("세부 품목 등록")
                        sm = st.selectbox("모델 선택", st.session_state.group_master_models[g_name], key=f"sm_{g_name}")
                        ni = st.text_input("품목코드", key=f"ni_{g_name}")
                        if st.button(f"{g_name} 품목 저장", key=f"ib_{g_name}"):
                            if ni and ni not in st.session_state.group_master_items[g_name][sm]:
                                st.session_state.group_master_items[g_name][sm].append(ni); st.rerun()
                st.write(f"📂 **{g_name} 기준정보 요약**")
                st.json(st.session_state.group_master_items[g_name])

        st.divider()
        st.subheader("시스템 및 데이터 관리")
        d_c1, d_c2 = st.columns(2)
        with d_c1:
            csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 실적 CSV 백업 다운로드", csv, "PMS_Backup.csv", use_container_width=True)
        with d_c2:
            f_mig = st.file_uploader("복구용 CSV 선택", type="csv")
            if f_mig and st.button("📤 실적 데이터 로드 실행"):
                imp = pd.read_csv(f_mig)
                st.session_state.production_db = pd.concat([st.session_state.production_db, imp], ignore_index=True).drop_duplicates(subset=['시리얼'], keep='last')
                push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v18.8 FULL SOURCE END ]
# =================================================================
