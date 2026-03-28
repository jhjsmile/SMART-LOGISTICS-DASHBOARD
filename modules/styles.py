import streamlit as st


def inject_styles():
    """CSS 스타일 주입"""
    st.markdown("""
    <style>
    /* ════════════════════════════════════════
       산업/공장 테마 (v2.0.0)
       배경: 콘크리트 회색
       강조: 산업용 오렌지 · 스틸 사이드바
    ════════════════════════════════════════ */

    /* 전체 앱 배경 */
    .stApp {
        background-color: #e9ebed !important;
        overflow-x: hidden;
    }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background-color: #cfd8dc !important;
        border-right: 2px solid #90a4ae !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span:not(.stButton span),
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stCaption {
        color: #1a242c !important;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1a242c !important;
    }
    /* 사이드바 secondary 버튼 텍스트는 기본 색상 유지 */
    [data-testid="stSidebar"] .stButton button {
        color: inherit;
    }

    /* 메인 컨테이너 */
    .block-container {
        max-width: 1300px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        background-color: #e9ebed;
    }

    /* 입력 필드 */
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        background-color: #ffffff !important;
        border: 1px solid #78909c !important;
        border-radius: 4px !important;
        color: #1a242c !important;
        max-width: 480px !important;
    }
    /* 검색 필드는 더 짧게 */
    .stTextInput input[placeholder*="검색"],
    .stTextInput input[placeholder*="S/N"],
    .stTextInput input[placeholder*="시리얼"] {
        max-width: 320px !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: #f4922a !important;
        box-shadow: 0 0 0 2px rgba(230,92,0,0.20) !important;
    }
    /* selectbox, multiselect 너비 제한 */
    .stSelectbox > div > div,
    .stMultiSelect > div > div {
        max-width: 480px !important;
    }
    /* selectbox 드롭다운 팝업 글자 선명하게 */
    [data-baseweb="popover"],
    [data-baseweb="popover"] * {
        -webkit-font-smoothing: antialiased !important;
        -moz-osx-font-smoothing: grayscale !important;
        font-smoothing: antialiased !important;
        opacity: 1 !important;
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
    }
    [data-baseweb="menu"] {
        background: #ffffff !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.25) !important;
        border: 1px solid #78909c !important;
        border-radius: 4px !important;
    }
    [data-baseweb="menu"] li,
    [data-baseweb="option"] {
        color: #1a242c !important;
        font-weight: 500 !important;
        opacity: 1 !important;
        background: #ffffff !important;
    }
    [data-baseweb="menu"] li:hover,
    [data-baseweb="option"]:hover {
        background: #eceff1 !important;
        color: #1a242c !important;
    }
    [aria-selected="true"][data-baseweb="option"] {
        background: #fff3e0 !important;
        color: #1a242c !important;
        font-weight: 700 !important;
    }
    /* number_input 짧게 */
    .stNumberInput {
        max-width: 200px !important;
    }
    /* 파일 업로더 너비 제한 */
    .stFileUploader {
        max-width: 520px !important;
    }

    /* ── 버튼 전체 공통 ── */
    .stButton > button,
    div[data-testid="stFormSubmitButton"] > button,
    button[kind="primary"],
    button[kind="secondary"] {
        display: inline-flex !important; justify-content: center !important; align-items: center !important;
        margin-top: 1px !important; padding: 6px 16px !important;
        min-width: 80px !important; max-width: 100% !important;
        border-radius: 4px !important; font-weight: 700 !important;
        white-space: nowrap !important; overflow: hidden !important;
        text-overflow: ellipsis !important; transition: all 0.15s ease !important;
        letter-spacing: 0.03em !important;
    }
    /* Secondary (기본) → 밝은 회색 */
    .stButton > button:not([kind="primary"]),
    div[data-testid="stFormSubmitButton"] > button:not([kind="primary"]) {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
    }
    .stButton > button:not([kind="primary"]):hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }
    /* Primary → 산업 오렌지 */
    .stButton > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
        background-color: #f4922a !important;
        border: 1px solid #e07a18 !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #e07a18 !important;
    }
    /* ── Streamlit 버튼 선택자 (구버전 baseButton-* + 신버전 stBaseButton-* 동시 지원) ── */
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-secondaryFormSubmit"],
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-secondaryFormSubmit"] {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
    }
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="baseButton-secondaryFormSubmit"]:hover,
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-primaryFormSubmit"],
    button[data-testid="stBaseButton-primary"],
    button[data-testid="stBaseButton-primaryFormSubmit"] {
        background-color: #f4922a !important;
        border: 1px solid #e07a18 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
    }
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="baseButton-primaryFormSubmit"]:hover,
    button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background-color: #e07a18 !important;
        color: #ffffff !important;
    }
    /* disabled 버튼 — 흐리게 표시, 텍스트 색은 유지 */
    button:disabled, button[disabled] {
        opacity: 0.45 !important;
        cursor: not-allowed !important;
    }
    /* 모든 버튼 텍스트 색 강제 (최후 방어) */
    .stButton button p,
    .stButton button span,
    .stButton button div {
        color: inherit !important;
    }
    /* 다운로드 버튼 */
    [data-testid="stDownloadButton"] > button {
        background-color: #eceff1 !important;
        border: 1px solid #78909c !important;
        color: #1a242c !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
        width: 100% !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #cfd8dc !important;
        border-color: #546e7a !important;
        color: #1a242c !important;
    }

    /* 컨테이너 border */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #f5f6f7 !important;
        border: 1px solid #90a4ae !important;
        border-radius: 4px !important;
    }

    /* 탭 */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #cfd8dc;
        border-radius: 4px;
        padding: 2px;
    }
    .stTabs [data-baseweb="tab"] { color: #546e7a !important; font-weight: 600 !important; }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important;
        color: #1a242c !important;
        border-bottom: 3px solid #f4922a !important;
        border-radius: 4px 4px 0 0;
    }

    /* 타이틀 / 섹션 헤더 */
    .centered-title {
        text-align: center; font-weight: bold;
        margin: 20px 0; color: #1a242c !important;
        letter-spacing: 0.05em;
    }
    .section-title {
        background-color: #cfd8dc; color: #1a242c;
        padding: 14px 20px; border-radius: 4px;
        font-weight: 800; margin: 8px 0 20px 0;
        border-left: 6px solid #f4922a;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        box-shadow: 0 2px 4px rgba(0,0,0,0.12);
    }

    /* 본문 텍스트 기본 색상 */
    .stApp p, .stApp label, .stApp .stMarkdown p {
        color: #1a242c;
    }
    /* subheader / h3 / h2 / write 텍스트 */
    .stApp h1, .stApp h2, .stApp h3,
    .stApp h4, .stApp h5, .stApp h6 {
        color: #1a242c !important;
    }
    /* st.write, st.caption 등 일반 텍스트 */
    .stApp .stMarkdown,
    .stApp .stMarkdown p,
    .stApp .stMarkdown span,
    .stApp .stMarkdown strong,
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] span {
        color: #1a242c !important;
    }
    /* metric, caption */
    .stApp [data-testid="stMetricLabel"],
    .stApp [data-testid="stMetricValue"],
    .stApp [data-testid="stCaptionContainer"] {
        color: #546e7a !important;
    }

    /* 통계 박스 */
    .stat-box {
        display: flex; flex-direction: column;
        justify-content: center; align-items: center;
        background-color: #f5f6f7; border-radius: 4px;
        padding: 16px 8px; border: 1px solid #90a4ae;
        margin-bottom: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.10);
        width: 100%; box-sizing: border-box; overflow: hidden;
    }
    .stat-label {
        font-size: clamp(0.65rem, 1vw, 0.88rem); color: #546e7a;
        font-weight: 700; margin-bottom: 8px; white-space: nowrap;
        text-transform: uppercase; letter-spacing: 0.06em;
    }
    .stat-value {
        font-size: clamp(1.4rem, 2vw, 2.4rem); color: #f4922a;
        font-weight: 800; line-height: 1; white-space: nowrap;
    }

    .button-spacer { margin-top: 28px; }

    /* 캘린더 셀 */
    .cal-day-wrap {
        cursor: pointer;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .cal-day-wrap:hover {
        box-shadow: 0 4px 12px rgba(230,92,0,0.25);
        border-color: #f4922a !important;
    }
    .cal-cell {
        background: #f5f6f7;
        border: 1px solid #90a4ae;
        border-radius: 4px;
        padding: 8px 6px;
        min-height: 120px;
        box-sizing: border-box;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        cursor: pointer;
    }
    .cal-cell:hover {
        transform: scale(1.04);
        box-shadow: 0 6px 18px rgba(230,92,0,0.20);
        border-color: #f4922a !important;
        z-index: 999; position: relative;
    }
    .cal-cell.today {
        background: #fff3e0;
        border: 2px solid #f4922a !important;
    }
    .cal-day-num {
        font-weight: bold; color: #1a242c;
        margin-bottom: 4px; font-size: 0.92rem;
    }
    .cal-event {
        border-radius: 3px; padding: 2px 5px;
        margin-bottom: 3px; font-size: 0.63rem; line-height: 1.3;
    }

    /* ── 캘린더 날짜 버튼 ── */
    .cal-day-btn > div > button,
    .cal-day-btn button {
        background-color: transparent !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #1a242c !important;
        font-weight: bold !important;
        font-size: 1.0rem !important;
        min-height: 28px !important;
        height: 28px !important;
        padding: 0 4px !important;
        margin: 0 !important;
        width: 100% !important;
        cursor: pointer !important;
        border-radius: 3px !important;
        transition: background 0.15s !important;
    }
    .cal-day-btn > div > button:hover,
    .cal-day-btn button:hover {
        background-color: #fff3e0 !important;
        color: #f4922a !important;
    }
    .cal-today-btn > div > button,
    .cal-today-btn button {
        color: #f4922a !important;
        font-weight: 900 !important;
    }

    /* ── Expander ── */
    .stExpander {
        border: 1px solid #90a4ae !important;
        border-radius: 4px !important;
        background-color: #f5f6f7 !important;
        margin-bottom: 8px !important;
    }
    .stExpander summary,
    .stExpander [data-testid="stExpanderToggleIcon"],
    .stExpander details summary {
        background-color: #cfd8dc !important;
        border-radius: 4px !important;
        color: #1a242c !important;
        padding: 10px 16px !important;
    }
    .stExpander summary:hover {
        background-color: #b0bec5 !important;
    }
    .stExpander summary p,
    .stExpander summary span,
    .stExpander details summary p {
        color: #1a242c !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }
    /* expander 내부 배경 */
    .stExpander details {
        background-color: #f5f6f7 !important;
        border-radius: 0 0 4px 4px !important;
    }

    /* 좁은 화면 */
    @media (max-width: 900px) {
        .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        .stat-value { font-size: 1.3rem; }
        .cal-cell { min-height: 80px; padding: 5px 4px; }
        .cal-day-num { font-size: 0.78rem; }
        .cal-event { font-size: 0.52rem; }
    }
    </style>
""", unsafe_allow_html=True)


