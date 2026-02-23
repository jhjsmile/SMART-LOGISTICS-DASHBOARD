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
st.set_page_config(page_title="생산 통합 관리 시스템 v16.0", layout="wide")

# 권한 정의 (리포트 -> 생산 리포트로 명칭 변경)
ROLES = {
    "master": [
        "조립 라인", "검사 라인", "포장 라인", 
        "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"
    ],
    "control_tower": [
        "생산 리포트", "수리 리포트", "마스터 관리"
    ],
    "assembly_team": [
        "조립 라인"
    ],
    "qc_team": [
        "검사 라인", "불량 공정"
    ],
    "packing_team": [
        "포장 라인"
    ]
}

st.markdown("""
    <style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stButton button { margin-top: 0px; padding: 2px 10px; width: 100%; }
    .centered-title { text-align: center; font-weight: bold; margin: 20px 0; }
    .section-title { 
        background-color: #f8f9fa; color: #000; padding: 15px; border-radius: 8px; 
        font-weight: bold; margin-bottom: 20px; border-left: 8px solid #007bff;
    }
    .status-red { color: #dc3545; font-weight: bold; }
    .status-green { color: #28a745; font-weight: bold; }
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
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 구글 서비스 연결 함수
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
# 3. 세션 상태 초기화
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

# =================================================================
# 4. 로그인 및 사이드바 (레이아웃 복구)
# =================================================================
if not st.session_state.login_status:
    _, l_col, _ = st.columns([1, 1.2, 1])
    with l_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 시스템 로그인</h2>", unsafe_allow_html=True)
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

st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): st.session_state.login_status = False; st.rerun()
st.sidebar.divider()

# 사이드바 메뉴 버튼 (명칭 변경: 생산 리포트)
allowed = ROLES.get(st.session_state.user_role, [])
menu_list = ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"]
icons = {"조립 라인":"📦", "검사 라인":"🔍", "포장 라인":"🚚", "생산 리포트":"📊", "불량 공정":"🛠️", "수리 리포트":"📈", "마스터 관리":"🔐"}

for m in menu_list:
    if m in allowed:
        if st.sidebar.button(f"{icons[m]} {m}", use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            st.session_state.current_line = m; st.rerun()

# 상단 알림 배너
bad_cnt = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_cnt > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_cnt}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 조립 라인 페이지 (함수 압축 해제 버전)
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 조립 라인 현황</h2>", unsafe_allow_html=True)
    
    # [집계표] 상단 현황판 레이아웃
    today = datetime.now().strftime('%Y-%m-%d')
    db = st.session_state.production_db
    t_data = db[(db['라인'] == "조립 라인") & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ 대기</div><div class='stat-value'>-</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(t_data)}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(t_data[t_data['상태']=='완료'])}</div></div>", unsafe_allow_html=True)
    
    st.divider()

    # [CELL 선택] 버튼 레이아웃 복구
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c; st.rerun()
    
    # [입력 폼] 전수 중복 체크 포함
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요."] + st.session_state.master_models)
            with st.form("asm_form"):
                r1, r2 = st.columns(2)
                i_choice = r1.selectbox("품목 선택", st.session_state.master_items_dict.get(m_choice, ["모델 선택 필요"]) if m_choice!="선택하세요." else ["모델 선택 필요"])
                s_input = r2.text_input("시리얼 번호")
                
                if st.form_submit_button("▶️ 조립 투입 등록", use_container_width=True, type="primary"):
                    if m_choice != "선택하세요." and s_input:
                        # [전수 중복 체크] 과거 데이터 전체 조회
                        full_match = db[(db['시리얼'] == s_input) & (db['상태'] != "구분선")]
                        if not full_match.empty and full_match.iloc[-1]['상태'] in ["완료", "진행 중"]:
                            st.error(f"❌ 중복 생산 오류: 시리얼 [ {s_input} ]은 이미 생산 이력이 있습니다.")
                        else:
                            new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                            updated_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            
                            # 10단위 구분선 체크
                            cnt = len(updated_db[(updated_db['라인'] == "조립 라인") & (updated_db['시간'].astype(str).str.contains(today)) & (updated_db['상태'] != "구분선")])
                            if cnt > 0 and cnt % 10 == 0:
                                marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                                updated_db = pd.concat([updated_db, pd.DataFrame([marker])], ignore_index=True)
                            
                            st.session_state.production_db = updated_db
                            save_to_gsheet(updated_db); st.rerun()

    # [로그 테이블] 조립 라인 리스트
    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    h_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for c, txt in zip(h_col, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): c.write(f"**{txt}**")
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee; text-align:center; border-radius:5px; font-weight:bold; margin:5px 0;'>{row['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                if b1.button("완료", key=f"ok_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{row['상태']}**")

# =================================================================
# 6. 검사 / 포장 라인 (긴 코드 레이아웃)
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line = st.session_state.current_line
    prev = "조립 라인" if line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>🔍 {line} 현황</h2>", unsafe_allow_html=True)
    
    db = st.session_state.production_db
    t_v = db[(db['라인'] == line) & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    # 대기 물량 계산
    p_done = set(db[(db['라인'] == prev) & (db['상태'] == '완료')]['시리얼'])
    c_in = set(db[db['라인'] == line]['시리얼'])
    wait_list = list(p_done - c_in)
    
    s1, s2, s3 = st.columns(3)
    with s1: st.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev} 대기</div><div class='stat-value' style='color:orange;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    with s2: st.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(t_v)}</div></div>", unsafe_allow_html=True)
    with s3: st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(t_v[t_v['상태']=='완료'])}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    with st.container(border=True):
        if wait_list:
            sel_sn = st.selectbox("입고 대상 시리얼 선택", wait_list)
            if st.button(f"📥 {line} 입고 승인", use_container_width=True):
                orig = db[(db['라인'] == prev) & (db['시리얼'] == sel_sn)].iloc[-1]
                new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line, 'CELL': '-', '모델': orig['모델'], '품목코드': orig['품목코드'], '시리얼': sel_sn, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                updated_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                
                # 10단위 구분선
                cnt = len(updated_db[(updated_db['라인'] == line) & (updated_db['시간'].astype(str).str.contains(today)) & (updated_db['상태'] != "구분선")])
                if cnt > 0 and cnt % 10 == 0:
                    marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line, 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                    updated_db = pd.concat([updated_db, pd.DataFrame([marker])], ignore_index=True)
                
                st.session_state.production_db = updated_db
                save_to_gsheet(updated_db); st.rerun()
        else: st.info("대기 물량이 없습니다.")
    
    st.divider()
    l_view = st.session_state.production_db[st.session_state.production_db['라인'] == line]
    h_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for c, txt in zip(h_col, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태제어"]): c.write(f"**{txt}**")
    
    for idx, row in l_view.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee; text-align:center; border-radius:5px; font-size:0.8em; font-weight:bold; margin:5px 0;'>{row['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        lr = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr[0].write(row['시간']); lr[1].write(row['CELL']); lr[2].write(row['모델']); lr[3].write(row['품목코드']); lr[4].write(row['시리얼'])
        with lr[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b1, b2 = st.columns(2)
                btn_name = "합격" if line == "검사 라인" else "출고"
                if b1.button(btn_name, key=f"ok_{line}_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b2.button("🚫불량", key=f"ng_{line}_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{row['상태']}**")

# =================================================================
# 7. 불량 공정 (사진 업로드 상세)
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 수리 센터</h2>", unsafe_allow_html=True)
    bad_df = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_df.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_df.iterrows():
            with st.container(border=True):
                st.subheader(f"시리얼: {row['시리얼']} ({row['모델']})")
                cl1, cl2 = st.columns(2)
                cause = cl1.text_input("불량 원인", key=f"c_{idx}")
                action = cl2.text_input("수리 조치", key=f"a_{idx}")
                img_f = st.file_uploader("사진 첨부", type=['jpg','png','jpeg'], key=f"i_{idx}")
                
                if st.button("🛠️ 수리 완료 및 재투입", key=f"btn_{idx}", type="primary"):
                    if cause and action:
                        link = ""
                        if img_f:
                            with st.spinner("드라이브에 사진 저장 중..."):
                                link = upload_image_to_drive(img_f, f"REPAIR_{row['시리얼']}_{datetime.now().strftime('%H%M')}.jpg")
                        
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = cause
                        st.session_state.production_db.at[idx, '수리'] = f"{action} (사진: {link})" if link else action
                        save_to_gsheet(st.session_state.production_db); st.success("수리 완료!"); st.rerun()
                    else: st.error("원인과 조치를 입력하세요.")

# =================================================================
# 8. 생산 리포트 (통합 대시보드)
# =================================================================
elif st.session_state.current_line == "생산 리포트":
    st.markdown("<h2 class='centered-title'>📊 통합 생산 리포트</h2>", unsafe_allow_html=True)
    if st.button("🔄 최신 데이터 불러오기"): st.cache_data.clear(); st.session_state.production_db = load_data(); st.rerun()
    
    r_df = st.session_state.production_db[st.session_state.production_db['상태'] != "구분선"]
    if not r_df.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("최종 출하량", f"{len(r_df[(r_df['라인']=='포장 라인') & (r_df['상태']=='완료')])} EA")
        m2.metric("누적 불량건수", f"{len(r_df[r_df['상태'].str.contains('불량', na=False)])} 건")
        m3.metric("현재 공정 수", len(r_df[r_df['상태']=='진행 중']))
        
        st.divider()
        st.plotly_chart(px.bar(r_df[r_df['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 생산 완료 현황"), use_container_width=True)
        st.dataframe(r_df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

elif st.session_state.current_line == "수리 리포트":
    st.header("📈 불량 수리 이력 리포트")
    rep_history = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    st.dataframe(rep_history[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# =================================================================
# 9. 마스터 관리 (계정 및 기준정보 상세)
# =================================================================
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 관리</h2>", unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        pw_in = st.text_input("관리자 암호", type="password")
        if st.button("인증"):
            if pw_in in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
            else: st.error("비밀번호 불일치")
    else:
        if st.button("🔓 관리자 세션 종료"): st.session_state.admin_authenticated = False; st.rerun()
        
        st.divider()
        st.subheader("👤 사용자 계정 관리")
        u1, u2, u3 = st.columns([3,3,2])
        n_id = u1.text_input("새 아이디")
        n_pw = u2.text_input("새 비밀번호")
        n_ro = u3.selectbox("권한", list(ROLES.keys()))
        if st.button("계정 생성/업데이트"):
            if n_id and n_pw:
                st.session_state.user_db[n_id] = {"pw": n_pw, "role": n_ro}; st.success(f"{n_id} 계정 저장됨")
        
        with st.expander("현재 등록 계정 보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
            
        st.divider()
        st.subheader("📋 기준 정보 관리")
        m_col, i_col = st.columns(2)
        with m_col:
            nm = st.text_input("새 모델 추가")
            if st.button("모델 등록"):
                if nm and nm not in st.session_state.master_models:
                    st.session_state.master_models.append(nm); st.session_state.master_items_dict[nm] = []; st.rerun()
        with i_col:
            sm = st.selectbox("품목 추가 모델", st.session_state.master_models)
            ni = st.text_input("새 품목코드")
            if st.button("품목 등록"):
                if ni and ni not in st.session_state.master_items_dict[sm]:
                    st.session_state.master_items_dict[sm].append(ni); st.rerun()

        st.divider()
        if st.button("⚠️ 전체 데이터 초기화 (영구 삭제)", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            save_to_gsheet(st.session_state.production_db); st.warning("초기화 완료"); st.rerun()
