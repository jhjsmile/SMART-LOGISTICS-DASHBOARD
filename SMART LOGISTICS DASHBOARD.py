import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
import time

# 구글 드라이브 연동 라이브러리
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v17.8", layout="wide")

# [핵심] 역할(Role) 정의
# line4 계정을 위해 'repair_team' 권한을 새롭게 정의했습니다.
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["생산 리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "repair_team": ["불량 공정"]  # line4 전용 수리 권한
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; }
    .alarm-banner { 
        background-color: #fff5f5; color: #c92a2a; padding: 15px; 
        border-radius: 8px; border: 1px solid #ffa8a8; font-weight: bold; margin-bottom: 20px;
        text-align: center;
    }
    .stat-box {
        background-color: #f0f2f6; border-radius: 10px; padding: 15px; text-align: center;
        border: 1px solid #e0e0e0; margin-bottom: 10px;
    }
    .stat-label { font-size: 0.9em; color: #555; font-weight: bold; }
    .stat-value { font-size: 1.8em; color: #007bff; font-weight: bold; }
    .stat-sub { font-size: 0.8em; color: #888; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 시트 및 드라이브 연결 (안정성 강화 및 데이터 보호)
# =================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def get_kst_now():
    """서버 시간이 아닌 한국 표준시(KST)를 반환합니다."""
    return datetime.now() + timedelta(hours=9)

def load_data():
    """구글 시트에서 데이터를 안전하게 읽어옵니다."""
    try:
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        
        # 데이터 보호 로직: 시트가 비어있는데 세션 데이터가 있다면 세션 유지
        if df.empty and 'production_db' in st.session_state:
            if not st.session_state.production_db.empty:
                return st.session_state.production_db
        return df
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    """빈 데이터 덮어쓰기를 방지하고 API 에러 시 3회 재시도합니다."""
    if df.empty:
        st.error("❌ 시스템 보호: 빈 데이터를 시트에 저장할 수 없습니다.")
        return False
    
    for i in range(3):
        try:
            conn.update(data=df)
            st.cache_data.clear()
            return True
        except Exception as e:
            if i < 2:
                time.sleep(1.5)
                continue
            else:
                st.error(f"⚠️ 구글 서버 통신 장애: {e}")
                return False

def upload_image_to_drive(file_obj, filename):
    """수리 사진을 구글 드라이브에 업로드합니다."""
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        
        if not folder_id:
            return "폴더ID설정안됨"

        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        return f"업로드실패({str(e)})"

# =================================================================
# 3. 세션 상태 초기화 & 계정 설정 (line4 수리전담 계정 포함)
# =================================================================
if 'production_db' not in st.session_state:
    st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"},
        "line4": {"pw": "4444", "role": "repair_team"}
    }

if 'login_status' not in st.session_state:
    st.session_state.login_status = False

if 'user_role' not in st.session_state:
    st.session_state.user_role = None

if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False

if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], 
        "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], 
        "T20C": ["T20C-S"]
    }

if 'current_line' not in st.session_state:
    st.session_state.current_line = "조립 라인"

if 'selected_cell' not in st.session_state:
    st.session_state.selected_cell = "CELL 1"

if 'repair_cache' not in st.session_state:
    st.session_state.repair_cache = {}

# =================================================================
# 4. 로그인 화면 및 사이드바 메뉴
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 계정 안내: master(전체), admin(관제), line1~4(현장)")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.cache_data.clear()
                    st.session_state.production_db = load_data()
                    st.session_state.login_status = True
                    st.session_state.user_id = uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else:
                    st.error("계정 정보가 일치하지 않습니다.")
    st.stop()

# 사이드바 설정
st.sidebar.title(f"🏭 {st.session_state.user_id}님 환영합니다.")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.rerun()
st.sidebar.divider()

def nav(name):
    st.session_state.current_line = name
    st.rerun()

allowed = ROLES.get(st.session_state.user_role, [])

# 메뉴 그룹 1: 생산 공정 및 리포트
menu_group_1 = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트"]
icons_1 = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊"}
g1_ok = False
for m in menu_group_1:
    if m in allowed:
        g1_ok = True
        label = f"{icons_1[m]} {m}" + (" 현황" if "라인" in m else "")
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

# 메뉴 그룹 2: 불량 및 수리
menu_group_2 = ["불량 공정", "수리 리포트"]
icons_2 = {"불량 공정":"🛠️", "수리 리포트":"📈"}
g2_ok = False
for m in menu_group_2:
    if m in allowed:
        g2_ok = True

