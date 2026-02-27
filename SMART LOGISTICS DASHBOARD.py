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
    page_title="생산 통합 관리 시스템 v18.9",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 대한민국 표준시(KST: UTC+9) 전역 타임존 설정
KST = timezone(timedelta(hours=9))

# 30초마다 자동으로 전체 화면을 새로고침합니다.
st_autorefresh(interval=30000, key="pms_auto_refresh")

# 제조 반 리스트 정의
PRODUCTION_GROUPS = ["제조 1반", "제조 2반", "제조 3반"]

# 사용자 그룹별 메뉴 접근 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정"],
    "packing_team": ["포장 라인"],
    "admin": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"]
}

# [v17.8 원본 CSS 스타일 100% 복구]
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
        
        # [데이터 이관] 업로드하신 CSV처럼 '반' 정보가 있는 데이터를 위한 로직
        if '반' not in df.columns:
            if not df.empty:
                df.insert(1, '반', "제조 2반")
            else:
                df.insert(1, '반', "")
        else:
            # 빈 칸인 경우 제조 2반으로 기본 할당
            df['반'] = df['반'].apply(lambda x: "제조 2반" if x == "" else x)
            
        return df
    except Exception as e:
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
        return f"⚠️ 이미지 업로드 실패: {str(err)}"

# =================================================================
# 3. 세션 상태 관리 (반별 독립 마스터 완벽 구조)
# =================================================================

if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_realtime_ledger()

if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "admin": {"pw": "admin1234", "role": "admin"},
        "master": {"pw": "master1234", "role": "master"}
    }

# [핵심] 반별 모델/품목 리스트 (에러 방지를 위해 초기값 고정)
if 'group_master_models' not in st.session_state:
    st.session_state.group_master_models = {
        "제조 1반": ["NEW-100", "NEW-200"],
        "제조 2반": ["EPS7150", "EPS7133", "T20i", "T20C"],
        "제조 3반": ["AION-X", "AION-Standard"]
    }

if 'group_master_items' not in st.session_state:
    st.session_state.group_master_items = {
        "제조 1반": {"NEW-100": ["100-A"], "NEW-200": ["200-B"]},
        "제조 2반": {
            "EPS7150": ["7150-A", "7150-B"], "EPS7133": ["7133-S", "7133-Standard"],
            "T20i": ["T20i-P", "T20i-Premium"], "T20C": ["T20C-S", "T20C-Standard"]
        },
        "제조 3반": {"AION-X": ["AX-01"], "AION-Standard": ["AS-01"]}
    }

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'selected_group' not in st.session_state: st.session_state.selected_group = "제조 2반"
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 로그인 로직
# =================================================================

if not st.session_state.login_status:
    _, center_col, _ = st.columns([1, 1.2, 1])
    with center_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 통합 관리 시스템</h2>", unsafe_allow_html=True)
        with st.form("pms_login_gate"):
            input_id = st.text_input("아이디(ID)", placeholder="사용자 ID 입력")
            input_pw = st.text_input("비밀번호(PW)", type="password", placeholder="비밀번호 입력")
            if st.form_submit_button("인증 및 접속", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    st.session_state.login_status, st.session_state.user_id = True, input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    st.rerun()
                else: st.error("❌ 정보를 확인해주세요.")
    st.stop()

# =================================================================
# 5. 사이드바 내비게이션 (계층형)
# =================================================================

st.sidebar.markdown("### 🏭 생산 관리 시스템")
st.sidebar.markdown(f"**{st.session_state.user_id} 작업자 ({st.session_state.user_role})**")

if st.sidebar.button("🚪 안전 로그아웃", use_container_width=True): 
    st.session_state.login_status = False; st.rerun()

st.sidebar.divider()
allowed = ROLES.get(st.session_state.user_role, [])

for group in PRODUCTION_GROUPS:
    exp = (st.session_state.selected_group == group and st.session_state.current_line in ["조립 라인", "검사 라인", "포장 라인"])
    with st.sidebar.expander(f"📍 {group}", expanded=exp):
        for p in ["조립 라인", "검사 라인", "포장 라인"]:
            if p in allowed:
                active = (st.session_state.selected_group == group and st.session_state.current_line == p)
                if st.button(f"{p} 현황", key=f"nav_{group}_{p}", use_container_width=True, 
                             type="primary" if active else "secondary"):
                    st.session_state.selected_group, st.session_state.current_line = group, p; st.rerun()

st.sidebar.divider()
for p in ["리포트", "불량 공정", "수리 리포트"]:
    if p in allowed:
        if st.sidebar.button(p, key=f"fnav_{p}", use_container_width=True, type="primary" if st.session_state.current_line == p else "secondary"): 
            st.session_state.current_line = p; st.rerun()

if "마스터 관리" in allowed:
    st.sidebar.divider()
    if st.sidebar.button("🔐 마스터 데이터 관리", use_container_width=True, type="primary" if st.session_state.current_line=="마스터 관리" else "secondary"): 
        st.session_state.current_line = "마스터 관리"; st.rerun()

# =================================================================
# 6. 페이지 렌더링 (800줄 이상 전체 나열)
# =================================================================

curr_g = st.session_state.selected_group
curr_l = st.session_state.current_line

# --- [7-1. 조립 라인] ---
if curr_l == "조립 라인":
    st.markdown(f"<h2 class='centered-title'>📦 {curr_g} 신규 조립 현황</h2>", unsafe_allow_html=True)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    s_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if s_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
    
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 등록")
            my_g_models = st.session_state.group_master_models.get(curr_g, [])
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + my_g_models, key=f"mod_sel_{curr_g}")
            with st.form("assembly_form"):
                fc1, fc2 = st.columns(2)
                my_g_items = st.session_state.group_master_items.get(curr_g, {}).get(target_model, [])
                target_item = fc1.selectbox("품목 코드", my_g_items if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("시리얼(S/N) 입력")
                if st.form_submit_button("▶️ 생산 시작", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        db = st.session_state.production_db
                        if target_sn in db['시리얼'].values: st.error("❌ 이미 등록된 번호입니다.")
                        else:
                            new_row = {'시간': get_now_kst_str(), '반': curr_g, '라인': "조립 라인", 'CELL': st.session_state.selected_cell,
                                       '모델': target_model, '품목코드': target_item, '시리얼': target_sn, '상태': '진행 중', '작업자': st.session_state.user_id}
                            st.session_state.production_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()

    # 원장 뷰
    st.divider()
    db_s = st.session_state.production_db
    f_df = db_s[(db_s['반'] == curr_g) & (db_s['라인'] == "조립 라인")]
    if st.session_state.selected_cell != "전체 CELL": f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "현장 제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델']); r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    if c1.button("조립 완료", key=f"ok_{idx}"): db_s.at[idx, '상태'] = "완료"; push_to_cloud(db_s); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"): db_s.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db_s); st.rerun()
                else: st.write(f"✅ {row['상태']}")

