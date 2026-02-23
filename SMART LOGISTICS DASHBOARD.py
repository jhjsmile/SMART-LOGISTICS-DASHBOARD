import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io

# 구글 드라이브 연동 라이브러리
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v15.4", layout="wide")

# 권한 체계 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"]
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
# 2. 구글 서비스 연결 함수 (시트 & 드라이브)
# =================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except:
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def save_to_gsheet(df):
    conn.update(data=df)
    st.cache_data.clear()

def upload_image_to_drive(file_obj, filename):
    try:
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        if not folder_id: return "폴더ID설정안됨"
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return file.get('webViewLink')
    except Exception as e:
        return f"업로드실패({str(e)})"

# =================================================================
# 3. 비즈니스 로직 (중복 체크 & 구분선)
# =================================================================
def is_serial_duplicate(serial_no, df):
    if df.empty: return False
    # 전체 데이터에서 해당 시리얼 검색 (구분선은 제외)
    match = df[(df['시리얼'] == serial_no) & (df['상태'] != "구분선")]
    if not match.empty:
        # 마지막 상태가 '완료' 혹은 '진행 중'이면 중복으로 간주
        last_status = match.iloc[-1]['상태']
        if last_status in ["완료", "진행 중"]: return True
    return False

def check_and_add_marker(df, line_name):
    today = datetime.now().strftime('%Y-%m-%d')
    # 오늘 생산량 집계
    count = len(df[(df['라인'] == line_name) & (df['시간'].astype(str).str.contains(today)) & (df['상태'] != "구분선")])
    if count > 0 and count % 10 == 0:
        marker_row = {
            '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line_name, 
            'CELL': '-', '모델': '----------------', '품목코드': '----------------', 
            '시리얼': f"✅ {count}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'
        }
        return pd.concat([df, pd.DataFrame([marker_row])], ignore_index=True)
    return df

# =================================================================
# 4. 세션 상태 및 초기 설정
# =================================================================
if 'production_db' not in st.session_state: st.session_state.production_db = load_data()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'master_models' not in st.session_state: st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {"EPS7150": ["7150-A"], "EPS7133": ["7133-S"], "T20i": ["T20i-P"], "T20C": ["T20C-S"]}
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"
if 'repair_cache' not in st.session_state: st.session_state.repair_cache = {}

# =================================================================
# 5. 로그인 로직
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 계정: master(전체), admin(관제), line1~3(현장)")
        with st.form("login_form"):
            uid = st.text_input("아이디(ID)")
            upw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if uid in st.session_state.user_db and st.session_state.user_db[uid]["pw"] == upw:
                    st.cache_data.clear()
                    st.session_state.production_db = load_data()
                    st.session_state.login_status, st.session_state.user_id = True, uid
                    st.session_state.user_role = st.session_state.user_db[uid]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else: st.error("계정 정보를 확인하세요.")
    st.stop()

# 사이드바 네비게이션
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()

allowed = ROLES.get(st.session_state.user_role, [])
def nav(name): st.session_state.current_line = name; st.rerun()

