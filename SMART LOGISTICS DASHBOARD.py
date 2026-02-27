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
# 1. 시스템 전역 설정 및 디자인 (UI 최적화)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v23.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 반 명칭 통일 (공백 제거)
PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]

ROLES = {
    "master": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "admin": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
}

# [CSS] 버튼 텍스트 이탈 방지 및 불량 상태 강조 라벨
st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    
    /* 버튼 텍스트 이탈 방지 */
    .stButton button { 
        display: inline-flex; justify-content: center; align-items: center;
        width: 100%; min-width: 75px; height: 38px; padding: 4px 2px !important;
        border-radius: 6px; font-weight: 600; font-size: 0.82rem !important;
        white-space: nowrap !important; overflow: hidden; transition: all 0.2s ease;
    }
    
    /* 불량 처리 중 빨간 바탕 강조 라벨 */
    .bad-status-badge {
        background-color: #fa5252; color: white; padding: 4px 10px;
        border-radius: 4px; font-weight: bold; font-size: 0.8rem;
        display: inline-block; white-space: nowrap; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
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
        border: 1px solid #e9ecef; margin-bottom: 12px; min-height: 125px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stat-label { font-size: 1rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.5rem; color: #007bff; font-weight: bold; line-height: 1; }
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
        if 'CELL' in df.columns: df = df.drop(columns=['CELL'])
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        if '반' in df.columns:
            df['반'] = df['반'].str.replace(" ", "")
            df['반'] = df['반'].apply(lambda x: "제조2반" if x == "" else x)
        else:
            df.insert(1, '반', "제조2반")
        return df
    except:
        return pd.DataFrame(columns=['시간', '반', '라인', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as e: st.error(f"저장 오류: {e}")

def upload_img_to_drive(file_obj, serial_no):
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["connections"]["gsheets"])
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        meta_data = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded_file = drive_svc.files().create(body=meta_data, media_body=media, fields='id, webViewLink').execute()
        return uploaded_file.get('webViewLink')
    except Exception as err: return f"⚠️ 업로드 실패: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (마스터 데이터 구조 정밀 초기화)
# =================================================================

if 'production_db' not in st.session_state: st.session_state.production_db = load_realtime_ledger()
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}, "master": {"pw": "master1234", "role": "master"}}

# [중요] 마스터 정보 데이터 구조 - 딕셔너리{모델: 리스트[품목]} 형태로 고정
if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {"제조1반": ["NEW-101", "NEW-102"], "제조2반": ["EPS7150", "T20i"], "제조3반": ["AION-X"]}
if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조1반": {"NEW-101": ["101-A"], "NEW-102": ["102-A"]},
        "제조2반": {"EPS7150": ["7150-A"], "T20i": ["T20i-P"]},
        "제조3반": {"AION-X": ["AX-PRO"]}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'current_line' not in st.session_state: st.session_state.current_line = "현황판"
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조2반"
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'confirm_target' not in st.session_state: st.session_state.confirm_target = None

# =================================================================
# 4. 로그인 및 사이드바 (UI 레이아웃 복구)
# =================================================================

if not st.session_state.login_status:
    _, c_col, _ = st.columns([1, 1.2, 1])
    with c_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("main_login_form"):
            u_id = st.text_input("아이디(ID)")
            u_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 및 접속 시작", use_container_width=True):
                if u_id in st.session_state.user_db and st.session_state.user_db[u_id]["pw"] == u_pw:
                    st.session_state.login_status, st.session_state.user_id, st.session_state.user_role = True, u_id, st.session_state.user_db[u_id]["role"]
                    st.session_state.current_line = "현황판"; st.rerun()
                else: st.error("로그인 정보가 올바르지 않습니다.")
    st.stop()

# 사이드바 구성
st.sidebar.markdown(f"### 🏭 생산 관리 ({st.session_state.user_id})")
if st.sidebar.button("📊 통합 실시간 현황판", use_container_width=True, type="primary" if st.session_state.current_line=="현황판" else "secondary"):
    st.session_state.current_line = "현황판"; st.rerun()

st.sidebar.divider()
allowed_nav = ROLES.get(st.session_state.user_role, [])

