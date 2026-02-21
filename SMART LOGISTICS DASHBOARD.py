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
    access_key = st.text_input("접근 인증키를 입력하세요 (기본: 7777)", type="password")
    if st.button("접속 승인"):
        if access_key == "7777":
            st.session_state.auth_done = True
            st.rerun()
        else:
            st.error("잘못된 인증키입니다.")
    st.stop()

# [2. 유틸리티 함수] - 기존 로직 유지
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

# [3. 세션 상태 관리] - 기존 로직 유지
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

# --- [사이드바: 사용자님이 쓰시던 기존 기능 100% 복구] ---
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    
    # CSV 데이터 로드
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.session_state.categories = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.success("데이터 로드 완료!")
    
    st.divider()

    # 관리자 로그인 및 항목 관리 (기존 방식 그대로)
    if not st.session_state.admin_mode:
        if st.session_state.failed_attempts < 5:
            st.subheader("🔒 관리자 로그인")
            admin_pw = st.text_input("관리자 비밀번호", type="password")
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
        if st.button("🔒 로그아웃"):
            st.session_state.admin_mode = False
            st.rerun()
        
        st.divider()
        st.subheader("🛠️ 항목 및 시리얼 관리")
        
        # 항목 추가
        new_cat = st.text_input("새 항목 추가 (예: TV)")
        if st.button("항목 생성"):
            if new_cat:
                st.session_state.categories[new_cat] = {}
                st.rerun()
        
        # 항목 삭제 및 시리얼 추가
        if st.session_state.categories:
            selected_cat = st.selectbox("항목 선택", list(st.session_state.categories.keys()))
            if st.button("선택 항목 삭제"):
                del st.session_state.categories[selected_cat]
                st.rerun()
            
            new_sn = st.text_input(f"[{selected_cat}] 시리얼 수동 추가")
            if st.button("시리얼 추가"):
                if new_sn:
                    st.session_state.categories[selected_cat][new_sn.strip()] = False
                    st.rerun()

        st.divider()
        with st.expander("📥 데이터 내보내기"):
            if st.session_state.categories:
                export_data = []
                for cat, items in st.session_state.categories.items():
                    for sn, status in items.items():
                        export_data.append({"항목": cat, "시리얼": sn, "상태": "완료" if status else "대기"})
                csv_bytes = pd.DataFrame(export_data).to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("💾 CSV 다운로드", csv_bytes, "status.csv")

# --- [메인 화면: 공정별 탭 적용] ---
st.title("📦 SMART LOGISTICS DASHBOARD")

tab1, tab2, tab3, tab4 = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])

def handle_scan(scan_val, step_name):
    if scan_val:
        cleaned = clean_serial(scan_val)
        found = False
        for cat, items in st.session_state.categories.items():
            if cleaned in items:
                items[cleaned] = True
                save_log_to_csv(cleaned, step_name, f"{step_name} 완료")
                st.success(f"✅ {cleaned} : {step_name} 처리 성공!")
                found = True
                break
        if not found:
            st.error(f"❌ {cleaned} : 등록되지 않은 시리얼입니다.")

with tab1:
    st.subheader("🚚 자재 입고")
    in_v = st.text_input("입고 바코드 스캔", key="in_v")
    if st.button("입고 완료", key="in_b"): handle_scan(in_v, "자재 입고")

with tab2:
    st.subheader("🔧 조립 완료")
    job_v = st.text_input("조립 바코드 스캔", key="job_v")
    if st.button("조립 완료", key="job_b"): handle_scan(job_v, "조립 완료")

with tab3:
    st.subheader("📦 포장 단계")
    pkg_v = st.text_input("포장 바코드 스캔", key="pkg_v")
    if st.button("포장 완료", key="pkg_b"): handle_scan(pkg_v, "포장 단계")

with tab4:
    st.subheader("⚠️ 불량 처리")
    fail_v = st.text_input("불량 시리얼 스캔", key="fail_v")
    reason = st.selectbox("불량 사유", ["파손", "기타"], key="fail_r")
    if st.button("불량 등록", key="fail_b"):
        if fail_v:
            c = clean_serial(fail_v)
            save_log_to_csv(c, "불량", f"사유: {reason}")
            st.warning(f"⚠️ {c} 불량 처리 완료")

# 하단 현황판 (기존 로직 유지)
st.divider()
if st.session_state.categories:
    cols = st.columns(len(st.session_state.categories))
    for i, (cat, items) in enumerate(st.session_state.categories.items()):
        total, done = len(items), sum(items.values())
        cols[i].metric(cat, f"{done}/{total}", f"{int(done/total*100) if total>0 else 0}%")
