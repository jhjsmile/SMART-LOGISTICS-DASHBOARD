import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 설정 및 스타일 정의
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 v15.6", layout="wide")

# 권한에 따른 메뉴 설정 (리포트 -> 생산 리포트로 명칭 변경)
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["생산 리포트", "수리 리포트", "마스터 관리"],
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
# 2. 구글 데이터베이스 연결 (시트 및 드라이브)
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
# 4. 로그인 화면 로직
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

# 사이드바 네비게이션
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()

allowed = ROLES.get(st.session_state.user_role, [])
for m in ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"]:
    if m in allowed:
        if st.sidebar.button(m, use_container_width=True, type="primary" if st.session_state.current_line==m else "secondary"):
            st.session_state.current_line = m
            st.rerun()

# 불량 알림 배너
bad_count = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_count > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_count}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 조립 라인 페이지 (긴 코드 버전 - 명시적 구현)
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.header("📦 조립 라인 현황")
    
    today = datetime.now().strftime('%Y-%m-%d')
    db = st.session_state.production_db
    today_data = db[(db['라인'] == "조립 라인") & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ 신규 대기</div><div class='stat-value'>-</div><div class='stat-sub'>조립 시작 전</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(today_data)}</div><div class='stat-sub'>Today</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(today_data[today_data['상태']=='완료'])}</div><div class='stat-sub'>Today</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for i, c in enumerate(cells):
        if c_cols[i].button(c, type="primary" if st.session_state.selected_cell==c else "secondary"): 
            st.session_state.selected_cell = c; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            m_choice = st.selectbox("모델 선택", ["선택하세요"] + st.session_state.master_models)
            with st.form("asm_form_detail"):
                col_a, col_b = st.columns(2)
                i_choice = col_a.selectbox("품목코드", st.session_state.master_items_dict.get(m_choice, ["모델선택"]) if m_choice != "선택하세요" else ["모델선택"])
                s_input = col_b.text_input("시리얼 번호 입력")
                
                if st.form_submit_button("▶️ 생산 투입 등록", use_container_width=True):
                    if m_choice != "선택하세요" and s_input:
                        # [전수 중복 체크] 날짜 무관 전체 DB 검사
                        full_match = db[(db['시리얼'] == s_input) & (db['상태'] != "구분선")]
                        if not full_match.empty and full_match.iloc[-1]['상태'] in ["완료", "진행 중"]:
                            st.error(f"❌ 중복 생산 불가: [ {s_input} ] 번호는 이미 생산 이력이 존재합니다.")
                        else:
                            new_row = {
                                '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, '모델': m_choice, '품목코드': i_choice, 
                                '시리얼': s_input, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            new_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                            
                            # 10단위 구분선 체크
                            line_cnt = len(new_db[(new_db['라인'] == "조립 라인") & (new_db['시간'].astype(str).str.contains(today)) & (new_db['상태'] != "구분선")])
                            if line_cnt > 0 and line_cnt % 10 == 0:
                                marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {line_cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                                new_db = pd.concat([new_db, pd.DataFrame([marker])], ignore_index=True)
                            
                            st.session_state.production_db = new_db
                            save_to_gsheet(new_db); st.success(f"{s_input} 등록 완료!"); st.rerun()

    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": l_db = l_db[l_db['CELL'] == st.session_state.selected_cell]
    
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee;text-align:center;padding:5px;border-radius:5px;font-weight:bold;margin:5px 0;'>{row['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        la, lb, lc, ld, le, lf = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        la.write(row['시간']); lb.write(row['CELL']); lc.write(row['모델']); ld.write(row['품목코드']); le.write(row['시리얼'])
        with lf:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                ok_btn, ng_btn = st.columns(2)
                if ok_btn.button("완료", key=f"ok_asm_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if ng_btn.button("불량", key=f"ng_asm_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{row['상태']}**")

# =================================================================
# 6. 검사 / 포장 라인 (입고 승인 로직)
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line_name = st.session_state.current_line
    prev_line = "조립 라인" if line_name == "검사 라인" else "검사 라인"
    st.header(f"🔍 {line_name} 현황")
    
    db = st.session_state.production_db
    today_data = db[(db['라인'] == line_name) & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    prev_done = set(db[(db['라인'] == prev_line) & (db['상태'] == '완료')]['시리얼'])
    curr_in = set(db[db['라인'] == line_name]['시리얼'])
    wait_list = list(prev_done - curr_in)
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev_line} 대기</div><div class='stat-value' style='color:orange;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(today_data)}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(today_data[today_data['상태']=='완료'])}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    with st.container(border=True):
        if wait_list:
            sel_sn = st.selectbox("입고 대상 시리얼 선택", wait_list)
            if st.button(f"📥 {line_name} 입고 승인", use_container_width=True):
                info = db[(db['라인'] == prev_line) & (db['시리얼'] == sel_sn)].iloc[-1]
                new_row = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line_name, 'CELL': '-', '모델': info['모델'], '품목코드': info['품목코드'], '시리얼': sel_sn, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                new_db = pd.concat([db, pd.DataFrame([new_row])], ignore_index=True)
                
                line_cnt = len(new_db[(new_db['라인'] == line_name) & (new_db['시간'].astype(str).str.contains(today)) & (new_db['상태'] != "구분선")])
                if line_cnt > 0 and line_cnt % 10 == 0:
                    marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line_name, 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {line_cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                    new_db = pd.concat([new_db, pd.DataFrame([marker])], ignore_index=True)
                
                st.session_state.production_db = new_db
                save_to_gsheet(new_db); st.rerun()
        else: st.info("입고 대기 물량이 없습니다.")
    
    st.divider()
    l_db = st.session_state.production_db[st.session_state.production_db['라인'] == line_name]
    for idx, row in l_db.sort_values('시간', ascending=False).iterrows():
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee;text-align:center;padding:5px;border-radius:5px;font-size:0.8em;'>{row['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        la, lb, lc, ld, le, lf = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        la.write(row['시간']); lb.write(row['CELL']); lc.write(row['모델']); ld.write(row['품목코드']); le.write(row['시리얼'])
        with lf:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                ok_btn, ng_btn = st.columns(2)
                if ok_btn.button("완료", key=f"ok_{line_name}_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if ng_btn.button("불량", key=f"ng_{line_name}_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{row['상태']}**")

# =================================================================
# 7. 불량 공정 (이미지 업로드 포함)
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.header("🛠️ 불량 수리 센터")
    bad_df = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_df.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_df.iterrows():
            with st.container(border=True):
                st.subheader(f"시리얼: {row['시리얼']} ({row['모델']})")
                c1, c2 = st.columns(2)
                cause = c1.text_input("불량 원인", key=f"cau_{idx}")
                action = c2.text_input("수리 조치", key=f"act_{idx}")
                img_f = st.file_uploader("사진 첨부", type=['jpg','png','jpeg'], key=f"img_{idx}")
                
                if st.button("🛠️ 수리 완료 및 재투입", key=f"rep_{idx}", type="primary"):
                    if cause and action:
                        link = ""
                        if img_f:
                            with st.spinner("드라이브에 사진 저장 중..."):
                                link = upload_image_to_drive(img_f, f"REPAIR_{row['시리얼']}_{datetime.now().strftime('%H%M')}.jpg")
                        
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = cause
                        st.session_state.production_db.at[idx, '수리'] = f"{action} (사진: {link})" if link else action
                        save_to_gsheet(st.session_state.production_db); st.success("수리 완료!"); st.rerun()

# =================================================================
# 8. 생산 리포트 (명칭 변경 반영)
# =================================================================
elif st.session_state.current_line == "생산 리포트":
    st.header("📊 통합 생산 리포트")
    if st.button("🔄 최신 데이터 불러오기"): st.cache_data.clear(); st.session_state.production_db = load_data(); st.rerun()
    
    df = st.session_state.production_db[st.session_state.production_db['상태'] != "구분선"]
    if not df.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("최종 출하량", f"{len(df[(df['라인']=='포장 라인') & (df['상태']=='완료')])} EA")
        m2.metric("누적 불량건수", f"{len(df[df['상태'].str.contains('불량', na=False)])} 건")
        m3.metric("현재 가동 공정", len(df[df['상태']=='진행 중']))
        
        st.divider()
        st.plotly_chart(px.bar(df[df['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 실적 현황"), use_container_width=True)
        st.dataframe(df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

elif st.session_state.current_line == "수리 리포트":
    st.header("📈 불량 수리 이력 리포트")
    rep_db = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    st.dataframe(rep_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)

# =================================================================
# 9. 마스터 관리 (계정 및 기준정보)
# =================================================================
elif st.session_state.current_line == "마스터 관리":
    st.header("🔐 시스템 마스터 설정")
    if not st.session_state.admin_authenticated:
        pw_in = st.text_input("관리자 암호", type="password")
        if st.button("인증"):
            if pw_in in ["admin1234", "master1234"]: st.session_state.admin_authenticated = True; st.rerun()
    else:
        st.subheader("👤 사용자 계정 관리")
        u_id = st.text_input("새 아이디")
        u_pw = st.text_input("새 비밀번호")
        u_ro = st.selectbox("권한", list(ROLES.keys()))
        if st.button("계정 추가/수정"):
            st.session_state.user_db[u_id] = {"pw": u_pw, "role": u_ro}; st.success(f"{u_id} 계정 정보 저장됨")
        
        st.divider()
        st.subheader("📋 기준 정보 관리")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            new_m = st.text_input("새 모델 추가")
            if st.button("모델 등록"):
                if new_m and new_m not in st.session_state.master_models:
                    st.session_state.master_models.append(new_m); st.session_state.master_items_dict[new_m] = []; st.rerun()
        with col_m2:
            sel_m = st.selectbox("품목 추가할 모델", st.session_state.master_models)
            new_i = st.text_input("새 품목코드")
            if st.button("품목 등록"):
                if new_i and new_i not in st.session_state.master_items_dict[sel_m]:
                    st.session_state.master_items_dict[sel_m].append(new_i); st.rerun()

        st.divider()
        if st.button("⚠️ 전체 생산 DB 초기화", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            save_to_gsheet(st.session_state.production_db); st.warning("초기화 완료"); st.rerun()
