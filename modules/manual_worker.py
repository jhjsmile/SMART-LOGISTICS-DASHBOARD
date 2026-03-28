import streamlit as st


def _html(html: str):
    try:
        st.html(html)
    except AttributeError:
        st.markdown(html, unsafe_allow_html=True)


def _section(icon, title, color="#1B3A5C"):
    _html(
        f"<div style='background:{color};color:#fff;padding:8px 16px;"
        f"border-radius:8px 8px 0 0;font-weight:700;font-size:1.0rem;margin-top:16px;'>"
        f"{icon} {title}</div>"
    )


def _box(html_content, bg="#f8f6f2"):
    _html(
        f"<div style='background:{bg};border:1px solid #ddd5c0;border-radius:0 0 8px 8px;"
        f"padding:14px 18px;font-size:0.92rem;line-height:1.75;margin-bottom:4px;'>"
        f"{html_content.strip()}</div>"
    )


def render_worker_manual():
    st.markdown("<h2 class='centered-title'> 작업자 매뉴얼</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#8a7f72;font-size:0.9rem;'>스마트 물류 대시보드 &nbsp;·&nbsp; 현장 작업자용</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── 1. 로그인 방법 ──────────────────────────────────────────
    with st.expander(" 1. 로그인 방법", expanded=False):
        _section("", "로그인 절차")
        _box("""
        <ol style='margin:0;padding-left:1.4em;'>
          <li>브라우저(Chrome 권장)에서 시스템 URL 접속</li>
          <li><b>아이디(ID)</b>와 <b>비밀번호(PW)</b> 입력 후 <b>인증 시작</b> 클릭</li>
          <li>로그인 성공 → 내 권한에 맞는 화면으로 자동 이동</li>
          <li>실패 시 '로그인 정보가 올바르지 않습니다.' 메시지 → 관리자 문의</li>
        </ol>
        <p style='margin:8px 0 4px;color:#7a5c00;background:#fff3d4;padding:6px 10px;border-radius:5px;'>
           비밀번호는 대소문자를 구분합니다. 초기 비밀번호는 관리자에게 문의하세요.
        </p>
        <p style='margin:4px 0 0;color:#1B5E20;background:#e8f5e9;padding:6px 10px;border-radius:5px;'>
           계정이 없으면 로그인 화면 하단 <b>계정 신청</b> 버튼으로 접근 권한을 요청할 수 있습니다. 관리자 승인 후 사용 가능합니다.
        </p>""")

    # ── 2. 생산 통합 현황판 ──────────────────────────────────────
    with st.expander(" 2. 생산 통합 현황판"):
        _section("", "생산 통합 현황판 (메인 대시보드)", "#1B3A5C")
        _box("""
        <p style='margin:0 0 8px;'>로그인 후 처음 보이는 화면으로, 전체 생산 상황을 한눈에 파악할 수 있습니다.</p>
        <b>표시 정보</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>실시간 차트</b>: 반별·공정별 진행 현황 막대 그래프, 전체 상태 비중 파이 차트, 반별 총 투입 차트</li>
          <li><b>전체 생산 요약 카드</b>: 총 투입 / 최종 완료 / 작업 중 / 불량 이슈 수량 (실시간)</li>
          <li><b>반별 상세 보기 토글</b>: 이번달 기준 반별 달성률 게이지 + 투입·완료·진행 중·불량 카드 (ON/OFF)</li>
          <li><b>모델별 생산 현황</b>: 현재 라인에 올라간 모델별 투입·진행·완료·불량·진행률 한눈에 확인</li>
          <li><b>생산 일정 달력</b>: 월별 캘린더에서 당일 포함 향후 일정 확인 가능</li>
        </ul>
        <p style='margin:0;color:#1B5E20;background:#e8f5e9;padding:6px 10px;border-radius:5px;'>
           데이터는 실시간으로 갱신됩니다. 화면이 오래됐다고 느껴지면 브라우저를 새로 고침하세요.
        </p>""")

        _section("", "반별 달성률 게이지 — 보는 방법", "#2B7CB5")
        _box("""
        <p style='margin:0 0 8px;'>각 반 카드 상단의 게이지 바와 % 숫자로 <b>이번 달 계획 대비 완료 실적</b>을 나타냅니다.</p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>색상</th>
            <th style='padding:6px 10px;text-align:left;'>의미</th>
            <th style='padding:6px 10px;text-align:left;'>행동 기준</th>
          </tr>
          <tr style='background:#e8f5e9;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#1e8449;'>● 초록 (100% 이상)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>계획 달성 완료</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>정상 — 유지</td>
          </tr>
          <tr style='background:#fff3d4;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'>● 주황 (70~99%)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>계획 대비 다소 지연</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>속도 향상 필요</td>
          </tr>
          <tr style='background:#fef2f2;'>
            <td style='padding:6px 10px;font-weight:700;color:#c0392b;'>● 빨강 (70% 미만)</td>
            <td style='padding:6px 10px;'>계획 대비 크게 지연</td>
            <td style='padding:6px 10px;'>관리자에게 즉시 보고</td>
          </tr>
        </table>
        <p style='margin:8px 0 0;color:#7a5c00;background:#fff3d4;padding:6px 10px;border-radius:5px;'>
           계획이 등록되지 않은 반은 <b>계획 미등록</b>으로 표시됩니다. 관리자에게 일정 등록을 요청하세요.
        </p>""")

        _section("", "모델별 생산 현황 — 보는 방법", "#2B7CB5")
        _box("""
        <p style='margin:0 0 8px;'>현재 라인에서 진행 중인 <b>모든 모델의 실시간 현황</b>을 표로 보여줍니다.</p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>컬럼</th>
            <th style='padding:6px 10px;text-align:left;'>의미</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;'>투입</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>현재 시스템에 등록된 해당 모델 전체 수량</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'>진행중</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>조립~출하 각 공정을 거치고 있는 수량</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#1e8449;'>완료</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>포장까지 완료된 최종 완성 수량</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#c0392b;'>불량</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>현재 불량·부적합 상태인 수량 (빨간 배경 = 주의)</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;font-weight:700;'>진행률</td>
            <td style='padding:6px 10px;'>완료 ÷ 투입 × 100% — 막대 길이로 시각화</td>
          </tr>
        </table>""")

    # ── 3. 생산 상태 흐름도 ──────────────────────────────────────
    with st.expander(" 3. 생산 상태 흐름도"):
        _section("", "제품이 거치는 상태 변화", "#2B7CB5")
        _box("""
        <div style='display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:4px 0;'>
          <span style='background:#2B7CB5;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>조립중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#0D9488;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>검사대기</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#0D9488;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>검사중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#16A34A;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>OQC대기</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#16A34A;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>OQC중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#F4892A;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>출하승인</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#7C3AED;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>포장중</span>
          <span style='color:#aaa;'>▶</span>
          <span style='background:#1B3A5C;color:#ffffff !important;padding:4px 10px;border-radius:5px;font-size:0.85rem;font-weight:600;'>완료</span>
        </div>
        <hr style='border:none;border-top:1px solid #e0d8c8;margin:10px 0;'>
        <p style='margin:0 0 6px;'><b> 불량 발생 시:</b>
          <span style='background:#DC2626;color:#ffffff !important;padding:3px 8px;border-radius:4px;font-size:0.82rem;'>불량 처리 중</span>
          → 불량 공정에서 원인 분석 →
          <span style='background:#F4892A;color:#ffffff !important;padding:3px 8px;border-radius:4px;font-size:0.82rem;'>수리 완료(재투입)</span>
          → 검사대기 복귀
        </p>
        <p style='margin:0;color:#64748B;font-size:0.88rem;'>※ 각 라인 담당자는 자기 공정 단계만 처리합니다. 다른 공정 제품은 수정하지 마세요.</p>""")

    # ── 4. 조립 라인 ─────────────────────────────────────────────
    with st.expander(" 4. 조립 라인 사용법"):
        _section("", "조립 라인", "#16A34A")
        _box("""
        <b>① 오늘 일정 확인</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>화면 상단에 당일 생산 일정이 자동 표시됩니다.</li>
          <li>새 일정 등록 시 알림 팝업 → <b>확인</b> 버튼으로 닫기</li>
        </ul>
        <b>② 신규 제품 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모델명·품목코드·시리얼 번호 입력 후 <b>등록</b> 버튼 클릭</li>
          <li>바코드 스캐너 연동 가능 — 스캔 후 자동 입력됩니다.</li>
          <li><b>일괄 등록</b>: 여러 시리얼을 줄바꿈으로 입력하면 한 번에 등록 가능</li>
          <li>자재 시리얼(부품 S/N)은 등록 화면 하단의 자재 항목에 추가 입력</li>
        </ul>
        <b>③ 조립 완료 처리</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>이력 목록에서 완료된 항목 체크박스 선택</li>
          <li><b>조립 완료</b> 버튼 클릭 → 상태가 <b>검사대기</b>로 자동 전환</li>
          <li>불량 발생 시 <b>불량 처리</b> 버튼 클릭 → 불량 공정으로 이동</li>
        </ul>
        <b>④ 자재 시리얼 등록</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>제품에 사용된 부품의 S/N을 자재명과 함께 등록합니다.</li>
          <li>바코드 스캔으로 빠르게 등록 가능</li>
          <li>등록된 자재 S/N은 나중에 <b>생산 현황 리포트 → 자재 S/N 추적</b>에서 역추적 가능</li>
        </ul>
        <p style='margin:6px 0 0;background:#e8f5e9;padding:6px 10px;border-radius:5px;color:#1B5E20;'>
           사이드바에서 반(제조1반·2반·3반)을 선택하면 해당 반의 일정과 이력만 표시됩니다.
        </p>""")

    # ── 5. 검사 라인 ─────────────────────────────────────────────
    with st.expander(" 5. 검사 라인 사용법"):
        _section("", "검사 라인", "#0D9488")
        _box("""
        <b>① 입고 처리 (검사대기 → 검사중)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>조립 완료된 제품 목록이 <b>검사대기</b> 섹션에 표시됩니다.</li>
          <li>수리 완료 후 재투입된 제품도 검사대기 목록에 포함됩니다.</li>
          <li>시리얼 번호 스캔/검색으로 빠른 조회</li>
          <li>체크박스 선택 후 <b>일괄 입고</b> 버튼 → <b>검사중</b>으로 전환</li>
        </ul>
        <b>② 검사 판정</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b> 검사 합격</b> 버튼 → 상태가 <b>OQC대기</b>로 자동 전환</li>
          <li><b> 불합격</b> 버튼 → 불량 원인 선택 후 확인 → <b>불량 처리 중</b>으로 전환</li>
        </ul>""")

    # ── 6. OQC 라인 ──────────────────────────────────────────────
    with st.expander(" 6. OQC 라인 사용법"):
        _section("", "OQC 라인 (최종 출하 품질 검사)", "#16A34A")
        _box("""
        <b>① OQC 시작 (OQC대기 → OQC중)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>검사 완료(OQC대기) 제품 목록에서 체크박스 선택 후 <b>OQC 시작</b> 버튼 클릭 → <b>OQC중</b> 전환</li>
        </ul>
        <b>② 최종 판정</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b> 합격</b> → <b>출하승인</b> 상태로 전환 (포장 라인으로 이동)</li>
          <li><b> 부적합</b> → 부적합 사유 드롭다운 선택(또는 직접 입력) 후 확인 → <b>불량 처리 중</b>으로 전환</li>
        </ul>""")

    # ── 7. 포장 라인 ─────────────────────────────────────────────
    with st.expander(" 7. 포장 라인 사용법"):
        _section("", "포장 라인", "#7C3AED")
        _box("""
        <b>① 입고 처리 (출하승인 → 포장중)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>OQC 합격(출하승인) 제품이 목록에 표시됩니다.</li>
          <li>체크박스 선택 후 <b>일괄 입고</b> 버튼 → <b>포장중</b>으로 전환</li>
        </ul>
        <b>② 포장 완료 처리</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>포장중 목록에서 <b>포장 완료</b> 버튼 클릭 → <b>완료</b> 상태로 최종 처리</li>
          <li>완료된 수량은 생산 지표 관리 KPI에 자동 반영됩니다.</li>
        </ul>""")

    # ── 8. 불량 공정 ─────────────────────────────────────────────
    with st.expander(" 8. 불량 공정 처리"):
        _section("", "불량 공정", "#DC2626")
        _box("""
        <ol style='margin:0;padding-left:1.4em;'>
          <li>불량 처리 중 목록에서 해당 제품 확인</li>
          <li><b>불량 원인</b> 드롭다운에서 원인 선택 (없으면 '기타(직접 입력)' 선택 후 입력)</li>
          <li><b>조치 방법</b> 드롭다운에서 선택 (재작업·폐기·반품 등)</li>
          <li><b>조치 완료</b> 버튼 클릭 → <b>수리 완료(재투입)</b> 상태로 전환</li>
          <li>재투입된 제품은 <b>검사대기</b> 목록으로 복귀하여 재검사 진행</li>
        </ol>
        <p style='margin:8px 0 0;color:#7F1D1D;background:#fef2f2;padding:6px 10px;border-radius:5px;'>
           불량 원인과 조치 방법의 드롭다운 항목은 관리자가 설정합니다. 새 항목이 필요하면 관리자에게 요청하세요.
        </p>""")

    # ── 9. 생산 현황 리포트 ───────────────────────────────────────
    with st.expander(" 9. 생산 현황 리포트"):
        _section("", "생산 현황 리포트", "#2B7CB5")
        _box("""
        <b>생산 현황 리포트 탭</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>기간·반 필터로 원하는 기간의 생산 이력을 조회합니다.</li>
          <li>시리얼 번호 검색으로 특정 제품의 공정 이력을 추적할 수 있습니다.</li>
          <li>조회 결과를 <b>Excel / CSV</b>로 다운로드 가능합니다.</li>
        </ul>
        <b>자재 S/N 추적 탭</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b>메인 S/N → 자재 조회</b>: 완제품 시리얼로 해당 제품에 쓰인 모든 자재 S/N 확인</li>
          <li><b>자재 S/N → 메인 역추적</b>: 부품 시리얼로 해당 부품이 어느 완제품에 사용됐는지 역추적</li>
          <li>품질 이슈 발생 시 영향받은 제품 범위를 신속하게 파악할 수 있습니다.</li>
        </ul>""")

    # ── 10. FAQ ───────────────────────────────────────────────────
    with st.expander(" 10. 자주 묻는 질문 (FAQ)"):
        _section("", "FAQ", "#64748B")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.91rem;'>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;width:42%;border-bottom:1px solid #ddd;'>Q. 로그인이 안 됩니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 아이디/비밀번호 재확인 후 관리자에게 계정 재설정 요청하세요. 또는 로그인 화면의 <b>계정 신청</b>을 이용하세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 데이터가 표시되지 않습니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 사이드바의 연결 상태 경고 확인 후 페이지를 새로 고침하세요.</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 버튼을 눌렀는데 반응이 없습니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 처리 후 자동 새로고침됩니다. 잠시 기다려 주세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 불량 처리 후 제품이 안 보입니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 불량 공정 화면에서 해당 시리얼을 검색하세요.</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 내 반이 아닌 데이터가 보입니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 사이드바에서 본인 반(제조1반·2반·3반)을 선택하세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 드롭다운에 필요한 항목이 없습니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 관리자에게 드롭박스 옵션 추가를 요청하세요. (마스터 관리 → 드롭박스 옵션 편집)</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:8px 12px;font-weight:700;border-bottom:1px solid #ddd;'>Q. 스캐너로 스캔했는데 중복으로 입력됩니다.</td>
            <td style='padding:8px 12px;border-bottom:1px solid #ddd;'>A. 시스템이 5초 내 중복 입력을 자동으로 무시합니다. 스캔 후 잠시 기다려 주세요.</td>
          </tr>
          <tr>
            <td style='padding:8px 12px;font-weight:700;'>Q. 실수로 잘못된 상태로 처리했습니다.</td>
            <td style='padding:8px 12px;'>A. 스스로 되돌릴 수 없습니다. 관리자에게 감사 로그 확인 및 수정을 요청하세요.</td>
          </tr>
        </table>""")
