import streamlit as st
import pandas as pd
import datetime
import os
import csv
import re

# [1. 보안: 시스템 접근 인증]
if 'auth_done' not in st.session_state:
    st.session_state.auth_done = False

# 인증되지 않은 경우 로그인 화면 표시
if not st.session_state.auth_done:
    st.title("🛡️ 시스템 접근 권한 확인")
    st.info("이 시스템은 허가된 사용자만 접속 가능합니다.")
    
    # 입력창과 버튼
    access_key = st.text_input("접근 인증키를 입력하세요 (기본: 7777)", type="password")
    if st.button("접속 승인"):
        if access_key == "7777":  # 마스터 인증키
            st.session_state.auth_done = True
            st.rerun()
        else:
            st.error("잘못된 인증키입니다. 접근 권한이 없습니다.")
    st.stop()  # 인증 전까지 아래 코드는 절대 실행 안 함

# --- 인증 성공 시 아래의 대시보드 로직이 실행됩니다 ---

# [1. 유틸리티 함수]
def clean_serial(serial):
    """한글 오타 교정 및 특수문자 제거"""
    kor_map = str.maketrans("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡ", "qwertyuiopasdfghjklzxcvbnm")
    s = str(serial).translate(kor_map).strip()
    s = re.sub(r'[^a-zA-Z0-9_-]', '', s)
    return s.upper()

def save_log_to_csv(serial_num, result_text):
    """스캔 시 실시간으로 로컬 CSV 로그 파일에 저장"""
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

# [2. 세션 상태 관리] (페이지 새로고침 시에도 데이터 유지)
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

# 사이드바 구성
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    
    # 📁 CSV 파일 업로드 (데이터 불러오기)
    uploaded_file = st.file_uploader("📂 CSV 데이터 로드", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        # 엑셀/CSV 각 열을 카테고리로, 행을 시리얼로 변환
        new_data = {col: {str(val).strip(): False for val in df[col].dropna()} for col in df.columns}
        st.session_state.categories = new_data
        st.success("데이터 로드 완료!")

    st.divider()

    # 🔒 관리자 인증 (비밀번호 보안)
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

    # 🛠️ 관리자 전용 메뉴 (인증 시 활성화)
    if st.session_state.admin_mode:
        st.divider()
        st.subheader("🛠️ 관리자 도구")
        
        # 항목 관리
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

        # 시리얼 자동 생성 (SerialGen)
        with st.expander("🔢 시리얼 자동 생성"):
            if st.session_state.categories:
                gen_cat = st.selectbox("생성 대상 선택", list(st.session_state.categories.keys()))
                prefix = st.text_input("고유 문자(Prefix)", "SN-")
                c1, c2 = st.columns(2)
                s_num = c1.number_input("시작", value=1)
                e_num = c2.number_input("끝", value=10)
                if st.button("🚀 생성 실행"):
                    for i in range(int(s_num), int(e_num) + 1):
                        sn = f"{prefix}{i:04d}"
                        st.session_state.categories[gen_cat][sn] = False
                    st.success("시리얼이 추가되었습니다.")
                    st.rerun()

        # 📥 데이터 내보내기 (Download)
        with st.expander("📥 데이터 내보내기"):
            if st.session_state.categories:
                export_list = []
                for cat, items in st.session_state.categories.items():
                    for sn, status in items.items():
                        export_list.append({"항목": cat, "시리얼": sn, "상태": "완료" if status else "대기"})
                
                export_df = pd.DataFrame(export_list)
                csv_bytes = export_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                
                st.download_button(
                    label="💾 CSV 다운로드",
                    data=csv_bytes,
                    file_name=f"스캔현황_{datetime.datetime.now().strftime('%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        # 암호 설정
        with st.expander("🔐 비밀번호 변경"):
            new_pw = st.text_input("새 암호", type="password")
            if st.button("변경"):
                st.session_state.admin_pass = new_pw
                st.success("암호가 변경되었습니다.")

# [4. 메인 화면 - 스캔 및 대시보드]
st.title("📦 SMART LOGISTICS DASHBOARD")

# 스캔 입력 섹션
sc1, sc2 = st.columns([1, 2])
with sc1:
    target_cat = st.selectbox("🎯 스캔 위치", ["전체 스캔"] + list(st.session_state.categories.keys()))
with sc2:
    scan_val = st.text_input("📷 바코드 스캔 입력 (Enter)", key="scan_input")

if scan_val:
    clean_bc = clean_serial(scan_val)
    found = False
    for cat, items in st.session_state.categories.items():
        if target_cat == "전체 스캔" or target_cat == cat:
            if clean_bc in items:
                found = True
                if not items[clean_bc]:
                    st.session_state.categories[cat][clean_bc] = True
                    save_log_to_csv(clean_bc, f"[{cat}] 스캔 성공")
                    st.toast(f"✅ {clean_bc} 완료", icon="🟢")
                else:
                    st.toast(f"⚠️ 이미 완료된 시리얼", icon="🟡")
    if not found:
        save_log_to_csv(clean_bc, f"미등록 시리얼 ({target_cat})")
        st.error(f"❌ 미등록 시리얼 감지: {clean_bc}")

st.divider()

# 대시보드 카드 섹션
if not st.session_state.categories:
    st.info("사이드바에서 CSV를 로드하거나 항목을 추가하세요.")
else:
    cats = list(st.session_state.categories.items())
    for i in range(0, len(cats), 3): # 3열씩 자동 줄바꿈
        cols = st.columns(3)
        for j, (name, bcs) in enumerate(cats[i:i+3]):
            with cols[j]:
                with st.container(border=True):
                    done = sum(bcs.values())
                    total = len(bcs)
                    st.subheader(f"📍 {name}")
                    st.progress(done/total if total > 0 else 0)
                    st.write(f"진행: {done} / {total}")
                    
                    # 상세 표 (Treeview 대체)
                    df_view = pd.DataFrame([{"시리얼": k, "상태": "✅" if v else "⏳"} for k, v in bcs.items()])
                    st.dataframe(df_view, use_container_width=True, hide_index=True, height=200)

# 로그 리포트 확인 버튼
if st.button("📋 오늘자 상세 로그 보기"):
    d_str = datetime.datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(f"scan_log_{d_str}.csv"):

        st.table(pd.read_csv(f"scan_log_{d_str}.csv").tail(10))
