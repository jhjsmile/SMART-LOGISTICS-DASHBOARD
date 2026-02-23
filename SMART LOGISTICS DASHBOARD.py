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
st.set_page_config(page_title="생산 통합 관리 시스템 v15.7", layout="wide")

# 권한에 따른 메뉴 설정 (리포트 -> 생산 리포트로 변경 완료)
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
        # 캐시 없이 실시간 데이터 로드
        df = conn.read(ttl=0).fillna("")
        if '시리얼' in df.columns:
            # 소수점 제거 로직
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
# 3. 세션 상태 초기화 및 데이터 로드
# =================================================================
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 기본 계정 DB
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
# 4. 로그인 로직
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

# 사이드바 메뉴 구성
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()

allowed_menus = ROLES.get(st.session_state.user_role, [])
for menu in ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"]:
    if menu in allowed_menus:
        if st.sidebar.button(menu, use_container_width=True, type="primary" if st.session_state.current_line==menu else "secondary"):
            st.session_state.current_line = menu
            st.rerun()

# 불량 발생 실시간 알림
bad_waiting = len(st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"])
if bad_waiting > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 제품이 {bad_waiting}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 조립 라인 페이지 (긴 코드 - 상세 구현)
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.header("📦 조립 라인 현황")
    
    today = datetime.now().strftime('%Y-%m-%d')
    db = st.session_state.production_db
    # 오늘 데이터 필터링 (구분선 제외)
    today_asm = db[(db['라인'] == "조립 라인") & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    # 3단 통계
    s1, s2, s3 = st.columns(3)
    s1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ 신규 대기</div><div class='stat-value'>-</div><div class='stat-sub'>조립 시작 전</div></div>", unsafe_allow_html=True)
    s2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(today_asm)}</div><div class='stat-sub'>Today</div></div>", unsafe_allow_html=True)
    s3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(today_asm[today_asm['상태']=='완료'])}</div><div class='stat-sub'>Today</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    # CELL 선택 버튼들
    cells = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    c_cols = st.columns(len(cells))
    for idx, c_name in enumerate(cells):
        if c_cols[idx].button(c_name, type="primary" if st.session_state.selected_cell==c_name else "secondary"): 
            st.session_state.selected_cell = c_name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            model_sel = st.selectbox("모델 선택", ["선택하세요"] + st.session_state.master_models)
            with st.form("asm_input_form"):
                row_a, row_b = st.columns(2)
                item_sel = row_a.selectbox("품목코드", st.session_state.master_items_dict.get(model_sel, ["모델선택"]) if model_sel != "선택하세요" else ["모델선택"])
                serial_in = row_b.text_input("시리얼 번호 입력")
                
                if st.form_submit_button("▶️ 생산 투입 등록", use_container_width=True):
                    if model_sel != "선택하세요" and serial_in:
                        # [핵심] 전수 중복 체크 로직
                        dup_check = db[(db['시리얼'] == serial_in) & (db['상태'] != "구분선")]
                        if not dup_check.empty and dup_check.iloc[-1]['상태'] in ["완료", "진행 중"]:
                            st.error(f"❌ 중복 생산 불가: [ {serial_in} ] 번호는 이미 생산 이력이 존재합니다.")
                        else:
                            new_entry = {
                                '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, '모델': model_sel, '품목코드': item_sel, 
                                '시리얼': serial_in, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            temp_db = pd.concat([db, pd.DataFrame([new_entry])], ignore_index=True)
                            
                            # 10단위 구분선 추가 로직
                            asm_cnt = len(temp_db[(temp_db['라인'] == "조립 라인") & (temp_db['시간'].astype(str).str.contains(today)) & (temp_db['상태'] != "구분선")])
                            if asm_cnt > 0 and asm_cnt % 10 == 0:
                                marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': "조립 라인", 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {asm_cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                                temp_db = pd.concat([temp_db, pd.DataFrame([marker])], ignore_index=True)
                            
                            st.session_state.production_db = temp_db
                            save_to_gsheet(temp_db); st.success(f"{serial_in} 등록 완료!"); st.rerun()

    # 조립 라인 로그 테이블
    st.divider()
    st.subheader(f"📝 {st.session_state.selected_cell} 실시간 작업 로그")
    log_db = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    if st.session_state.selected_cell != "전체 CELL": 
        log_db = log_db[log_db['CELL'] == st.session_state.selected_cell]
    
    for i, r in log_db.sort_values('시간', ascending=False).iterrows():
        if r['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee;text-align:center;padding:5px;border-radius:5px;font-weight:bold;margin:5px 0;'>{r['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        
        c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        c1.write(r['시간']); c2.write(r['CELL']); c3.write(r['모델']); c4.write(r['품목코드']); c5.write(r['시리얼'])
        with c6:
            if r['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_ok, b_ng = st.columns(2)
                if b_ok.button("완료", key=f"ok_asm_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b_ng.button("불량", key=f"ng_asm_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{r['상태']}**")

# =================================================================
# 6. 검사 / 포장 라인 페이지 (공정 연동 및 입고 승인)
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    line = st.session_state.current_line
    prev = "조립 라인" if line == "검사 라인" else "검사 라인"
    st.header(f"🔍 {line} 현황")
    
    db = st.session_state.production_db
    today_v = db[(db['라인'] == line) & (db['시간'].astype(str).str.contains(today)) & (db['상태'] != '구분선')]
    
    # 대기 리스트 계산
    prev_done_sns = set(db[(db['라인'] == prev) & (db['상태'] == '완료')]['시리얼'])
    curr_in_sns = set(db[db['라인'] == line]['시리얼'])
    waiting_sns = list(prev_done_sns - curr_in_sns)
    
    s1, s2, s3 = st.columns(3)
    s1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {prev} 대기</div><div class='stat-value' style='color:orange;'>{len(waiting_sns)}</div></div>", unsafe_allow_html=True)
    s2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(today_v)}</div></div>", unsafe_allow_html=True)
    s3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(today_v[today_v['상태']=='완료'])}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    # 입고 승인 폼
    with st.container(border=True):
        if waiting_sns:
            sns_sel = st.selectbox("입고 대상 시리얼 선택", waiting_sns)
            if st.button(f"📥 {line} 입고 승인", use_container_width=True):
                info_row = db[(db['라인'] == prev) & (db['시리얼'] == sns_sel)].iloc[-1]
                new_entry = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line, 'CELL': '-', '모델': info_row['모델'], '품목코드': info_row['품목코드'], '시리얼': sns_sel, '상태': '진행 중', '증상': '', '수리': '', '작업자': st.session_state.user_id}
                new_db = pd.concat([db, pd.DataFrame([new_entry])], ignore_index=True)
                
                # 구분선 체크
                cur_cnt = len(new_db[(new_db['라인'] == line) & (new_db['시간'].astype(str).str.contains(today)) & (new_db['상태'] != "구분선")])
                if cur_cnt > 0 and cur_cnt % 10 == 0:
                    marker = {'시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': line, 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {cur_cnt}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'}
                    new_db = pd.concat([new_db, pd.DataFrame([marker])], ignore_index=True)
                
                st.session_state.production_db = new_db
                save_to_gsheet(new_db); st.rerun()
        else: st.info("입고 대기 물량이 없습니다.")
    
    # 라인 로그 테이블
    st.divider()
    l_db_line = st.session_state.production_db[st.session_state.production_db['라인'] == line]
    for i, r in l_db_line.sort_values('시간', ascending=False).iterrows():
        if r['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#eee;text-align:center;padding:5px;border-radius:5px;font-size:0.8em;'>{r['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
        c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        c1.write(r['시간']); c2.write(r['CELL']); c3.write(r['모델']); c4.write(r['품목코드']); c5.write(r['시리얼'])
        with c6:
            if r['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_ok, b_ng = st.columns(2)
                if b_ok.button("완료", key=f"ok_{line}_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "완료"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
                if b_ng.button("불량", key=f"ng_{line}_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "불량 처리 중"
                    save_to_gsheet(st.session_state.production_db); st.rerun()
            else: st.write(f"**{r['상태']}**")

# =================================================================
# 7. 불량 수리 센터 (사진 업로드 포함)
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.header("🛠️ 불량 수리 센터")
    bad_list = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if bad_list.empty: st.success("✅ 수리 대기 중인 불량 제품이 없습니다.")
    else:
        for idx, row in bad_list.iterrows():
            with st.container(border=True):
                st.subheader(f"시리얼: {row['시리얼']} ({row['모델']})")
                cl1, cl2 = st.columns(2)
                in_cause = cl1.text_input("불량 원인", key=f"cau_{idx}")
                in_action = cl2.text_input("수리 조치", key=f"act_{idx}")
                in_file = st.file_uploader("수리 사진 첨부", type=['jpg','png','jpeg'], key=f"img_{idx}")
                
                if st.button("🛠️ 수리 완료 및 재투입", key=f"rep_{idx}", type="primary"):
                    if in_cause and in_action:
                        link_url = ""
                        if in_file:
                            with st.spinner("구글 드라이브에 사진 저장 중..."):
                                link_url = upload_image_to_drive(in_file, f"REPAIR_{row['시리얼']}_{datetime.now().strftime('%H%M')}.jpg")
                        
                        st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                        st.session_state.production_db.at[idx, '증상'] = in_cause
                        st.session_state.production_db.at[idx, '수리'] = f"{in_action} (사진: {link_url})" if link_url else in_action
                        save_to_gsheet(st.session_state.production_db); st.success("수리 완료 및 기록 성공!"); st.rerun()
                    else: st.error("원인과 조치 내용을 모두 입력해야 합니다.")

# =================================================================
# 8. 생산 리포트 (통합 대시보드)
# =================================================================
elif st.session_state.current_line == "생산 리포트":
    st.header("📊 통합 생산 리포트")
    if st.button("🔄 최신 데이터 불러오기"): 
        st.cache_data.clear()
        st.session_state.production_db = load_data()
        st.rerun()
    
    total_df = st.session_state.production_db[st.session_state.production_db['상태'] != "구분선"]
    if not total_df.empty:
        # 주요 지표
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("최종 출하량 (포장완료)", f"{len(total_df[(total_df['라인']=='포장 라인') & (total_df['상태']=='완료')])} EA")
        kpi2.metric("누적 불량 발생", f"{len(total_df[total_df['상태'].str.contains('불량', na=False)])} 건")
        kpi3.metric("현재 진행 공정 수", len(total_df[total_df['상태']=='진행 중']))
        
        st.divider()
        # 공정별 실적 차트
        st.plotly_chart(px.bar(total_df[total_df['상태']=='완료'].groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', color='라인', title="공정별 생산 완료 현황"), use_container_width=True)
        # 전체 로그 데이터프레임
        st.dataframe(total_df.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)

elif st.session_state.current_line == "수리 리포트":
    st.header("📈 불량 수리 이력 리포트")
    rep_history = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    if not rep_history.empty:
        st.dataframe(rep_history[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else: st.info("수리 이력이 아직 없습니다.")

# =================================================================
# 9. 마스터 관리 (계정 및 기준 정보)
# =================================================================
elif st.session_state.current_line == "마스터 관리":
    st.header("🔐 시스템 마스터 관리")
    if not st.session_state.admin_authenticated:
        pw_input = st.text_input("관리자 암호를 입력하세요", type="password")
        if st.button("인증"):
            if pw_input in ["admin1234", "master1234"]: 
                st.session_state.admin_authenticated = True
                st.rerun()
            else: st.error("비밀번호가 틀렸습니다.")
    else:
        st.subheader("👤 사용자 계정 관리")
        u_id_new = st.text_input("새 아이디")
        u_pw_new = st.text_input("새 비밀번호")
        u_ro_new = st.selectbox("권한", list(ROLES.keys()))
        if st.button("계정 생성/수정"):
            if u_id_new and u_pw_new:
                st.session_state.user_db[u_id_new] = {"pw": u_pw_new, "role": u_ro_new}
                st.success(f"{u_id_new} 계정이 설정되었습니다.")
        
        with st.expander("현재 시스템 등록 계정 보기"):
            st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
            
        st.divider()
        st.subheader("📋 기준 정보 관리")
        mc1, mc2 = st.columns(2)
        with mc1:
            m_add = st.text_input("신규 모델명 추가")
            if st.button("모델 등록"):
                if m_add and m_add not in st.session_state.master_models:
                    st.session_state.master_models.append(m_add); st.session_state.master_items_dict[m_add] = []; st.rerun()
        with mc2:
            m_sel_for_i = st.selectbox("품목 추가할 모델 선택", st.session_state.master_models)
            i_add = st.text_input("신규 품목코드 추가")
            if st.button("품목 등록"):
                if i_add and i_add not in st.session_state.master_items_dict[m_sel_for_i]:
                    st.session_state.master_items_dict[m_sel_for_i].append(i_add); st.rerun()

        st.divider()
        if st.button("⚠️ 전체 생산 데이터 초기화 (영구 삭제)", type="secondary"):
            st.session_state.production_db = pd.DataFrame(columns=['시간','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
            save_to_gsheet(st.session_state.production_db)
            st.warning("모든 생산 데이터가 초기화되었습니다."); st.rerun()
