#!/usr/bin/env python3
"""
SMART LOGISTICS DASHBOARD — 모니터링 봇
========================================
Supabase 데이터를 주기적으로 감시하고 Telegram으로 알림을 보냅니다.

감시 항목:
  1. 중복 시리얼  — 동일 S/N이 활성 레코드에 2건 이상 존재
  2. 상태 이상    — STUCK_HOURS 이상 진행 상태로 멈춰있는 레코드
  3. DB 연결 오류 — Supabase 연결 실패
  4. 데이터 정합성 — NULL 시리얼, 잘못된 상태값, 반 필드 누락

실행 방법:
  python monitor.py          # 상시 루프 (standalone)
  python monitor.py --once   # 1회 실행 (GitHub Actions / cron)
"""

import os
import sys
import json
import time
import hashlib
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ─── 설정 ─────────────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL_SEC  = int(os.getenv("CHECK_INTERVAL_SEC", "300"))   # 기본 5분
STUCK_HOURS         = int(os.getenv("STUCK_HOURS", "8"))            # 기본 8시간

KST = timezone(timedelta(hours=9))

# 시스템에서 사용하는 유효한 상태값
VALID_STATES = {
    "조립중", "검사대기", "검사중", "OQC대기", "OQC중",
    "출하승인", "포장대기", "포장중", "완료",
    "수리 완료(재투입)", "불량 처리 중", "교체됨", "부적합(OQC)",
}

# 장시간 정체 감시 대상 상태 (완료·교체됨은 제외)
ACTIVE_STATES = {
    "조립중", "검사대기", "검사중", "OQC대기", "OQC중",
    "출하승인", "포장대기", "포장중", "수리 완료(재투입)", "불량 처리 중",
}

