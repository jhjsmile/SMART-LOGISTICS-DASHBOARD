import streamlit as st
import pandas as pd
import datetime
import os
import csv
import re

# [보안: 시스템 접근 인증]
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

# [유틸리티 함수]
def clean_serial(serial):
    kor_map = str.maketrans("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡ", "qwertyuiopasdfghjklzxcvbnm")
    s = str(serial).translate(kor_map).strip()
    s = re.sub(r'[^a-zA-Z0-9_-]', '', s)
    return s.upper()

def save_log_to_csv(serial_num, proc_name, result_text):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    filename = f"scan_log_{date_str}.csv"
    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["날짜", "시간", "공정", "시리얼", "결과"])
        writer.writerow([date_str, time_str, proc_name, serial_num, result_text])

# [세션 상태 관리]
if 'categories' not in st.session_state: st.session_state.categories = {}
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'admin_pass' not in st.session_state: st.session_state.admin_pass = "1234"

st.set_page_config(page_title="SMART LOGISTICS WEB", layout="wide")

# --- [왼쪽 사이드바: image_5fcc3d.png의 기능을 100% 복구] ---
with st.sidebar:
    st.header("🛠️ 관리자 도구")
    
    # 1. 항목 추가/삭제 섹션
    with st.expander("📂 항목 추가/삭제", expanded=True):
        new_cat_name = st.text_input("새 카테고리 이름")
        if st.button("➕ 추가"):
            if new_cat_name and new_cat_name not in st.session_state.categories:
                st.session_state.categories[new_cat_name] = {}
                st.rerun()
        
        if st.session_state.categories:
            del_cat_name = st.selectbox("삭제할 항목 선택", list(st.session_state.categories.keys()))
            if st.button("❌ 삭제"):
                del st.session_state.categories[del_cat_name]
                st.rerun()

    # 2. 시리얼 자동 생성 섹션
    with st.expander("🔢 시리얼 자동 생성"):
        if st.session_state.categories:
            target_cat = st.selectbox("생성 대상 선택", list(st.session_state.categories.keys()))
            prefix = st.text_input("고유 문자(Prefix)", value="SN-")
            col1, col2 = st.columns(2)
            start_num = col1.number_input("시작", value=1)
            end_num = col2.number_input("끝", value=10)
            if st.button("🚀 생성 실행"):
                for i in range(int(start_num), int(end_num) + 1):
                    sn = f"{prefix}{i:03d}"
                    st.session_state.categories[target_cat][sn] = False
                st.success(f"{end_num-start_num+1}개 생성 완료!")

    # 3. 데이터 로드/내보내기
    with st.expander("💾 데이터 관리"):
        uploaded = st.file_uploader("CSV 로드", type="csv")
        if uploaded:
            df = pd.read_csv(uploaded)
            st.session_state.categories = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        
        if st.session_state.categories:
            export_list = []
            for c, items in st.session_state.categories.items():
                for s, status in items.items():
                    export_list.append({"항목": c, "시리얼": s, "상태": "완료" if status else "대기"})
            csv_data = pd.DataFrame(export_list).to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button("📥 CSV 다운로드", csv_data, "status.csv")

    # 4. 비밀번호 변경
    with st.expander("🔐 비밀번호 변경"):
        new_pw = st.text_input("새 암호", type="password")
        if st.button("변경"):
            st.session_state.admin_pass = new_pw
            st.success("변경 완료!")

# --- [메인 화면: 4단계 공정 탭] ---
st.title("📦 SMART LOGISTICS DASHBOARD")

tabs = st.tabs(["🚚 자재 입고", "🔧 조립 완료", "📦 포장 단계", "⚠️ 불량 처리"])
labels = ["자재 입고", "조립 완료", "포장 단계", "불량 처리"]

def process_scan(val, proc):
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
        if not found: st.error(f"❌ {c} : 미등록 번호")

for i, tab in enumerate(tabs):
    with tab:
        st.subheader(f"📍 {labels[i]}")
        if i < 3:
            s_in = st.text_input(f"{labels[i]} 스캔", key=f"input_{i}")
            if st.button("확인", key=f"btn_{i}"): process_scan(s_in, labels[i])
        else:
            f_in = st.text_input("불량 시리얼 스캔", key="f_in")
            reason = st.selectbox("사유", ["파손", "기타"], key="f_re")
            if st.button("불량 등록"):
                if f_in:
                    cc = clean_serial(f_in)
                    save_log_to_csv(cc, "불량", f"사유:{reason}")
                    st.warning(f"⚠️ {cc} 불량 처리됨")

# 하단 전광판
st.divider()
if st.session_state.categories:
    cols = st.columns(len(st.session_state.categories))
    for i, (cat, items) in enumerate(st.session_state.categories.items()):
        total, done = len(items), sum(items.values())
        cols[i].metric(cat, f"{done}/{total}", f"{int(done/total*100) if total>0 else 0}%")
