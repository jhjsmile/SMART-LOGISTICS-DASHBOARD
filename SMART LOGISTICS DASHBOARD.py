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
    access_key = st.text_input("접근 인증키 (기본: 7777)", type="password")
    if st.button("접속 승인"):
        if access_key == "7777":
            st.session_state.auth_done = True
            st.rerun()
        else:
            st.error("인증키가 틀렸습니다.")
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
if 'categories' not in st.session_state: st.session_state.categories = {}
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'admin_pass' not in st.session_state: st.session_state.admin_pass = "1234"

# [4. UI 설정]
st.set_page_config(page_title="SMART LOGISTICS WEB", layout="wide")

# --- [왼쪽 사이드바: 사라진 기능 모두 복구] ---
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    
    # 1. 데이터 로드
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.session_state.categories = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.success("데이터 로드 완료!")
    
    st.divider()

    # 2. 관리자 로그인 및 설정 (핵심 복구 구간)
    if not st.session_state.admin_mode:
        st.subheader("🔒 관리자 로그인")
        input_pw = st.text_input("비밀번호 입력", type="password")
        if st.button("로그인"):
            if input_pw == st.session_state.admin_pass:
                st.session_state.admin_mode = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
    else:
        st.success("🔓 관리자 모드 활성화")
        if st.button("로그아웃"):
            st.session_state.admin_mode = False
            st.rerun()
        
        st.divider()
        st.subheader("🛠️ 항목 및 시리얼 관리")
        
        # [기능 1: 항목 추가]
        new_cat = st.text_input("➕ 새 항목(카테고리) 추가")
        if st.button("항목 생성"):
            if new_cat and new_cat not in st.session_state.categories:
                st.session_state.categories[new_cat] = {}
                st.rerun()
        
        # [기능 2: 시리얼 생성 및 항목 삭제]
        if st.session_state.categories:
            sel_cat = st.selectbox("관리할 항목 선택", list(st.session_state.categories.keys()))
            
            if st.button("🗑️ 선택한 항목 전체 삭제"):
                del st.session_state.categories[sel_cat]
                st.rerun()
            
            st.write(f"--- [{sel_cat}] 시리얼 관리 ---")
            add_sn = st.text_input("신규 시리얼 번호 입력")
            if st.button("시리얼 생성/추가"):
                if add_sn:
                    st.session_state.categories[sel_cat][add_sn.strip()] = False
                    st.rerun()

        st.divider()
        # [기능 3: 암호 변경]
        with st.expander("🔑 관리자 암호 변경"):
            new_pass = st.text_input("새 비밀번호 입력", type="password")
            if st.button("암호 변경 저장"):
                if new_pass:
                    st.session_state.admin_pass = new_pass
                    st.success("비밀번호가 변경되었습니다.")

        # [기능 4: 데이터 내보내기]
        with st.expander("📥 데이터 내보내기"):
            if st.session_state.categories:
                export_list = []
                for cat, items in st.session_state.categories.items():
                    for sn, status in items.items():
                        export_list.append({"항목": cat, "시리얼": sn, "상태": "완료" if status else "대기"})
                csv_bytes = pd.DataFrame(export_list).to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("💾 CSV 다운로드", csv_bytes, "logistics_status.csv")

# --- [메인 화면: 4단계 공정 탭 유지] ---
st.title("📦 SMART LOGISTICS DASHBOARD")

tab1, tab2, tab3, tab4 = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])

def do_scan(val, proc):
    if val:
        c = clean_serial(val)
        found = False
        for cat, items in st.session_state.categories.items():
            if c in items:
                items[c] = True
                save_log_to_csv(c, proc, "성공")
                st.success(f"✅ {c} : {proc} 완료")
                found = True
                break
        if not found:
            st.error(f"❌ {c} : 미등록 시리얼")

with tab1:
    s1 = st.text_input("입고 스캔", key="s1")
    if st.button("입고 확인", key="b1"): do_scan(s1, "자재 입고")
with tab2:
    s2 = st.text_input("조립 스캔", key="s2")
    if st.button("조립 확인", key="b2"): do_scan(s2, "조립 완료")
with tab3:
    s3 = st.text_input("포장 스캔", key="s3")
    if st.button("포장 확인", key="b3"): do_scan(s3, "포장 단계")
with tab4:
    s4 = st.text_input("불량 스캔", key="s4")
    r = st.selectbox("사유", ["파손", "기타"], key="r4")
    if st.button("불량 등록"):
        if s4:
            cc = clean_serial(s4)
            save_log_to_csv(cc, "불량", f"사유:{r}")
            st.warning(f"⚠️ {cc} 불량 기록됨")

# 하단 전광판
st.divider()
if st.session_state.categories:
    cols = st.columns(len(st.session_state.categories))
    for i, (cat, items) in enumerate(st.session_state.categories.items()):
        total, done = len(items), sum(items.values())
        cols[i].metric(cat, f"{done}/{total}", f"{int(done/total*100) if total>0 else 0}%")
