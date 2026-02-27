import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh
import json

# [구글 클라우드 서비스 연동] 드라이브 API 및 인증 라이브러리
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 디자인 (UI 최적화)
# =================================================================
st.set_page_config(
    page_title="생산 통합 관리 시스템 v26.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

KST = timezone(timedelta(hours=9))
st_autorefresh(interval=30000, key="pms_auto_refresh")

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
        display: inline-flex; justify-content: center; align-items: center;
        width: 100%; min-width: 75px; height: 38px; padding: 4px 2px !important;
        border-radius: 6px; font-weight: 600; font-size: 0.82rem !important;
        white-space: nowrap !important; overflow: hidden; transition: all 0.2s ease;
    }
    .bad-status-badge {
        background-color: #fa5252; color: white; padding: 4px 10px;
        border-radius: 4px; font-weight: bold; font-size: 0.8rem;
        display: inline-block; white-space: nowrap; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .centered-title { text-align: center; font-weight: bold; margin: 25px 0; color: #1a1c1e; }
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
# 2. 핵심 유틸리티 및 시트 연동 함수
# =================================================================
def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_sheet_data(sheet_name="Sheet1"):
    try:
        df = gs_conn.read(worksheet=sheet_name, ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except:
        return pd.DataFrame()

def push_to_cloud(df, sheet_name="Sheet1"):
    try:
        gs_conn.update(worksheet=sheet_name, data=df)
        st.cache_data.clear()
    except Exception as e: st.error(f"저장 실패: {e}")

def sync_master_data():
    master_df = load_sheet_data("Master_DB")
    models = {g: [] for g in PRODUCTION_GROUPS}
    items = {g: {} for g in PRODUCTION_GROUPS}
    if not master_df.empty:
        for _, row in master_df.iterrows():
            g, mod, it = str(row.get('반','')).strip(), str(row.get('모델','')).strip(), str(row.get('품목코드','')).strip()
            if g in models:
                if mod not in models[g]: models[g].append(mod)
                if mod not in items[g]: items[g][mod] = []
                if it and it not in items[g][mod]: items[g][mod].append(it)
    return models, items

# =================================================================
# 3. 세션 상태 관리
# =================================================================
if 'production_db' not in st.session_state:
    st.session_state.production_db = load_sheet_data("Sheet1")

m_models, m_items = sync_master_data()
st.session_state.group_master_models = m_models
st.session_state.group_master_items = m_items

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'current_line' not in st.session_state: st.session_state.current_line = "현황판"
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조2반"
if 'confirm_target' not in st.session_state: st.session_state.confirm_target = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# =================================================================
# 4. 로그인 및 사이드바
# =================================================================
if not st.session_state.login_status:
    _, c_col, _ = st.columns([1, 1.2, 1])
    with c_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("main_login"):
            uid = st.text_input("아이디")
            upw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("인증 및 접속", use_container_width=True):
                if upw in ["admin1234", "master1234"]: # 단순화된 예시
                    st.session_state.login_status, st.session_state.user_id = True, uid
                    st.rerun()
    st.stop()

st.sidebar.markdown(f"### 🏭 생산 관리 ({st.session_state.user_id})")
if st.sidebar.button("📊 통합 실시간 현황판", use_container_width=True):
    st.session_state.current_line = "현황판"; st.rerun()

st.sidebar.divider()
for group in PRODUCTION_GROUPS:
    exp = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=exp):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True):
                st.session_state.selected_group, st.session_state.current_line = group, p; st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if st.sidebar.button(p, key=f"fnav_{p}", use_container_width=True): 
        st.session_state.current_line = p; st.rerun()

st.sidebar.divider()
if st.sidebar.button("🔐 마스터 관리", use_container_width=True): 
    st.session_state.current_line = "마스터 관리"; st.rerun()
if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): st.session_state.login_status = False; st.rerun()

# =================================================================
# 5. 메인 로직 (조립 라인까지)
# =================================================================
db = st.session_state.production_db
curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

if curr_l == "현황판":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 실시간 현황판</h2>", unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📦 누적 투입", len(db))
    k2.metric("🚚 생산 완료", len(db[(db['라인']=='포장 라인') & (db['상태']=='완료')]))
    k3.metric("⚙️ 현재 재공", len(db[db['상태']=='진행 중']))
    k4.metric("⚠️ 분석 불량", len(db[db['상태'].str.contains('불량', na=False)]))
    st.divider()
    st.dataframe(db.sort_values('시간', ascending=False).head(20), use_container_width=True, hide_index=True)

