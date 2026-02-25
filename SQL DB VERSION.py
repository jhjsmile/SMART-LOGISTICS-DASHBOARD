import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from streamlit_gsheets import GSheetsConnection
import io
from streamlit_autorefresh import st_autorefresh
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =================================================================
# 1. 시스템 전역 설정 및 연결 (중복 제거 완료)
# =================================================================
st.set_page_config(page_title="생산 통합 관리 시스템 SQL TEST", layout="wide")
KST = timezone(timedelta(hours=9))

# [중요] 새로고침은 파일 상단에 한 번만 선언 (key 충돌 방지)
st_autorefresh(interval=30000, key="pms_auto_refresh_final")

# 구글 시트 연결 객체 (하나로 통일)
conn = st.connection("gsheets", type=GSheetsConnection)

# 사용자 권한 정의
ROLES = {
    "master": ["조립 라인", "검사 라인", "포장 라인", "리포트", "불량 공정", "수리 리포트", "마스터 관리"],
    "control_tower": ["리포트", "수리 리포트", "마스터 관리"],
    "assembly_team": ["조립 라인"],
    "qc_team": ["검사 라인", "불량 공정", "수리 리포트"],
    "packing_team": ["포장 라인"]
}

# =================================================================
# 2. 핵심 유틸리티 및 데이터 로드 함수
# =================================================================

def get_now_kst_str():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

def load_test_logs():
    try:
        # 통합된 시트 파일 내의 'sql_logs_test' 탭을 읽음
        df = conn.read(worksheet="sql_logs_test", ttl=0).fillna("")
        if '시리얼' in df.columns:
            df['시리얼'] = df['시리얼'].astype(str).str.replace(r'\.0$', '', regex=True)
        return df
    except:
        return pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])

def load_test_accounts():
    default_acc = {"master": {"pw": "master1234", "role": "master"}}
    try:
        df = conn.read(worksheet="sql_accounts_test", ttl=0)
        if df is None or df.empty: return default_acc
        
        acc_dict = {}
        for _, row in df.iterrows():
            uid = str(row['id']).strip() if pd.notna(row['id']) else ""
            if uid:
                # [수정 포인트] 비밀번호가 숫자일 경우 소수점(.0)을 강제로 제거합니다.
                raw_pw = str(row['pw']).strip() if pd.notna(row['pw']) else ""
                if raw_pw.endswith('.0'):
                    raw_pw = raw_pw[:-2]
                
                acc_dict[uid] = {
                    "pw": raw_pw,
                    "role": str(row['role']).strip() if pd.notna(row['role']) else "user"
                }
        return acc_dict if acc_dict else default_acc
    except:
        return default_acc

def push_to_cloud(df):
    try:
        conn.update(worksheet="sql_logs_test", data=df)
        st.success("✅ 클라우드 데이터 동기화 완료")
        st.session_state.production_db = df
    except Exception as e:
        st.error(f"저장 오류: {e}")

# =================================================================
# 3. 세션 상태 관리
# =================================================================
if 'user_db' not in st.session_state:
    st.session_state.user_db = load_test_accounts()

if 'production_db' not in st.session_state:
    st.session_state.production_db = load_test_logs()

if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'admin_authenticated' not in st.session_state: st.session_state.admin_authenticated = False
if 'current_line' not in st.session_state: st.session_state.current_line = "조립 라인"
if 'selected_cell' not in st.session_state: st.session_state.selected_cell = "CELL 1"

# [디버깅 정보]
with st.expander("🔍 시스템 연결 디버깅"):
    st.write("현재 접속 계정 DB:", st.session_state.user_db)
    st.write("연결 탭: sql_accounts_test / sql_logs_test")

if 'master_models' not in st.session_state:
    st.session_state.master_models = ["EPS7150", "EPS7133", "T20i", "T20C"]

if 'master_items_dict' not in st.session_state:
    st.session_state.master_items_dict = {
        "EPS7150": ["7150-A", "7150-B"],
        "EPS7133": ["7133-S", "7133-Standard"],
        "T20i": ["T20i-P", "T20i-Premium"],
        "T20C": ["T20C-S", "T20C-Standard"]
    }

