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


def render_admin_manual():
    st.markdown("<h2 class='centered-title'> 관리자 매뉴얼</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#8a7f72;font-size:0.9rem;'>스마트 물류 대시보드 &nbsp;·&nbsp; 관리자·마스터 전용</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── 1. 사용자 권한 안내 ──────────────────────────────────────
    with st.expander(" 1. 사용자 권한(Role) 안내", expanded=False):
        _section("", "역할별 접근 메뉴")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.89rem;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:7px 10px;text-align:left;'>역할</th>
            <th style='padding:7px 10px;text-align:left;'>Role ID</th>
            <th style='padding:7px 10px;text-align:left;'>접근 가능 화면</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 마스터 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>master</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>전체 메뉴</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>admin</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>전체 메뉴</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 컨트롤 타워</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>control_tower</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>KPI·리포트·마스터관리·매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 조립 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>assembly_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>조립 라인·작업자 매뉴얼</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 검사 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>qc_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>검사 라인·불량공정·작업자 매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 포장 담당자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>packing_team</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>포장 라인·작업자 매뉴얼</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 일정 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>schedule_manager</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 지표 관리·작업자 매뉴얼</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;'> OQC 품질팀</td>
            <td style='padding:6px 10px;font-family:monospace;'>oqc_team</td>
            <td style='padding:6px 10px;'>OQC 라인·작업자 매뉴얼</td>
          </tr>
        </table>
        <p style='margin:10px 0 0;color:#1B5E20;background:#e8f5e9;padding:6px 10px;border-radius:5px;'>
           계정 등록·수정·삭제는 마스터 관리 앱 또는 Supabase Table Editor → <code>users</code> 테이블에서 관리합니다.
        </p>""")

    # ── 2. 마스터 데이터 관리 ────────────────────────────────────
    with st.expander(" 2. 마스터 데이터 관리"):
        _section("", "모델·품목코드 기준 정보 등록", "#2B7CB5")
        _box("""
        <p style='margin:0 0 8px;background:#fef2f2;padding:6px 10px;border-radius:5px;color:#7F1D1D;font-weight:700;'>
           마스터 비밀번호 인증 필요 — 관리자·마스터 권한만 접근 가능 (별도 마스터 관리 앱)
        </p>
        <b>모델 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>반별(제조1·2·3반) 탭 선택 후 모델명 입력 (줄바꿈으로 여러 개 한 번에 등록)</li>
          <li>등록된 모델은 조립 라인 등록 화면의 드롭다운에 즉시 반영</li>
        </ul>
        <b>품목코드(P/N) 등록</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모델 선택 후 품목코드 입력 (줄바꿈으로 일괄 등록 가능)</li>
          <li>모델-품목 연결 관계가 설정되어 조립 화면에서 선택 가능</li>
        </ul>
        <b>삭제</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>개별 삭제: 목록에서 삭제 버튼 클릭 (확인 팝업)</li>
          <li>전체 삭제: 해당 반의 모든 모델/품목 일괄 삭제</li>
          <li> 삭제는 되돌릴 수 없으므로 신중하게 진행</li>
        </ul>""")

    # ── 3. 생산 일정 관리 ────────────────────────────────────────
    with st.expander(" 3. 생산 일정 관리"):
        _section("", "생산 계획 등록 및 편집", "#D97706")
        _box("""
        <b>일정 등록 방법</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>메인 현황판 하단 월별 달력에서 <b>날짜 클릭</b> → 일정 입력 팝업</li>
          <li>입력 항목: 날짜·유형·모델명·P/N·처리수량·출하계획·특이사항</li>
          <li>유형별 색상:  조립계획 /  포장계획 /  출하계획</li>
        </ul>
        <b>엑셀 일괄 업로드</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>생산 지표 관리 → <b>일정 관리</b> 탭 → 엑셀 업로드</li>
          <li>지원 형식: .xlsx (헤더: 날짜·유형·모델·P/N·처리수·출하·특이사항)</li>
        </ul>
        <b>편집·삭제 권한</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>마스터·관리자·컨트롤 타워·일정 관리자만 추가/수정/삭제 가능</li>
        </ul>""")

    # ── 4. 생산 지표(KPI) 관리 ──────────────────────────────────
    with st.expander(" 4. 생산 지표(KPI) 분석"):
        _section("", "핵심 지표 카드 — 보는 방법", "#1B3A5C")
        _box("""
        <p style='margin:0 0 8px;'>화면 상단 5개 카드가 선택한 기간·반 기준 핵심 수치를 요약합니다.</p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>카드</th>
            <th style='padding:6px 10px;text-align:left;'>의미 및 판단 기준</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;'>계획</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>등록된 조립 계획 수량 — 기준점. 이 숫자를 목표로 생산합니다.</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;'>생산 완료</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>포장까지 완료된 실제 출고 가능 수량 (아카이브 포함)</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'>달성률</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>완료 ÷ 계획 × 100%. <b>100% 이상</b>이 목표. 월말에 100% 미달 시 미달 원인 분석 필요.</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;'>진행 중</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>현재 각 공정을 통과 중인 WIP(Work In Progress) 수량</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;font-weight:700;color:#c0392b;'>불량률</td>
            <td style='padding:6px 10px;'><b>3% 이하</b> 유지가 목표. 5% 초과 시 품질 긴급 점검 필요.</td>
          </tr>
        </table>""")

        _section("", "반별 달성률 게이지 — 보는 방법", "#2471a3")
        _box("""
        <p style='margin:0 0 8px;'>각 반의 이번달 계획 대비 완료 실적을 게이지 바와 % 숫자로 보여줍니다.</p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#2471a3;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>색상 / 수치</th>
            <th style='padding:6px 10px;text-align:left;'>상태</th>
            <th style='padding:6px 10px;text-align:left;'>관리자 행동</th>
          </tr>
          <tr style='background:#e8f5e9;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#1e8449;'>● 초록 100% 이상</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>계획 달성 완료</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>정상 유지</td>
          </tr>
          <tr style='background:#fff3d4;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'>● 주황 70~99%</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>지연 중 — 만회 가능</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>병목 공정 점검, 투입 속도 확인</td>
          </tr>
          <tr style='background:#fef2f2;'>
            <td style='padding:6px 10px;font-weight:700;color:#c0392b;'>● 빨강 70% 미만</td>
            <td style='padding:6px 10px;'>심각한 지연</td>
            <td style='padding:6px 10px;'>원인 즉시 파악 — 인력·설비·자재 점검</td>
          </tr>
        </table>
        <p style='margin:8px 0 0;background:#e0f2fe;padding:6px 10px;border-radius:5px;color:#0C4A6E;'>
           <b>0% + 계획 0대</b>로 표시되는 반은 해당 월 조립 계획이 미등록 상태입니다. 일정 관리에서 등록하세요.
        </p>""")

        _section("", "공정 흐름 병목 감지 — 보는 방법", "#7a6f65")
        _box("""
        <p style='margin:0 0 8px;'>조립 → 검사 → 포장 각 공정의 진행 중 수량을 비교해 <b>어느 공정에 제품이 쌓이고 있는지</b> 자동 감지합니다.</p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#5a4f45;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>표시</th>
            <th style='padding:6px 10px;text-align:left;'>의미</th>
            <th style='padding:6px 10px;text-align:left;'>조치</th>
          </tr>
          <tr style='background:#fde8e7;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#c0392b;'> 병목! (빨강)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>전체 공정 중 가장 많이 쌓인 공정 (70% 이상 집중)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>해당 라인 인력 보강 또는 우선 처리</td>
          </tr>
          <tr style='background:#fff3d4;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'> 주의 (주황)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>적체가 진행 중 (40~69% 수준)</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>추이 모니터링, 이상 시 선제 대응</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;font-weight:700;color:#2471a3;'>표시 없음 (정상)</td>
            <td style='padding:6px 10px;'>공정 흐름 원활</td>
            <td style='padding:6px 10px;'>정상 유지</td>
          </tr>
        </table>
        <p style='margin:8px 0 0;background:#fff3d4;padding:6px 10px;border-radius:5px;color:#7a5c00;'>
           <b>대기 N대</b>는 이전 공정에서 완료됐으나 다음 공정으로 아직 이동하지 않은 대기 수량입니다. 대기가 많으면 전달이 지연되고 있는 것입니다.
        </p>""")

        _section("", "모델별 불량 파레토 차트 — 보는 방법", "#c0392b")
        _box("""
        <p style='margin:0 0 8px;'>어떤 모델에서 불량이 집중되는지 파악하고, 전체 불량의 80%를 유발하는 핵심 원인을 찾는 차트입니다.</p>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>막대 (왼쪽 축)</b>: 모델별 불량률(%) — 높을수록 품질 문제가 심각</li>
          <li><b>꺾은선 (오른쪽 축)</b>: 누적 불량 비중(%) — 왼쪽 모델부터 누적</li>
          <li><b>점선 80% 기준선</b>: 이 선에 닿는 지점까지의 모델이 <b>전체 불량의 80%를 차지</b>하는 핵심 불량 모델</li>
        </ul>
        <p style='margin:0 0 6px;color:#7F1D1D;background:#fef2f2;padding:6px 10px;border-radius:5px;'>
           <b>파레토 법칙 (80/20 법칙)</b>: 소수 모델이 대부분의 불량을 유발합니다. 80% 선 왼쪽 모델을 집중 관리하면 전체 불량을 효과적으로 줄일 수 있습니다.
        </p>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:8px;'>
          <tr style='background:#c0392b;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>막대 색상</th>
            <th style='padding:6px 10px;text-align:left;'>불량률 기준</th>
            <th style='padding:6px 10px;text-align:left;'>조치</th>
          </tr>
          <tr style='background:#fde8e7;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#c0392b;'>● 빨강</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>불량률 10% 초과</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>즉시 원인 분석 및 라인 점검</td>
          </tr>
          <tr style='background:#fff3d4;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-weight:700;color:#d68910;'>● 주황</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>불량률 5~10%</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>원인 파악 후 개선 계획 수립</td>
          </tr>
          <tr style='background:#fffde7;'>
            <td style='padding:6px 10px;font-weight:700;color:#b7950b;'>● 노랑</td>
            <td style='padding:6px 10px;'>불량률 5% 이하</td>
            <td style='padding:6px 10px;'>모니터링 유지</td>
          </tr>
        </table>""")

        _section("", "모델별 생산 현황 (메인 현황판) — 보는 방법", "#2B7CB5")
        _box("""
        <p style='margin:0 0 8px;'>메인 현황판 하단에 위치하며, 현재 시스템에 등록된 <b>모든 모델의 실시간 진행 상태</b>를 한 표로 보여줍니다.</p>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>진행률 막대</b>: 완료 ÷ 투입 × 100% — 짧으면 아직 많이 남은 것</li>
          <li><b>불량 셀 빨간 배경</b>: 해당 모델에 불량이 발생 중임을 즉시 인지</li>
          <li>여러 모델 혼류 생산 시 <b>어느 모델이 지연되는지</b> 빠르게 파악 가능</li>
        </ul>
        <p style='margin:0;background:#e0f2fe;padding:6px 10px;border-radius:5px;color:#0C4A6E;'>
           이 표는 production_db(현재 진행 중) 기준입니다. 완료 후 아카이브된 수량은 포함되지 않습니다.
        </p>""")

    # ── 5. 수리 현황 리포트 & 감사 로그 ─────────────────────────
    with st.expander(" 5. 수리 현황 리포트 & 감사 로그"):
        _section("", "품질 추적 및 이력 관리", "#DC2626")
        _box("""
        <b>수리 현황 리포트</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>라인별 불량 건수 막대 차트</li>
          <li>모델별 불량 분포 파이 차트</li>
          <li>전체 수리 이력 테이블 (시리얼·모델·원인·조치)</li>
        </ul>
        <b>감사 로그 (Audit Log)</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>모든 상태 변화 이력 기록 (누가·언제·어떤 제품을·어떤 상태로 변경)</li>
          <li>필터: 반 / 이후 상태 / 시리얼 번호 검색</li>
          <li>컬럼: 시간·시리얼·모델·반·이전상태·이후상태·작업자·비고</li>
        </ul>
        <p style='margin:0;background:#fef2f2;padding:6px 10px;border-radius:5px;color:#7F1D1D;'>
           감사 로그는 완전한 추적 이력(Traceability)을 제공합니다. 품질 이슈 발생 시 반드시 확인하세요.
        </p>""")

    # ── 6. 시스템 설정 안내 ──────────────────────────────────────
    with st.expander(" 6. 시스템 설정 안내 (Streamlit Secrets)"):
        _section("", "운영 환경 설정", "#64748B")
        _box("""
        <b>Streamlit Cloud Secrets 주요 항목</b>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:6px;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>키</th>
            <th style='padding:6px 10px;text-align:left;'>설명</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>master_admin_pw_hash</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>마스터 데이터 관리 비밀번호 SHA-256 해시 (최상위 키)</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>master_admin_url</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>마스터 관리 앱 URL (최상위 키)</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>[supabase] url / key</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>Supabase 프로젝트 URL 및 anon 키</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>[connections.gsheets]</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>Google Sheets 서비스 계정 인증 정보</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;font-family:monospace;'>[fallback_users]</td>
            <td style='padding:6px 10px;'>Supabase 연결 실패 시 임시 계정 해시 (선택)</td>
          </tr>
        </table>
        <p style='margin:10px 0 0;background:#fff3d4;padding:6px 10px;border-radius:5px;color:#7a5c00;'>
           <code>master_admin_pw_hash</code>와 <code>master_admin_url</code>은 반드시 <b>최상위 키</b>(어떤 [섹션] 밖)에 위치해야 합니다.
        </p>""")

    # ── 7. Supabase 테이블 구조 ──────────────────────────────────
    with st.expander(" 7. Supabase 테이블 구조"):
        _section("", "DB 테이블 목록 및 주요 컬럼", "#2B7CB5")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#1B3A5C;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>테이블</th>
            <th style='padding:6px 10px;text-align:left;'>주요 컬럼</th>
            <th style='padding:6px 10px;text-align:left;'>용도</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>production</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시간·반·라인·모델·품목코드·시리얼·상태·deleted_at</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 이력 메인 테이블 (진행 중)</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>production_history</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>동일 구조</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>완료 후 아카이브 테이블 (KPI 집계 기준)</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>users</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>username·password_hash·role</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>사용자 계정 관리</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>model_master</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>반·모델명·품목코드</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>모델/품목 기준 정보</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>production_schedule</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>날짜·유형·모델·수량·출하계획</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>생산 일정</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>audit_log</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시간·시리얼·이전상태·이후상태·작업자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>상태 변화 이력</td>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;font-family:monospace;'>system_config</td>
            <td style='padding:6px 10px;'>key·master_hash</td>
            <td style='padding:6px 10px;'>마스터 비밀번호 등 시스템 설정</td>
          </tr>
        </table>""")

    # ── 8. 계정 신청 승인 ────────────────────────────────────────
    with st.expander(" 8. 계정 신청 승인"):
        _section("", "신규 계정 신청 처리", "#166534")
        _box("""
        <b>신청 확인 위치</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>사이드바 하단 <b>마스터 관리</b> 이동 → 마스터 비밀번호 인증</li>
          <li><b>계정 신청 관리</b> 섹션에서 대기 중인 신청 목록 확인</li>
        </ul>
        <b>승인 처리</b>
        <ol style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>신청자 이름·요청 권한(Role) 확인</li>
          <li><b>승인</b> 버튼 클릭 → 해당 사용자 계정 즉시 활성화</li>
          <li>승인 후 작업자에게 로그인 가능함을 별도 안내</li>
        </ol>
        <b>거절 처리</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li><b>거절</b> 버튼 클릭 → 신청 삭제 (재신청 가능)</li>
          <li> 승인/거절 후에는 되돌릴 수 없으므로 신중하게 처리</li>
        </ul>""")

    # ── 9. 도움 요청 처리 ────────────────────────────────────────
    with st.expander("🆘 9. 작업자 도움 요청 처리"):
        _section("🆘", "현장 도움 요청 확인 및 처리", "#7C2D12")
        _box("""
        <b>알림 확인</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>사이드바에 <b>🆘 도움 요청 (N건)</b> 배지가 표시되면 미처리 요청이 있는 것</li>
          <li>클릭하여 요청 목록 확인: 작업자명·요청 내용·시각</li>
        </ul>
        <b>처리 방법</b>
        <ol style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>요청 내용 확인 후 현장 지원 또는 응답</li>
          <li><b>처리 완료</b> 버튼 클릭 → 요청 목록에서 제거</li>
        </ol>
        <b>Telegram 알림 연동</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>작업자가 <b>관리자 호출</b> 버튼을 누르면 Telegram 메시지로 즉시 수신</li>
          <li>Telegram 미설정 시 사이드바 목록에서만 확인 가능</li>
        </ul>""")

    # ── 10. 제품 상태 수동 변경 ─────────────────────────────────
    with st.expander("↩ 10. 제품 상태 수동 변경"):
        _section("↩", "잘못 처리된 제품 상태 복구", "#92400E")
        _box("""
        <p style='margin:0 0 8px;background:#fef2f2;padding:6px 10px;border-radius:5px;color:#7F1D1D;font-weight:700;'>
           관리자·마스터 전용 기능 — 생산 현황 리포트 화면에서 사용
        </p>
        <b>접근 경로</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>사이드바 → <b>생산 현황 리포트</b> → 하단 <b>제품 상태 수동 변경</b> 섹션</li>
        </ul>
        <b>사용 방법</b>
        <ol style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>시리얼 번호 입력 후 <b>조회</b></li>
          <li>현재 상태 확인 후 변경할 상태 선택</li>
          <li><b>상태 변경</b> 버튼 클릭 → 감사 로그에 "관리자 수동 상태 변경" 비고로 기록</li>
        </ol>
        <p style='margin:0;background:#fff3d4;padding:6px 10px;border-radius:5px;color:#7a5c00;'>
           모든 수동 변경 이력은 감사 로그에 남습니다. 남용하지 마세요.
        </p>""")

    # ── 11. 드롭박스 옵션 편집 ───────────────────────────────────
    with st.expander(" 11. 드롭박스 옵션 편집"):
        _section("", "불량 원인 · 조치 방법 항목 관리", "#1B3A5C")
        _box("""
        <b>접근 경로</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>사이드바 → <b>마스터 관리</b> → 마스터 비밀번호 인증 → <b>드롭박스 옵션 편집</b> 섹션</li>
        </ul>
        <b>편집 가능 항목</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>불량 원인</b>: 불량 공정 화면의 원인 드롭다운 선택지</li>
          <li><b>조치 방법</b>: 불량 공정 화면의 조치 드롭다운 선택지</li>
          <li><b>OQC 부적합 사유</b>: OQC 라인 부적합 처리 시 선택지</li>
          <li><b>자재명</b>: 조립 라인 자재 S/N 등록 시 사용하는 자재 목록</li>
        </ul>
        <b>추가/삭제 방법</b>
        <ol style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>항목 입력란에 새 옵션 입력 후 <b>추가</b> 버튼 클릭</li>
          <li>기존 항목 옆 <b>삭제()</b> 버튼으로 제거</li>
          <li>변경 사항은 즉시 모든 작업자 화면에 반영</li>
        </ol>
        <p style='margin:0;background:#e0f2fe;padding:6px 10px;border-radius:5px;color:#0C4A6E;'>
           작업자가 "드롭다운에 항목이 없다"고 요청하면 여기서 추가하세요.
        </p>""")

    # ── 12. 사용자별 권한 개별 설정 ─────────────────────────────
    with st.expander(" 12. 사용자별 권한 개별 설정"):
        _section("", "메뉴·읽기/쓰기 권한 세부 조정", "#4A1D96")
        _box("""
        <b>접근 경로</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>마스터 관리 → 사용자 목록 → 해당 사용자 → <b>권한 설정</b></li>
        </ul>
        <b>설정 가능 항목</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li><b>메뉴 접근</b>: 기본 Role에서 특정 메뉴를 추가/제외</li>
          <li><b>읽기 전용(read)</b>: 데이터 조회만 가능, 등록·수정 불가</li>
          <li><b>쓰기(write)</b>: 데이터 등록·수정·삭제 가능</li>
        </ul>
        <b>주요 활용 예시</b>
        <ul style='margin:4px 0 0;padding-left:1.4em;'>
          <li>조립 담당자에게 생산 현황 리포트 <b>읽기 전용</b> 추가 부여</li>
          <li>특정 계정의 쓰기 권한을 일시적으로 제한</li>
          <li>컨트롤 타워에게 조립 라인 <b>읽기 전용</b> 접근 허용</li>
        </ul>""")

    # ── 13. Telegram 봇 설정 ────────────────────────────────────
    with st.expander(" 13. Telegram 관리자 호출 봇 설정"):
        _section("", "Telegram 알림 봇 연동", "#0C4A6E")
        _box("""
        <b>설정 위치</b>
        <ul style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>Streamlit Cloud → Settings → Secrets</li>
        </ul>
        <b>필요한 값</b>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:6px;'>
          <tr style='background:#0C4A6E;color:#ffffff;'>
            <th style='padding:6px 10px;text-align:left;'>키</th>
            <th style='padding:6px 10px;text-align:left;'>설명</th>
          </tr>
          <tr style='background:#f0f4f8;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>TG_TOKEN</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>BotFather에서 발급받은 봇 토큰</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;font-family:monospace;'>TG_CHAT_ID</td>
            <td style='padding:6px 10px;'>알림 수신할 채팅방 또는 그룹 Chat ID</td>
          </tr>
        </table>
        <b style='display:block;margin-top:10px;'>봇 생성 절차</b>
        <ol style='margin:4px 0 10px;padding-left:1.4em;'>
          <li>Telegram에서 <code>@BotFather</code> 검색 → <code>/newbot</code> 명령</li>
          <li>봇 이름 및 사용자명 설정 후 <b>토큰</b> 수령</li>
          <li>알림 받을 채팅방에 봇 초대 후 Chat ID 확인</li>
          <li>Streamlit Secrets에 <code>TG_TOKEN</code>, <code>TG_CHAT_ID</code> 입력</li>
        </ol>
        <p style='margin:0;background:#e0f2fe;padding:6px 10px;border-radius:5px;color:#0C4A6E;'>
           Chat ID 확인: <code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code> 접속 후 <code>chat.id</code> 값 사용
        </p>""")

    with st.expander(" 14. 생산 중단 일지"):
        _section("", "생산 중단 일지 개요", "#6B3A2A")
        _box("""
        생산 현장에서 발생하는 라인 중단 이벤트를 기록·추적하는 메뉴입니다.<br><br>
        <b>접근 권한</b>
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;margin-top:6px;'>
          <tr style='background:#6B3A2A;color:#fff;'>
            <th style='padding:7px 10px;text-align:left;'>역할</th>
            <th style='padding:7px 10px;text-align:left;'>등록</th>
            <th style='padding:7px 10px;text-align:left;'>조회</th>
            <th style='padding:7px 10px;text-align:left;'>수정·삭제·완료 처리</th>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 마스터 관리자 · 관리자</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>✅</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>✅</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>✅</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;'>그 외 모든 역할</td>
            <td style='padding:6px 10px;'>—</td>
            <td style='padding:6px 10px;'>✅ (조회만)</td>
            <td style='padding:6px 10px;'>—</td>
          </tr>
        </table>""")

        _section("", "일지 등록 항목", "#6B3A2A")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#6B3A2A;color:#fff;'>
            <th style='padding:7px 10px;text-align:left;'>항목</th>
            <th style='padding:7px 10px;text-align:left;'>설명</th>
            <th style='padding:7px 10px;text-align:left;'>필수</th>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>중단 날짜 / 반</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>발생 날짜와 해당 반 선택</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>✅</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>라인 / 중단 유형</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>조립·검사·OQC·포장·전체 라인 / 설비 고장·자재 부족·품질 이슈·작업 불량·관리자 작업지도 불량 등</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>✅</td>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시작/종료 시간</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>HH:MM 형식. 종료 미입력 시 <b>진행 중</b> 상태로 등록</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>시작 ✅ / 종료 선택</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>중단 원인 / 조치 사항</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>구체적인 원인과 취해진 조치 기술</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>원인 ✅ / 조치 선택</td>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>조치 수량</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>해당 중단으로 처리된 반제품·완제품 수량</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>선택</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;'>재작업 예정 일정</td>
            <td style='padding:6px 10px;'>전체 재작업이 당일 불가 시 예정일·예정 수량·비고 등록</td>
            <td style='padding:6px 10px;'>선택</td>
          </tr>
        </table>""")

        _section("", "조회 탭 사용법", "#6B3A2A")
        _box("""
        <ul style='margin:0;padding-left:1.4em;'>
          <li><b>기간 프리셋</b>: 오늘 / 이번 주 / 이번 달 / 지난 달 / 전체 / 직접 입력 선택</li>
          <li><b>반·유형 필터</b>: 특정 반 또는 중단 유형으로 범위 축소</li>
          <li>상단 KPI 카드: 총 건수 · 진행 중 · 설비 고장 · 자재 부족 현황 요약</li>
          <li>각 일지를 클릭하면 원인·조치·수량·재작업 예정 정보 확인 가능</li>
        </ul>""")

        _section("", "관리자 전용 기능", "#6B3A2A")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>
          <tr style='background:#6B3A2A;color:#fff;'>
            <th style='padding:7px 10px;text-align:left;'>버튼</th>
            <th style='padding:7px 10px;text-align:left;'>동작</th>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 재작업 완료</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>재작업 예정일이 등록된 미완료 건에만 표시. 클릭 시 <b>재작업 완료</b> 뱃지로 전환</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 종료 처리</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'><b>진행 중</b> 상태의 일지에 종료 시간 입력 후 완료 처리</td>
          </tr>
          <tr style='background:#f8f4f0;'>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'> 수정</td>
            <td style='padding:6px 10px;border-bottom:1px solid #ddd;'>모든 필드 인라인 수정 (재작업 예정 일정 포함)</td>
          </tr>
          <tr>
            <td style='padding:6px 10px;'> 삭제</td>
            <td style='padding:6px 10px;'>해당 일지 영구 삭제</td>
          </tr>
        </table>""")

        _section("", "Supabase 테이블 구조 (production_stoppage_log)", "#6B3A2A")
        _box("""
        <table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>
          <tr style='background:#6B3A2A;color:#fff;'>
            <th style='padding:6px 10px;text-align:left;'>컬럼</th>
            <th style='padding:7px 10px;text-align:left;'>타입</th>
            <th style='padding:7px 10px;text-align:left;'>설명</th>
          </tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>id</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>bigserial</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>자동 증가 PK</td></tr>
          <tr><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>날짜</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>YYYY-MM-DD</td></tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>반 / 라인 / 중단유형</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>분류 값</td></tr>
          <tr><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>시작시간 / 종료시간</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>HH:MM, 종료 null = 진행 중</td></tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>중단원인 / 조치사항</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>자유 텍스트</td></tr>
          <tr><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>반제품수량 / 완제품수량</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>integer</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>조치 수량</td></tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>재작업예정일</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>YYYY-MM-DD, null = 재작업 없음</td></tr>
          <tr><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>재작업반제품 / 재작업완제품</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>integer</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>재작업 예정 수량</td></tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>재작업비고</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>재작업 관련 메모</td></tr>
          <tr><td style='padding:5px 10px;border-bottom:1px solid #ddd;font-family:monospace;'>재작업완료</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>text</td><td style='padding:5px 10px;border-bottom:1px solid #ddd;'>"Y" = 완료, 공백 = 미완료</td></tr>
          <tr style='background:#f8f4f0;'><td style='padding:5px 10px;font-family:monospace;'>작성자 / 등록시간</td><td style='padding:5px 10px;'>text</td><td style='padding:5px 10px;'>로그인 ID / KST 등록 시각</td></tr>
        </table>""")

    st.markdown("<br>", unsafe_allow_html=True)
    st.info(" Supabase 테이블 편집은 [supabase.com](https://supabase.com) → 프로젝트 → Table Editor에서 진행합니다.")
