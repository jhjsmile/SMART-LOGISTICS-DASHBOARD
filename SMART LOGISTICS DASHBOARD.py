import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh
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

# 대한민국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동 새로고침
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 제조 반 리스트 정의
PRODUCTION_GROUPS = ["제조 1반", "제조 2반", "제조 3반"]

# [정밀 검수된 CSS 스타일]
st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { 
        display: flex; justify-content: center; align-items: center;
        padding: 6px 10px; width: 100%; border-radius: 8px; font-weight: 600;
        white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis;
    }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; color: #1a1c1e; }
    .section-title { 
        background-color: #f8f9fa; color: #111; padding: 15px; border-radius: 10px; 
        font-weight: bold; margin: 10px 0 20px 0; border-left: 10px solid #007bff;
    }
    .stat-box {
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        background-color: #ffffff; border-radius: 12px; padding: 20px; border: 1px solid #e9ecef;
        margin-bottom: 15px; min-height: 100px; box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stat-label { font-size: 0.9rem; color: #6c757d; font-weight: bold; }
    .stat-value { font-size: 2rem; color: #007bff; font-weight: bold; }
    .status-red { color: #fa5252; font-weight: bold; }
    .status-green { color: #40c057; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 핵심 유틸리티 함수 (Core Utilities)
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

gs_conn = st.connection("gsheets", type=GSheetsConnection)

def load_realtime_ledger():
    try:
        df = gs_conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # [중요] 기존 데이터 제조 2반으로 이관 로직
        if '반' not in df.columns:
            if not df.empty:
                df['반'] = "제조 2반"
            else:
                df.insert(1, '반', "") # 시간 컬럼 뒤에 반 컬럼 삽입
        return df
    except Exception as e:
        return pd.DataFrame(columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def push_to_cloud(df):
    try:
        gs_conn.update(data=df)
        st.cache_data.clear()
    except Exception as error:
        st.error(f"클라우드 저장 실패: {error}")

# =================================================================
# 3. 세션 상태 관리 (Session State)
# =================================================================

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_realtime_ledger()

# 현재 선택된 반 및 라인 추적
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조 2반"
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'user_id' not in st.session_state: st.session_state.user_id = "현준"

# 기준 정보
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], "T20C": ["T20C-Standard"]
    }

# =================================================================
# 4. 사이드바 내비게이션 (계층형 메뉴 구현)
# =================================================================

st.sidebar.markdown("### 🏭 생산 통합 관리 v18.0")
st.sidebar.markdown(f"**작업자:** {st.session_state.user_id}")
st.sidebar.divider()

# [메뉴 구성 1] 제조 반별 공정 현황 (Expander 활용)
for group in PRODUCTION_GROUPS:
    with st.sidebar.expander(f"📍 {group}", expanded=(st.session_state.selected_group == group)):
        for line in ["조립 라인", "검사 라인", "포장 라인"]:
            is_active = (st.session_state.selected_group == group and st.session_state.current_line == line)
            if st.button(f"{line} 현황", key=f"nav_{group}_{line}", type="primary" if is_active else "secondary"):
                st.session_state.selected_group = group
                st.session_state.current_line = line
                st.rerun()

st.sidebar.divider()

# [메뉴 구성 2] 통합 리포트 섹션
with st.sidebar.expander("📊 리포트 센터", expanded=("리포트" in st.session_state.current_line)):
    for rep in ["생산 리포트", "불량 리포트"]:
        if st.button(rep, key=f"nav_{rep}", type="primary" if st.session_state.current_line == rep else "secondary"):
            st.session_state.current_line = rep
            st.rerun()

# [메뉴 구성 3] 시스템 관리
if st.sidebar.button("🔐 마스터 데이터 관리", type="primary" if st.session_state.current_line == "마스터 관리" else "secondary"):
    st.session_state.current_line = "마스터 관리"
    st.rerun()

# =================================================================
# 5. 공통 비즈니스 로직 함수
# =================================================================

def draw_v18_optimized_log(group_key, line_key, ok_btn_txt="완료 처리"):
    """반별/라인별 필터링된 실시간 작업 원장을 출력합니다."""
    st.markdown(f"<h3 class='centered-title'>📝 {group_key} {line_key} 실시간 원장</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    
    # 해당 반 + 해당 라인 데이터만 필터링
    f_df = db[(db['반'] == group_key) & (db['라인'] == line_key)]
    
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL":
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]

    if f_df.empty:
        st.info(f"현재 {group_key} {line_key}에 할당된 제품이 없습니다.")
        return

    # 헤더
    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    for col, txt in zip(h_row, ["기록 시간", "CELL", "생산모델", "품목코드", "시리얼", "현장 제어"]):
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
                b1, b2 = st.columns(2)
                if b1.button(ok_btn_txt, key=f"ok_{idx}"):
                    db.at[idx, '상태'] = "완료"; push_to_cloud(db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 품질 이슈 분석 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 정상 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 렌더링 (Page Views)
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# --- 6-1. 조립 라인 ---
if curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 조립 생산 현황</h2>", unsafe_allow_html=True)
    
    stations = ["CELL 1", "CELL 2", "CELL 3", "CELL 4", "전체 CELL"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"):
            st.session_state.selected_cell = name; st.rerun()

    if "전체" not in st.session_state.selected_cell:
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 등록")
            target_model = st.selectbox("모델 선택", st.session_state.master_models)
            with st.form("entry_form"):
                fc1, fc2 = st.columns(2)
                t_item = fc1.selectbox("품목 코드", st.session_state.master_items_dict.get(target_model, []))
                t_sn = fc2.text_input("시리얼(S/N)")
                if st.form_submit_button("▶️ 생산 등록", use_container_width=True):
                    if t_sn:
                        full_db = st.session_state.production_db
                        if t_sn in full_db['시리얼'].values:
                            st.error("이미 등록된 시리얼입니다.")
                        else:
                            new_row = {
                                '시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, '모델': target_model, 
                                '품목코드': t_item, '시리얼': t_sn, '상태': '진행 중', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new_row])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()

    draw_v18_optimized_log(curr_g, "조립 라인", "조립 완료")

# --- 6-2. 검사 / 포장 라인 ---
elif curr_l in ["검사 라인", "포장 라인"]:
    prev_line = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l}</h2>", unsafe_allow_html=True)
    
    # 입고 대기 (동일 반 내에서 이전 공정 완료된 것)
    db_ref = st.session_state.production_db
    wait_list = db_ref[(db_ref['반'] == curr_g) & (db_ref['라인'] == prev_line) & (db_ref['상태'] == "완료")]
    
    with st.container(border=True):
        st.markdown(f"**📥 {prev_line} → {curr_l} 입고 대기: {len(wait_list)}건**")
        if not wait_list.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_list.iterrows()):
                if w_cols[i % 4].button(f"승인: {row['시리얼']}", key=f"in_{idx}"):
                    db_ref.at[idx, '시간'] = get_now_kst_str()
                    db_ref.at[idx, '라인'] = curr_l
                    db_ref.at[idx, '상태'] = "진행 중"
                    push_to_cloud(db_ref); st.rerun()
        else:
            st.caption("대기 물량이 없습니다.")

    draw_v18_optimized_log(curr_g, curr_l, "합격 처리" if "검사" in curr_l else "포장 완료")

# --- 6-3. 생산 리포트 (반별 필터링) ---
elif curr_l == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 제조 반별 생산 리포트</h2>", unsafe_allow_html=True)
    
    # 리포트 상단 반 선택 필터
    rep_g = st.radio("조회 대상 선택", ["전체보기"] + PRODUCTION_GROUPS, horizontal=True)
    df_rep = st.session_state.production_db
    if rep_g != "전체보기":
        df_rep = df_rep[df_rep['반'] == rep_g]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("총 투입", f"{len(df_rep)} EA")
    c2.metric("완제품 실적", f"{len(df_rep[(df_rep['라인']=='포장 라인') & (df_rep['상태']=='완료')])} EA")
    c3.metric("진행 중(WIP)", f"{len(df_rep[df_rep['상태']=='진행 중'])} EA")
    
    st.divider()
    fig = px.bar(df_rep.groupby(['반', '라인']).size().reset_index(name='수량'), 
                 x='라인', y='수량', color='반', barmode='group', title="반별/공정별 재공 현황")
    st.plotly_chart(fig, use_container_width=True)
    
    st.dataframe(df_rep.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 리포트 (반별 필터링) ---
elif curr_l == "불량 리포트":
    st.markdown("<h2 class='centered-title'>🛠️ 품질 이슈 분석 리포트</h2>", unsafe_allow_html=True)
    rep_g = st.radio("조회 대상 선택", ["전체보기"] + PRODUCTION_GROUPS, horizontal=True, key="bad_rep_g")
    df_bad = st.session_state.production_db[st.session_state.production_db['상태'].str.contains("불량", na=False)]
    
    if rep_g != "전체보기":
        df_bad = df_bad[df_bad['반'] == rep_g]
        
    if df_bad.empty:
        st.success("조회된 품질 이슈가 없습니다.")
    else:
        st.dataframe(df_bad[['시간', '반', '라인', '모델', '시리얼', '증상', '수리']], use_container_width=True, hide_index=True)

# --- 6-5. 마스터 관리 ---
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    st.info("관리자 권한으로 시스템 기준 정보를 수정할 수 있습니다.")
    
    with st.expander("데이터 초기화 (주의)"):
        if st.button("⚠️ 전체 실적 데이터 영구 삭제"):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '반', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v18.0 소스코드 종료 ]
# =================================================================