# =================================================================
# 4. 로그인 및 인터페이스 (중복 제거 및 UI 유지)
# =================================================================
# [CSS 스타일 생략 - 기존 스타일 유지]
st.markdown("""<style>...</style>""", unsafe_allow_html=True) # 기존 CSS 코드를 여기에 넣으세요

if not st.session_state.login_status:
    _, center_l, _ = st.columns([1, 1.2, 1])
    with center_l:
        st.title("🔐 통합 관리 시스템")
        with st.form("login_form"):
            input_id = st.text_input("아이디(ID)")
            input_pw = st.text_input("비밀번호(PW)", type="password")
            if st.form_submit_button("접속 시작"):
                db = st.session_state.user_db
                if input_id in db and db[input_id]["pw"] == input_pw:
                    st.session_state.login_status = True
                    st.session_state.user_id = input_id
                    st.session_state.user_role = db[input_id]["role"]
                    st.session_state.current_line = ROLES[st.session_state.user_role][0]
                    st.rerun()
                else:
                    st.error("❌ 아이디 또는 비밀번호가 틀립니다.")
    st.stop()

# [이후 페이지 렌더링 로직(조립, 검사, 리포트 등)은 기존 v17.8 코드 유지]
# ... (기존에 작성하신 draw_v17_optimized_log 함수 및 각 페이지 if문 코드를 이어서 붙여넣으세요)

# =================================================================
# 5. 핵심 비즈니스 로직 및 컴포넌트 (Core Logic)
# =================================================================

@st.dialog("📋 공정 단계 전환 입고 확인")
def trigger_entry_dialog():
    """
    제품이 다음 공정으로 이동할 때 호출되는 팝업입니다.
    기존 행을 업데이트하여 1인 1행 데이터 무결성을 유지합니다.
    """
    st.warning(f"승인 대상 S/N: [ {st.session_state.confirm_target} ]")
    st.markdown(f"이동 공정: **{st.session_state.current_line}**")
    st.write("---")
    
    c_ok, c_no = st.columns(2)
    if c_ok.button("✅ 입고 승인", type="primary", use_container_width=True):
        db_full = st.session_state.production_db
        # 시리얼 번호를 고유 키로 행 검색
        idx_match = db_full[db_full['시리얼'] == st.session_state.confirm_target].index
        if not idx_match.empty:
            idx = idx_match[0]
            db_full.at[idx, '시간'] = get_now_kst_str()
            db_full.at[idx, '라인'] = st.session_state.current_line
            db_full.at[idx, '상태'] = '진행 중'
            db_full.at[idx, '작업자'] = st.session_state.user_id
            push_to_cloud(db_full)
            
        st.session_state.confirm_target = None
        st.success("공정 입고 처리가 완료되었습니다."); st.rerun()
        
    if c_no.button("❌ 취소", use_container_width=True): 
        st.session_state.confirm_target = None
        st.rerun()

