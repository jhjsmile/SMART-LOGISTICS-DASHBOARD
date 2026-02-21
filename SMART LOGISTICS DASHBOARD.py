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

# [2. 유틸리티 함수 - 기존 로직 유지]
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

# [3. 세션 상태 관리 - 기존 데이터 구조 유지]
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

# 사이드바 (기존 기능 유지)
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.session_state.categories = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.success("데이터 로드 완료!")
    
    st.divider()
    if st.button("🔒 로그아웃/메뉴잠금"):
        st.session_state.admin_mode = False
        st.rerun()

# [5. 메인 화면: 공정별 탭 분리]
st.title("📦 SMART LOGISTICS DASHBOARD")

# 4개의 개별 공정 탭 생성
tab1, tab2, tab3, tab4 = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])

def process_scan(scan_input, proc_name):
    if scan_input:
        cleaned = clean_serial(scan_input)
        # 모든 카테고리에서 해당 시리얼 검색
        found = False
        for cat, items in st.session_state.categories.items():
            if cleaned in items:
                items[cleaned] = True
                save_log_to_csv(cleaned, proc_name, f"{proc_name} 완료")
                st.success(f"✅ [성공] {cleaned} : {proc_name} 처리되었습니다.")
                found = True
                break
        if not found:
            st.error(f"❌ [미등록] {cleaned} : 등록되지 않은 시리얼입니다.")

with tab1:
    st.subheader("🚚 자재 입고 스캔")
    in_scan = st.text_input("입고 시리얼 번호를 입력하세요", key="scan_in")
    if st.button("입고 처리", key="btn_in"):
        process_scan(in_scan, "자재 입고")

with tab2:
    st.subheader("🔧 조립 완료 스캔")
    job_scan = st.text_input("조립 완료 시리얼을 입력하세요", key="scan_job")
    if st.button("조립 확인", key="btn_job"):
        process_scan(job_scan, "조립 완료")

with tab3:
    st.subheader("📦 포장 단계 스캔")
    pkg_scan = st.text_input("포장 시리얼 번호를 입력하세요", key="scan_pkg")
    if st.button("포장 완료", key="btn_pkg"):
        process_scan(pkg_scan, "포장 단계")

with tab4:
    st.subheader("⚠️ 불량 처리")
    fail_scan = st.text_input("불량 발생 시리얼을 입력하세요", key="scan_fail")
    reason = st.selectbox("불량 사유", ["부품 파손", "조립 불량", "오염", "기타"])
    if st.button("불량 등록", key="btn_fail"):
        if fail_scan:
            cleaned = clean_serial(fail_scan)
            save_log_to_csv(cleaned, "불량 발생", f"사유: {reason}")
            st.warning(f"⚠️ {cleaned} 건이 불량으로 기록되었습니다.")

# [6. 실시간 현황 요약 (하단)]
st.divider()
st.subheader("📊 실시간 공정 현황")
if st.session_state.categories:
    cols = st.columns(len(st.session_state.categories))
    for i, (cat, items) in enumerate(st.session_state.categories.items()):
        total = len(items)
        done = sum(items.values())
        cols[i].metric(cat, f"{done}/{total}", f"{int(done/total*100) if total>0 else 0}%")