def inject_js():
    """JS 인젝션 (키보드 억제 등)"""
    st.markdown("""
<script>
(function() {
    var _busy = false;
    var _SEARCH_RE = /검색|S\/N|스캔|시리얼/;

    function getLabelText(el) {
        var box = el.closest('[data-testid="stTextInput"]');
        if (!box) return null;
        var lbl = box.querySelector('label');
        return lbl ? lbl.textContent.trim() : null;
    }

    function isSearchInput(el) {
        var t = getLabelText(el) || '';
        var ph = el.getAttribute('placeholder') || '';
        return _SEARCH_RE.test(t) || _SEARCH_RE.test(ph);
    }

    function cleanValue(el) {
        var val = el.value;
        var cleaned = val.replace(/[^a-zA-Z0-9]/g, '');
        if (cleaned === val) return;
        _busy = true;
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, cleaned);
        el.dispatchEvent(new Event('input', {bubbles: true}));
        _busy = false;
    }

    /* 영문/숫자 필터 - 일반 입력 */
    document.addEventListener('input', function(e) {
        if (_busy || !e.target || e.target.tagName !== 'INPUT') return;
        if (!isSearchInput(e.target)) return;
        cleanValue(e.target);
    }, true);

    /* 영문/숫자 필터 - 한글 IME */
    document.addEventListener('compositionend', function(e) {
        if (!e.target || e.target.tagName !== 'INPUT') return;
        if (!isSearchInput(e.target)) return;
        cleanValue(e.target);
    }, true);

    /* ── 스캐너 자동 포커스 복원 ──────────────────────────────────
       Streamlit은 rerun 후 포커스를 body로 이동시킴.
       blur 발생 후 50ms 내 activeElement가 body이면 rerun에 의한
       포커스 소실로 판단 → 해당 입력란을 재포커스 (최대 8회 재시도).
       동일 label을 가진 입력란이 여러 섹션에 있을 경우,
       blur된 입력란의 수직 위치와 가장 가까운 입력란에 포커스. */
    var _lastBlurTop = -1;

    function tryRefocus(label, attempt) {
        attempt = attempt || 0;
        var ae = document.activeElement;
        /* 사용자가 다른 입력 요소를 직접 선택한 경우 중단 */
        if (ae && ae !== document.body && ae !== document.documentElement &&
            (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA')) return;
        var inputs = document.querySelectorAll(
            '[data-testid="stTextInput"] input[type="text"]');
        var bestEl = null, bestDist = Infinity;
        for (var i = 0; i < inputs.length; i++) {
            if (getLabelText(inputs[i]) !== label) continue;
            if (inputs[i].disabled || inputs[i].readOnly || inputs[i].offsetParent === null) continue;
            /* 위치 기반: blur된 입력란과 수직 거리가 가장 가까운 것 선택 */
            var dist = _lastBlurTop >= 0
                ? Math.abs(inputs[i].getBoundingClientRect().top + window.scrollY - _lastBlurTop)
                : i;
            if (dist < bestDist) { bestDist = dist; bestEl = inputs[i]; }
        }
        if (bestEl) { bestEl.focus(); return; }
        /* 아직 rerun 완료 전 - 최대 8회(약 2초) 재시도 */
        if (attempt < 8) {
            setTimeout(function() { tryRefocus(label, attempt + 1); }, 250);
        }
    }

    document.addEventListener('blur', function(e) {
        if (!e.target || e.target.tagName !== 'INPUT') return;
        if (!isSearchInput(e.target)) return;
        var label = getLabelText(e.target);
        var r = e.target.getBoundingClientRect();
        _lastBlurTop = r.top + window.scrollY;
        setTimeout(function() {
            var ae = document.activeElement;
            if (ae === document.body || ae === document.documentElement) {
                tryRefocus(label, 0);
            }
        }, 50);
    }, true);

    /* ── 드랍박스 키보드 억제 ────────────────────────────────────────
       selectbox 내부 input에 inputmode=none 적용 → 드랍박스 탭 시
       소프트 키보드 미표시. "직접 입력" 텍스트 필드는 제외. */
    function suppressSelectboxKeyboard() {
        document.querySelectorAll('[data-testid="stSelectbox"] input').forEach(function(el) {
            el.setAttribute('inputmode', 'none');
        });
    }
    suppressSelectboxKeyboard();
    var _sbObs = new MutationObserver(function() {
        suppressSelectboxKeyboard();
    });
    _sbObs.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)