def draw_v17_optimized_log(line_key, ok_btn_txt="완료 처리"):
    """
    [v17.7 UI 최적화 반영] 
    1. '공정구분' -> '작업구분(CELL)'으로 명칭 변경
    2. 컬럼 비율 [2.2, 1, 1.5, 1.5, 1.8, 4] 조정하여 버튼 공간 확보
    """
    st.divider()
    st.markdown(f"<h3 class='centered-title'>📝 {line_key} 실시간 작업 원장</h3>", unsafe_allow_html=True)
    db_source = st.session_state.production_db
    f_df = db_source[db_source['라인'] == line_key]
    
    # 조립 라인은 선택된 CELL별로 필터링
    if line_key == "조립 라인" and st.session_state.selected_cell != "전체 CELL": 
        f_df = f_df[f_df['CELL'] == st.session_state.selected_cell]
    
    if f_df.empty: 
        st.info("현재 해당 공정에 할당된 제품 데이터가 없습니다.")
        return
    
    # [UI 패치] 헤더 컬럼 비율 및 명칭 최적화
    h_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
    header_labels = ["기록 시간", "작업구분(CELL)", "생산모델", "품목코드", "S/N 시리얼", "현장 제어"]
    for col, txt in zip(h_row, header_labels): 
        col.write(f"**{txt}**")
    
    for idx, row in f_df.sort_values('시간', ascending=False).iterrows():
        r_row = st.columns([2.2, 1, 1.5, 1.5, 1.8, 4])
        r_row[0].write(row['시간'])
        # 무의미한 점(dot) 대신 실제 CELL 정보를 표시하여 출처를 명확히 함
        r_row[1].write(row['CELL'] if row['CELL'] != "-" else "N/A")
        r_row[2].write(row['모델'])
        r_row[3].write(row['품목코드'])
        r_row[4].write(f"`{row['시리얼']}`")
        
        with r_row[5]:
            if row['상태'] in ["진행 중", "수리 완료(재투입)"]:
                b_grid1, b_grid2 = st.columns(2)
                if b_grid1.button(ok_btn_txt, key=f"ok_idx_{idx}", type="secondary"):
                    db_source.at[idx, '상태'] = "완료"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
                if b_grid2.button("🚫불량", key=f"ng_idx_{idx}"):
                    db_source.at[idx, '상태'] = "불량 처리 중"
                    db_source.at[idx, '작업자'] = st.session_state.user_id
                    push_to_cloud(db_source); st.rerun()
            elif row['상태'] == "불량 처리 중":
                st.markdown("<span class='status-red'>🔴 품질 이슈 분석 대기</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-green'>🟢 공정 정상 완료됨</span>", unsafe_allow_html=True)

# =================================================================
# 6. 각 페이지별 렌더링 (Page Views)
# =================================================================

# --- 6-1. 조립 라인 현황 ---
if st.session_state.current_line == "조립 라인":
    st.markdown("<h2 class='centered-title'>📦 신규 조립 생산 라인 현황</h2>", unsafe_allow_html=True)
    
    # CELL(작업대) 선택 시스템 (v9.1 스타일 고정)
    stations = ["전체 CELL", "CELL 1", "CELL 2", "CELL 3", "CELL 4", "CELL 5", "CELL 6"]
    station_cols = st.columns(len(stations))
    for i, name in enumerate(stations):
        if station_cols[i].button(name, type="primary" if st.session_state.selected_cell == name else "secondary"): 
            st.session_state.selected_cell = name; st.rerun()
            
    if st.session_state.selected_cell != "전체 CELL":
        with st.container(border=True):
            st.markdown(f"#### ➕ {st.session_state.selected_cell} 신규 생산 등록")
            target_model = st.selectbox("투입 모델 선택", ["선택하세요."] + st.session_state.master_models, key=f"am_{st.session_state.selected_cell}")
            with st.form("assembly_entry_gate"):
                fc1, fc2 = st.columns(2)
                target_item = fc1.selectbox("세부 품목 코드", st.session_state.master_items_dict.get(target_model, []) if target_model!="선택하세요." else ["모델 선택 대기"])
                target_sn = fc2.text_input("제품 시리얼(S/N) 입력")
                
                if st.form_submit_button("▶️ 생산 시작 등록", use_container_width=True, type="primary"):
                    if target_model != "선택하세요." and target_sn:
                        full_db = st.session_state.production_db
                        # [규칙] 시리얼 중복 등록 방지 로직 (데이터 무결성)
                        if target_sn in full_db['시리얼'].values:
                            st.error(f"❌ 중복 오류: 시리얼 '{target_sn}'은 이미 등록되어 있는 번호입니다.")
                        else:
                            new_entry = {
                                '시간': get_now_kst_str(), '라인': "조립 라인", 'CELL': st.session_state.selected_cell, 
                                '모델': target_model, '품목코드': target_item, '시리얼': target_sn, '상태': '진행 중', 
                                '증상': '', '수리': '', '작업자': st.session_state.user_id
                            }
                            st.session_state.production_db = pd.concat([full_db, pd.DataFrame([new_entry])], ignore_index=True)
                            push_to_cloud(st.session_state.production_db); st.rerun()
    
    draw_v17_optimized_log("조립 라인", "조립 완료")

