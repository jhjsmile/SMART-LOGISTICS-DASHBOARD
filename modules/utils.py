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
    iframe 위치 기준으로 가장 가까운 입력란에 포커스 (동일 label/placeholder가
    여러 섹션에 존재할 때 첫 번째 요소가 아닌 올바른 요소를 선택).
    placeholder 지정 시 placeholder 속성으로 후보 필터링.
    label 지정 시 aria-label로 후보 필터링.
    둘 다 없으면 모든 활성 text input 중 가장 가까운 것에 포커스.
    """
    import streamlit.components.v1 as components
    if placeholder:
        safe = placeholder.replace('"', '\\"')
        selector = f'input[placeholder="{safe}"]'
    elif label:
        safe = label.replace('"', '\\"')
        selector = f'input[aria-label="{safe}"]'
    else:
        selector = 'input[type="text"]'
    js = (
        f'<script>(function(){{'
        f'function f(){{'
        f'var pdoc=window.parent.document;'
        f'var inputs=pdoc.querySelectorAll(\'{selector}\');'
        f'if(!inputs.length)return false;'
        f'var ifr=window.frameElement;'
        f'if(ifr){{'
        f'var ir=ifr.getBoundingClientRect();'
        f'var best=null,bestD=Infinity;'
        f'for(var i=0;i<inputs.length;i++){{'
        f'var inp=inputs[i];'
        f'if(inp.disabled||inp.readOnly||inp.offsetParent===null)continue;'
        f'var r=inp.getBoundingClientRect();'
        f'var d=Math.abs(r.bottom-ir.top)+Math.abs(r.left-ir.left);'
        f'if(d<bestD){{bestD=d;best=inp;}}}}'
        f'if(best){{best.focus();var bl=best.value.length;best.setSelectionRange(bl,bl);return true;}}}}'
        f'var inp=inputs[0];'
        f'if(inp&&!inp.disabled&&!inp.readOnly&&inp.offsetParent!==null)'
        f'{{inp.focus();var il=inp.value.length;inp.setSelectionRange(il,il);return true;}}return false;}}'
        f'if(!f()){{setTimeout(function(){{if(!f())setTimeout(f,300);}},100);}}'
        f'}})();</script>'
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


# =================================================================
# 모바일 카메라 바코드 스캐너
# =================================================================

def render_mobile_camera_scanner(target_placeholder: str, key: str = "cam_scan"):
    """모바일/태블릿 전용 카메라 바코드 스캐너 버튼을 렌더링한다.

    iOS Safari/Chrome 호환을 위해 네이티브 카메라 캡처(<input capture>) 방식을 사용한다.
    사진 촬영 → 캔버스 리사이즈 → 바코드 디코딩 → 결과를 text_input에 주입.

    디코딩 순서:
      1) BarcodeDetector API (Chrome Android 등 네이티브 지원 시)
      2) html5-qrcode 라이브러리 (동적 로드)

    PC (화면 너비 > 1024px)에서는 자동으로 숨겨진다.

    Args:
        target_placeholder: 스캔 결과를 넣을 text_input의 placeholder 문자열
        key: Streamlit 위젯 키 (중복 방지용)
    """
    import streamlit.components.v1 as components
    import html as _h

    safe_placeholder = _h.escape(target_placeholder).replace("'", "\\'")
    cid = _h.escape(key).replace("'", "\\'").replace("-", "_")

    html_code = (
        '<style>'
        f'.cam-wrap-{cid} {{ display: none; }}'
        f'@media (max-width: 1024px) {{ .cam-wrap-{cid} {{ display: block; }} }}'
        f'.cam-wrap-{cid} label {{'
        '  display: block; background: #1a73e8; color: #fff; border: none;'
        '  border-radius: 8px; padding: 10px 16px; font-size: 0.85rem;'
        '  font-weight: 600; cursor: pointer; text-align: center; margin: 4px 0;'
        '}'
        f'.cam-wrap-{cid} label:active {{ background: #1558b0; }}'
        f'.cam-wrap-{cid} input[type="file"] {{ display: none; }}'
        f'#cam-status-{cid} {{'
        '  text-align: center; padding: 4px; font-size: 0.8rem;'
        '  font-weight: 600; min-height: 20px;'
        '}'
        '</style>'
        f'<div class="cam-wrap-{cid}">'
        f'  <label for="cam-file-{cid}">카메라 스캔</label>'
        f'  <input type="file" id="cam-file-{cid}" accept="image/*" capture="environment">'
        f'  <div id="cam-status-{cid}"></div>'
        '</div>'
        '<script>'
        '(function() {'
        f'  var fileInput = document.getElementById("cam-file-{cid}");'
        f'  var status = document.getElementById("cam-status-{cid}");'
        '  if (!fileInput || !status) return;'
        ''
        '  fileInput.addEventListener("change", function() {'
        '    if (!fileInput.files || !fileInput.files[0]) return;'
        '    var origFile = fileInput.files[0];'
        '    status.textContent = "이미지 처리 중...";'
        '    status.style.color = "#1a73e8";'
        ''
        '    var reader = new FileReader();'
        '    reader.onerror = function() {'
        '      status.textContent = "파일 읽기 실패";'
        '      status.style.color = "#d93025";'
        '      fileInput.value = "";'
        '    };'
        '    reader.onload = function(ev) {'
        '      var img = new Image();'
        '      img.onerror = function() {'
        '        status.textContent = "이미지 로드 실패";'
        '        status.style.color = "#d93025";'
        '        fileInput.value = "";'
        '      };'
        '      img.onload = function() {'
        '        var MAX = 1200;'
        '        var w = img.width, h = img.height;'
        '        if (w > MAX || h > MAX) {'
        '          var ratio = Math.min(MAX / w, MAX / h);'
        '          w = Math.round(w * ratio);'
        '          h = Math.round(h * ratio);'
        '        }'
        '        var canvas = document.createElement("canvas");'
        '        canvas.width = w; canvas.height = h;'
        '        var ctx = canvas.getContext("2d");'
        '        ctx.drawImage(img, 0, 0, w, h);'
        '        status.textContent = "바코드 검색 중...";'
        ''
        '        /* 1) BarcodeDetector API */'
        '        if (typeof BarcodeDetector !== "undefined") {'
        '          try {'
        '            var detector = new BarcodeDetector({'
        '              formats: ["code_128","code_39","code_93","ean_13","ean_8",'
        '                        "upc_a","upc_e","itf","codabar","qr_code","data_matrix"]'
        '            });'
        '            detector.detect(canvas)'
        '              .then(function(barcodes) {'
        '                if (barcodes && barcodes.length > 0) {'
        f'                  injectResult("{cid}", barcodes[0].rawValue, status, fileInput);'
        '                } else {'
        '                  status.textContent = "바코드를 찾지 못함 — 가까이서 다시 촬영";'
        '                  status.style.color = "#d93025";'
        '                  fileInput.value = "";'
        '                }'
        '              })'
        '              .catch(function() {'
        f'                tryLib("{cid}", canvas, status, fileInput);'
        '              });'
        '            return;'
        '          } catch(e) {}'
        '        }'
        ''
        '        /* 2) html5-qrcode fallback */'
        f'        tryLib("{cid}", canvas, status, fileInput);'
        '      };'
        '      img.src = ev.target.result;'
        '    };'
        '    reader.readAsDataURL(origFile);'
        '  });'
        '})();'
        ''
        '/* html5-qrcode 라이브러리로 스캔 */'
        'function tryLib(cid, canvas, status, fileInput) {'
        '  function doScan() {'
        '    canvas.toBlob(function(blob) {'
        '      if (!blob) {'
        '        status.textContent = "이미지 변환 실패";'
        '        status.style.color = "#d93025";'
        '        fileInput.value = "";'
        '        return;'
        '      }'
        '      var scanFile = new File([blob], "scan.jpg", { type: "image/jpeg" });'
        '      var rdiv = document.createElement("div");'
        '      rdiv.id = "cam_rd_" + cid + "_" + Date.now();'
        '      rdiv.style.display = "none";'
        '      document.body.appendChild(rdiv);'
        '      try {'
        '        var html5qr = new Html5Qrcode(rdiv.id, {'
        '          formatsToSupport: ['
        '            Html5QrcodeSupportedFormats.QR_CODE,'
        '            Html5QrcodeSupportedFormats.CODE_128,'
        '            Html5QrcodeSupportedFormats.CODE_39,'
        '            Html5QrcodeSupportedFormats.CODE_93,'
        '            Html5QrcodeSupportedFormats.EAN_13,'
        '            Html5QrcodeSupportedFormats.EAN_8,'
        '            Html5QrcodeSupportedFormats.UPC_A,'
        '            Html5QrcodeSupportedFormats.UPC_E,'
        '            Html5QrcodeSupportedFormats.ITF,'
        '            Html5QrcodeSupportedFormats.CODABAR,'
        '            Html5QrcodeSupportedFormats.DATA_MATRIX'
        '          ], verbose: false'
        '        });'
        '        html5qr.scanFile(scanFile, false)'
        '          .then(function(decoded) {'
        '            try { html5qr.clear(); } catch(e) {}'
        '            try { rdiv.remove(); } catch(e) {}'
        f'            injectResult(cid, decoded, status, fileInput);'
        '          })'
        '          .catch(function(err) {'
        '            try { html5qr.clear(); } catch(e) {}'
        '            try { rdiv.remove(); } catch(e) {}'
        '            status.textContent = "인식 실패 — 가까이서 다시 촬영해주세요";'
        '            status.style.color = "#d93025";'
        '            fileInput.value = "";'
        '          });'
        '      } catch(ex) {'
        '        try { rdiv.remove(); } catch(e) {}'
        '        status.textContent = "스캔 오류: " + String(ex).substring(0, 60);'
        '        status.style.color = "#d93025";'
        '        fileInput.value = "";'
        '      }'
        '    }, "image/jpeg", 0.85);'
        '  }'
        ''
        '  if (typeof Html5Qrcode !== "undefined") {'
        '    doScan();'
        '  } else {'
        '    status.textContent = "스캔 라이브러리 로딩...";'
        '    var s = document.createElement("script");'
        '    s.src = "https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js";'
        '    s.onload = function() { doScan(); };'
        '    s.onerror = function() {'
        '      status.textContent = "라이브러리 로드 실패 (네트워크 확인)";'
        '      status.style.color = "#d93025";'
        '      fileInput.value = "";'
        '    };'
        '    document.head.appendChild(s);'
        '  }'
        '}'
        ''
        '/* 스캔 결과를 가장 가까운 input에 주입 */'
        'function injectResult(cid, decoded, status, fileInput) {'
        '  status.textContent = decoded;'
        '  status.style.color = "#1e8e3e";'
        '  fileInput.value = "";'
        ''
        '  var pdoc = window.parent.document;'
        f'  var inputs = pdoc.querySelectorAll(\'input[placeholder*="{safe_placeholder}"]\');'
        '  if (!inputs.length) inputs = pdoc.querySelectorAll(\'input[type="text"]\');'
        '  var ifr = window.frameElement;'
        '  var target = null;'
        '  if (ifr && inputs.length) {'
        '    var ir = ifr.getBoundingClientRect();'
        '    var bestD = Infinity;'
        '    for (var i = 0; i < inputs.length; i++) {'
        '      var inp = inputs[i];'
        '      if (inp.disabled || inp.readOnly || inp.offsetParent === null) continue;'
        '      var r = inp.getBoundingClientRect();'
        '      var d = Math.abs(r.top - ir.top) + Math.abs(r.left - ir.left);'
        '      if (d < bestD) { bestD = d; target = inp; }'
        '    }'
        '  }'
        '  if (!target && inputs.length) target = inputs[0];'
        '  if (target) {'
        '    var nativeSet = Object.getOwnPropertyDescriptor('
        '      window.parent.HTMLInputElement.prototype, "value").set;'
        '    nativeSet.call(target, decoded);'
        '    target.dispatchEvent(new Event("input", { bubbles: true }));'
        '    setTimeout(function() {'
        '      target.dispatchEvent('
        '        new KeyboardEvent("keydown", { key: "Enter", code: "Enter",'
        '          keyCode: 13, which: 13, bubbles: true }));'
        '    }, 150);'
        '  }'
        '}'
        '</script>'
    )
    components.html(html_code, height=55, scrolling=False)