for m in ["조립 라인", "검사 라인", "포장 라인", "리포트"]:
    if m in allowed:
        if st.sidebar.button(m, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"): nav(m)

st.sidebar.divider()
for m in ["불량 공정", "수리 리포트"]:
    if m in allowed:
        if st.sidebar.button(m, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"): nav(m)

if "마스터 관리" in allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): nav("마스터 관리")

# =================================================================
# 6. 공용 UI 컴포넌트 함수
# =================================================================
def display_flow_stats(line_name):
    db = st.session_state.production_db
    today = datetime.now().strftime('%Y-%m-%d')
    today_data = db[(db['라인'] == line_name) & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    today_in = len(today_data)
    today_out = len(today_data[today_data['상태'] == '완료'])
    
    wait_count = 0
    prev_line = "조립 라인" if line_name == "검사 라인" else "검사 라인" if line_name == "포장 라인" else None
    
    if prev_line:
        prev_done = set(db[(db['라인'] == prev_line) & (db['상태'] == '완료')]['시리얼'])
        curr_in = set(db[db['라인'] == line_name]['시리얼'])
        wait_count = len(prev_done - curr_in)
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev_line if prev_line else '신규'} 대기</div><div class='stat-value' style='color:orange;'>{wait_count if prev_line else '-'}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{today_in}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{today_out}</div></div>", unsafe_allow_html=True)

def display_log_table(line_name, ok_label="완료"):
    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    if line_name == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    if l_db.empty: st.info("표시할 데이터가 없습니다."); return
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee;text-align:center;border-radius:5px;font-weight:bold;margin:5px 0;'>{row['시리얼']} ---------------------------------</div>", unsafe_allow_html=True)
            continue
            
        col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        col[0].write(row['시간']); col[1].write(row['CELL']); col[2].write(row['모델']); col[3].write(row['품목코드']); col[4].write(row['시리얼'])
        with col[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button(ok_label, key=f"ok_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{row['상태']}**")

# =================================================================
# 7. 메인 페이지 로직
# =================================================================

# --- 7-1. 조립 라인 ---
if st.session_state.current_line == "조립 라인":
    st.header("📦 조립 라인 관리")
    display_flow_stats("조립 라인")
    
    # CELL 선택 버튼
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c; st.rerun()

    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요"] + st.session_state.master_models)
            with st.form("asm_input"):
                c1, c2 = st.columns(2)
                i_choice = c1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, ["모델선택"]) if m_choice != "선택하세요" else ["모델선택"])
                s_input = c2.text_input("시리얼 번호 입력")
                if st.form_submit_button("🚀 조립 투입 등록", use_container_width=True):
                    if m_choice != "선택하세요" and s_input:
                        if is_serial_duplicate(s_input, st.session_state.production_db):
                            st.error(f"❌ 중복 생산 불가: {s_input}은 이미 등록된 시리얼입니다.")
                        else:
                            new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                            df = pd.concat([st.session_state.production_db, pd.DataFrame([new_row])], ignore_index=True)
                            df = check_and_add_marker(df, "조립 라인")
                            st.session_state.production_db = df
                            save_to_gsheet(df); st.success(f"{s_input} 등록 완료!"); st.rerun()
    display_log_table("조립 라인")

# --- 7-2. 검사 / 포장 라인 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line = st.session_state.current_line
    prev = "조립 라인" if line == "검사 라인" else "검사 라인"
    st.header(f"🔍 {line} 관리")
    display_flow_stats(line)
    
    with st.container(border=True):
        db = st.session_state.production_db
        # 이전 단계 완료 물량 중 현재 단계 투입 안 된 것 필터링
        ready_df = db[(db['라인'] == prev) & (db['상태'] == "완료")]
        already_in = set(db[db['라인'] == line]['시리얼'])
        avail_list = [s for s in ready_df['시리얼'].unique() if s not in already_in]
        
        if avail_list:
            st.success(f"📦 입고 대기 물량: {len(avail_list)}건")
            sel_s = st.selectbox("입고할 제품 선택", avail_list)
            if st.button(f"📥 {line} 입고 승인", use_container_width=True):
                orig = ready_df[ready_df['시리얼'] == sel_s].iloc[-1]
                new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line, 'CELL': '-', '모델': orig['모델'], '품목코드': orig['품목코드'], '시리얼': sel_s, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                df = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                df = check_and_add_marker(df, line)
                st.session_state.production_db = df
                save_to_gsheet(df); st.rerun()
        else: st.info("입고 대기 중인 물량이 없습니다.")
    display_log_table(line, "검사통과" if line=="검사 라인" else "출고완료")