# --- 6-2. 품질 / 포장 라인 현황 ---
elif st.session_state.current_line in ["검사 라인", "포장 라인"]:
    pg_title_txt = "🔍 품질 검사 공정 현황" if st.session_state.current_line == "검사 라인" else "🚚 출하 포장 현황"
    pv_line_name = "조립 라인" if st.session_state.current_line == "검사 라인" else "검사 라인"
    st.markdown(f"<h2 class='centered-title'>{pg_title_txt}</h2>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("<div class='section-title'>📥 이전 공정 완료 물량 (입고 승인 대기)</div>", unsafe_allow_html=True)
        db_raw_ref = st.session_state.production_db
        # 이전 단계 '완료' 항목 중 현재 단계에 들어오지 않은 데이터 필터링
        wait_list_df = db_raw_ref[(db_raw_ref['라인'] == pv_line_name) & (db_raw_ref['상태'] == "완료")]
        
        if not wait_list_df.empty:
            st.success(f"현재 총 {len(wait_list_df)}개의 제품이 입고 승인을 기다리고 있습니다.")
            wait_grid = st.columns(4)
            for i, (idx, row) in enumerate(wait_list_df.iterrows()):
                if wait_grid[i % 4].button(f"입고: {row['시리얼']}", key=f"wait_in_{row['시리얼']}", use_container_width=True):
                    st.session_state.confirm_target = row['시리얼']
                    st.session_state.confirm_model = row['모델']
                    st.session_state.confirm_item = row['품목코드']
                    trigger_entry_dialog()
        else: 
            st.info("입고 가능한 대기 물량이 없습니다. 공정 상류 흐름을 확인하세요.")
            
    draw_v17_optimized_log(st.session_state.current_line, "합격 처리" if st.session_state.current_line=="검사 라인" else "포장 완료")

# --- 6-3. 통합 리포트 (디자인 최적화 버전) ---
elif st.session_state.current_line == "리포트":
    st.markdown("<h2 class='centered-title'>📊 생산 운영 통합 모니터링</h2>", unsafe_allow_html=True)
    db_rep_source = st.session_state.production_db
    
    if not db_rep_source.empty:
        # 주요 운영 KPI 지표 산출
        q_tot = len(db_rep_source)
        q_fin = len(db_rep_source[(db_rep_source['라인'] == '포장 라인') & (db_rep_source['상태'] == '완료')])
        q_wip = len(db_rep_source[db_rep_source['상태'] == '진행 중'])
        q_bad = len(db_rep_source[db_rep_source['상태'].str.contains("불량", na=False)])
        
        m_row_cols = st.columns(4)
        m_row_cols[0].metric("누적 총 투입", f"{q_tot} EA")
        m_row_cols[1].metric("최종 생산 실적", f"{q_fin} EA")
        m_row_cols[2].metric("현재 공정 재공(WIP)", f"{q_wip} EA")
        m_row_cols[3].metric("품질 이슈 발생", f"{q_bad} 건", delta=q_bad, delta_color="inverse")
        
        st.divider()
        # [차트 레이아웃] 막대 그래프 넓게(1.8), 도넛 차트 축소(1.2) - v17.0 설정 적용
        chart_l, chart_r = st.columns([1.8, 1.2])
        
        with chart_l:
            # 1) 공정 단계별 분포 차트 (정수 표기 dtick=1 고정 및 격자선)
            pos_sum_df = db_rep_source.groupby('라인').size().reset_index(name='수량')
            fig_bar_main = px.bar(
                pos_sum_df, x='라인', y='수량', color='라인', 
                title="<b>[공정 단계별 제품 분포 현황]</b>",
                color_discrete_map={"검사 라인": "#A0D1FB", "조립 라인": "#0068C9", "포장 라인": "#FFABAB"},
                template="plotly_white"
            )
            fig_bar_main.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            # [핵심] Y축 눈금을 정수(1, 2, 3...) 단위로 강제 고정
            fig_bar_main.update_yaxes(dtick=1, rangemode='tozero', showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_bar_main, use_container_width=True)
            
        with chart_r:
            # 2) 모델 비중 도넛 차트 (물리적 크기 축소 350px)
            mod_sum_df = db_rep_source.groupby('모델').size().reset_index(name='수량')
            fig_pie_main = px.pie(mod_sum_df, values='수량', names='모델', hole=0.5, title="<b>[생산 모델별 비중]</b>")
            fig_pie_main.update_layout(height=350, margin=dict(l=30, r=30, t=60, b=30))
            st.plotly_chart(fig_pie_main, use_container_width=True)
        
        st.markdown("<div class='section-title'>📋 실시간 통합 생산 관리 원장 (Ledger)</div>", unsafe_allow_html=True)
        st.dataframe(db_rep_source.sort_values('시간', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.warning("분석할 생산 데이터가 아직 존재하지 않습니다.")

# --- 6-4. 불량 수리 센터 [v17.5 판독 강화 + v17.1 레이아웃] ---
elif st.session_state.current_line == "불량 공정":
    st.markdown("<h2 class='centered-title'>🛠️ 불량 분석 및 수리 조치 관리</h2>", unsafe_allow_html=True)
    db_bad_target = st.session_state.production_db
    wait_list = db_bad_target[db_bad_target['상태'] == "불량 처리 중"]
    
    # [v17.5 판독 엔진] 금일 조치 완료 카운트 (데이터 시점 문제 해결)
    today_dt = datetime.now(KST).date()
    def check_today_match(v):
        try: return pd.to_datetime(v).date() == today_dt
        except: return False

    rep_done_today = len(db_bad_target[(db_bad_target['상태'] == "수리 완료(재투입)") & (db_bad_target['시간'].apply(check_today_match))])
    
    # 상단 수리 현황 KPI
    stat1, stat2 = st.columns(2)
    with stat1: 
        st.markdown(f"<div class='stat-box'><div class='stat-label'>🛠️ 분석 대기 건수</div><div class='stat-value' style='color:#fa5252;'>{len(wait_list)}</div></div>", unsafe_allow_html=True)
    with stat2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>✅ 금일 조치 완료</div><div class='stat-value' style='color:#40c057;'>{rep_done_today}</div></div>", unsafe_allow_html=True)

    if wait_list.empty: 
        st.success("✅ 조치가 필요한 품질 이슈 사항이 없습니다.")
    else:
        # 불량 품목별 조치 카드 생성
        for idx, row in wait_list.iterrows():
            with st.container(border=True):
                st.markdown(f"**이슈 시리얼: `{row['시리얼']}`** (모델: {row['모델']} / 발생공정: {row['라인']})")
                
                # [v17.1 개편 레이아웃] 1행: 입력 필드
                r1c1, r1c2 = st.columns(2)
                v_cause = r1c1.text_input("⚠️ 불량 원인 분석", placeholder="원인 상세 입력", key=f"rc_{idx}")
                v_action = r1c2.text_input("🛠️ 수리 조치 사항", placeholder="조치 내용 입력", key=f"ra_{idx}")
                
                # [v17.1 개편 레이아웃] 2행: 이미지 및 버튼 (정렬 보정)
                r2c1, r2c2 = st.columns([3, 1])
                v_img_f = r2c1.file_uploader("📸 증빙 사진 등록", type=['jpg','png','jpeg'], key=f"ri_{idx}")
                
                r2c2.markdown("<div class='button-spacer'></div>", unsafe_allow_html=True)
                if r2c2.button("✅ 수리 확정", key=f"rb_{idx}", type="primary", use_container_width=True):
                    if v_cause and v_action:
                        web_url = ""
                        if v_img_f:
                            with st.spinner("이미지 업로드 중..."):
                                res_url = upload_img_to_drive(v_img_f, row['시리얼'])
                                if "http" in res_url: web_url = f" [사진 확인: {res_url}]"
                        
                        # 상태 업데이트 (수리 완료 및 시간 갱신)
                        db_bad_target.at[idx, '상태'] = "수리 완료(재투입)"
                        db_bad_target.at[idx, '시간'] = get_now_kst_str() 
                        db_bad_target.at[idx, '증상'], db_bad_target.at[idx, '수리'] = v_cause, v_action + web_url
                        db_bad_target.at[idx, '작업자'] = st.session_state.user_id
                        push_to_cloud(db_bad_target); st.rerun()
                    else:
                        st.error("필수 항목(원인 및 조치내용)을 채워주세요.")

# --- 6-5. 수리 이력 리포트 ---
elif st.session_state.current_line == "수리 리포트":
    st.markdown("<h2 class='centered-title'>📈 품질 분석 및 수리 이력 리포트</h2>", unsafe_allow_html=True)
    db_hist_ledger = st.session_state.production_db
    hist_df = db_hist_ledger[db_hist_ledger['수리'] != ""]
    
    if not hist_df.empty:
        # 리포트 차트 (1.8 : 1.2 비율 적용)
        hl_c, hr_c = st.columns([1.8, 1.2])
        with hl_c:
            fig_h_bar = px.bar(hist_df.groupby('라인').size().reset_index(name='수량'), x='라인', y='수량', title="공정별 이슈 빈도", template="plotly_white")
            fig_h_bar.update_yaxes(dtick=1, showgrid=True, gridcolor='rgba(200,200,200,0.3)')
            st.plotly_chart(fig_h_bar, use_container_width=True)
        with hr_c:
            fig_h_pie = px.pie(hist_df.groupby('모델').size().reset_index(name='수량'), values='수량', names='모델', hole=0.4, title="모델별 불량 비중")
            fig_h_pie.update_layout(height=350)
            st.plotly_chart(fig_h_pie, use_container_width=True)
            
        st.markdown("<div class='section-title'>📜 상세 불량 수리 조치 데이터 원본</div>", unsafe_allow_html=True)
        st.dataframe(hist_df[['시간', '라인', '모델', '시리얼', '증상', '수리', '작업자']], use_container_width=True, hide_index=True)
    else:
        st.info("현재까지 기록된 품질 이슈 내역이 없습니다.")

# --- 6-6. 마스터 정보 관리 (어드민) ---
elif st.session_state.current_line == "마스터 관리":
    st.markdown("<h2 class='centered-title'>🔐 시스템 마스터 데이터 관리</h2>", unsafe_allow_html=True)
    
    # 관리자 보안 인증
    if not st.session_state.admin_authenticated:
        with st.form("master_verify_gate"):
            m_pw_in = st.text_input("마스터 비밀번호 입력", type="password")
            if st.form_submit_button("권한 인증"):
                if m_pw_in == "master1234":
                    st.session_state.admin_authenticated = True; st.rerun()
                else: st.error("❌ 비밀번호 불일치: 접근이 거부되었습니다.")
    else:
        # 인증 성공 시 도구 노출
        if st.sidebar.button("🔓 관리자 세션 잠금(Lock)", use_container_width=True):
            st.session_state.admin_authenticated = False; handle_nav("조립 라인")

        # 섹션 1: 기준정보 관리
        st.markdown("<div class='section-title'>📋 생산 기준정보 및 마스터 데이터 설정</div>", unsafe_allow_html=True)
        m_col_1, m_col_2 = st.columns(2)
        
        with m_col_1:
            with st.container(border=True):
                st.subheader("모델/품목 신규 등록")
                add_m = st.text_input("신규 모델명")
                if st.button("모델 등록 확정", use_container_width=True):
                    if add_m and add_m not in st.session_state.master_models:
                        st.session_state.master_models.append(add_m)
                        st.session_state.master_items_dict[add_m] = []; st.rerun()
                st.divider()
                add_i_m = st.selectbox("품목용 모델 선택", st.session_state.master_models)
                add_i = st.text_input("신규 품목코드")
                if st.button("품목 등록 확정", use_container_width=True):
                    if add_i and add_i not in st.session_state.master_items_dict[add_i_m]:
                        st.session_state.master_items_dict[add_i_m].append(add_i); st.rerun()

        with m_col_2:
            with st.container(border=True):
                st.subheader("데이터 백업 및 마이그레이션")
                # CSV 백업 다운로드
                raw_ledger_csv = st.session_state.production_db.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 전체 실적 CSV 백업", raw_ledger_csv, f"PMS_Export_{datetime.now(KST).strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
                st.divider()
                # 백업 데이터 복구 로드
                f_mig_in = st.file_uploader("복구용 CSV 선택", type="csv")
                if f_mig_in and st.button("📤 실적 데이터 로드 실행", use_container_width=True):
                    try:
                        imp_df = pd.read_csv(f_mig_in)
                        combined_ledger = pd.concat([st.session_state.production_db, imp_df], ignore_index=True)
                        # 중복 시리얼 번호는 최신 실적만 남기고 정제
                        st.session_state.production_db = combined_ledger.drop_duplicates(subset=['시리얼'], keep='last')
                        push_to_cloud(st.session_state.production_db); st.rerun()
                    except: st.error("파일 구조 오류: 유효한 PMS 데이터 형식이 아닙니다.")

        # 섹션 2: 계정 관리 (수정본)
        st.divider()
        st.markdown("<div class='section-title'>👤 사용자 계정 및 시스템 보안 관리</div>", unsafe_allow_html=True)
        u_c1, u_c2, u_c3 = st.columns([3, 3, 2])
        r_uid = u_c1.text_input("ID 생성")
        r_upw = u_c2.text_input("PW 설정", type="password")
        
        # 권한 부여 항목을 ROLES 설정값에 맞게 선택박스로 구현
        r_url = u_c3.selectbox("권한 부여", list(ROLES.keys())) 
        
        if st.button("사용자 정보 업데이트 및 구글 시트 저장", use_container_width=True):
            if r_uid and r_upw:
                # 1. 메모리 업데이트
                st.session_state.user_db[r_uid] = {"pw": r_upw, "role": r_url}
                
                # 2. 구글 시트 업데이트용 데이터 준비
                acc_df = pd.DataFrame.from_dict(st.session_state.user_db, orient='index').reset_index()
                acc_df.columns = ['id', 'pw', 'role']
                
                try:
                    # 'accounts' 워크시트에 덮어쓰기 저장
                    conn.update(worksheet="sql_accounts_test", data=acc_df)
                    st.success(f"사용자 '{r_uid}' 계정이 구글 시트에 영구 저장되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"시트 저장 실패: {e}. 구글 시트에 'accounts' 탭이 있는지 확인하세요.")
            else:
                st.warning("ID와 PW를 입력해주세요.")
        
        with st.expander("현재 시스템 등록 계정 전체 리스트 확인"):
            if st.session_state.user_db:
                display_acc_df = pd.DataFrame.from_dict(st.session_state.user_db, orient='index').reset_index()
                display_acc_df.columns = ['아이디(ID)', '비밀번호(PW)', '권한역할']
                st.table(display_acc_df)

        st.divider()
        # [데이터 영구 초기화]
        if st.button("⚠️ 시스템 전체 실적 데이터 영구 삭제(초기화)", type="secondary", use_container_width=True):
            st.session_state.production_db = pd.DataFrame(columns=['시간', '라인', 'CELL', '모델', '품목코드', '시리얼', '상태', '증상', '수리', '작업자'])
            push_to_cloud(st.session_state.production_db); st.rerun()

# =================================================================
# [ PMS v17.8 최종 소스코드 종료 ]
# =================================================================