if g1_ok and g2_ok:
    st.sidebar.divider()

for m in menu_group_2:
    if m in allowed:
        label = f"{icons_2[m]} {m}"
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            nav(m)

if "마스터 관리" in allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True):
        nav("마스터 관리")

# =================================================================
# 5. 공용 컴포넌트 (수량 오류 수정 및 구분선 상세 로직)
# =================================================================
def check_and_add_marker(df, line_name):
    """10대 단위로 구분선을 추가합니다."""
    today = get_kst_now().strftime('%Y-%m-%d')
    today_count = len(df[
        (df['라인'] == line_name) & 
        (df['시간'].astype(str).str.contains(today)) & 
        (df['상태'] != "구분선")
    ])
    
    if today_count > 0 and today_count % 10 == 0:
        marker_row = {
            '시간': '-------------------', 
            '라인': '----------------', 
            'CELL': '-------', 
            '모델': '----------------', 
            '품목코드': '----------------', 
            '시리얼': f"✅ {today_count}대 달성", 
            '상태': '구분선', 
            '증상': '----------------', 
            '수리': '----------------', 
            '작업자': '----------------'
        }
        return pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
    return df

@st.dialog("📦 공정 입고 승인")
def confirm_entry_dialog():
    st.warning(f"시리얼 [ {st.session_state.confirm_target} ] 입고하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("✅ 승인", type="primary", use_container_width=True):
        new_row = {
            '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
            '라인': st.session_state.current_line, 
            'CELL': "-", 
            '모델': st.session_state.confirm_model, 
            '품목코드': st.session_state.confirm_item, 
            '시리얼': st.session_state.confirm_target, 
            '상태': '진행 중', 
            '증상': '', 
            '수리': '', 
            '작업자': st.session_state.user_id
        }
        updated_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
        updated_db = check_and_add_marker(updated_db, st.session_state.current_line)
        st.session_state.production_db = updated_db
        if save_to_gsheet(st.session_state.production_db):
            st.session_state.confirm_target = None
            st.rerun()
    if c2.button("❌ 취소", use_container_width=True):
        st.session_state.confirm_target = None
        st.rerun()

def display_line_flow_stats(current_line):
    """상단 통계 바를 렌더링합니다. 수량 계산 오류를 수정한 고유 키 로직을 사용합니다."""
    db = st.session_state.production_db
    today_str = get_kst_now().strftime('%Y-%m-%d')
    today_data = db[
        (db['라인'] == current_line) & 
        (db['시간'].astype(str).str.contains(today_str)) & 
        (db['상태'] != '구분선')
    ].copy()
    
    t_input = len(today_data)
    t_output = len(today_data[today_data['상태'] == '완료'])
    
    buffer_count = 0
    prev_line = None
    if current_line == "검사 라인": prev_line = "조립 라인"
    elif current_line == "포장 라인": prev_line = "검사 라인"
    
    if prev_line:
        # [수정] 모델+시리얼 조합으로 개별 제품 식별 (5->14 오류 해결)
        prev_df = db[(db['라인'] == prev_line) & (db['상태'] == '완료')]
        prev_keys = prev_df['모델'] + "_" + prev_df['시리얼']
        
        curr_df = db[db['라인'] == current_line]
        curr_keys = curr_df['모델'] + "_" + curr_df['시리얼']
        
        waiting_keys = [k for k in prev_keys if k not in curr_keys.values]
        buffer_count = len(waiting_keys)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev_line if prev_line else '신규'} 대기</div><div class='stat-value' style='color: #ff9800;'>{buffer_count if prev_line else '-'}</div><div class='stat-sub'>건 (누적)</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{t_input}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color: #28a745;'>{t_output}</div><div class='stat-sub'>건 (Today)</div></div>", unsafe_allow_html=True)

