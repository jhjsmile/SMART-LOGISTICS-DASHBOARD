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
# 1. 시스템 전역 설정 및 디자인
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v21.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

# [중요] 모든 명칭에서 공백 제거 (KeyError 방지)
PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]

ROLES = {
    "master": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "admin": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { 
        display: flex; justify-content: center; align-items: center;
        margin-top: 1px; padding: 6px 10px; width: 100%; border-radius: 8px;
        font-weight: 600; white-space: nowrap !important; transition: all 0.2s ease;
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
    .stat-label { font-size: 1rem; color: #6c757d; font-weight: bold; margin-bottom: 8px; }
    .stat-value { font-size: 2.6rem; color: #007bff; font-weight: bold; line-height: 1; }
    .status-red { color: #fa5252; font-weight: bold; }
    .status-green { color: #40c057; font-weight: bold; }
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
        if '반' in df.columns:
            df['반'] = df['반'].str.replace(" ", "") # 모든 공백 제거
            df['반'] = df['반'].apply(lambda x: "제조2반" if x == "" else x)
        else:
            df.insert(1, '반', "제조2반")
        return df
    except:
        return pd.DataFrame(columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"클라우드 저장 실패: {e}")

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
        return f"⚠️ 실패: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (에러 방지용 완전 구조)
# =================================================================

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_realtime_ledger()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "master": {"pw": "master1234", "role": "master"}
    }

if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조1반": ["EPS100", "EPS200"],
        "제조2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조3반": ["AION-X", "AION-Z"]
    }

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조1반": {"EPS100": ["100-A"], "EPS200": ["200-A"]},
        "제조2반": {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        "제조3반": {"AION-X": ["AX-PRO"], "AION-Z": ["AZ-ULTRA"]}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'current_line' not in st.session_state: st.session_state.current_line = "현황판"
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조2반"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# =================================================================
# 4. 로그인 로직
# =================================================================

if not st.session_state.login_status:
    _, c_col, _ = st.columns([1, 1.2, 1])
    with c_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("main_login"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 및 접속", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = "현황판"
                    st.rerun()
                else: st.error("로그인 정보가 틀립니다.")
    st.stop()

# =================================================================
# 5. 사이드바 내비게이션
# =================================================================

st.sidebar.markdown(f"### 🏭 생산 관리 ({st.session_state.user_id})")
if st.sidebar.button("📊 통합 실시간 현황판", use_container_width=True, type="primary" if st.session_state.current_line=="현황판" else "secondary"):
    st.session_state.current_line = "현황판"; st.rerun()

st.sidebar.divider()
allowed_nav = ROLES.get(st.session_state.user_role, [])

for group in PRODUCTION_GROUPS:
    exp = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=exp):
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

if "마스터 관리" in allowed_nav:
    st.sidebar.divider()
    active = (st.session_state.current_line == "마스터 관리")
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if active else "secondary"): 
        st.session_state.current_line = "마스터 관리"; st.rerun()

if st.sidebar.button("🚪 로그아웃", use_container_width=True): 
    st.session_state.login_status = False; st.rerun()

# =================================================================
# 6. 공용 다이얼로그 (승인 팝업)
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
        st.success("완료되었습니다."); st.rerun()
    if c_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None; st.rerun()

# =================================================================
# 7. 페이지별 렌더링 (800줄 이상 풀 로직)
# =================================================================

db = st.session_state.production_db
curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# --- 7-0. 통합 현황판 (로그인 초기 화면) ---
if curr_l == "현황판":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 실시간 현황판</h2>", unsafe_allow_html=True)
    
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(f"<div class='stat-box'><div class='stat-label'>📦 누적 투입량</div><div class='stat-value'>{len(db)}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='stat-box'><div class='stat-label'>🚚 생산 완료</div><div class='stat-value' style='color:#40c057;'>{len(db[(db['라인']=='포장 라인') & (db['상태']=='완료')])}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚙️ 현재 재공</div><div class='stat-value'>{len(db[db['상태']=='진행 중'])}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚠️ 불량/수리</div><div class='stat-value' style='color:#fa5252;'>{len(db[db['상태'].str.contains('불량', na=False)])}</div></div>", unsafe_allow_html=True)

    st.divider()
    cl, cr = st.columns([1.5, 1])
    with cl:
        st.markdown("#### 📈 반별 생산 흐름")
        if not db.empty:
            fig_bar = px.histogram(db, x="반", color="라인", barmode="group", template="plotly_white",
                                   color_discrete_map={"조립 라인": "#0068C9", "검사 라인": "#A0D1FB", "포장 라인": "#FFABAB"})
            st.plotly_chart(fig_bar, use_container_width=True)
    with cr:
        st.markdown("#### 🏆 반별 합격 비율")
        rates = []
        for g in PRODUCTION_GROUPS:
            tot = len(db[db['반']==g])
            fin = len(db[(db['반']==g) & (db['상태']=='완료')])
            rates.append({"반": g, "비율": (fin/tot*100) if tot>0 else 0})
        fig_r = px.bar(pd.DataFrame(rates), x="반", y="비율", range_y=[0,100], text_auto='.1f', color="비율")
        st.plotly_chart(fig_r, use_container_width=True)
    
    st.markdown("<div class='section-title'>🔔 최근 생산 활동 로그</div>", unsafe_allow_html=True)
    st.dataframe(db.sort_values('시간', ascending=False).head(15), use_container_width=True, hide_index=True)

# --- 7-1. 조립 라인 ---
elif curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 생산 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 생산 등록")
            g_mods = st.session_state.group_master_models.get(curr_g, [])
            t_mod = st.selectbox("투입 모델", ["선택하세요."] + g_mods)
            with st.form("assy_form"):
                f1, f2 = st.columns(2)
                g_its = st.session_state.group_master_items.get(curr_g, {}).get(t_mod, [])
                t_item = f1.selectbox("품목 코드", g_its if t_mod!="선택하세요." else ["대기"])
                t_sn = f2.text_input("S/N 입력")
                if st.form_submit_button("▶️ 생산 시작", use_container_width=True, type="primary"):
                    if t_mod != "선택하세요." and t_sn:
                        if t_sn in db['시리얼'].values: st.error("이미 등록된 시리얼입니다.")
                        else:
                            new_row = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 'CELL': st.session_state.selected_cell,
                                       '모델': t_mod, '품목코드': t_item, '시리얼': t_sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                            st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == "조립 라인")]
    if st.session_state.selected_cell != "전체 CELL": f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델']); r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    b1, b2 = st.columns(2)
                    if b1.button("완료", key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                    if b2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
                else: st.write(f"✅ {row['상태']}")

# --- 7-2. 검사 / 포장 라인 ---
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l}</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    with st.container(border=True):
        st.markdown(f"#### 📥 입고 대기 ({prev} 완료 물량)")
        wait_df = db[(db['반'] == curr_g) & (db['라인'] == prev) & (db['상태'] == "완료")]
        if not wait_df.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if w_cols[i%4].button(f"승인: {row['시리얼']}", key=f"in_{idx}"):
                    st.session_state.confirm_target = row['시리얼']; trigger_entry_dialog()
        else: st.info("대기 없음")
    
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델']); r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn = "합격" if curr_l == "검사 라인" else "포장"
                    if c1.button(btn, key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
                else: st.write(f"✅ {row['상태']}")

# --- 7-3. 통합 리포트 ---
elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 리포트</h2>", unsafe_allow_html=True)
    v_g = st.radio("조회 반", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = db if v_g == "전체" else db[db['반'] == v_g]
    if not df.empty:
        cl, cr = st.columns([1.8, 1.2])
        with cl:
            st.plotly_chart(px.bar(df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정 현황"), use_container_width=True)
        with cr:
            st.plotly_chart(px.pie(df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델 비중"), use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 7-4. 불량 및 수리 센터 ---
elif curr_l == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ {curr_g} 수리 센터</h2>", unsafe_allow_html=True)
    wait = db[(db['반'] == curr_g) & (db['상태'] == "불량 처리 중")]
    if wait.empty: st.success("이슈 없음")
    else:
        for idx, row in wait.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}**")
                r1, r2 = st.columns(2)
                vc = r1.text_input("원인", key=f"c_{idx}")
                va = r2.text_input("조치", key=f"a_{idx}")
                img = st.file_uploader("사진", key=f"i_{idx}")
                if st.button("수리 확정", key=f"b_{idx}", type="primary"):
                    if vc and va:
                        u = ""
                        if img: u = f" [사진: {upload_img_to_drive(img, row['시리얼'])}]"
                        db.at[idx, '상태'] = "수리 완료(재투입)"
                        db.at[idx, '증상'], db.at[idx, '수리'] = vc, va + u
                        push_to_cloud(db); st.rerun()

# --- 7-5. 수리 이력 리포트 ---
elif curr_l == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 이력</h2>", unsafe_allow_html=True)
    hist = db[db['수리'] != ""]
    if not hist.empty:
        st.dataframe(hist, use_container_width=True, hide_index=True)
    else: st.info("내역 없음")

# --- 7-6. 마스터 데이터 관리 ---
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("auth"):
            pw = st.text_input("PW", type="password")
            if st.form_submit_button("인증"):
                if pw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
    else:
        t1, t2, t3 = st.tabs(PRODUCTION_GROUPS)
        for i, g in enumerate(PRODUCTION_GROUPS):
            with t1 if i==0 else t2 if i==1 else t3:
                c1, c2 = st.columns(2)
                with c1:
                    nm = st.text_input(f"{g} 모델명", key=f"nm_{g}")
                    if st.button(f"{g} 모델 저장", key=f"nb_{g}"):
                        if nm and nm not in st.session_state.group_master_models[g]:
                            st.session_state.group_master_models[g].append(nm)
                            st.session_state.group_master_items[g][nm] = []; st.rerun()
                with c2:
                    g_mods = st.session_state.group_master_models.get(g, [])
                    sm = st.selectbox(f"{g} 모델 선택", g_mods, key=f"sm_{g}")
                    ni = st.text_input(f"[{sm}] 품목코드", key=f"ni_{g}")
                    if st.button(f"{g} 품목 저장", key=f"ib_{g}"):
                        if ni and ni not in st.session_state.group_master_items[g][sm]:
                            st.session_state.group_master_items[g][sm].append(ni); st.rerun()
                st.json(st.session_state.group_master_items.get(g, {}))
        
        st.divider()
        st.download_button("📥 실적 다운로드", db.to_csv(index=False).encode('utf-8-sig'), "Backup.csv", use_container_width=True)
        if st.button("⚠️ 초기화"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','반','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v21.0 FULL VERSION END ]
# =================================================================