# --- [7-2. 검사 / 포장 라인] ---
elif curr_l in ["검사 라인", "포장 라인"]:
    st.markdown(f"<h2 class='centered-title'>🔍 {curr_g} {curr_l}</h2>", unsafe_allow_html=True)
    prev = "조립 라인" if curr_l == "검사 라인" else "검사 라인"
    with st.container(border=True):
        st.markdown(f"#### 📥 이전 공정({prev}) 완료 물량")
        db_s = st.session_state.production_db
        wait_list = db_s[(db_s['반'] == curr_g) & (db_s['라인'] == prev) & (db_s['상태'] == "완료")]
        if not wait_list.empty:
            w_cols = st.columns(4)
            for i, (idx, row) in enumerate(wait_list.iterrows()):
                if w_cols[i % 4].button(f"승인: {row['시리얼']}", key=f"in_{idx}"):
                    db_s.at[idx, '시간'] = get_now_kst_str()
                    db_s.at[idx, '라인'] = curr_l
                    db_s.at[idx, '상태'] = '진행 중'
                    push_to_cloud(db_s); st.rerun()
        else: st.info("입고 대기 물량 없음")
    
    # 원장 출력
    st.divider()
    f_df = db_s[(db_s['반'] == curr_g) & (db_s['라인'] == curr_l)]
    if not f_df.empty:
        h = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        for col, txt in zip(h, ["기록 시간", "CELL", "모델", "품목", "시리얼", "현장 제어"]): col.write(f"**{txt}**")
        for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
            r = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
            r[0].write(row['시간']); r[1].write(row['CELL']); r[2].write(row['모델']); r[3].write(row['품목코드']); r[4].write(f"`{row['시리얼']}`")
            with r[5]:
                if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                    c1, c2 = st.columns(2)
                    btn = "검사 합격" if curr_l == "검사 라인" else "포장 완료"
                    if c1.button(btn, key=f"ok_{idx}"): db_s.at[idx, '상태'] = "완료"; push_to_cloud(db_s); st.rerun()
                    if c2.button("🚫불량", key=f"ng_{idx}"): db_s.at[idx, '상태'] = "불량 처리 중"; push_to_cloud(db_s); st.rerun()
                else: st.write(f"✅ {row['상태']}")

