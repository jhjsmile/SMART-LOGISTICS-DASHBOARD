"""
Supabase Realtime 백그라운드 리스너
====================================
- 모듈 레벨로 관리 → Streamlit rerun 사이에서도 스레드 유지
- DB 테이블 변경 감지 시 테이블명을 _changed 집합에 추가
- 메인 앱은 pop_changed_tables() 로 변경 목록을 가져간 뒤
  해당 테이블의 캐시만 초기화

사용 예:
    from modules.realtime import start_realtime, pop_changed_tables

    # 앱 최초 실행 시 1회 (이미 실행 중이면 무시)
    start_realtime(url, key)

    # 매 rerun 마다
    changed = pop_changed_tables()   # set[str] – 변경된 테이블 목록
    if changed:
        clear_cache_for_tables(changed)
"""

import asyncio
import logging
import threading
from typing import Set

log = logging.getLogger(__name__)

# ── 모듈 레벨 상태 (rerun 간 유지) ─────────────────────────────────
_changed: Set[str] = set()
_lock = threading.Lock()
_thread: threading.Thread | None = None

# 실시간 감시 테이블 목록
WATCHED_TABLES = [
    "production",
    "production_schedule",
    "audit_log",
    "material_serial",
    "production_plan",
    "plan_change_log",
]


# ── 공개 API ────────────────────────────────────────────────────────

def pop_changed_tables() -> Set[str]:
    """변경된 테이블 집합을 반환하고 내부 집합 초기화."""
    with _lock:
        result = set(_changed)
        _changed.clear()
    return result


def has_changes() -> bool:
    with _lock:
        return bool(_changed)


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start_realtime(url: str, key: str) -> None:
    """Realtime 리스너 스레드 시작 (이미 실행 중이면 무시)."""
    global _thread
    if is_running():
        return
    _thread = threading.Thread(
        target=_listener_loop,
        args=(url, key),
        daemon=True,
        name="supabase-realtime",
    )
    _thread.start()
    log.info("Supabase Realtime 리스너 스레드 시작")


# ── 내부 구현 ────────────────────────────────────────────────────────

def _mark_changed(table: str):
    with _lock:
        _changed.add(table)
    log.debug("Realtime 변경 감지: %s", table)


def _make_callback(table: str):
    def _cb(payload):
        _mark_changed(table)
    return _cb


def _listener_loop(url: str, key: str) -> None:
    """백그라운드 스레드 진입점 – asyncio 루프를 직접 실행."""
    asyncio.run(_async_listener(url, key))


async def _async_listener(url: str, key: str) -> None:
    """
    Supabase async 클라이언트로 Postgres Changes 구독.
    연결 오류 시 지수 백오프로 재시도.
    """
    backoff = 5  # 초기 재시도 대기 (초)

    while True:
        client = None
        try:
            # supabase-py v2 비동기 클라이언트
            try:
                from supabase._async.client import AsyncClient  # noqa: F401
                from supabase import acreate_client
            except ImportError:
                # 구버전 호환
                from supabase import create_async_client as acreate_client  # type: ignore

            client = await acreate_client(url, key)
            channels = []

            for table in WATCHED_TABLES:
                ch = client.channel(f"rt-{table}")
                ch.on_postgres_changes(
                    event="*",
                    schema="public",
                    table=table,
                    callback=_make_callback(table),
                )
                await ch.subscribe()
                channels.append(ch)

            log.info(
                "Supabase Realtime 연결 완료 (%d 테이블 구독)", len(WATCHED_TABLES)
            )
            backoff = 5  # 성공 시 백오프 초기화

            # 연결 유지 (30초마다 살아있음 확인)
            while True:
                await asyncio.sleep(30)

        except Exception as exc:
            log.warning(
                "Realtime 연결 오류 – %ds 후 재시도: %s", backoff, exc
            )
            # 채널 정리 시도
            if client and "channels" in dir(client):
                try:
                    for ch in channels:  # type: ignore[name-defined]
                        await client.remove_channel(ch)
                except Exception:
                    pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)  # 최대 60초 대기