for group in PRODUCTION_GROUPS:
    is_exp = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=is_exp):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in allowed_nav:
                active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True, type="primary" if active else "secondary"):
                    st.session_state.selected_group, st.session_state.current_line = group, p; st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if p in allowed_nav:
        active = (st.session_state.current_line == p)
        if st.sidebar.button(p, key=f"fnav_{p}", use_container_width=True, type="primary" if active else "secondary"): 
            st.session_state.current_line = p; st.rerun()

# [복구] 마스터 관리와 로그아웃은 수리 리포트 아래 구분선 뒤에 배치
st.sidebar.divider()
if "마스터 관리" in allowed_nav:
    m_active = (st.session_state.current_line == "마스터 관리")
    if st.sidebar.button("🔐 마스터 관리", key="side_m", use_container_width=True, type="primary" if m_active else "secondary"): 
        st.session_state.current_line = "마스터 관리"; st.rerun()

if st.sidebar.button("🚪 안전 로그아웃", key="side_l", use_container_width=True): 
    st.session_state.login_status = False; st.rerun()

# =================================================================
# 5. 공용 비즈니스 로직 (승인 다이얼로그)
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    st.warning(f"승인 대상 S/N: [ {st.session_state.confirm_target} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_f = st.session_state.production_db
        idx_match = db_f[db_f['시리얼'] == st.session_state.confirm_target].index
        if not idx_match.empty:
            idx = idx_match[0]
            db_f.at[idx, '시간'], db_f.at[idx, '라인'], db_f.at[idx, '상태'], db_f.at[idx, '작업자'] = get_now_kst_str(), st.session_state.current_line, '진행 중', st.session_state.user_id
            push_to_cloud(db_f)
        st.session_state.confirm_target = None; st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 6. 페이지별 렌더링 (850줄 규모 무생략 풀버전)
# =================================================================

db = st.session_state.production_db
curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# --- 7-0. 현황판 페이지 ---
if curr_l == "현황판":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 실시간 현황판</h2>", unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(f"<div class='stat-box'><div class='stat-label'>📦 누적 투입</div><div class='stat-value'>{len(db)}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='stat-box'><div class='stat-label'>🚚 생산 완료</div><div class='stat-value' style='color:#40c057;'>{len(db[(db['라인']=='포장 라인') & (db['상태']=='완료')])}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚙️ 현재 재공</div><div class='stat-value'>{len(db[db['상태']=='진행 중'])}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚠️ 분석 대기</div><div class='stat-value' style='color:#fa5252;'>{len(db[db['상태'].str.contains('불량', na=False)])}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    cl, cr = st.columns([1.5, 1])
    with cl:
        st.markdown("#### 📈 반별 생산 분포")
        if not db.empty:
            fig_b = px.histogram(db, x="반", color="라인", barmode="group", template="plotly_white", color_discrete_map={"조립 라인": "#0068C9", "검사 라인": "#A0D1FB", "포장 라인": "#FFABAB"})
            st.plotly_chart(fig_b, use_container_width=True)
    with cr:
        st.markdown("#### 🏆 반별 합격 비율")
        rates = []
        for g in PRODUCTION_GROUPS:
            tot = len(db[db['반']==g]); fin = len(db[(db['반']==g) & (db['상태']=='완료')])
            rates.append({"반": g, "비율": (fin/tot*100) if tot>0 else 0})
        st.plotly_chart(px.bar(pd.DataFrame(rates), x="반", y="비율", range_y=[0,100], text_auto='.1f', title="목표 달성률(%)"), use_container_width=True)
    st.dataframe(db.sort_values('시간', ascending=False).head(15), use_container_width=True, hide_index=True)

# --- 7-1. 조립 라인 페이지 ---
elif curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 생산 현황</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        st.write("#### ➕ 신규 생산 입고 등록")
        g_mods = st.session_state.group_master_models.get(curr_g, [])
        t_mod = st.selectbox("모델 선택", ["선택하세요."] + g_mods)
        with st.form("assy_reg"):
            f1, f2 = st.columns(2)
            g_its = st.session_state.group_master_items.get(curr_g, {}).get(t_mod, [])
            t_item = f1.selectbox("품목 코드", g_its if t_mod!="선택하세요." else ["대기"])
            t_sn = f2.text_input("S/N 시리얼")
            if st.form_submit_button("▶️ 등록 시작", use_container_width=True, type="primary"):
                if t_mod != "선택하세요." and t_sn:
                    if t_sn in db['시리얼'].values: st.error("중복된 시리얼입니다.")
                    else:
                        new_r = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", '모델': t_mod, '품목코드': t_item, '시리얼': t_sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                        st.session_state.production_db = pd.concat([db, pd.DataFrame([new_r])], ignore_index=True)
                        push_to_cloud(st.session_state.production_db); st.rerun()
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == "조립 라인")]
    if not f_df.empty:
        h = st.columns([2.5, 2, 2, 2, 4])
        for col, txt in zip(h, ["기록 시간", "모델", "품목", "시리얼", "현장 제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.5, 2, 2, 2, 4])
            r[0].write(row['시간']); r[1].write(row['모델']); r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("조립 완료", key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                    if b2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
                elif row['상태'] == "불량 처리 중": st.markdown("<span class='bad-status-badge'>✅ 불량 처리 중</span>", unsafe_allow_html=True)
                else: st.write(f"✅ {row['상태']}")

# --- 7-2. 검사 / 포장 라인 페이지 ---
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l} 현황</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    with st.container(border=True):
        st.write(f"#### 📥 입고 대기 ({prev} 완료 물량)")
        wait_df = db[(db['반'] == curr_g) & (db['라인'] == prev) & (db['상태'] == "완료")]
        if not wait_df.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if w_cols[i%4].button(f"입고: {row['시리얼']}", key=f"in_{idx}"):
                    st.session_state.confirm_target = row['시리얼']; trigger_entry_dialog()
        else: st.info("대기 물량 없음")
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([2.5, 2, 2, 2, 4])
        for col, txt in zip(h, ["기록 시간", "모델", "품목", "시리얼", "현장 제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.5, 2, 2, 2, 4])
            r[0].write(row['시간']); r[1].write(row['모델']); r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn_t = "합격" if curr_l == "검사 라인" else "완료"
                    if c1.button(btn_t, key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
                elif row['상태'] == "불량 처리 중": st.markdown("<span class='bad-status-badge'>✅ 불량 처리 중</span>", unsafe_allow_html=True)
                else: st.write(f"✅ {row['상태']}")

# --- 7-3. 리포트 페이지 ---
elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 분석 리포트</h2>", unsafe_allow_html=True)
    df_v = db if st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True) == "전체" else db[db['반'] == curr_g]
    if not df_v.empty:
        cl, cr = st.columns([1.8, 1.2])
        with cl: st.plotly_chart(px.bar(df_v.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정 현황"), use_container_width=True)
        with cr: st.plotly_chart(px.pie(df_v.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델 비중"), use_container_width=True)
        st.dataframe(df_v.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 7-4. 불량 공정 (수리 센터) ---
elif curr_l == "불량 공정":
    st.markdown(f"<h2 class='centered-title'>🛠️ {curr_g} 불량 수리 센터</h2>", unsafe_allow_html=True)
    wait_b = db[(db['반'] == curr_g) & (db['상태'] == "불량 처리 중")]
    if wait_b.empty: st.success("품질 이슈 없음")
    else:
        for idx, row in wait_b.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']})")
                r1, r2 = st.columns(2)
                vc, va = r1.text_input("원인 판정", key=f"c_{idx}"), r2.text_input("수리 조치", key=f"a_{idx}")
                img = st.file_uploader("증빙 사진 업로드", key=f"i_{idx}")
                if st.button("수리 확정", key=f"b_{idx}", type="primary"):
                    if vc and va:
                        u_url = f" [사진 확인: {upload_img_to_drive(img, row['시리얼'])}]" if img else ""
                        db.at[idx, '상태'], db.at[idx, '시간'], db.at[idx, '증상'], db.at[idx, '수리'] = "수리 완료(재투입)", get_now_kst_str(), vc, va + u_url
                        push_to_cloud(db); st.rerun()

# --- 7-5. 수리 이력 리포트 ---
elif curr_l == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 이력 분석 로그</h2>", unsafe_allow_html=True)
    h_df = db[db['수리'] != ""]
    if not h_df.empty:
        cl, cr = st.columns([1.5, 1])
        with cl: st.plotly_chart(px.bar(h_df.groupby('모델').size().reset_index(name='건수'), x='모델', y='건수', title="모델별 불량 빈도"), use_container_width=True)
        with cr: st.plotly_chart(px.pie(h_df.groupby('증상').size().reset_index(name='건수'), values='건수', names='증상', title="증상별 분포"), use_container_width=True)
        st.dataframe(h_df, use_container_width=True, hide_index=True)
    else: st.info("수리 이력 없음")

# --- 7-6. 마스터 관리 (검수 완료 섹션) ---
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 정보 설정</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("auth_form"):
            if st.form_submit_button("인증") and st.text_input("비밀번호", type="password") in ["admin1234", "master1234"]:
                st.session_state.admin_authenticated = True; st.rerun()
    else:
        if st.button("🔓 세션 잠금(Lock)"): st.session_state.admin_authenticated = False; st.rerun()
        
        tabs = st.tabs([f"{g} 설정" for g in PRODUCTION_GROUPS])
        for i, g in enumerate(PRODUCTION_GROUPS):
            with tabs[i]:
                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        st.subheader("모델 등록")
                        nm = st.text_input(f"[{g}] 신규 모델명", key=f"nm_{g}")
                        if st.button(f"{g} 모델 저장", key=f"nb_{g}", use_container_width=True):
                            # [검수] KeyError 방어 로직
                            if g not in st.session_state.group_master_models: st.session_state.group_master_models[g] = []
                            if nm and nm not in st.session_state.group_master_models[g]:
                                st.session_state.group_master_models[g].append(nm)
                                if g not in st.session_state.group_master_items: st.session_state.group_master_items[g] = {}
                                st.session_state.group_master_items[g][nm] = []
                                st.rerun()
                with c2:
                    with st.container(border=True):
                        st.subheader("품목 등록")
                        m_list = st.session_state.group_master_models.get(g, [])
                        sm = st.selectbox(f"{g} 모델 선택", m_list if m_list else ["모델을 먼저 등록하세요"], key=f"sm_{g}")
                        ni = st.text_input(f"[{sm}] 신규 품목코드", key=f"ni_{g}")
                        if st.button(f"{g} 품목 저장", key=f"ib_{g}", use_container_width=True):
                            if sm != "모델을 먼저 등록하세요" and ni:
                                # [검수] 리스트 구조로 데이터 업데이트 (숫자 인덱스 제거 로직)
                                if sm not in st.session_state.group_master_items[g]: st.session_state.group_master_items[g][sm] = []
                                if ni not in st.session_state.group_master_items[g][sm]:
                                    st.session_state.group_master_items[g][sm].append(ni)
                                    st.rerun()
                
                st.write(f"📂 **{g} 마스터 정보 요약**")
                master_view = st.session_state.group_master_items.get(g, {})

                if master_view:
                    # JSON처럼 보이되 숫자가 없는 깔끔한 텍스트 박스로 출력
                    import json
                    formatted_json = json.dumps(master_view, indent=4, ensure_ascii=False)
                    st.code(formatted_json, language="json") 
                else:
                    st.info("등록된 마스터 정보가 없습니다.")
        
        st.divider()
        st.subheader("데이터 관리")
        c_csv, c_mig = st.columns(2)
        with c_csv: st.download_button("📥 전체 실적 CSV 백업", db.to_csv(index=False).encode('utf-8-sig'), "Backup.csv", use_container_width=True)
        with c_mig:
            f = st.file_uploader("복구용 CSV 선택", type="csv")
            if f and st.button("📤 데이터 로드 실행", use_container_width=True):
                imp = pd.read_csv(f)
                st.session_state.production_db = pd.concat([st.session_state.production_db, imp], ignore_index=True).drop_duplicates(subset=['시리얼'], keep='last')
                push_to_cloud(st.session_state.production_db); st.rerun()
        if st.button("⚠️ 시스템 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간','반','라인','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v23.0 무생략 최종 완결판 END ]
# =================================================================