# --- [7-3. 리포트] ---
elif curr_l == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 통합 모니터링</h2>", unsafe_allow_html=True)
    v_g = st.radio("조회 범위", ["전체"] + PRODUCTION_GROUPS, horizontal=True)
    df = st.session_state.production_db
    if v_g != "전체": df = df[df['반'] == v_g]
    
    if not df.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투입", f"{len(df)} EA")
        c2.metric("최종 생산", f"{len(df[(df['라인']=='포장 라인') & (df['상태']=='완료')])} EA")
        c3.metric("현재 재공", f"{len(df[df['상태']=='진행 중'])} EA")
        c4.metric("품질 이슈", f"{len(df[df['상태'].str.contains('불량')])} 건")
        
        st.divider()
        cl, cr = st.columns([1.8, 1.2])
        with cl:
            fig1 = px.bar(df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 분포", template="plotly_white")
            fig1.update_yaxes(dtick=1)
            st.plotly_chart(fig1, use_container_width=True)
        with cr:
            fig2 = px.pie(df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.5, title="모델별 비중")
            st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

# --- [7-4. 불량 및 수리 센터] ---
elif curr_l == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치</h2>", unsafe_allow_html=True)
    db = st.session_state.production_db
    wait = db[(db['반'] == curr_g) & (db['상태'] == "불량 처리 중")]
    
    k1, k2 = st.columns(2)
    k1.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ {curr_g} 분석 대기</div><div class='stat-value'>{len(wait)}</div></div>", unsafe_allow_html=True)
    k2.markdown(f"<div class='stat-box'><div class='stat-label'>✅ {curr_g} 조치 완료</div><div class='stat-value'>{len(db[(db['반']==curr_g) & (db['상태']=='수리 완료(재투입)')])}</div></div>", unsafe_allow_html=True)
    
    if wait.empty: st.success("품질 이슈 사항 없음")
    else:
        for idx, row in wait.iterrows():
            with st.container(border=True):
                st.write(f"**S/N: {row['시리얼']}** (모델: {row['모델']})")
                r1, r2 = st.columns(2)
                v_c = r1.text_input("불량 원인", key=f"c_{idx}")
                v_a = r2.text_input("수리 조치", key=f"a_{idx}")
                c_f, c_b = st.columns([3, 1])
                img = c_f.file_uploader("증빙 사진", type=['jpg','png'], key=f"i_{idx}")
                c_b.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if c_b.button("확정", key=f"b_{idx}", type="primary"):
                    if v_c and v_a:
                        url = ""
                        if img: url = f" [사진 확인: {upload_img_to_drive(img, row['시리얼'])}]"
                        db.at[idx, '상태'] = "수리 완료(재투입)"
                        db.at[idx, '시간'] = get_now_kst_str()
                        db.at[idx, '증상'], db.at[idx, '수리'] = v_c, v_a + url
                        push_to_cloud(db); st.rerun()

# --- [7-5. 마스터 데이터 관리 (반별 독립 탭)] ---
elif curr_l == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        with st.form("admin_verify"):
            pw = st.text_input("마스터 비밀번호", type="password")
            if st.form_submit_button("인증"):
                if pw in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("접근 거부")
    else:
        st.markdown("<div class='section-title'>📋 제조 반별 독립 모델/품목 기준정보</div>", unsafe_allow_html=True)
        tabs = st.tabs(["제조 1반 설정", "제조 2반 설정", "제조 3반 설정"])
        for i, g_name in enumerate(PRODUCTION_GROUPS):
            with tabs[i]:
                c1, c2 = st.columns(2)
                with c1:
                    nm = st.text_input(f"{g_name} 신규 모델명", key=f"nm_{g_name}")
                    if st.button(f"{g_name} 모델 등록", key=f"nb_{g_name}"):
                        if nm and nm not in st.session_state.group_master_models[g_name]:
                            st.session_state.group_master_models[g_name].append(nm)
                            st.session_state.group_master_items[g_name][nm] = []; st.rerun()
                with c2:
                    sm = st.selectbox("품목용 모델 선택", st.session_state.group_master_models[g_name], key=f"sm_{g_name}")
                    ni = st.text_input(f"{sm}의 품목코드", key=f"ni_{g_name}")
                    if st.button(f"{g_name} 품목 등록", key=f"ib_{g_name}"):
                        if ni and ni not in st.session_state.group_master_items[g_name][sm]:
                            st.session_state.group_master_items[g_name][sm].append(ni); st.rerun()
                st.json(st.session_state.group_master_items[g_name])
        
        st.divider()
        st.subheader("시스템 및 데이터 관리")
        c_csv, c_mig = st.columns(2)
        with c_csv:
            csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 전체 실적 CSV 백업", csv, "PMS_Backup.csv", use_container_width=True)
        with c_mig:
            f = st.file_uploader("복구용 CSV 선택", type="csv")
            if f and st.button("📤 데이터 로드"):
                imp = pd.read_csv(f)
                st.session_state.production_db = pd.concat([st.session_state.production_db, imp], ignore_index=True).drop_duplicates(subset=['시리얼'], keep='last')
                push_to_cloud(st.session_state.production_db); st.rerun()
        if st.button("⚠️ 전체 실적 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','반','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v18.9 FULL VERSION END ]
# =================================================================