# --- 7-3. 불량 수리 센터 ---
elif st.session_state.current_line == "불량 공정":
    st.header("🛠️ 불량 수리 센터")
    bad_df = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_df.empty: st.success("✅ 현재 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_df.iterrows():
            with st.container(border=True):
                st.subheader(f"S/N: {row['시리얼']} ({row['모델']})")
                c1, c2 = st.columns(2)
                cause = c1.text_input("불량 원인", key=f"c_{idx}")
                action = c2.text_input("수리 조치", key=f"a_{idx}")
                img_file = st.file_uploader("수리 증빙 사진 업로드", type=['jpg','png','jpeg'], key=f"i_{idx}")
                
                if st.button("✅ 수리 및 재투입 완료", key=f"btn_{idx}", type="primary"):
                    if cause and action:
                        with st.spinner("데이터 저장 중..."):
                            link = ""
                            if img_file:
                                link = upload_image_to_drive(img_file, f"REPAIR_{row['시리얼']}_{datetime.now().strftime('%H%M%S')}.jpg")
                            
                            st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                            st.session_state.production_db.at[idx, '증상'] = cause
                            st.session_state.production_db.at[idx, '수리'] = f"{action} (사진: {link})" if link else action
                            st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                            save_to_gsheet(st.session_state.production_db)
                            st.success("수리 정보가 저장되었습니다."); st.rerun()
                    else: st.error("원인과 조치 내용을 입력해주세요.")

# --- 7-4. 통합 리포트 ---
elif st.session_state.current_line == "리포트":
    st.header("📊 통합 생산 리포트")
    if st.button("🔄 최신 데이터 불러오기"): st.cache_data.clear(); st.session_state.production_db = load_data(); st.rerun()
    
    df = st.session_state.production_db[st.session_state.production_db['상태'] != "구분선"]
    if not df.empty:
        t_done = len(df[(df['라인'] == '포장 라인') & (df['상태'] == '완료')])
        t_bad = len(df[df['상태'].str.contains("불량", na=False)])
        
        m1, m2, m3 = st.columns(3)
        m1.metric("최종 생산량", f"{t_done} EA")
        m2.metric("누적 불량", f"{t_bad} 건")
        m3.metric("현재 공정 수", len(df[df['상태'] == '진행 중']))
        
        st.divider()
        st.plotly_chart(px.bar(df[df['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 실적"), use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- 7-5. 수리 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.header("📈 수리 이력 리포트")
    rep_df = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    if not rep_df.empty:
        st.dataframe(rep_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else: st.info("수리 이력이 없습니다.")

# --- 7-6. 마스터 관리 (계정 관리 포함) ---
elif st.session_state.current_line == "마스터 관리":
    st.header("🔐 시스템 마스터 관리")
    if not st.session_state.admin_authenticated:
        pw_in = st.text_input("관리자 비밀번호를 입력하세요", type="password")
        if st.button("인증"):
            if pw_in in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
            else: st.error("비밀번호 불일치")
    else:
        if st.button("🔓 관리자 세션 종료"): st.session_state.admin_authenticated = False; st.rerun()
        
        st.divider()
        st.subheader("👤 사용자 계정 관리")
        u1, u2, u3 = st.columns([3,3,2])
        new_id = u1.text_input("새 아이디")
        new_pw = u2.text_input("새 비밀번호", type="password")
        new_ro = u3.selectbox("권한", list(ROLES.keys()))
        if st.button("➕ 계정 추가/업데이트"):
            if new_id and new_pw:
                st.session_state.user_db[new_id] = {"pw": new_pw, "role": new_ro}
                st.success(f"{new_id} 계정 설정 완료")
        
        with st.expander("현재 등록 계정 보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
            
        st.divider()
        st.subheader("📋 기준 정보 관리")
        m_col, i_col = st.columns(2)
        with m_col:
            new_m = st.text_input("새 모델 추가")
            if st.button("모델 등록"):
                if new_m and new_m not in st.session_state.master_models:
                    st.session_state.master_models.append(new_m); st.session_state.master_items_dict[new_m] = []; st.rerun()
        with i_col:
            sel_m = st.selectbox("품목 추가할 모델", st.session_state.master_models)
            new_i = st.text_input("새 품목코드")
            if st.button("품목 등록"):
                if new_i and new_i not in st.session_state.master_items_dict[sel_m]:
                    st.session_state.master_items_dict[sel_m].append(new_i); st.rerun()

        st.divider()
        if st.button("⚠️ 시스템 전체 DB 초기화 (구글 시트 삭제)", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            save_to_gsheet(st.session_state.production_db); st.warning("초기화 완료"); st.rerun()