def display_process_log(line_name, ok_label="완료"):
    """현장 실시간 로그 테이블을 렌더링합니다."""
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_name} 실시간 로그</h3>", unsafe_allow_html=True)
    
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty:
        st.info("현재 표시할 작업 데이터가 없습니다.")
        return
    
    # 헤더 정의
    lh = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    header_texts = ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]
    for i, txt in enumerate(header_texts):
        lh[i].write(f"**{txt}**")
    
    # 데이터 행 렌더링 (최신순)
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color: #e9ecef; padding: 5px; text-align: center; border-radius: 5px; font-weight: bold; color: #495057;'>📦 {row['시리얼']} -----------------------------------------------------</div>", unsafe_allow_html=True)
            continue

        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간'])
        lr[1].write(row['CELL'])
        lr[2].write(row['모델'])
        lr[3].write(row['품목코드'])
        lr[4].write(row['시리얼'])
        
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(st.session_state.production_db):
                        st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    if save_to_gsheet(st.session_state.production_db):
                        st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span style='color: #c92a2a; font-weight: bold;'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color: #2b8a3e; font-weight: bold;'>🟢 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 상세 로직
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인") 
    st.divider()

    # CELL 선택 버튼
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c
            st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("asm_form"):
                r1, r2 = st.columns(2)
                items = st.session_state.master_items_dict.get(m_choice, ["모델 선택 필요"]) if m_choice != "선택하세요." else ["모델 선택 필요"]
                i_choice = r1.selectbox("품목코드 선택", items)
                s_input = r2.text_input("시리얼 번호 입력")
                
                if st.form_submit_button("▶️ 신규 조립 등록", use_container_width=True, type="primary"):
                    if m_choice != "선택하세요." and s_input:
                        # [전수 중복 체크] 과거 모든 데이터 대상
                        db_all = st.session_state.production_db
                        is_dup = not db_all[
                            (db_all['모델'] == m_choice) & 
                            (db_all['품목코드'] == i_choice) & 
                            (db_all['시리얼'] == s_input) & 
                            (db_all['상태'] != "구분선")
                        ].empty
                        
                        if is_dup:
                            st.error(f"❌ 중복 등록 불가: [ {s_input} ] 번호는 이미 생산 이력이 존재합니다.")
                        else:
                            new_row = {
                                '시간': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': m_choice, 
                                '품목코드': i_choice, 
                                '시리얼': s_input, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            new_db = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
                            new_db = check_and_add_marker(new_db, "조립 라인")
                            st.session_state.production_db = new_db
                            if save_to_gsheet(st.session_state.production_db):
                                st.rerun()
                    else:
                        st.warning("모델과 시리얼 번호를 모두 입력해주세요.")
    
    display_process_log("조립 라인", "완료")

# --- 6-2. 검사 및 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_title = "🔍 품질 검사 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    prev_line = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    
    st.markdown(f"<h2 class='centered-title'>{line_title}</h2>", unsafe_allow_html=True)
    display_line_flow_stats(st.session_state.current_line) 
    st.divider()

    with st.container(border=True):
        f1, f2 = st.columns(2)
        sm = f1.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"sm_{st.session_state.current_line}")
        si = f2.selectbox("품목코드 선택", ["품목 선택"] + st.session_state.master_items_dict.get(sm, []) if sm != "선택하세요." else ["품목 선택"], key=f"si_{st.session_state.current_line}")
        
        if sm != "선택하세요." and si != "품목 선택":
            db = st.session_state.production_db
            # 이전 공정 완료 물량 중 현재 공정에 아직 안 들어온 것 찾기
            ready = db[(db['라인'] == prev_line) & (db['상태'] == "완료") & (db['모델'] == sm) & (db['품목코드'] == si)]
            already_in = db[db['라인'] == st.session_state.current_line]['시리얼'].unique()
            avail = [s for s in ready['시리얼'].unique() if s not in already_in]
            
            if avail:
                st.success(f"📦 입고 가능한 대기 물량이 {len(avail)}건 있습니다.")
                grid = st.columns(4)
                for i, sn in enumerate(avail):
                    if grid[i % 4].button(f"📥 입고: {sn}", key=f"btn_{sn}"):
                        st.session_state.confirm_target = sn
                        st.session_state.confirm_model = sm
                        st.session_state.confirm_item = si
                        confirm_entry_dialog()
            else:
                st.info("이전 공정에서 넘어온 입고 대기 물량이 없습니다.")
                
    display_process_log(st.session_state.current_line, "합격" if st.session_state.current_line=="검사 라인" else "출하")

