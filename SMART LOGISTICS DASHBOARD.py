import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from streamlit_gsheets import GSheetsConnection
import io

# 구글 드라이브 연동을 위한 필수 라이브러리들
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 환경 설정 및 UI 스타일 정의
# =================================================================
# 앱의 제목과 레이아웃을 전체 화면 모드로 설정합니다.
st.set_page_config(page_title="생산 통합 관리 시스템 v15.9", layout="wide")

# 사용자 권한별 메뉴 접근 권한을 정의합니다. (생산 리포트로 명칭 변경 반영)
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

# 현장 분위기에 맞는 커스텀 CSS 스타일을 적용합니다.
st.markdown("""
    <style>
    /* 전체 앱의 최대 폭 설정 */
    .stApp { 
        max-width: 1200px; 
        margin: 0 auto; 
    }
    /* 버튼 스타일 조정: 현장에서 클릭하기 쉽게 최적화 */
    .stButton button { 
        margin-top: 0px; 
        padding: 2px 10px; 
        width: 100%; 
    }
    /* 제목 중앙 정렬 및 강조 */
    .centered-title { 
        text-align: center; 
        font-weight: bold; 
        margin: 20px 0; 
    }
    /* 불량 알림용 긴급 배너 스타일 */
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
    /* 현황판 숫자 박스 스타일 */
    .stat-box {
        background-color: #f0f2f6; 
        border-radius: 10px; 
        padding: 15px; 
        text-align: center;
        border: 1px solid #e0e0e0; 
        margin-bottom: 10px;
    }
    .stat-label { 
        font-size: 0.9em; 
        color: #555; 
        font-weight: bold; 
    }
    .stat-value { 
        font-size: 1.8em; 
        color: #007bff; 
        font-weight: bold; 
    }
    .stat-sub { 
        font-size: 0.8em; 
        color: #888; 
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. 데이터베이스 연동 및 유틸리티 함수
# =================================================================
# 구글 스프레드시트 연결 오브젝트 생성
conn = st.connection("gsheets", type=GSheetsConnection)

# 데이터를 불러오는 함수 (캐시를 사용하지 않아 실시간성을 보장함)
def load_data():
    try:
        # ttl=0 설정을 통해 매번 새로 읽어오도록 강제함
        df = conn.read(ttl=0).fillna("")
        # 시리얼 번호가 숫자로 인식되어 .0이 붙는 현상을 정규식으로 제거함
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        # 데이터가 없거나 로드 실패 시 빈 데이터프레임 구조 생성
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

# 수정한 데이터를 다시 구글 시트에 반영하는 함수
def save_to_gsheet(df):
    conn.update(data=df)
    # 저장 후에는 로컬 캐시를 비워 다음 읽기 때 신선한 데이터를 가져오게 함
    st.cache_data.clear()

# 구글 드라이브 폴더에 이미지를 저장하는 함수
def upload_image_to_drive(file_obj, filename):
    try:
        # secrets.toml에 저장된 서비스 계정 정보 로드
        raw_creds = st.secrets["connections"]["gsheets"]
        creds = service_account.Credentials.from_service_account_info(raw_creds)
        
        # 구글 드라이브 API 서비스 빌드
        service = build('drive', 'v3', credentials=creds)
        
        # 목적지 폴더 ID 가져오기
        folder_id = st.secrets["connections"]["gsheets"].get("image_folder_id")
        if not folder_id:
            return "폴더ID설정안됨"

        # 파일 메타데이터 정의
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        # 실제 파일 데이터 스트림 준비
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # 업로드 실행 및 결과 수신
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink') # 저장된 파일의 주소 반환
    except Exception as e:
        return f"업로드실패({str(e)})"

# =================================================================
# 3. 세션 상태(Session State) 초기화 관리
# =================================================================
# 앱이 처음 실행될 때 필요한 변수들을 메모리에 할당합니다.
if 'production_db' not in st.session_state: 
    st.session_state.production_db = load_data()

# 기본 계정 정보 설정
if 'user_db' not in st.session_state:
    st.session_state.user_db = {
        "master": {"pw": "master1234", "role": "master"},
        "admin": {"pw": "admin1234", "role": "control_tower"},
        "line1": {"pw": "1111", "role": "assembly_team"},
        "line2": {"pw": "2222", "role": "qc_team"},
        "line3": {"pw": "3333", "role": "packing_team"}
    }

# 앱 구동 상태 변수
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False

# 마스터 데이터 (모델 및 품목)
if 'master_models' not in st.session_state: 
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]
if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A"], 
        "EPS7133": ["7133-S"], 
        "T20i": ["T20i-P"], 
        "T20C": ["T20C-S"]
    }

# UI 상태 변수
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# =================================================================
# 4. 보안 및 로그인 관리 시스템
# =================================================================
if not st.session_state.login_status:
    # 로그인 폼을 화면 중앙에 배치
    _, login_col, _ = st.columns([1, 1.2, 1])
    with login_col:
        st.markdown("<h2 class='centered-title'>🔐 생산 시스템 로그인</h2>", unsafe_allow_html=True)
        st.info("💡 계정 안내: master(전체), admin(관제), line1~3(현장)")
        with st.form("login_form"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("로그인", use_container_width=True):
                if input_id in st.session_state.user_db and st.session_state.user_db[input_id]["pw"] == input_pw:
                    # 로그인 성공 시 캐시 청소 및 최신 데이터 동기화
                    st.cache_data.clear()
                    st.session_state.production_db = load_data()
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = st.session_state.user_db[input_id]["role"]
                    # 소속 권한에 맞는 첫 번째 메뉴로 자동 연결
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else:
                    st.error("계정 정보가 일치하지 않습니다.")
    st.stop() # 로그인 전까지 아래 코드 실행 중단

# 사이드바 구성
st.sidebar.title(f"🏭 {st.session_state.user_id}님")
if st.sidebar.button("전체 로그아웃"): 
    st.session_state.login_status = False
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()

# 권한에 따른 메뉴 필터링 및 버튼 생성
my_menus = ROLES.get(st.session_state.user_role, [])
for m_name in ["조립 라인", "검사 라인", "포장 라인", "생산 리포트", "불량 공정", "수리 리포트", "마스터 관리"]:
    if m_name in my_menus:
        if st.sidebar.button(m_name, use_container_width=True, type="primary" if st.session_state.current_line==m_name else "secondary"):
            st.session_state.current_line = m_name
            st.rerun()

# 불량 발생 시 실시간 상단 배너 표시
bad_records = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
if len(bad_records) > 0:
    st.markdown(f"<div class='alarm-banner'>⚠️ 현장 알림: 수리 대기 중인 불량 제품이 {len(bad_records)}건 있습니다.</div>", unsafe_allow_html=True)

# =================================================================
# 5. 조립 라인 (Assembly Line) 섹션 - 상세 구현
# =================================================================
if st.session_state.current_line == "조립 라인":
    st.header("📦 조립 라인 현황")
    
    # 오늘 날짜 기준 데이터 필터링 (구분선은 통계에서 제외)
    today_date = datetime.now().strftime('%Y-%m-%d')
    main_db = st.session_state.production_db
    asm_today_data = main_db[(main_db['라인'] == "조립 라인") & (main_db['시간'].astype(str).str.contains(today_date)) & (main_db['상태'] != '구분선')]
    
    # 상단 3단 현황 박스 배치
    box1, box2, box3 = st.columns(3)
    box1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ 신규 대기</div><div class='stat-value'>-</div><div class='stat-sub'>생산 시작 전</div></div>", unsafe_allow_html=True)
    box2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(asm_today_data)}</div><div class='stat-sub'>Today Total</div></div>", unsafe_allow_html=True)
    box3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(asm_today_data[asm_today_data['상태']=='완료'])}</div><div class='stat-sub'>Today Done</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    # CELL 선택 시스템 (버튼식)
    st.subheader("📍 작업 CELL 선택")
    cell_names = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    btn_grid = st.columns(len(cell_names))
    for i, c_name in enumerate(cell_names):
        if btn_grid[i].button(c_name, key=f"cell_btn_{c_name}", type="primary" if st.session_state.selected_cell==c_name else "secondary"): 
            st.session_state.selected_cell = c_name
            st.rerun()
            
    # 제품 투입 입력 폼
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"### ⚙️ {st.session_state.selected_cell} 제품 투입")
            selected_model = st.selectbox("투입 모델 선택", ["선택하세요"] + st.session_state.master_models)
            
            with st.form("assembly_entry_form"):
                form_col1, form_col2 = st.columns(2)
                selected_item = form_col1.selectbox("품목코드", st.session_state.master_items_dict.get(selected_model, ["모델을 선택하세요"]) if selected_model != "선택하세요" else ["모델을 먼저 선택하세요"])
                input_serial = form_col2.text_input("시리얼 번호 스캔/입력")
                
                if st.form_submit_button("🚀 생산 투입 등록", use_container_width=True):
                    if selected_model != "선택하세요" and input_serial:
                        # [가장 중요한 전수 중복 체크]
                        # 날짜 상관없이 전체 DB를 훑어서 같은 시리얼이 '완료' 혹은 '진행 중'인지 확인
                        duplicate_data = main_db[(main_db['시리얼'] == input_serial) & (main_db['상태'] != "구분선")]
                        
                        if not duplicate_data.empty and duplicate_data.iloc[-1]['상태'] in ["완료", "진행 중"]:
                            st.error(f"❌ 중복 생산 오류: 시리얼 [ {input_serial} ] 번호는 이미 이력이 존재합니다.")
                            st.toast("중복 시리얼 감지됨", icon="🚨")
                        else:
                            # 신규 행 생성
                            new_data_row = {
                                '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                                '라인': "조립 라인", 
                                'CELL': st.session_state.selected_cell, 
                                '모델': selected_model, 
                                '품목코드': selected_item, 
                                '시리얼': input_serial, 
                                '상태': '진행 중', 
                                '증상': '', 
                                '수리': '', 
                                '작업자': st.session_state.user_id
                            }
                            # 데이터프레임 병합
                            temp_db = pd.concat([main_db, pd.DataFrame([new_data_row])], ignore_index=True)
                            
                            # 10단위 달성 시 자동 구분선 삽입 로직
                            current_total = len(temp_db[(temp_db['라인'] == "조립 라인") & (temp_db['시간'].astype(str).str.contains(today_date)) & (temp_db['상태'] != "구분선")])
                            if current_total > 0 and current_total % 10 == 0:
                                marker_data = {
                                    '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                                    '라인': "조립 라인", 
                                    'CELL': '-', 
                                    '모델': '----------------', 
                                    '품목코드': '----------------', 
                                    '시리얼': f"✅ {current_total}대 달성", 
                                    '상태': '구분선', 
                                    '증상': '', 
                                    '수리': '', 
                                    '작업자': '-'
                                }
                                temp_db = pd.concat([temp_db, pd.DataFrame([marker_data])], ignore_index=True)
                            
                            st.session_state.production_db = temp_db
                            save_to_gsheet(temp_db)
                            st.success(f"시리얼 {input_serial} 등록 성공!")
                            st.rerun()

    # 조립 라인 실시간 작업 현황 테이블 (압축 해제된 상세 코드)
    st.divider()
    st.subheader(f"📝 {st.session_state.selected_cell} 실시간 작업 로그")
    current_asm_view = st.session_state.production_db[st.session_state.production_db['라인'] == "조립 라인"]
    
    # 특정 CELL이 선택된 경우 해당 CELL 데이터만 필터링
    if st.session_state.selected_cell != "전체 CELL": 
        current_asm_view = current_asm_view[current_asm_view['CELL'] == st.session_state.selected_cell]
    
    # 헤더 출력
    h_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    h_titles = ["시간", "CELL", "모델", "품목코드", "시리얼", "작업제어"]
    for col_obj, title_txt in zip(h_col, h_titles):
        col_obj.write(f"**{title_txt}**")
    
    # 데이터 행 루프 (최신 데이터가 위로 오도록 역순 정렬)
    for idx, row in current_asm_view.sort_values('시간', ascending=False).iterrows():
        # 구분선 행 처리
        if row['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#f8f9fa; text-align:center; padding:5px; border-radius:5px; font-weight:bold; color:#6c757d; margin:5px 0;'>{row['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        r_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        r_col[0].write(row['시간'])
        r_col[1].write(row['CELL'])
        r_col[2].write(row['모델'])
        r_col[3].write(row['품목코드'])
        r_col[4].write(row['시리얼'])
        
        with r_col[5]:
            # '진행 중' 상태일 때만 작업 버튼 노출
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                act_col1, act_col2 = st.columns(2)
                if act_col1.button("✅ 완료", key=f"btn_ok_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "완료"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()
                if act_col2.button("🚫 불량", key=f"btn_ng_{idx}"):
                    st.session_state.production_db.at[idx, '상태'] = "불량 처리 중"
                    st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span style='color:red; font-weight:bold;'>🔴 불량 처리 중</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:green; font-weight:bold;'>🟢 작업 완료</span>", unsafe_allow_html=True)

# =================================================================
# 6. 검사 / 포장 라인 (QC & Packing) 섹션 - 연동 로직 구현
# =================================================================
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    current_line_name = st.session_state.current_line
    # 이전 단계가 무엇인지 정의 (검사 <- 조립 / 포장 <- 검사)
    previous_line_name = "조립 라인" if current_line_name == "검사 라인" else "검사 라인"
    st.header(f"🔍 {current_line_name} 현황")
    
    # 실시간 데이터 집계
    total_db = st.session_state.production_db
    now_today = datetime.now().strftime('%Y-%m-%d')
    line_today_data = total_db[(total_db['라인'] == current_line_name) & (total_db['시간'].astype(str).str.contains(now_today)) & (total_db['상태'] != '구분선')]
    
    # 이전 공정 완료 물량 중 현재 공정에 아직 안 들어온 '대기 물량' 계산
    prev_line_finished = set(total_db[(total_db['라인'] == previous_line_name) & (total_db['상태'] == '완료')]['시리얼'])
    this_line_started = set(total_db[total_db['라인'] == current_line_name]['시리얼'])
    waiting_pool = list(prev_line_finished - this_line_started)
    
    # 3단 통계 보드
    st_c1, st_c2, st_c3 = st.columns(3)
    st_c1.markdown(f"<div class='stat-box'><div class='stat-label'>⏳ {previous_line_name} 대기</div><div class='stat-value' style='color:orange;'>{len(waiting_pool)}</div><div class='stat-sub'>물량 입고 필요</div></div>", unsafe_allow_html=True)
    st_c2.markdown(f"<div class='stat-box'><div class='stat-label'>📥 금일 투입</div><div class='stat-value'>{len(line_today_data)}</div><div class='stat-sub'>Today In</div></div>", unsafe_allow_html=True)
    st_c3.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 완료</div><div class='stat-value' style='color:green;'>{len(line_today_data[line_today_data['상태']=='완료'])}</div><div class='stat-sub'>Today Out</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    # 입고 승인 처리 구역
    with st.container(border=True):
        st.subheader("📥 공정 입고 승인")
        if waiting_pool:
            selected_sn = st.selectbox("입고할 시리얼 번호 선택", waiting_pool)
            if st.button(f"✅ {current_line_name} 입고 확인", use_container_width=True):
                # 이전 공정의 마지막 기록에서 모델/품목 정보 추출
                prev_info = total_db[(total_db['라인'] == previous_line_name) & (total_db['시리얼'] == selected_sn)].iloc[-1]
                
                # 새로운 공정 투입 행 생성
                new_in_row = {
                    '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                    '라인': current_line_name, 
                    'CELL': '-', 
                    '모델': prev_info['모델'], 
                    '품목코드': prev_info['품목코드'], 
                    '시리얼': selected_sn, 
                    '상태': '진행 중', 
                    '증상': '', 
                    '수리': '', 
                    '작업자': st.session_state.user_id
                }
                final_db = pd.concat([total_db, pd.DataFrame([new_in_row])], ignore_index=True)
                
                # 이 라인의 10단위 구분선 체크
                line_count_now = len(final_db[(final_db['라인'] == current_line_name) & (final_db['시간'].astype(str).str.contains(now_today)) & (final_db['상태'] != "구분선")])
                if line_count_now > 0 and line_count_now % 10 == 0:
                    marker_row = {
                        '시간': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '라인': current_line_name, 'CELL': '-', '모델': '----------------', '품목코드': '----------------', '시리얼': f"✅ {line_count_now}대 달성", '상태': '구분선', '증상': '', '수리': '', '작업자': '-'
                    }
                    final_db = pd.concat([final_db, pd.DataFrame([marker_row])], ignore_index=True)
                
                st.session_state.production_db = final_db
                save_to_gsheet(final_db)
                st.rerun()
        else:
            st.info("현재 이전 공정에서 넘어온 대기 물량이 없습니다.")
            
    # 라인 실시간 로그 테이블
    st.divider()
    st.subheader(f"📝 {current_line_name} 작업 로그")
    line_log_df = st.session_state.production_db[st.session_state.production_db['라인'] == current_line_name]
    
    # 헤더
    lh_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
    for l_obj, l_txt in zip(lh_col, ["시간", "CELL", "모델", "품목코드", "시리얼", "상태관리"]):
        l_obj.write(f"**{l_txt}**")
        
    for i, r in line_log_df.sort_values('시간', ascending=False).iterrows():
        if r['상태'] == "구분선":
            st.markdown(f"<div style='background-color:#f1f3f5; text-align:center; padding:5px; border-radius:5px; font-size:0.8em; font-weight:bold; margin:5px 0;'>📦 {r['시리얼']} ---------------------------------------</div>", unsafe_allow_html=True)
            continue
            
        lr_col = st.columns([2.5, 1, 1.5, 1.5, 2, 3])
        lr_col[0].write(r['시간'])
        lr_col[1].write(r['CELL'])
        lr_col[2].write(r['모델'])
        lr_col[3].write(r['품목코드'])
        lr_col[4].write(r['시리얼'])
        with lr_col[5]:
            if r['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_c1, b_c2 = st.columns(2)
                # 라인별 맞춤 버튼 이름 (검사-합격/포장-출고)
                btn_name = "검사합격" if current_line_name == "검사 라인" else "출고완료"
                if b_c1.button(btn_name, key=f"btn_fin_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "완료"
                    st.session_state.production_db.at[i, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()
                if b_c2.button("🚫불량", key=f"btn_bad_{i}"):
                    st.session_state.production_db.at[i, '상태'] = "불량 처리 중"
                    st.session_state.production_db.at[i, '작업자'] = st.session_state.user_id
                    save_to_gsheet(st.session_state.production_db)
                    st.rerun()
            else:
                st.write(f"**{r['상태']}**")

# =================================================================
# 7. 불량 수리 센터 (Repair Center) 섹션 - 이미지 연동 포함
# =================================================================
elif st.session_state.current_line == "불량 공정":
    st.header("🛠️ 불량 수리 센터")
    
    # 상태가 '불량 처리 중'인 데이터만 추출
    waiting_repair = st.session_state.production_db[st.session_state.production_db['상태'] == "불량 처리 중"]
    
    if waiting_repair.empty:
        st.success("✅ 현재 수리 대기 중인 불량 제품이 없습니다. 현장이 깨끗합니다!")
    else:
        st.warning(f"현재 총 {len(waiting_repair)}건의 불량 제품이 조치 대기 중입니다.")
        
        for idx, row in waiting_repair.iterrows():
            with st.container(border=True):
                st.subheader(f"🔎 불량 발생 S/N: {row['시리얼']}")
                st.write(f"모델: {row['모델']} | 발생공정: {row['라인']} | 발생시간: {row['시간']}")
                
                c_rep1, c_rep2 = st.columns(2)
                # 입력값 임시 저장을 위해 key에 인덱스 활용
                cause_input = c_rep1.text_input("불량 원인 판명", key=f"input_cause_{idx}")
                repair_input = c_rep2.text_input("수리 조치 내용", key=f"input_action_{idx}")
                
                # 사진 업로드 필드
                photo_file = st.file_uploader("수리 증빙 사진 (드라이브 저장)", type=['jpg','png','jpeg'], key=f"upload_{idx}")
                
                if st.button("✅ 수리 완료 및 공정 재투입", key=f"btn_repair_{idx}", type="primary"):
                    if cause_input and repair_input:
                        with st.spinner("이미지 및 데이터를 서버에 저장 중..."):
                            img_url = ""
                            if photo_file:
                                # 구글 드라이브에 이미지 업로드 시도
                                img_url = upload_image_to_drive(photo_file, f"REPAIR_{row['시리얼']}_{datetime.now().strftime('%H%M%S')}.jpg")
                            
                            # 데이터 업데이트
                            st.session_state.production_db.at[idx, '상태'] = "수리 완료(재투입)"
                            st.session_state.production_db.at[idx, '증상'] = cause_input
                            # 수리 내용에 드라이브 링크를 함께 저장
                            st.session_state.production_db.at[idx, '수리'] = f"{repair_input} (사진: {img_url})" if img_url else repair_input
                            st.session_state.production_db.at[idx, '작업자'] = st.session_state.user_id
                            
                            save_to_gsheet(st.session_state.production_db)
                            st.success(f"{row['시리얼']} 수리 완료 및 재투입 처리되었습니다.")
                            st.rerun()
                    else:
                        st.error("불량 원인과 조치 내용을 모두 입력해야 수리 완료가 가능합니다.")

# =================================================================
# 8. 생산 리포트 (Production Report) 섹션 - 통합 대시보드
# =================================================================
elif st.session_state.current_line == "생산 리포트":
    st.header("📊 통합 생산 리포트 대시보드")
    
    # 상단 기능 버튼
    if st.button("🔄 최신 생산 데이터 강제 새로고침"):
        st.cache_data.clear()
        st.session_state.production_db = load_data()
        st.rerun()
        
    # 구분선을 제외한 순수 데이터만 추출
    report_df = st.session_state.production_db[st.session_state.production_db['상태'] != "구분선"]
    
    if not report_df.empty:
        # 주요 생산 지표 (KPI)
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        
        # 포장 라인 완료 기준 최종 생산량
        final_shipment = len(report_df[(report_df['라인'] == '포장 라인') & (report_df['상태'] == '완료')])
        # 전체 불량 발생 건수
        total_bad = len(report_df[report_df['상태'].str.contains("불량", na=False)])
        # 현재 전체 공정 내 진행 중인 수량
        current_wip = len(report_df[report_df['상태'] == '진행 중'])
        # 직행률 (First Time Through)
        ftt_rate = (final_shipment / (final_shipment + total_bad) * 100) if (final_shipment + total_bad) > 0 else 100
        
        kpi_c1.metric("최종 생산량", f"{final_shipment} EA")
        kpi_c2.metric("누적 불량", f"{total_bad} 건", delta=total_bad, delta_color="inverse")
        kpi_c3.metric("현재 공정중(WIP)", f"{current_wip} 건")
        kpi_c4.metric("직행률(FTT)", f"{ftt_rate:.1f}%")
        
        st.divider()
        
        # 시각화 그래프
        chart_col1, chart_col2 = st.columns([3, 2])
        
        with chart_col1:
            st.subheader("📈 공정별 생산 완료 누적 실적")
            done_summary = report_df[report_df['상태'] == '완료'].groupby('라인').size().reset_index(name='수량')
            fig_bar = px.bar(done_summary, x='라인', y='수량', color='라인', text_auto=True)
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with chart_col2:
            st.subheader("🍰 모델별 생산 비중")
            model_summary = report_df.groupby('모델').size().reset_index(name='수량')
            fig_pie = px.pie(model_summary, values='수량', names='모델', hole=0.3)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        st.divider()
        st.subheader("📋 전체 생산 상세 로그 데이터")
        # 검색 기능 추가 (시리얼 번호 찾기용)
        search_sn = st.text_input("🔍 시리얼 번호로 검색")
        display_df = report_df.sort_values('시간', ascending=False)
        if search_sn:
            display_df = display_df[display_df['시리얼'].str.contains(search_sn)]
            
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("현재 분석할 생산 데이터가 존재하지 않습니다.")

# 수리 리포트 별도 분리
elif st.session_state.current_line == "수리 리포트":
    st.header("📈 불량 수리 이력 리포트")
    # 수리 내용이 기재된 데이터만 추출
    repair_db = st.session_state.production_db[st.session_state.production_db['수리'] != ""]
    
    if not repair_db.empty:
        st.write(f"총 {len(repair_db)}건의 수리 이력이 조회되었습니다.")
        st.dataframe(repair_db[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
        
        # CSV 다운로드 기능
        csv_data = repair_db.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 수리 리포트 다운로드 (CSV)", csv_data, "repair_report.csv", "text/csv")
    else:
        st.info("아직 등록된 수리 이력이 없습니다.")

# =================================================================
# 9. 마스터 관리 (Master Admin) 섹션 - 시스템 컨트롤
# =================================================================
elif st.session_state.current_line == "마스터 관리":
    st.header("🔐 시스템 마스터 관리 설정")
    
    # 2차 보안 인증 (마스터 전용)
    if not st.session_state.admin_authenticated:
        st.warning("⚠️ 관리자 권한 확인이 필요합니다.")
        with st.form("admin_verify"):
            admin_pw = st.text_input("마스터 비밀번호 입력", type="password")
            if st.form_submit_button("인증하기"):
                if admin_pw in ["admin1234", "master1234"]:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
    else:
        st.success("✅ 관리자 인증 완료")
        if st.button("🔓 관리자 세션 종료"):
            st.session_state.admin_authenticated = False
            st.rerun()
            
        st.divider()
        
        # (1) 사용자 계정 관리
        st.subheader("👤 시스템 사용자 계정 관리")
        with st.container(border=True):
            ua, ub, uc = st.columns([3, 3, 2])
            new_uid = ua.text_input("생성/수정 ID")
            new_upw = ub.text_input("비밀번호 설정")
            new_u_role = uc.selectbox("권한 등급", list(ROLES.keys()))
            
            if st.button("💾 계정 정보 저장/업데이트", use_container_width=True):
                if new_uid and new_upw:
                    st.session_state.user_db[new_uid] = {"pw": new_upw, "role": new_u_role}
                    st.success(f"[{new_uid}] 계정 설정이 완료되었습니다.")
                else:
                    st.error("ID와 비밀번호를 모두 입력해야 합니다.")
            
            with st.expander("현재 시스템 등록 계정 목록 확인"):
                st.table(pd.DataFrame.from_dict(st.session_state.user_db, orient='index'))
                
        st.divider()
        
        # (2) 기준 정보(모델/품목) 관리
        st.subheader("📋 공정 기준 정보 관리")
        m_c1, m_c2 = st.columns(2)
        
        with m_c1:
            st.write("**모델(Model) 관리**")
            new_model_name = st.text_input("신규 모델명 입력")
            if st.button("➕ 모델 등록"):
                if new_model_name and new_model_name not in st.session_state.master_models:
                    st.session_state.master_models.append(new_model_name)
                    st.session_state.master_items_dict[new_model_name] = []
                    st.success(f"모델 '{new_model_name}' 등록 완료")
                    st.rerun()
                    
        with m_c2:
            st.write("**품목코드(Item Code) 관리**")
            target_m = st.selectbox("품목을 추가할 모델 선택", st.session_state.master_models)
            new_item_code = st.text_input("신규 품목코드 입력")
            if st.button("➕ 품목 등록"):
                if new_item_code and new_item_code not in st.session_state.master_items_dict[target_m]:
                    st.session_state.master_items_dict[target_m].append(new_item_code)
                    st.success(f"품목 '{new_item_code}' 등록 완료")
                    st.rerun()
                    
        st.divider()
        
        # (3) 데이터 관리 및 초기화
        st.subheader("⚠️ 데이터 관리 및 초기화")
        col_db1, col_db2 = st.columns(2)
        
        with col_db1:
            st.info("모든 생산 데이터를 백업 파일로 다운로드합니다.")
            csv_backup = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 전체 DB 백업 다운로드 (CSV)", csv_backup, f"production_backup_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
            
        with col_db2:
            st.error("※ 주의: 초기화 버튼 클릭 시 구글 시트의 모든 데이터가 즉시 삭제됩니다.")
            if st.button("🚨 생산 DB 전체 초기화 실행"):
                # 빈 데이터프레임으로 덮어쓰기
                empty_db = pd.DataFrame(columns=['시간','라인','CELL','모델','품목코드','시리얼','상태','증상','수리','작업자'])
                st.session_state.production_db = empty_db
                save_to_gsheet(empty_db)
                st.warning("시스템이 초기화되었습니다. 페이지를 새로고침 하세요.")
                st.rerun()

# [마지막] 시스템 버전 정보 출력 (가독성을 위한 푸터)
st.sidebar.caption("Production Management System v15.9 (Full Edition)")
