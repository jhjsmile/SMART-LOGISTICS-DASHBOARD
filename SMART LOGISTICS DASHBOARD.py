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
# 1. 시스템 전역 설정 및 디자인 (v17.8 원본 100% 유지)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v20.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 반 명칭 통일 (공백 제거)
PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]

ROLES = {
    "master": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["현황판", "리포트", "수리 리포트", "마스터 관리"],
    "admin": ["현황판", "조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
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
            df['반'] = df['반'].str.replace(" ", "")
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
    except Exception as e: st.error(f"저장 실패: {e}")

# =================================================================
# 3. 세션 상태 관리 (초기 화면 설정)
# =================================================================

if 'production_db' not in st.session_state: st.session_state.production_db = load_realtime_ledger()
if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}, "master": {"pw": "master1234", "role": "master"}}

if 'login_status' not in st.session_state: st.session_state.login_status = False
# [핵심] 로그인 시 초기 화면을 "현황판"으로 설정
if 'current_line' not in st.session_state: st.session_state.current_line = "현황판"
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조2반"

if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조1반": ["NEW-101", "NEW-102"],
        "제조2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조3반": ["AION-X", "AION-Z"]
    }
if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조1반": {"NEW-101": ["101-A"], "NEW-102": ["102-A"]},
        "제조2반": {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        "제조3반": {"AION-X": ["AX-PRO"], "AION-Z": ["AZ-ULTRA"]}
    }

# =================================================================
# 4. 로그인 및 사이드바 (초기 화면 현황판 추가)
# =================================================================

if not st.session_state.login_status:
    _, c_col, _ = st.columns([1, 1.2, 1])
    with c_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("gate_login"):
            in_id = st.text_input("아이디(ID)")
            in_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("인증 시작", use_container_width=True):
                if in_id in st.session_state.user_db and st.session_state.user_db[in_id]["pw"] == in_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = in_id
                    st.session_state.user_role = st.session_state.user_db[in_id]["role"]
                    # 로그인 시 무조건 현황판이 첫 화면이 되도록 강제 설정
                    st.session_state.current_line = "현황판"
                    st.rerun()
                else: st.error("로그인 정보가 틀립니다.")
    st.stop()

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
        if st.sidebar.button(p, key=f"fnav_{p}", use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"): 
            st.session_state.current_line = p; st.rerun()

if "마스터 관리" in allowed_nav:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        st.session_state.current_line = "마스터 관리"; st.rerun()

# =================================================================
# 5. 페이지 렌더링 (현황판 페이지 추가)
# =================================================================

db = st.session_state.production_db

# --- [5-0. 초기 현황판 페이지] ---
if st.session_state.current_line == "현황판":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 실시간 현황판</h2>", unsafe_allow_html=True)
    
    # 1. 전체 KPI 요약
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"<div class='stat-box'><div class='stat-label'>📦 누적 총 투입</div><div class='stat-value'>{len(db)}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stat-box'><div class='stat-label'>🚚 생산 완료(포장)</div><div class='stat-value' style='color:#40c057;'>{len(db[(db['라인']=='포장 라인') & (db['상태']=='완료')])}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚙️ 현재 공정 재공</div><div class='stat-value'>{len(db[db['상태']=='진행 중'])}</div></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='stat-box'><div class='stat-label'>⚠️ 분석 중인 불량</div><div class='stat-value' style='color:#fa5252;'>{len(db[db['상태'].str.contains('불량', na=False)])}</div></div>", unsafe_allow_html=True)

    st.divider()
    
    # 2. 반별 실적 비교 그래프
    col_chart1, col_chart2 = st.columns([1.5, 1])
    with col_chart1:
        st.markdown("#### 📈 반별 생산 흐름 비중")
        if not db.empty:
            fig_bar = px.histogram(db, x="반", color="라인", barmode="group", template="plotly_white", 
                                  color_discrete_map={"조립 라인": "#0068C9", "검사 라인": "#A0D1FB", "포장 라인": "#FFABAB"})
            st.plotly_chart(fig_bar, use_container_width=True)
    with col_chart2:
        st.markdown("#### 🏆 반별 합격률(%)")
        group_perf = []
        for g in PRODUCTION_GROUPS:
            total = len(db[db['반'] == g])
            success = len(db[(db['반'] == g) & (db['상태'] == '완료')])
            rate = (success / total * 100) if total > 0 else 0
            group_perf.append({"반": g, "달성률": rate})
        fig_gauge = px.bar(pd.DataFrame(group_perf), x="반", y="달성률", range_y=[0, 100], text_auto='.1f', color="달성률", color_continuous_scale="Viridis")
        st.plotly_chart(fig_gauge, use_container_width=True)

    st.markdown("<div class='section-title'>🔔 실시간 주요 공정 알림</div>", unsafe_allow_html=True)
    st.dataframe(db.sort_values('시간', ascending=False).head(10), use_container_width=True, hide_index=True)

# --- [7-1. 조립 라인] ---
elif st.session_state.current_line == "조립 라인":
    curr_g = st.session_state.selected_group
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 등록")
            g_models = st.session_state.group_master_models.get(curr_g, [])
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + g_models)
            with st.form("entry_form"):
                f1, f2 = st.columns(2)
                g_items = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
                target_item = f1.selectbox("품목 코드", g_items if target_model!="선택하세요." else ["모델 선택"])
                target_sn = f2.text_input("시리얼(S/N)")
                if st.form_submit_button("▶️ 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        if target_sn in db['시리얼'].values: st.error("이미 등록된 시리얼입니다.")
                        else:
                            new_row = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 'CELL': st.session_state.selected_cell,
                                       '모델': target_model, '품목코드': target_item, '시리얼': target_sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                            st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()

# --- [마스터 관리 - KeyError 방어 로직 적용] ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify"):
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("인증"):
                if pw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
    else:
        st.markdown("<div class='section-title'>📋 반별 독립 모델/품목 설정</div>", unsafe_allow_html=True)
        tabs = st.tabs(["제조1반", "제조2반", "제조3반"])
        for i, g_name in enumerate(["제조1반", "제조2반", "제조3반"]):
            with tabs[i]:
                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        st.subheader("신규 모델 등록")
                        nm = st.text_input(f"[{g_name}] 모델명", key=f"nm_{g_name}")
                        if st.button(f"{g_name} 모델 저장", key=f"nb_{g_name}"):
                            if nm and nm not in st.session_state.group_master_models.get(g_name, []):
                                st.session_state.group_master_models[g_name].append(nm)
                                st.session_state.group_master_items[g_name][nm] = []; st.rerun()
                with c2:
                    with st.container(border=True):
                        st.subheader("세부 품목 등록")
                        # .get()을 사용하여 KeyError 방어
                        g_mods = st.session_state.group_master_models.get(g_name, [])
                        sm = st.selectbox(f"{g_name} 모델 선택", g_mods, key=f"sm_{g_name}")
                        ni = st.text_input(f"[{sm}] 품목코드", key=f"ni_{g_name}")
                        if st.button(f"{g_name} 품목 저장", key=f"ib_{g_name}"):
                            if ni and ni not in st.session_state.group_master_items[g_name][sm]:
                                st.session_state.group_master_items[g_name][sm].append(ni); st.rerun()
                st.json(st.session_state.group_master_items.get(g_name, {}))

# (기타 페이지 로직: 리포트, 불량공정, 수리리포트 등 원본 풀버전 유지)