# --- 6-3. 생산 리포트 (통합 대시보드) ---
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 리포트 통합 대시보드</h2>", unsafe_allow_html=True)
    if st.button("🔄 최신 데이터 불러오기 (새로고침)"):
        st.session_state.production_db = load_data()
        st.rerun()
        
    db = st.session_state.production_db
    if not db.empty:
        # 구분선 제외 순수 데이터
        real_db = db[db['상태'] != '구분선']
        
        # 주요 지표 계산
        final_pack = len(real_db[(real_db['라인'] == '포장 라인') & (real_db['상태'] == '완료')])
        total_bad = len(real_db[real_db['상태'].str.contains("불량", na=False)])
        ftt_rate = (final_pack / (final_pack + total_bad) * 100) if (final_pack + total_bad) > 0 else 100
        
        m_cols = st.columns(4)
        m_cols[0].metric("최종 생산 수량", f"{final_pack} EA")
        m_cols[1].metric("전체 공정 진행", len(real_db[real_db['상태'] == '진행 중']))
        m_cols[2].metric("누적 불량 건수", f"{total_bad} 건", delta=total_bad, delta_color="inverse")
        m_cols[3].metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        c1, c2 = st.columns([3, 2])
        with c1:
            perf_df = real_db[real_db['상태']=='완료'].groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(perf_df, x='라인', y='수량', color='라인', title="공정별 생산 실적"), use_container_width=True)
        with c2:
            model_df = real_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_df, values='수량', names='모델', hole=0.3, title="모델별 비중"), use_container_width=True)
            
        st.divider()
        st.markdown("##### 👷 현장 작업자별 누적 처리 건수")
        worker_df = real_db.groupby('작업자').size().reset_index(name='건수')
        st.plotly_chart(px.bar(worker_df, x='작업자', y='건수', color='작업자'), use_container_width=True)
        
        st.markdown("##### 📋 전체 생산 이력 로그 (최신순)")
        st.dataframe(db.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 6-4. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터 (Repair Center)</h2>", unsafe_allow_html=True)
    display_line_flow_stats("조립 라인") # 조립라인 기준 통계 표시

    bad_items = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_items.empty:
        st.success("✅ 현재 수리가 필요한 불량 제품이 없습니다.")
    else:
        for idx, row in bad_items.iterrows():
            with st.container(border=True):
                st.markdown(f"**제품 정보: {row['시리얼']}** ({row['모델']} / 발생공정: {row['라인']})")
                
                c1, c2, c3 = st.columns([4, 4, 2])
                
                # 캐시된 입력값 로드
                cache_s = st.session_state.repair_cache.get(f"s_{idx}", "")
                cache_a = st.session_state.repair_cache.get(f"a_{idx}", "")
                
                s_val = c1.text_input("불량 증상 및 원인", value=cache_s, key=f"s_{idx}")
                a_val = c2.text_input("수리 및 조치 사항", value=cache_a, key=f"a_{idx}")
                
                # 캐시 업데이트
                st.session_state.repair_cache[f"s_{idx}"] = s_val
                st.session_state.repair_cache[f"a_{idx}"] = a_val
                
                up_file = st.file_uploader("수리 증빙 사진 업로드", type=['jpg','png','jpeg'], key=f"img_{idx}")
                if up_file:
                    st.image(up_file, width=300, caption="업로드 예정 사진")
                
                if c3.button("✅ 수리 완료 및 재투입", key=f"r_{idx}", type="primary", use_container_width=True):
                    if s_val and a_val:
                        img_link = ""
                        if up_file is not None:
                            with st.spinner("사진을 안전하게 저장 중입니다..."):
                                file_name = f"{row['시리얼']}_{get_kst_now().strftime('%Y%m%d_%H%M')}.jpg"
                                res = upload_image_to_drive(up_file, file_name)
                                if "http" in res:
                                    img_link = f" [사진보기: {res}]"
                        
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = s_val
                        st.session_state.production_db.at[idx, '수리'] = a_val + img_link
                        st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                        
                        if save_to_gsheet(st.session_state.production_db):
                            # 성공 시 캐시 삭제
                            st.session_state.repair_cache.pop(f"s_{idx}", None)
                            st.session_state.repair_cache.pop(f"a_{idx}", None)
                            st.success("수리가 정상적으로 완료되었습니다!")
                            st.rerun()
                    else:
                        st.error("증상과 조치 내용을 모두 입력해야 완료할 수 있습니다.")

# --- 6-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 수리 결과 분석 리포트</h2>", unsafe_allow_html=True)
    
    # 수리 완료된 데이터만 필터링
    repair_db = st.session_state.production_db[
        (st.session_state.production_db['상태'].str.contains("재투입", na=False)) | 
        (st.session_state.production_db['수리'] != "")
    ]
    
    if not repair_db.empty:
        c1, c2 = st.columns(2)
        with c1:
            line_bad = repair_db.groupby('라인').size().reset_index(name='수량')
            st.plotly_chart(px.bar(line_bad, x='라인', y='수량', title="공정별 불량 발생 건수"), use_container_width=True)
        with c2:
            model_bad = repair_db.groupby('모델').size().reset_index(name='수량')
            st.plotly_chart(px.pie(model_bad, values='수량', names='모델', hole=0.3, title="불량 발생 모델 비중"), use_container_width=True)
            
        st.dataframe(repair_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("아직 수리 완료 데이터가 없습니다.")

# --- 6-6. 마스터 관리 (Admin 전용) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    
    if not st.session_state.admin_authenticated:
        with st.form("admin_auth"):
            apw = st.text_input("관리자 비밀번호를 입력하세요 (admin1234)", type="password")
            if st.form_submit_button("인증하기"):
                if apw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("비밀번호가 틀렸습니다.")
    else:
        if st.button("🔓 관리자 세션 종료 (잠금)", use_container_width=True):
            st.session_state.admin_authenticated = False
            nav("생산 리포트")

        st.markdown("<div class='section-title'>📋 1. 제품 및 품목 마스터 관리</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1:
            with st.container(border=True):
                st.subheader("모델 등록")
                new_m = st.text_input("추가할 모델명")
                if st.button("모델 추가 등록", use_container_width=True):
                    if new_m and new_m not in st.session_state.master_models:
                        st.session_state.master_models.append(new_m)
                        st.session_state.master_items_dict[new_m] = []
                        st.rerun()

        with m2:
            with st.container(border=True):
                st.subheader("품목코드 등록")
                target_m = st.selectbox("품목을 추가할 모델 선택", st.session_state.master_models)
                new_i = st.text_input("추가할 품목코드")
                if st.button("품목코드 추가 등록", use_container_width=True):
                    if new_i and new_i not in st.session_state.master_items_dict[target_m]:
                        st.session_state.master_items_dict[target_m].append(new_i)
                        st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>💾 2. 데이터 백업 및 복구</div>", unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            st.write("현재까지의 모든 생산 데이터를 다운로드합니다.")
            csv_data = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 전체 데이터 다운로드 (CSV)", 
                csv_data, 
                f"production_backup_{get_kst_now().strftime('%Y%m%d')}.csv", 
                "text/csv", 
                use_container_width=True
            )
        with b2:
            st.write("외부 CSV 데이터를 불러와 현재 시스템에 병합합니다.")
            up_csv = st.file_uploader("백업 CSV 파일 업로드", type="csv")
            if up_csv and st.button("📤 데이터 로드 및 시트 업데이트", use_container_width=True):
                loaded_df = pd.read_csv(up_csv)
                st.session_state.production_db = pd.concat([st.session_state.production_db, loaded_df], ignore_index=True)
                if save_to_gsheet(st.session_state.production_db):
                    st.rerun()

        st.divider()
        st.markdown("<div class='section-title'>👤 3. 사용자 계정 및 권한 관리</div>", unsafe_allow_html=True)
        u1, u2, u3 = st.columns([3, 3, 2])
        n_id = u1.text_input("신규 생성할 ID")
        n_pw = u2.text_input("신규 생성할 PW", type="password")
        n_rl = u3.selectbox("부여할 권한", ["control_tower", "assembly_team", "qc_team", "packing_team", "repair_team", "master"])
        
        if st.button("👤 계정 생성 및 시스템 업데이트", use_container_width=True):
            if n_id and n_pw:
                st.session_state.user_db[n_id] = {"pw": n_pw, "role": n_rl}
                st.success(f"계정 [{n_id}]이(가) 정상적으로 생성되었습니다.")
                st.rerun()
        
        with st.expander("현재 시스템 등록 계정 목록 확인"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))

        st.divider()
        if st.button("⚠️ 시스템 전체 데이터 초기화 (주의)", type="secondary", use_container_width=True):
             st.warning("경고: 시트의 모든 데이터가 삭제됩니다. 백업을 완료하셨나요?")
             if st.button("❌ 예, 전체 삭제를 확정합니다."):
                 st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
                 if save_to_gsheet(st.session_state.production_db):
                     st.rerun()
