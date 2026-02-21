import streamlit as st
import pandas as pd
import datetime
import os
import csv
import re

# [1. 보안: 시스템 접근 인증]
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
            st.error("잘못된 인증키입니다.")
    st.stop()

# [2. 유틸리티 함수]
def clean_serial(serial):
    kor_map = str.maketrans("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡ", "qwertyuiopasdfghjklzxcvbnm")
    s = str(serial).translate(kor_map).strip()
    s = re.sub(r'[^a-zA-Z0-9_-]', '', s)
    return s.upper()

def save_log_to_csv(serial_num, category, result_text):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    filename = f"scan_log_{date_str}.csv"
    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["날짜", "시간", "공정단계", "시리얼 번호", "결과"])
        writer.writerow([date_str, time_str, category, serial_num, result_text])

# [3. 세션 상태 관리]
if 'categories' not in st.session_state:
    st.session_state.categories = {}
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'failed_attempts' not in st.session_state:
    st.session_state.failed_attempts = 0
if 'admin_pass' not in st.session_state:
    st.session_state.admin_pass = "1234"

# [4. UI 레이아웃]
st.set_page_config(page_title="SMART LOGISTICS WEB", layout="wide")

# --- [왼쪽 사이드바 메뉴: 완전 복구] ---
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    
    # CSV 로드 기능
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.session_state.categories = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.success("데이터 로드 완료!")
    
    st.divider()

    # 관리자 인증 로직
    if st.session_state.failed_attempts < 5:
        if not st.session_state.admin_mode:
            st.subheader("🔒 관리자 로그인")
            admin_pw = st.text_input("관리자 비밀번호", type="password", key="admin_login_pw")
            if st.button("로그인"):
                if admin_pw == st.session_state.admin_pass:
                    st.session_state.admin_mode = True
                    st.session_state.failed_attempts = 0
                    st.rerun()
                else:
                    st.session_state.failed_attempts += 1
                    st.error(f"비번 오류 ({st.session_state.failed_attempts}/5)")
        else:
            st.success("🔓 관리자 모드 활성화")
            if st.button("로그아웃"):
                st.session_state.admin_mode = False
                st.rerun()
            
            st.divider()
            # 관리자 전용 도구 (데이터 내보내기 등)
            with st.expander("📥 데이터 내보내기"):
                if st.session_state.categories:
                    export_list = []
                    for cat, items in st.session_state.categories.items():
                        for sn, status in items.items():
                            export_list.append({"항목": cat, "시리얼": sn, "상태": "완료" if status else "대기"})
                    csv_bytes = pd.DataFrame(export_list).to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button("💾 CSV 다운로드", data=csv_bytes, file_name="inventory_status.csv")

# --- [메인 화면: 4단계 공정] ---
st.title("📦 SMART LOGISTICS DASHBOARD")

tab1, tab2, tab3, tab4 = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])

def process_scan(scan_input, proc_name):
    if scan_input:
        cleaned = clean_serial(scan_input)
        found = False
        for cat, items in st.session_state.categories.items():
            if cleaned in items:
                items[cleaned] = True
                save_log_to_csv(cleaned, proc_name, f"{proc_name} 완료")
                st.success(f"✅ [성공] {cleaned} : {proc_name} 처리")
                found = True
                break
        if not found:
            st.error(f"❌ [미등록] {cleaned} : 시리얼을 찾을 수 없습니다.")

with tab1:
    st.subheader("🚚 자재 입고")
    in_scan = st.text_input("입고 스캔", key="in")
    if st.button("입고 완료", key="b_in"): process_scan(in_scan, "자재 입고")

with tab2:
    st.subheader("🔧 조립 완료")
    job_scan = st.text_input("조립 스캔", key="job")
    if st.button("조립 완료 확인", key="b_job"): process_scan(job_scan, "조립 완료")

with tab3:
    st.subheader("📦 포장 단계")
    pkg_scan = st.text_input("포장 스캔", key="pkg")
    if st.button("포장 완료 확인", key="b_pkg"): process_scan(pkg_scan, "포장 단계")

with tab4:
    st.subheader("⚠️ 불량 처리")
    f_scan = st.text_input("불량 시리얼 스캔", key="fail")
    f_reason = st.selectbox("사유", ["파손", "조립불량", "기타"])
    if st.button("불량 등록", key="b_fail"):
        if f_scan:
            c = clean_serial(f_scan)
            save_log_to_csv(c, "불량", f"사유: {f_reason}")
            st.warning(f"⚠️ {c} 불량 처리됨")

# 실시간 요약 현황
st.divider()
if st.session_state.categories:
    cols = st.columns(len(st.session_state.categories))
    for i, (cat, items) in enumerate(st.session_state.categories.items()):
        total = len(items)
        done = sum(items.values())
        cols[i].metric(cat, f"{done}/{total}", f"{int(done/total*100) if total>0 else 0}%")
