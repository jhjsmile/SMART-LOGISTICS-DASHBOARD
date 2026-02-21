import streamlit as st
import pandas as pd
import datetime
import os
import csv
import re

# [1. 보안: 시스템 접근 인증] - 기존 로직 유지
if 'auth_done' not in st.session_state:
    st.session_state.auth_done = False

if not st.session_state.auth_done:
    st.title("🛡️ 시스템 접근 권한 확인")
    st.info("이 시스템은 허가된 사용자만 접속 가능합니다.")
    access_key = st.text_input("접근 인증키를 입력하세요 (기본: 7777)", type="password")
    if st.button("접속 승인"):
        if access_key == "7777":
            st.session_state.auth_done = True
            st.rerun()
        else:
            st.error("잘못된 인증키입니다. 접근 권한이 없습니다.")
    st.stop()

# [1. 유틸리티 함수] - 기존 로직 유지
def clean_serial(serial):
    kor_map = str.maketrans("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡ", "qwertyuiopasdfghjklzxcvbnm")
    s = str(serial).translate(kor_map).strip()
    s = re.sub(r'[^a-zA-Z0-9_-]', '', s)
    return s.upper()

def save_log_to_csv(serial_num, result_text):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    filename = f"scan_log_{date_str}.csv"
    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["날짜", "시간", "시리얼 번호", "결과"])
        writer.writerow([date_str, time_str, serial_num, result_text])

# [2. 세션 상태 관리] - 기존 로직 유지
if 'categories' not in st.session_state:
    st.session_state.categories = {}
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'failed_attempts' not in st.session_state:
    st.session_state.failed_attempts = 0
if 'admin_pass' not in st.session_state:
    st.session_state.admin_pass = "1234"

# [3. 웹 UI 레이아웃 설정]
st.set_page_config(page_title="SMART LOGISTICS WEB", layout="wide")

# --- [사이드바: 사용자님이 강조하신 기존 기능 100% 복구 및 유지] ---
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        new_data = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.session_state.categories = new_data
        st.success("데이터 로드 완료!")

    st.divider()

    if st.session_state.failed_attempts >= 5:
        st.error("🚫 보안 잠금: 관리자에게 문의하세요.")
    else:
        btn_label = "🔒 메뉴 잠금" if st.session_state.admin_mode else "⚙️ 관리자 설정"
        if st.button(btn_label):
            if st.session_state.admin_mode:
                st.session_state.admin_mode = False
                st.rerun()
            else:
                st.session_state.show_pw_input = True
        
        if getattr(st.session_state, 'show_pw_input', False) and not st.session_state.admin_mode:
            input_pw = st.text_input("비밀번호 입력", type="password")
            if st.button("확인"):
                if input_pw == st.session_state.admin_pass:
                    st.session_state.admin_mode = True
                    st.session_state.failed_attempts = 0
                    st.session_state.show_pw_input = False
                    st.rerun()
                else:
                    st.session_state.failed_attempts += 1
                    st.error(f"비번 오류 ({st.session_state.failed_attempts}/5)")

    if st.session_state.admin_mode:
        st.divider()
        st.subheader("🛠️ 관리자 도구")
        
        # 📂 항목 관리 (기존 유지)
        with st.expander("📝 항목 추가/삭제"):
            add_name = st.text_input("새 카테고리 이름")
            if st.button("➕ 추가"):
                if add_name and add_name.upper() not in st.session_state.categories:
                    st.session_state.categories[add_name.upper()] = {}
                    st.rerun()
            
            if st.session_state.categories:
                del_target = st.selectbox("삭제할 항목 선택", list(st.session_state.categories.keys()))
                if st.button("❌ 삭제"):
                    del st.session_state.categories[del_target]
                    st.rerun()

        # 🔢 시리얼 자동 생성 (기존 유지)
        with st.expander("🔢 시리얼 자동 생성"):
            if st.session_state.categories:
                gen_cat = st.selectbox("생성 대상 선택", list(st.session_state.categories.keys()))
                prefix = st.text_input("고유 문자(Prefix)")
                c1, c2 = st.columns(2)
                s_num = c1.number_input("시작", value=1)
                e_num = c2.number_input("끝", value=10)
                if st.button("🚀 생성 실행"):
                    for i in range(int(s_num), int(e_num) + 1):
                        sn = f"{prefix}{i:04d}"
                        st.session_state.categories[gen_cat][sn] = False
                    st.success("시리얼이 추가되었습니다.")
                    st.rerun()

        # 📥 데이터 내보내기 (기존 유지)
        with st.expander("📥 데이터 내보내기"):
            if st.session_state.categories:
                export_list = []
                for cat, items in st.session_state.categories.items():
                    for sn, status in items.items():
                        export_list.append({"항목": cat, "시리얼": sn, "상태": "완료" if status else "대기"})
                export_df = pd.DataFrame(export_list)
                csv_bytes = export_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(label="💾 CSV 다운로드", data=csv_bytes, 
                                 file_name=f"스캔현황_{datetime.datetime.now().strftime('%m%d_%H%M')}.csv",
                                 mime="text/csv", use_container_width=True)

        # 🔐 암호 설정 (기존 유지)
        with st.expander("🔐 비밀번호 변경"):
            new_pw = st.text_input("새 암호", type="password")
            if st.button("변경"):
                st.session_state.admin_pass = new_pw
                st.success("암호가 변경되었습니다.")

