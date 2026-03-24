"""
유틸리티 함수 모듈
- 시간 유틸
- 텔레그램 알림
- UI 헬퍼 (autofocus, notify popup)
- Google Drive 업로드
"""

import requests
import streamlit as st
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# =================================================================
# 시간 유틸
# =================================================================

def get_now_kst_str() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')


# =================================================================
# UI 헬퍼
# =================================================================

def _inject_autofocus(label: str = None, placeholder: str = None):
    """스캔 입력 후 재렌더 시 text input에 자동 포커스 (JS 주입).
    placeholder 지정 시 placeholder 속성으로 탐색 (가장 정확).
    label 지정 시 aria-label로 탐색.
    둘 다 없으면 페이지의 첫 번째 활성 text input에 포커스.
    """
    import streamlit.components.v1 as components
    if placeholder:
        safe = placeholder.replace('"', '\\"')
        js = (
            f'<script>(function(){{'
            f'function f(){{'
            f'var inp=window.parent.document.querySelector(\'input[placeholder="{safe}"]\');'
            f'if(inp&&!inp.disabled&&!inp.readOnly&&inp.offsetParent!==null)'
            f'{{inp.focus();return true;}}return false;}}'
            f'if(!f()){{setTimeout(function(){{if(!f())setTimeout(f,300);}},100);}}'
            f'}})();</script>'
        )
    elif label:
        safe = label.replace('"', '\\"')
        js = (
            f'<script>(function(){{'
            f'function f(){{'
            f'var inp=window.parent.document.querySelector(\'input[aria-label="{safe}"]\');'
            f'if(inp&&!inp.disabled&&!inp.readOnly&&inp.offsetParent!==null)'
            f'{{inp.focus();return true;}}return false;}}'
            f'if(!f()){{setTimeout(function(){{if(!f())setTimeout(f,300);}},100);}}'
            f'}})();</script>'
        )
    else:
        js = (
            "<script>(function(){function f(){var els=window.parent.document"
            ".querySelectorAll('input[type=text]');for(var i=0;i<els.length;i++)"
            "{var e=els[i];if(!e.disabled&&!e.readOnly&&e.offsetParent!==null)"
            "{e.focus();return true;}}return false;}"
            "if(!f()){setTimeout(function(){if(!f())setTimeout(f,300);},100);}})();"
            "</script>"
        )
    components.html(js, height=0, scrolling=False)


def notify_new_arrivals(curr_cnt: int, notif_key: str, label: str):
    """입고 대기 수량이 증가하면 가운데 팝업 알림 + 사운드를 출력한다."""
    import html as _html_mod
    prev = st.session_state.get(notif_key, -1)
    if curr_cnt > 0 and curr_cnt > prev:
        _safe_label = _html_mod.escape(str(label))
        now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
        st.components.v1.html(f"""
        <script>
        (function(){{
            var pdoc = window.parent.document;

            // ── 사운드 ──
            try {{
                var AudioCtx = window.parent.AudioContext || window.parent.webkitAudioContext;
                var ctx = new AudioCtx();
                function beep(freq, t, dur) {{
                    var o = ctx.createOscillator();
                    var g = ctx.createGain();
                    o.connect(g); g.connect(ctx.destination);
                    o.type = 'sine';
                    o.frequency.setValueAtTime(freq, t);
                    g.gain.setValueAtTime(0.4, t);
                    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
                    o.start(t); o.stop(t + dur);
                }}
                var t = ctx.currentTime;
                beep(880,  t,       0.18);
                beep(1100, t+0.22,  0.18);
                beep(1320, t+0.44,  0.25);
            }} catch(e) {{}}

            // ── 기존 팝업 제거 ──
            var existing = pdoc.getElementById('sld_notif_overlay');
            if (existing) existing.remove();

            // ── 애니메이션 스타일 ──
            if (!pdoc.getElementById('sld_notif_style')) {{
                var s = pdoc.createElement('style');
                s.id = 'sld_notif_style';
                s.textContent = '@keyframes sldPopIn {{from{{transform:scale(0.6);opacity:0}}to{{transform:scale(1);opacity:1}}}}';
                pdoc.head.appendChild(s);
            }}

            // ── 오버레이 ──
            var overlay = pdoc.createElement('div');
            overlay.id = 'sld_notif_overlay';
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.55);z-index:999999;display:flex;align-items:center;justify-content:center;';

            // ── 팝업 박스 ──
            var box = pdoc.createElement('div');
            box.style.cssText = 'background:#fff;border-radius:20px;padding:44px 60px;text-align:center;box-shadow:0 12px 48px rgba(0,0,0,0.4);animation:sldPopIn 0.3s ease;min-width:340px;';
            box.innerHTML =
                '<div style="font-size:3.5rem;margin-bottom:12px;">📥</div>'
                + '<div style="font-size:1.6rem;font-weight:800;color:#1a1a2e;margin-bottom:8px;">입고 대기 알림</div>'
                + '<div style="font-size:1.05rem;color:#2E75B6;font-weight:600;margin-bottom:8px;">{_safe_label}</div>'
                + '<div style="font-size:2.6rem;font-weight:900;color:#c8605a;margin-bottom:28px;">{curr_cnt}건 도착!</div>'
                + '<button id="sld_notif_btn" style="background:#2E75B6;color:#fff;border:none;border-radius:10px;padding:14px 44px;font-size:1.15rem;cursor:pointer;font-weight:700;">✅ 확인</button>';

            overlay.appendChild(box);
            pdoc.body.appendChild(overlay);

            pdoc.getElementById('sld_notif_btn').addEventListener('click', function(){{
                overlay.remove();
            }});
        }})();
        </script>
        """, height=0)
    st.session_state[notif_key] = curr_cnt