# ─── 로거 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("monitor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── Supabase 클라이언트 ───────────────────────────────────────────────────────
def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── Telegram 알림 ────────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    """Telegram 봇으로 메시지 전송. 성공 시 True."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram 미설정 — 콘솔 출력으로 대체:\n%s", message)
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("Telegram 알림 전송 완료")
            return True
        log.error("Telegram 전송 실패: HTTP %s — %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        log.error("Telegram 예외: %s", exc)
        return False


# ─── 중복 알림 방지 (상태 파일) ───────────────────────────────────────────────
_STATE_FILE = "monitor_state.json"


def load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error("상태 파일 저장 실패: %s", exc)


def issue_hash(issues: list) -> str:
    """이슈 목록 → MD5 해시 (동일 이슈 재알림 방지)"""
    payload = json.dumps(sorted(issues), ensure_ascii=False).encode()
    return hashlib.md5(payload).hexdigest()


# ─── 감시 함수 ────────────────────────────────────────────────────────────────
def check_db_connection(sb: Client) -> tuple[bool, str]:
    """Supabase 연결 확인. (성공 여부, 에러 메시지) 반환."""
    try:
        sb.table("production").select("시리얼").limit(1).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def check_duplicate_serials(sb: Client) -> list[dict]:
    """
    deleted_at IS NULL 레코드에서 동일 시리얼이 2건 이상인 경우 반환.
    [{"시리얼": "...", "건수": 2, "상태목록": [...]}]
    """
    try:
        res = (
            sb.table("production")
            .select("시리얼,반,모델,상태")
            .is_("deleted_at", "null")
            .execute()
        )
        data = res.data or []
        counts = Counter(r["시리얼"] for r in data if r.get("시리얼", "").strip())
        result = []
        for sn, cnt in counts.items():
            if cnt > 1:
                rows = [r for r in data if r.get("시리얼") == sn]
                result.append(
                    {
                        "시리얼": sn,
                        "건수": cnt,
                        "상태목록": [r.get("상태", "?") for r in rows],
                        "반목록": list({r.get("반", "?") for r in rows}),
                    }
                )
        return result
    except Exception as exc:
        log.error("중복 시리얼 체크 오류: %s", exc)
        return []


def check_stuck_records(sb: Client, hours: int) -> list[dict]:
    """
    ACTIVE_STATES 상태에서 hours 시간 이상 변경 없는 레코드 반환.
    """
    try:
        cutoff = (datetime.now(KST) - timedelta(hours=hours)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        res = (
            sb.table("production")
            .select("시리얼,모델,반,상태,시간")
            .in_("상태", list(ACTIVE_STATES))
            .is_("deleted_at", "null")
            .lte("시간", cutoff)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        log.error("정체 레코드 체크 오류: %s", exc)
        return []


def check_data_integrity(sb: Client) -> list[str]:
    """
    데이터 정합성 이슈 탐지.
    - 빈/NULL 시리얼
    - 허용되지 않는 상태값
    - 반(班) 필드 누락
    """
    issues = []
    try:
        res = (
            sb.table("production")
            .select("시리얼,반,모델,상태")
            .is_("deleted_at", "null")
            .execute()
        )
        data = res.data or []

        # 1. 빈/NULL 시리얼
        empty_sn = [r for r in data if not r.get("시리얼", "").strip()]
        if empty_sn:
            bans = ", ".join(sorted({r.get("반", "?") for r in empty_sn}))
            issues.append(f"빈 시리얼 {len(empty_sn)}건 (반: {bans})")

        # 2. 유효하지 않은 상태값
        invalid = [r for r in data if r.get("상태", "") not in VALID_STATES]
        if invalid:
            bad = ", ".join(sorted({r.get("상태", "?") for r in invalid}))
            issues.append(f"잘못된 상태값 {len(invalid)}건: [{bad}]")

        # 3. 반(班) 필드 누락
        no_ban = [r for r in data if not r.get("반", "").strip()]
        if no_ban:
            issues.append(f"반(班) 필드 누락 {len(no_ban)}건")

    except Exception as exc:
        log.error("정합성 체크 오류: %s", exc)
        issues.append(f"정합성 체크 실패: {exc}")
    return issues


# ─── 메시지 포맷 ──────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


def build_alert_message(
    duplicates: list, stuck: list, integrity: list
) -> Optional[str]:
    """이슈가 1건 이상일 때만 알림 메시지 반환, 없으면 None."""
    if not duplicates and not stuck and not integrity:
        return None

    lines = [f"🚨 <b>생산 시스템 이상 감지</b>\n🕐 {_now()}\n"]

    if duplicates:
        lines.append(f"⚠️ <b>중복 시리얼 {len(duplicates)}건</b>")
        for d in duplicates[:5]:
            states = " / ".join(d["상태목록"])
            lines.append(
                f"  • <code>{d['시리얼']}</code>  "
                f"{d['건수']}개 중복  [{states}]  반: {', '.join(d['반목록'])}"
            )
        if len(duplicates) > 5:
            lines.append(f"  … 외 {len(duplicates) - 5}건")
        lines.append("")

    if stuck:
        lines.append(
            f"⏰ <b>장시간 정체 {len(stuck)}건</b>  ({STUCK_HOURS}h 이상 미처리)"
        )
        for r in stuck[:5]:
            ts = str(r.get("시간", ""))[:16]
            lines.append(
                f"  • <code>{r.get('시리얼','?')}</code>  "
                f"[{r.get('반','?')}]  {r.get('상태','?')}  {ts}"
            )
        if len(stuck) > 5:
            lines.append(f"  … 외 {len(stuck) - 5}건")
        lines.append("")

    if integrity:
        lines.append("🔴 <b>데이터 정합성 이슈</b>")
        for iss in integrity:
            lines.append(f"  • {iss}")

    return "\n".join(lines)


def build_recovery_message() -> str:
    return f"✅ <b>모든 이슈 해결됨</b>\n🕐 {_now()}\n생산 시스템이 정상 상태입니다."


# ─── 메인 로직 ────────────────────────────────────────────────────────────────
def run_once() -> None:
    """한 번 실행 (GitHub Actions / cron 단일 호출용)."""
    log.info("━━━ 모니터링 체크 시작 ━━━")
    state = load_state()

    # ── DB 연결 확인 ──────────────────────────────────────────────────────────
    try:
        sb = get_client()
    except ValueError as exc:
        log.error("설정 오류: %s", exc)
        return

    ok, err = check_db_connection(sb)
    if not ok:
        log.error("DB 연결 실패: %s", err)
        if state.get("last_db_error") != err:
            send_telegram(
                f"🔴 <b>DB 연결 오류</b>\n🕐 {_now()}\n<code>{err}</code>"
            )
            state["last_db_error"] = err
            save_state(state)
        return

    # DB 연결 복구 시 알림
    if state.pop("last_db_error", None):
        send_telegram(f"✅ <b>DB 연결 복구됨</b>\n🕐 {_now()}")

    # ── 각 항목 체크 ──────────────────────────────────────────────────────────
    duplicates = check_duplicate_serials(sb)
    stuck      = check_stuck_records(sb, STUCK_HOURS)
    integrity  = check_data_integrity(sb)

    log.info(
        "결과 — 중복시리얼: %d건 / 정체레코드: %d건 / 정합성이슈: %d건",
        len(duplicates), len(stuck), len(integrity),
    )

    # ── 중복 알림 방지 ────────────────────────────────────────────────────────
    current_keys = (
        [f"dup:{d['시리얼']}" for d in duplicates]
        + [f"stuck:{r.get('시리얼','?')}:{r.get('상태','?')}" for r in stuck]
        + [f"int:{i}" for i in integrity]
    )
    h = issue_hash(current_keys)
    had_issues = bool(state.get("last_issue_hash"))

    if current_keys:
        if h != state.get("last_issue_hash"):
            msg = build_alert_message(duplicates, stuck, integrity)
            if msg:
                send_telegram(msg)
            state["last_issue_hash"] = h
        else:
            log.info("동일 이슈 재감지 — 중복 알림 건너뜀")
    else:
        if had_issues:
            send_telegram(build_recovery_message())
        state["last_issue_hash"] = ""

    save_state(state)
    log.info("━━━ 모니터링 체크 완료 ━━━")


def run_loop() -> None:
    """상시 루프 실행 (standalone 서버용)."""
    log.info(
        "모니터링 봇 시작  |  주기: %ds  |  정체 기준: %dh",
        CHECK_INTERVAL_SEC,
        STUCK_HOURS,
    )
    while True:
        try:
            run_once()
        except Exception as exc:
            log.exception("예외 발생: %s", exc)
        time.sleep(CHECK_INTERVAL_SEC)


# ─── 진입점 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()
