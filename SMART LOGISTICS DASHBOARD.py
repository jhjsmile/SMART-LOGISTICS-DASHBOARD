import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io

# [구글 서비스 연동을 위한 라이브러리]
# 서비스 계정 인증 및 드라이브 API 사용을 위한 설정
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# [1. 시스템 전역 설정] - v9.1 스타일 기반
# =================================================================
# 앱의 타이틀과 레이아웃(와이드 모드)을 설정합니다.
st.set_page_config(
    page_title="생산 통합 관리 시스템 v16.8",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST) 설정: 서버 위치에 상관없이 한국 시간으로 기록하기 위함
KST = timezone(timedelta(hours=9))

# 사용자 그룹별 권한(Role) 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [CSS 스타일 커스텀] - v9.1 디자인 완벽 복구
st.markdown("""
    <style>
    /* 메인 컨테이너 너비 제한 (v9.1 기준 1200px) */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    
    /* 버튼 스타일: 패딩 및 정렬 복구 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
        border-radius: 5px;
    }
    
    /* 제목 중앙 정렬 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 20px 0; 
    }
    
    /* v9.1 전용 섹션 타이틀: 회색 배경에 파란색 왼쪽 굵은 테두리 */
    .section-title { 
        background-color: #f8f9fa; 
        color: #000; 
        padding: 15px; 
        border-radius: 8px; 
        font-weight: bold; 
        margin-bottom: 20px; 
        border-left: 8px solid #007bff;
    }
    
    /* 상태 표시 색상 정의 */
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
    
    /* 대시보드 상단 통계 박스 (v9.1 스타일 기반 보완) */
    .stat-box {
        background-color: #f0f2f6; 
        border-radius: 10px; 
        padding: 15px; 
        text-align: center;
        border: 1px solid #e0e0e0; 
        margin-bottom: 10px;
    }
    .stat-label { font-size: 0.9em; color: #555; font-weight: bold; }
    .stat-value { font-size: 1.8em; color: #007bff; font-weight: bold; }
    .stat-sub { font-size: 0.8em; color: #888; }
    
    /* 알림 배너 */
    .alarm-banner { 
        background-color: #fff5f5; 
        color: #c92a2a; 
        padding: 15px; 
        border-radius: 8px; 
        border: 1px solid #ffa8a8; 
        font-weight: bold; 
        margin-bottom: 20px;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# [2. 핵심 유틸리티 함수]
# =================================================================

def get_now_kst():
    """현재 한국 표준시를 'YYYY-MM-DD HH:MM:SS' 형식으로 반환"""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

# 구글 시트 커넥션 객체 생성
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """구글 시트 실시간 데이터 로드 및 전처리"""
    try:
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception:
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """시트 업데이트 및 캐시 초기화"""
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    """구글 드라이브 이미지 업로드"""
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        if not folder_id: return "❌ 폴더 설정 누락"
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return file.get('webViewLink') 
    except Exception as e:
        return f"⚠️ 실패: {str(e)}"

# =================================================================
# [3. 세션 상태 관리]
# =================================================================
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {"admin": {"pw": "admin1234", "role": "admin"}}

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]
    }
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# [4. 로그인 및 사이드바 내비게이션] - v9.1 스타일
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 시스템 로그인</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("계정 정보를 확인하세요.")
    st.stop()

# 사이드바 구성
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def nav(name): 
    st.session_state.current_line = name
    st.rerun()

allowed = ROLES.get(st.session_state.user_role, [])

# v9.1 스타일의 내비게이션 버튼 배치
if "조립 라인" in allowed:
    if st.sidebar.button("📦 조립 라인 현황", use_container_width=True, type="primary" if st.session_state.current_line=="조립 라인" else "secondary"): nav("조립 라인")
if "검사 라인" in allowed:
    if st.sidebar.button("🔍 품질 검사 현황", use_container_width=True, type="primary" if st.session_state.current_line=="검사 라인" else "secondary"): nav("검사 라인")
if "포장 라인" in allowed:
    if st.sidebar.button("🚚 출하 포장 현황", use_container_width=True, type="primary" if st.session_state.current_line=="포장 라인" else "secondary"): nav("포장 라인")
if "리포트" in allowed:
    if st.sidebar.button("📊 통합 생산 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="리포트" else "secondary"): nav("리포트")

st.sidebar.divider()
if "불량 공정" in allowed:
    if st.sidebar.button("🛠️ 불량 수리 센터", use_container_width=True, type="primary" if st.session_state.current_line=="불량 공정" else "secondary"): nav("불량 공정")
if "수리 리포트" in allowed:
    if st.sidebar.button("📈 불량 수리 리포트", use_container_width=True, type="primary" if st.session_state.current_line=="수리 리포트" else "secondary"): nav("수리 리포트")

if st.session_state.user_role == "admin" or "마스터 관리" in allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리 (Admin)", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav("마스터 관리")

# 불량 알림 배너
bad_cnt = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_cnt > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_cnt}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# [5. 공용 로직 (v9.1 디자인 + v16.7 기능)]
# =================================================================

@st.dialog("📦 공정 입고 승인 확인")
def confirm_entry_dialog():
    """v16.7의 1제품 1행 업데이트 로직 적용"""
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        db = st.session_state.production_db
        idx_list = db[db['시리얼'] == st.session_state.confirm_target].index
        if not idx_list.empty:
            target_idx = idx_list[0]
            db.at[target_idx, '시간'] = get_now_kst()
            db.at[target_idx, '라인'] = st.session_state.current_line
            db.at[target_idx, '상태'] = '진행 중'
            db.at[target_idx, '작업자'] = st.session_state.user_id
            save_to_gsheet(db)
        st.session_state.confirm_target = None
        st.rerun()
    if c2.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def display_process_log(line_name, ok_label="완료"):
    """v9.1 스타일의 로그 레이아웃 (컬럼 비중 [2.5, 1, 1.5, 1.5, 2, 3])"""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그 현황</h3>", unsafe_allow_html=True)
    db = st.session_state.production_db
    l_db = db[db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty: st.info("데이터가 없습니다."); return
    
    # v9.1 컬럼 비중 유지
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for col, txt in zip(lh, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): 
        col.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간'])
        lr[1].write(row['CELL'])
        lr[2].write(row['모델'])
        lr[3].write(row['품목코드'])
        lr[4].write(f"`{row['시리얼']}`")
        
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{idx}", type="secondary"):
                    db.at[idx, '상태'] = "완료"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    db.at[idx, '상태'] = "불량 처리 중"
                    db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(db); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# [6. 세부 페이지 로직]
# =================================================================

# --- 6-1. 조립 라인 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    
    # v9.1 스타일 CELL 선택 인터페이스
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"m_{st.session_state.selected_cell}")
            with st.form("asm_form"):
                r1, r2 = st.columns(2)
                i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, []) if m_choice!="선택하세요." else ["모델 선택 필요"])
                s_input = r2.text_input("시리얼 번호")
                if st.form_submit_button("▶️ 조립 등록", use_container_width=True, type="primary"):
                    if m_choice != "선택하세요." and s_input:
                        db = st.session_state.production_db
                        if s_input in db['시리얼'].values:
                            st.error("❌ 이미 등록된 시리얼입니다.")
                        else:
                            new_row = {
                                '시간': get_now_kst(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            save_to_gsheet(st.session_state.production_db); st.rerun()
    display_process_log("조립 라인", "완료")

# --- 6-2. 품질 / 포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        db = st.session_state.production_db
        # 이전 공정 완료 항목 필터링
        ready = db[(db['라인'] == prev_line) & (db['상태'] == "완료")]
        if not ready.empty:
            st.success(f"📦 대기 물량: {len(ready)}건")
            grid = st.columns(4)
            for i, (idx, row) in enumerate(ready.iterrows()):
                if grid[i % 4].button(f"입고: {row['시리얼']}", key=f"btn_{row['시리얼']}"):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    confirm_entry_dialog()
        else: st.info("대기 물량이 없습니다.")
    display_process_log(st.session_state.current_line, "합격" if st.session_state.current_line=="검사 라인" else "출고")

# --- 6-3. 통합 리포트 (다크 테마 + 정수 표기) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    if not db.empty:
        met = st.columns(4)
        met[0].metric("최종 완료", len(db[db['상태'] == '완료']))
        met[1].metric("진행 중", len(db[db['상태'] == '진행 중']))
        met[2].metric("총 수량", len(db))
        
        st.divider()
        # [복구] 다크 테마 및 Y축 정수 표기 그래프
        c1, c2 = st.columns([1, 2])
        with c1:
            loc_data = db.groupby('라인').size().reset_index(name='수량')
            fig1 = px.bar(
                loc_data, x='라인', y='수량', color='라인', title="공정별 제품 위치",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_dark"
            )
            fig1.update_yaxes(dtick=1, rangemode='tozero')
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            st.plotly_chart(px.pie(db.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.3, title="모델별 비중", template="plotly_dark"), use_container_width=True)
        
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    bad = db[db['상태'] == "불량 처리 중"]
    
    if bad.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** ({row['모델']} / 발생: {row['라인']})")
                c1, c2, c3 = st.columns([4, 4, 2])
                sv, av = c1.text_input("불량 원인", key=f"s_{idx}"), c2.text_input("수리 조치", key=f"a_{idx}")
                up_f = st.file_uploader("사진 등록", type=['jpg','png','jpeg'], key=f"img_{idx}")
                if c3.button("✅ 수리 완료", key=f"r_{idx}", use_container_width=True):
                    if sv and av:
                        img_link = ""
                        if up_f:
                            with st.spinner("이미지 저장 중..."):
                                res = upload_image_to_drive(up_f, f"REPAIR_{row['시리얼']}.jpg")
                                if "http" in res: img_link = f" [사진: {res}]"
                        db.at[idx, '상태'] = "수리 완료(재투입)"
                        db.at[idx, '증상'], db.at[idx, '수리'] = sv, av + img_link
                        save_to_gsheet(db); st.rerun()

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 불량 수리 리포트</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    rep_db = db[db['수리'] != ""]
    if not rep_db.empty:
        fig_r = px.bar(rep_db.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="라인별 수리 건수", template="plotly_dark")
        fig_r.update_yaxes(dtick=1)
        st.plotly_chart(fig_r, use_container_width=True)
        st.dataframe(rep_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# --- 6-6. 마스터 관리 (v9.1 디자인 + v16.7 기능) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 마스터 데이터 및 계정 관리</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth"):
            apw = st.text_input("관리자 PW (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if apw == "admin1234": st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("인증 실패")
    else:
        if st.button("🔓 관리 세션 종료", use_container_width=True):
            st.session_state.admin_authenticated = False; nav("조립 라인")

        # v9.1 스타일 섹션 타이틀 및 2열 레이아웃
        st.markdown("<div class='section-title'>📋 기준정보 및 데이터 관리</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        
        with m1:
            with st.container(border=True):
                st.subheader("모델 및 품목 등록")
                nm = st.text_input("신규 모델 추가")
                if st.button("모델 등록", use_container_width=True):
                    if nm and nm not in st.session_state.master_models:
                        st.session_state.master_models.append(nm); st.session_state.master_items_dict[nm] = []; st.rerun()
                st.divider()
                sm = st.selectbox("품목 등록용 모델 선택", st.session_state.master_models)
                ni = st.text_input("신규 품목코드 추가")
                if st.button("품목 등록", use_container_width=True):
                    if ni and ni not in st.session_state.master_items_dict[sm]:
                        st.session_state.master_items_dict[sm].append(ni); st.rerun()

        with m2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 로드")
                csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 생산 데이터 다운로드 (CSV)", csv_data, f"backup_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                up_f = st.file_uploader("백업 파일 로드 (CSV)", type="csv")
                if up_f and st.button("📤 데이터 업로드 (병합)", use_container_width=True):
                    merged = pd.concat([st.session_state.production_db, pd.read_csv(up_f)], ignore_index=True)
                    st.session_state.production_db = merged.drop_duplicates(subset=['시리얼'], keep='last')
                    save_to_gsheet(st.session_state.production_db); st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👤 사용자 계정 관리 (ID/PW 부여)</div>", unsafe_allow_html=True)
        u_col1, u_col2, u_col3 = st.columns([3, 3, 2])
        new_uid = u_col1.text_input("ID")
        new_upw = u_col2.text_input("PW", type="password")
        new_role_choice = u_col3.selectbox("권한", ["user", "admin"])
        
        if st.button("계정 생성/수정", use_container_width=True):
            if new_uid and new_upw:
                st.session_state.user_db[new_uid] = {"pw": new_upw, "role": new_role_choice}
                st.success(f"[{new_uid}] 계정 업데이트 완료"); st.rerun()
        
        with st.expander("현재 계정 리스트 확인"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        if st.button("⚠️ 시스템 초기화", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            save_to_gsheet(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v16.8 배포 버전 종료 ]
# =================================================================