# --- [메인 화면: 4단계 공정 탭 추가] ---
st.title("📦 SMART LOGISTICS DASHBOARD")

# 기존 스캔 로직을 활용한 공정 처리 함수
def handle_scan_logic(scan_val, proc_name):
    if scan_val:
        clean_bc = clean_serial(scan_val)
        found = False
        for cat, items in st.session_state.categories.items():
            if clean_bc in items:
                found = True
                if not items[clean_bc]:
                    st.session_state.categories[cat][clean_bc] = True
                    save_log_to_csv(clean_bc, f"[{cat}] {proc_name} 성공")
                    st.success(f"✅ {clean_bc} : {proc_name} 처리 완료!")
                else:
                    st.warning(f"⚠️ {clean_bc} : 이미 완료된 시리얼입니다.")
        if not found:
            save_log_to_csv(clean_bc, f"미등록 시리얼 ({proc_name})")
            st.error(f"❌ 미등록 시리얼 감지: {clean_bc}")

# 4개 공정 탭 생성
tab1, tab2, tab3, tab4 = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])

with tab1:
    st.subheader("🚚 자재 입고 스캔")
    in_val = st.text_input("입고 바코드를 스캔하세요", key="tab_in")
    if st.button("입고 확인", key="btn_in"): handle_scan_logic(in_val, "자재 입고")

with tab2:
    st.subheader("🔧 조립 완료 스캔")
    job_val = st.text_input("조립 완료 바코드를 스캔하세요", key="tab_job")
    if st.button("조립 확인", key="btn_job"): handle_scan_logic(job_val, "조립 완료")

with tab3:
    st.subheader("📦 포장 단계 스캔")
    pkg_val = st.text_input("포장 바코드를 스캔하세요", key="tab_pkg")
    if st.button("포장 확인", key="btn_pkg"): handle_scan_logic(pkg_val, "포장 단계")

with tab4:
    st.subheader("⚠️ 불량 처리")
    fail_val = st.text_input("불량 발생 시리얼 스캔", key="tab_fail")
    fail_reason = st.selectbox("불량 사유", ["부품 파손", "조립 불량", "오염", "기타"])
    if st.button("불량 등록", key="btn_fail"):
        if fail_val:
            c_bc = clean_serial(fail_val)
            save_log_to_csv(c_bc, f"불량 발생 (사유: {fail_reason})")
            st.error(f"⚠️ {c_bc} 건이 불량 처리되었습니다.")

st.divider()

# --- [하단 대시보드 및 상세 표: 기존 기능 100% 유지] ---
if not st.session_state.categories:
    st.info("사이드바에서 CSV를 로드하거나 항목을 추가하세요.")
else:
    cats = list(st.session_state.categories.items())
    for i in range(0, len(cats), 3):
        cols = st.columns(3)
        for j, (name, bcs) in enumerate(cats[i:i+3]):
            with cols[j]:
                with st.container(border=True):
                    done = sum(bcs.values())
                    total = len(bcs)
                    st.subheader(f"📍 {name}")
                    st.progress(done/total if total > 0 else 0)
                    st.write(f"진행: {done} / {total}")
                    df_view = pd.DataFrame([{"시리얼": k, "상태": "✅" if v else "⏳"} for k, v in bcs.items()])
                    st.dataframe(df_view, use_container_width=True, hide_index=True, height=200)

if st.button("📋 오늘자 상세 로그 보기"):
    d_str = datetime.datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(f"scan_log_{d_str}.csv"):
        st.table(pd.read_csv(f"scan_log_{d_str}.csv").tail(10))