# =================================================================
# 텔레그램 알림
# =================================================================

def _get_tg_creds():
    """TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID를 최상위 또는 theme 섹션에서 찾아 반환."""
    token, chat = "", ""
    for _key in ("TELEGRAM_BOT_TOKEN",):
        try: token = str(st.secrets[_key]).strip(); break
        except (KeyError, AttributeError): pass
        try: token = str(st.secrets["theme"][_key]).strip(); break
        except (KeyError, AttributeError): pass
    for _key in ("TELEGRAM_CHAT_ID",):
        try: chat = str(st.secrets[_key]).strip(); break
        except (KeyError, AttributeError): pass
        try: chat = str(st.secrets["theme"][_key]).strip(); break
        except (KeyError, AttributeError): pass
    return token, chat


_TG_SENT_CACHE: set = set()   # 프로세스 내 중복 전송 방지 캐시

try:
    _TELEGRAM_BOT_TOKEN, _TELEGRAM_CHAT_ID = _get_tg_creds()
except Exception:
    _TELEGRAM_BOT_TOKEN, _TELEGRAM_CHAT_ID = "", ""


def _send_telegram(message: str) -> str:
    """텔레그램 메시지 전송. 성공 시 'ok', 실패 시 오류 문자열 반환."""
    _token, _chat = _get_tg_creds()
    if not _token or not _chat:
        return "전송 실패: TELEGRAM 시크릿 없음"
    try:
        url = f"https://api.telegram.org/bot{_token}/sendMessage"
        res = requests.post(url, json={"chat_id": _chat, "text": message, "parse_mode": "HTML"}, timeout=10)
        if res.ok:
            return "ok"
        return f"HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return str(e)


# =================================================================
# Google Drive 이미지 업로드
# =================================================================

def upload_img_to_drive(file_obj, serial_no: str) -> str:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        gcp_info  = st.secrets["connections"]["gsheets"]
        creds     = service_account.Credentials.from_service_account_info(gcp_info)
        drive_svc = build('drive', 'v3', credentials=creds)
        folder_id = gcp_info.get("image_folder_id")
        meta      = {'name': f"REPAIR_{serial_no}.jpg", 'parents': [folder_id]}
        media     = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        uploaded  = drive_svc.files().create(body=meta, media_body=media, fields='id,webViewLink').execute()
        return uploaded.get('webViewLink', "")
    except Exception:
        return "⚠️ 이미지 업로드에 실패했습니다. 관리자에게 문의하세요."