elif curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 현황</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        mods = st.session_state.group_master_models.get(curr_g, [])
        t_mod = st.selectbox("모델 선택", ["선택하세요."] + mods)
        with st.form("assy_reg"):
            f1, f2 = st.columns(2)
            its = st.session_state.group_master_items.get(curr_g, {}).get(t_mod, [])
            t_item = f1.selectbox("품목", its if t_mod!="선택하세요." else ["대기"])
            t_sn = f2.text_input("S/N 입력")
            if st.form_submit_button("▶️ 생산 등록", use_container_width=True, type="primary"):
                if t_mod != "선택하세요." and t_sn:
                    new_r = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", '모델': t_mod, '품목코드': t_item, '시리얼': t_sn, '상태': '진행 중'}
                    st.session_state.production_db = pd.concat([db, pd.DataFrame([new_r])], ignore_index=True)
                    push_to_cloud(st.session_state.production_db); st.rerun()
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == "조립 라인")]
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r = st.columns([3, 2, 2, 2, 3])
        r[0].write(row['시간']); r[1].write(row['모델']); r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
        with r[4]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                c1, c2 = st.columns(2)
                if c1.button("완료", key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                if c2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
            elif row['상태'] == "불량 처리 중": st.markdown("<span class='bad-status-badge'>✅ 불량 처리 중</span>", unsafe_allow_html=True)
            else: st.write(f"✅ {row['상태']}")

# 이 다음 코드(검사 라인부터 끝까지)는 바로 다음 메시지에서 이어집니다.

# --- 1/2 파트에서 이어지는 코드입니다 ---

elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l} 현황</h2>", unsafe_allow_html=True)
    prev_line = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    
    with st.container(border=True):
        st.write(f"#### 📥 입고 대기 ({prev_line} 완료 물량)")
        wait_df = db[(db['반'] == curr_g) & (db['라인'] == prev_line) & (db['상태'] == "완료")]
        if not wait_df.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_df.iterrows()):
                if w_cols[i%4].button(f"입고: {row['시리얼']}", key=f"in_{idx}"):
                    # 입고 승인 로직 (다이얼로그 대신 즉시 처리로 안정성 강화)
                    db.at[idx, '시간'], db.at[idx, '라인'], db.at[idx, '상태'] = get_now_kst_str(), curr_l, '진행 중'
                    push_to_cloud(db); st.rerun()
        else: st.info("현재 대기 중인 물량이 없습니다.")
        
    st.divider()
    f_df = db[(db['반'] == curr_g) & (db['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([3, 2, 2, 2, 3])
        for col, txt in zip(h, ["기록 시간", "모델", "품목", "시리얼", "제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([3, 2, 2, 2, 3])
            r[0].write(row['시간']); r[1].write(row['모델']); r[2].write(row['품목코드']); r[3].write(f"`{row['시리얼']}`")
            with r[4]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn_label = "합격" if curr_l == "검사 라인" else "완료"
                    if c1.button(btn_label, key=f"ok_{idx}"): db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"): db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
                elif row['상태'] == "불량 처리 중": st.markdown("<span class='bad-status-badge'>✅ 불량 처리 중</span>", unsafe_allow_html=True)
                else: st.write(f"✅ {row['상태']}")

elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 실시간 생산 분석 리포트</h2>", unsafe_allow_html=True)
    sel_range = st.radio("조회 범위 선택", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df_v = db if sel_range == "전체" else db[db['반'] == sel_range]
    
    if not df_v.empty:
        col_l, col_r = st.columns([1.8, 1.2])
        with col_l:
            st.plotly_chart(px.bar(df_v.groupby('라인').size().reset_index(name='수량'), 
                                   x='라인', y='수량', color='라인', title="공정별 재공 분포"), use_container_width=True)
        with col_r:
            st.plotly_chart(px.pie(df_v.groupby('모델').size().reset_index(name='수량'), 
                                   values='수량', names='모델', hole=0.4, title="모델별 생산 비중"), use_container_width=True)
        st.divider()
        st.write("#### 📋 상세 데이터 리스트")
        st.dataframe(df_v.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else: st.warning("데이터가 없습니다.")

elif curr_l == "불량 공정":
    st.markdown(f"<h2 class='centered-title'>🛠️ {curr_g} 불량 수리 센터</h2>", unsafe_allow_html=True)
    wait_b = db[(db['반'] == curr_g) & (db['상태'] == "불량 처리 중")]
    
    if wait_b.empty: st.success("현재 처리할 품질 이슈가 없습니다.")
    else:
        for idx, row in wait_b.iterrows():
            with st.container(border=True):
                st.write(f"**🚨 불량 발생 S/N: {row['시리얼']}** (모델: {row['모델']})")
                r1, r2 = st.columns(2)
                cause = r1.text_input("불량 원인 판정", key=f"cause_{idx}")
                action = r2.text_input("수리 조치 내용", key=f"action_{idx}")
                
                # 이미지 업로드 로직
                img_file = st.file_uploader("증빙 사진 업로드", key=f"img_{idx}")
                
                if st.button("수리 완료 등록", key=f"repair_btn_{idx}", type="primary"):
                    if cause and action:
                        img_url = ""
                        if img_file: img_url = f" [사진 확인: {upload_img_to_drive(img_file, row['시리얼'])}]"
                        
                        db.at[idx, '상태'] = "수리 완료(재투입)"
                        db.at[idx, '시간'] = get_now_kst_str()
                        db.at[idx, '증상'] = cause
                        db.at[idx, '수리'] = action + img_url
                        push_to_cloud(db); st.rerun()
                    else: st.error("원인과 조치 내용을 입력해 주세요.")

elif curr_l == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 이력 분석 로그</h2>", unsafe_allow_html=True)
    h_df = db[db['수리'] != ""]
    if not h_df.empty:
        c1, c2 = st.columns([1.5, 1])
        with c1: st.plotly_chart(px.bar(h_df.groupby('모델').size().reset_index(name='건수'), x='모델', y='건수', title="모델별 불량 발생 건수"), use_container_width=True)
        with c2: st.plotly_chart(px.pie(h_df.groupby('증상').size().reset_index(name='건수'), values='건수', names='증상', title="주요 불량 원인 비중"), use_container_width=True)
        st.dataframe(h_df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else: st.info("기록된 수리 이력이 없습니다.")

elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 대량 관리 (Google Sheet 연동)</h2>", unsafe_allow_html=True)
    
    # 관리자 인증
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth"):
            pw = st.text_input("관리자 비밀번호", type="password")
            if st.form_submit_button("인증"):
                if pw == "admin1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("비밀번호가 틀렸습니다.")
    else:
        st.info("💡 **동기화 안내:** 구글 스프레드시트의 **'Master_DB'** 탭에서 데이터를 수정한 후 아래 버튼을 누르면 대량 등록이 완료됩니다.")
        
        if st.button("🔄 시트 데이터 동기화 (새로고침)", type="primary", use_container_width=True):
            m_m, m_i = sync_master_data()
            st.session_state.group_master_models, st.session_state.group_master_items = m_m, m_i
            st.success("✅ 시트로부터 최신 마스터 정보를 성공적으로 불러왔습니다."); st.rerun()
            
        st.divider()
        st.subheader("현재 등록 현황 확인")
        tabs = st.tabs(PRODUCTION_GROUPS)
        for i, g in enumerate(PRODUCTION_GROUPS):
            with tabs[i]:
                m_v = st.session_state.group_master_items.get(g, {})
                if m_v:
                    # 현준님 요청사항: 숫자가 안 나오는 깔끔한 JSON 코드 박스 출력
                    st.code(json.dumps(m_v, indent=4, ensure_ascii=False), language="json")
                else: st.info("등록된 모델/품목 데이터가 없습니다.")

        st.divider()
        st.subheader("⚙️ 데이터 초기화 및 백업")
        c1, c2 = st.columns(2)
        with c1: st.download_button("📥 전체 실적 CSV 다운로드", db.to_csv(index=False).encode('utf-8-sig'), "PMS_Backup.csv", use_container_width=True)
        with c2: 
            if st.button("⚠️ 시스템 실적 초기화", type="secondary", use_container_width=True):
                st.session_state.production_db = pd.DataFrame(columns=['시간','반','라인','모델','품목코드','시리얼','상태','증상','수리','작업자'])
                push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v26.0 FULL VERSION END ]
# =================================================================
