"""
Supabase DB 함수 모듈
- 연결 관리 (get_supabase, keep_supabase_alive)
- 캐시 초기화 헬퍼
- 생산 이력 / 감사 로그 / 자재 시리얼 / 일정 / 계획 / 마스터 CRUD
"""

import re
import threading
import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta, date
from supabase import create_client, Client

from modules.utils import get_now_kst_str, _send_telegram

# 모듈 내부 상수 (메인 파일 constants 미러)
_KST              = timezone(timedelta(hours=9))
_PRODUCTION_GROUPS = ["제조1반", "제조2반", "제조3반"]
_DEFAULT_PAGE_SIZE = 100
_MAX_AUDIT_LOG_ROWS = 200

# =================================================================
# 서버사이드 로그인 잠금 (프로세스 공유 — session_state 우회 방지)
# =================================================================
# 구조: {"username": {"count": int, "lockout_until": float}}
_LOGIN_ATTEMPTS: dict = {}
_LOGIN_LOCK = threading.Lock()


def check_login_lockout(username: str) -> tuple:
    """잠금 여부 반환. (is_locked: bool, remaining_seconds: int)"""
    with _LOGIN_LOCK:
        info = _LOGIN_ATTEMPTS.get(username, {})
        lockout_until = info.get("lockout_until", 0.0)
        now = datetime.now(_KST).timestamp()
        if lockout_until > now:
            return True, int(lockout_until - now)
        return False, 0


def record_login_failure(username: str, max_attempts: int, lockout_seconds: int) -> int:
    """실패 횟수 기록. 초과 시 잠금 설정. 현재 시도 횟수 반환."""
    with _LOGIN_LOCK:
        info = _LOGIN_ATTEMPTS.setdefault(username, {"count": 0, "lockout_until": 0.0})
        info["count"] += 1
        if info["count"] >= max_attempts:
            info["lockout_until"] = datetime.now(_KST).timestamp() + lockout_seconds
        return info["count"]


def clear_login_attempts(username: str) -> None:
    """로그인 성공 시 잠금 카운터 초기화."""
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(username, None)


# =================================================================
# Supabase 연결
# =================================================================

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def keep_supabase_alive() -> None:
    try:
        get_supabase().table("production").select("id").limit(1).execute()
    except Exception as e:
        st.sidebar.warning(f"⚠️ Supabase 연결 확인 실패: {e}")


# =================================================================
# 캐시 초기화 헬퍼
# =================================================================

def _clear_production_cache() -> None:
    load_realtime_ledger.clear()
    load_production_history.clear()

def _clear_schedule_cache() -> None:
    load_schedule.clear()

def _clear_plan_cache() -> None:
    load_production_plan.clear()
    load_plan_change_log.clear()

def _clear_master_cache() -> None:
    load_model_master.clear()

def _clear_audit_cache() -> None:
    load_audit_log.clear()
    load_oqc_fail_audit_log.clear()

def _clear_help_request_cache() -> None:
    load_help_requests.clear()

def _clear_access_request_cache() -> None:
    load_access_requests.clear()

def _clear_all_cache() -> None:
    _clear_production_cache()
    _clear_schedule_cache()
    _clear_plan_cache()
    _clear_master_cache()
    _clear_audit_cache()


def clear_cache_for_tables(tables: set) -> None:
    """Realtime 변경 감지 시 해당 테이블 캐시만 선택적으로 초기화."""
    if "production" in tables:
        _clear_production_cache()
    if "production_schedule" in tables:
        _clear_schedule_cache()
    if "production_plan" in tables or "plan_change_log" in tables:
        _clear_plan_cache()
    if "model_master" in tables:
        _clear_master_cache()
    if "audit_log" in tables:
        _clear_audit_cache()
    if "help_requests" in tables:
        _clear_help_request_cache()
    if "access_requests" in tables:
        _clear_access_request_cache()
    if "material_serial" in tables:
        load_material_serials.clear()


# =================================================================
# 생산 이력
# =================================================================

@st.cache_data(ttl=120)
def load_realtime_ledger() -> pd.DataFrame:
    """실시간 현황 전용: 오늘 생성 제품 + 이전 날짜 생성이지만 아직 미완료인 WIP 제품.
    TTL=120s — Realtime 구독이 변경 감지 시 캐시를 즉시 무효화하므로 체감 지연 없음."""
    _EMPTY_COLS = ['시간','반','라인','모델','품목코드','시리얼','상태','증상','수리','OQC판정','작업자','라벨시리얼']
    today_str = date.today().strftime('%Y-%m-%d')
    sb = get_supabase()

    def _query(q):
        try:
            return q.is_("deleted_at", "null").order("시간", desc=False).execute()
        except Exception:
            return q.order("시간", desc=False).execute()

    try:
        # ① 오늘 생성된 전체 제품 (완료 포함) — 3반 풀가동 하루 최대 3,000건 여유
        res_today = _query(
            sb.table("production").select("*").gte("시간", today_str).limit(3000)
        )
        # ② 어제 이전 생성됐으나 아직 미완료(WIP) 제품
        res_wip = _query(
            sb.table("production").select("*")
              .lt("시간", today_str).neq("상태", "완료").limit(1000)
        )
        rows = (res_today.data or []) + (res_wip.data or [])
        if rows:
            df = pd.DataFrame(rows)
            df = df.drop(columns=[c for c in ['id','deleted_at','deleted_by'] if c in df.columns])
            return df.fillna("")
        return pd.DataFrame(columns=_EMPTY_COLS)
    except Exception as e:
        if st.session_state.get('login_status', False):
            st.warning(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=_EMPTY_COLS)


@st.cache_data(ttl=120)
def load_production_history(date_from: str, date_to: str, limit: int = 5000) -> pd.DataFrame:
    """이력/리포트 조회 전용.
    - 최근 30일 이내 데이터: production 테이블 조회
    - 30일 이전 데이터    : production_history 테이블 조회 (Option B 아카이브)
    - 범위가 양쪽 걸치면  : 두 테이블 합산 후 정렬·중복 제거
    """
    _EMPTY_COLS = ['시간','반','라인','모델','품목코드','시리얼','상태','증상','수리','OQC판정','작업자','라벨시리얼']
    cutoff = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    sb = get_supabase()
    rows = []

    def _fetch(table: str, from_d: str, to_d: str) -> list:
        try:
            return (sb.table(table).select("*")
                      .gte("시간", from_d)
                      .lte("시간", to_d + " 23:59:59")
                      .is_("deleted_at", "null")
                      .order("시간", desc=True)
                      .limit(limit)
                      .execute().data or [])
        except Exception:
            try:
                return (sb.table(table).select("*")
                          .gte("시간", from_d)
                          .lte("시간", to_d + " 23:59:59")
                          .order("시간", desc=True)
                          .limit(limit)
                          .execute().data or [])
            except Exception:
                return []

    try:
        # 최근 30일 이내 구간이 조회 범위에 포함되면 production 조회
        if date_to >= cutoff:
            eff_from = cutoff if date_from < cutoff else date_from
            rows += _fetch("production", eff_from, date_to)

        # 30일 이전 구간이 조회 범위에 포함되면 production_history 조회
        if date_from < cutoff:
            rows += _fetch("production_history", date_from, cutoff)

        if rows:
            df = pd.DataFrame(rows)
            df = df.drop(columns=[c for c in ['id','deleted_at','deleted_by'] if c in df.columns])
            df = df.drop_duplicates(subset=['시리얼','시간'])
            df = df.sort_values('시간', ascending=False).head(limit)
            return df.fillna("")
        return pd.DataFrame(columns=_EMPTY_COLS)
    except Exception as e:
        if st.session_state.get('login_status', False):
            st.warning(f"이력 로드 실패: {e}")
        return pd.DataFrame(columns=_EMPTY_COLS)


def archive_old_completed(days: int = 30) -> int:
    """완료 후 N일 이상 지난 production 레코드를 production_history로 이동.
    production_history 테이블이 없으면 조용히 0 반환 (기존 동작 유지).
    반환값: 이동된 건수
    """
    cutoff = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    sb = get_supabase()
    try:
        old = (sb.table("production")
                 .select("*")
                 .eq("상태", "완료")
                 .lt("시간", cutoff)
                 .is_("deleted_at", "null")
                 .limit(500)
                 .execute())
        if not old.data:
            return 0
        # production_history에 upsert (시리얼 기준 중복 방지)
        sb.table("production_history").upsert(old.data, on_conflict="시리얼").execute()
        # production에서 hard delete
        for row in old.data:
            sb.table("production").delete().eq("시리얼", row["시리얼"]).execute()
        # 캐시 무효화
        load_production_history.clear()
        return len(old.data)
    except Exception:
        return 0  # production_history 테이블 미생성 환경에서도 앱 정상 동작


def insert_row(row: dict) -> bool:
    sn = row.get('시리얼', '')
    sb = get_supabase()
    try:
        sb.table("production").insert(row).execute()
        return True
    except Exception as e:
        err_str = str(e)
        if "23505" in err_str or "duplicate key" in err_str or "already exists" in err_str:
            # 중복키 에러 → DB에 이미 해당 시리얼이 존재함이 확실.
            # 세션 캐시(production_db)는 로드 타이밍에 따라 비어있을 수 있으므로
            # 캐시 기준으로 판단하지 않고 DB에서 직접 현재 상태 조회 후 에러 표시.
            # (기존: 캐시가 비어있으면 UPSERT → 진행 중인 제품을 조립중으로 덮어쓰는 버그)
            try:
                existing = sb.table("production").select("시리얼,상태,반,모델").eq("시리얼", sn).execute()
                if existing.data:
                    ex = existing.data[0]
                    st.error(
                        f"⚠️ 이미 등록된 시리얼입니다: **{sn}**\n\n"
                        f"현재 상태: **{ex.get('상태','')}** | 반: {ex.get('반','')} | 모델: {ex.get('모델','')}\n\n"
                        f"동일한 S/N이 이미 생산 이력에 존재합니다. 시리얼을 확인해주세요."
                    )
                    return False
            except Exception:
                pass
            st.error(f"⚠️ 이미 등록된 시리얼입니다: **{sn}**\n\n시리얼을 확인해주세요.")
            return False
        else:
            st.error(f"등록 실패: {e}")
        return False


def update_row(시리얼: str, data: dict) -> bool:
    try:
        get_supabase().table("production").update(data).eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"업데이트 실패: {e}"); return False


def delete_all_rows() -> bool:
    """Soft delete + 백업 자동 생성"""
    msgs = []
    try:
        sb = get_supabase()
        backup_time = get_now_kst_str()
        all_data = sb.table("production").select("*").execute()
        if all_data.data:
            backup_records = [{
                **record,
                'deleted_at': backup_time,
                'deleted_by': st.session_state.get('user_id', 'unknown')
            } for record in all_data.data]
            try:
                sb.table("production_backup").insert(backup_records).execute()
            except Exception as e:
                msgs.append(("warning", f"⚠️ 백업 실패 (데이터 복구 불가능): {e}"))
        try:
            sb.table("production").update({
                'deleted_at': backup_time,
                'deleted_by': st.session_state.get('user_id', 'unknown')
            }).is_('deleted_at', 'null').execute()
        except Exception as e:
            msgs.append(("warning", f"⚠️ Soft delete 불가 — Hard delete 실행됨: {e}"))
            sb.table("production").delete().gte("id", 0).execute()
        st.session_state['_delete_msgs'] = msgs
        return True
    except Exception as e:
        st.session_state['_delete_msgs'] = [("error", f"삭제 실패: {e}")]
        return False


def delete_production_row_by_sn(시리얼: str) -> bool:
    try:
        get_supabase().table("production").delete().eq("시리얼", 시리얼).execute()
        return True
    except Exception as e:
        st.error(f"삭제 실패: {e}"); return False


# =================================================================
# 앱 설정
# =================================================================

def load_app_setting(key: str):
    try:
        import json as _j
        res = get_supabase().table("app_settings").select("value").eq("key", key).execute()
        if res.data:
            return _j.loads(res.data[0]["value"])
    except Exception:
        pass
    return None


def save_app_setting(key: str, value):
    try:
        import json as _j
        get_supabase().table("app_settings").upsert(
            {"key": key, "value": _j.dumps(value, ensure_ascii=False)},
            on_conflict="key"
        ).execute()
        return True
    except Exception as e:
        return str(e)


# =================================================================
# 도움 요청 / 접근 요청
# =================================================================

def submit_help_request(requester: str, role: str, page: str, message: str) -> tuple:
    try:
        get_supabase().table("help_requests").insert({
            "requester": requester, "role": role,
            "page": page, "message": message,
            "status": "open", "created_at": get_now_kst_str()
        }).execute()
    except Exception:
        pass
    _now = datetime.now(_KST).strftime("%Y-%m-%d %H:%M")
    _tg_result = _send_telegram(
        f"🆘 <b>관리자 도움 요청</b>\n"
        f"작업자: {requester}\n"
        f"페이지: {page}\n"
        f"내용: {message}\n"
        f"시각: {_now}"
    )
    return _tg_result == "ok", _tg_result


@st.cache_data(ttl=20)
def load_help_requests(status: str = "open") -> pd.DataFrame:
    try:
        res = (get_supabase().table("help_requests")
               .select("*").eq("status", status)
               .order("created_at", desc=True).execute())
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def submit_access_request(username: str, pw_hash: str, name: str,
                           department: str, requested_role: str, reason: str):
    """성공 시 True, 실패 시 오류 메시지 문자열 반환"""
    try:
        get_supabase().table("access_requests").insert({
            "username": username, "password_hash": pw_hash,
            "name": name, "department": department,
            "requested_role": requested_role, "reason": reason,
            "status": "pending", "created_at": get_now_kst_str()
        }).execute()
        return True
    except Exception as e:
        return str(e)


@st.cache_data(ttl=30)
def load_access_requests(status: str = "pending") -> pd.DataFrame:
    try:
        res = (get_supabase().table("access_requests")
               .select("*").eq("status", status)
               .order("created_at", desc=True).execute())
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def review_access_request(req_id: int, action: str,
                           reviewed_by: str, reject_reason: str = "") -> bool:
    try:
        get_supabase().table("access_requests").update({
            "status": action, "reviewed_by": reviewed_by,
            "reviewed_at": get_now_kst_str(), "reject_reason": reject_reason
        }).eq("id", req_id).execute()
        return True
    except Exception:
        return False


# =================================================================
# 감사 로그
# =================================================================

def insert_audit_log(시리얼: str, 모델: str, 반: str,
                     이전상태: str, 이후상태: str,
                     작업자: str, 비고: str = "") -> bool:
    try:
        get_supabase().table("audit_log").insert({
            "시간":    get_now_kst_str(),
            "시리얼":  시리얼,
            "모델":    모델,
            "반":      반,
            "이전상태": 이전상태,
            "이후상태": 이후상태,
            "작업자":  작업자,
            "비고":    비고,
        }).execute()
        return True
    except Exception:
        return False


@st.cache_data(ttl=30)
def load_audit_log(limit: int = _MAX_AUDIT_LOG_ROWS) -> pd.DataFrame:
    try:
        res = get_supabase().table("audit_log").select("*").order("시간", desc=True).limit(limit).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])
    except Exception:
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])


@st.cache_data(ttl=30)
def load_oqc_fail_audit_log() -> pd.DataFrame:
    """OQC 부적합 판정 이벤트만 서버 필터로 조회 (행 수 제한 없음)."""
    try:
        res = (get_supabase().table("audit_log")
               .select("*")
               .like("비고", "OQC 부적합 - 사유:%")
               .order("시간", desc=True)
               .execute())
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])
    except Exception:
        return pd.DataFrame(columns=['시간','시리얼','모델','반','이전상태','이후상태','작업자','비고'])


def delete_all_audit_log() -> bool:
    try:
        get_supabase().table("audit_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"감사로그 삭제 실패: {e}"); return False


def delete_audit_log_row(row_id) -> bool:
    try:
        get_supabase().table("audit_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"감사로그 행 삭제 실패: {e}"); return False


# =================================================================
# 자재 시리얼
# =================================================================

def insert_material_serials(메인시리얼: str, 모델: str, 반: str,
                             자재목록: list, 작업자: str) -> bool:
    try:
        sb = get_supabase()
        rows = [{
            "시간":     get_now_kst_str(),
            "메인시리얼": 메인시리얼,
            "모델":     모델,
            "반":       반,
            "자재명":   m.get("자재명",""),
            "자재시리얼": m.get("자재시리얼",""),
            "작업자":   작업자,
        } for m in 자재목록 if m.get("자재시리얼","").strip()]
        if rows:
            sb.table("material_serial").insert(rows).execute()
        return True
    except Exception as e:
        st.error(f"자재 시리얼 등록 실패: {e}")
        return False


@st.cache_data(ttl=60)
def load_material_serials(메인시리얼: str = "") -> pd.DataFrame:
    try:
        sb  = get_supabase()
        q   = sb.table("material_serial").select("*")
        if 메인시리얼:
            q = q.eq("메인시리얼", 메인시리얼)
        res = q.order("시간", desc=False).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
    except Exception:
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])


@st.cache_data(ttl=60)
def load_material_serials_bulk(serials: tuple) -> pd.DataFrame:
    if not serials:
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
    try:
        res = get_supabase().table("material_serial").select("*").in_("메인시리얼", list(serials)).order("시간", desc=False).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])
    except Exception:
        return pd.DataFrame(columns=['시간','메인시리얼','모델','반','자재명','자재시리얼','작업자'])


def search_material_by_sn(자재시리얼: str) -> pd.DataFrame:
    try:
        자재시리얼_cleaned = re.sub(r'[^\w가-힣-]', '', 자재시리얼) if 자재시리얼 else ""
        res = get_supabase().table("material_serial").select("*").ilike("자재시리얼", f"%{자재시리얼_cleaned}%").execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def update_material_serial_sn(메인시리얼: str, 구자재시리얼: str, 신자재시리얼: str) -> bool:
    try:
        get_supabase().table("material_serial").update({
            "자재시리얼": 신자재시리얼,
            "시간": get_now_kst_str()
        }).eq("메인시리얼", 메인시리얼).eq("자재시리얼", 구자재시리얼).execute()
        return True
    except Exception as e:
        st.error(f"자재 시리얼 교체 실패: {e}"); return False


def delete_all_material_serial() -> bool:
    try:
        get_supabase().table("material_serial").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"자재시리얼 삭제 실패: {e}"); return False


def delete_material_serial_row(row_id) -> bool:
    try:
        get_supabase().table("material_serial").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"자재시리얼 행 삭제 실패: {e}"); return False


# =================================================================
# 생산 일정
# =================================================================

@st.cache_data(ttl=60)
def load_schedule() -> pd.DataFrame:
    try:
        res = get_supabase().table("production_schedule").select("*").order("날짜", desc=False).execute()
        if res.data:
            return pd.DataFrame(res.data).fillna("")
        return pd.DataFrame(columns=['id','날짜','반','카테고리','pn','모델명','조립수','출하계획','특이사항','작성자'])
    except Exception as e:
        if st.session_state.get('login_status', False):
            st.warning(f"일정 로드 실패: {e}")
        return pd.DataFrame(columns=['id','날짜','반','카테고리','pn','모델명','조립수','출하계획','특이사항','작성자'])


def insert_schedule(row: dict) -> bool:
    try:
        allowed = {'날짜', '반', '카테고리', 'pn', '모델명', '조립수', '출하계획', '특이사항', '작성자'}
        clean_row = {k: v for k, v in row.items() if k in allowed}
        if '날짜' in clean_row and hasattr(clean_row['날짜'], 'strftime'):
            clean_row['날짜'] = clean_row['날짜'].strftime('%Y-%m-%d')
        get_supabase().table("production_schedule").insert(clean_row).execute()
        반   = str(clean_row.get('반', '')).strip()
        모델 = str(clean_row.get('모델명', '')).strip()
        pn   = str(clean_row.get('pn', '')).strip()
        if 반 in _PRODUCTION_GROUPS and 모델:
            upsert_model_master(반, 모델, pn if pn else 모델)
            if 모델 not in st.session_state.group_master_models.get(반, []):
                st.session_state.group_master_models.setdefault(반, []).append(모델)
            if 모델 not in st.session_state.group_master_items.get(반, {}):
                st.session_state.group_master_items.setdefault(반, {})[모델] = []
            if pn and pn not in st.session_state.group_master_items[반][모델]:
                st.session_state.group_master_items[반][모델].append(pn)
        return True
    except Exception as e:
        st.error(f"일정 등록 실패: {e}")
        return False


def update_schedule(row_id: int, data: dict) -> bool:
    try:
        get_supabase().table("production_schedule").update(data).eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정 수정 실패: {e}"); return False


def delete_schedule(row_id: int) -> bool:
    try:
        get_supabase().table("production_schedule").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정 삭제 실패: {e}"); return False


def delete_all_production_schedule() -> bool:
    try:
        get_supabase().table("production_schedule").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"생산일정 삭제 실패: {e}"); return False


# =================================================================
# 일정 변경 로그
# =================================================================

def insert_schedule_change_log(sch_id: int, 날짜: str, 반: str, 모델명: str,
                                이전내용: str, 변경내용: str,
                                변경사유: str, 사유상세: str, 작업자: str) -> bool:
    try:
        get_supabase().table("schedule_change_log").insert({
            "시간":     get_now_kst_str(),
            "일정id":   sch_id,
            "날짜":     날짜,
            "반":       반,
            "모델명":   모델명,
            "이전내용": 이전내용,
            "변경내용": 변경내용,
            "변경사유": 변경사유,
            "사유상세": 사유상세,
            "작업자":   작업자,
        }).execute()
        return True
    except Exception:
        return False


def delete_all_schedule_change_log() -> bool:
    try:
        get_supabase().table("schedule_change_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"일정변경이력 삭제 실패: {e}"); return False


def delete_schedule_change_log_row(row_id) -> bool:
    try:
        get_supabase().table("schedule_change_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"일정변경이력 행 삭제 실패: {e}"); return False


# =================================================================
# 모델 마스터
# =================================================================

@st.cache_data(ttl=300)
def load_model_master() -> pd.DataFrame:
    try:
        res = get_supabase().table("model_master").select("*").execute()
        if res.data:
            return pd.DataFrame(res.data)
        return pd.DataFrame(columns=['id','반','모델명','품목코드'])
    except Exception:
        return pd.DataFrame(columns=['id','반','모델명','품목코드'])


def upsert_model_master(반: str, 모델명: str, 품목코드: str) -> bool:
    try:
        get_supabase().table("model_master").upsert(
            {"반": 반, "모델명": 모델명, "품목코드": 품목코드},
            on_conflict="반,모델명,품목코드"
        ).execute()
        return True
    except Exception:
        return False


def delete_model_from_master(반: str, 모델명: str) -> bool:
    try:
        get_supabase().table("model_master").delete().eq("반", 반).eq("모델명", 모델명).execute()
        return True
    except Exception:
        return False


def delete_item_from_master(반: str, 모델명: str, 품목코드: str) -> bool:
    try:
        get_supabase().table("model_master").delete().eq("반", 반).eq("모델명", 모델명).eq("품목코드", 품목코드).execute()
        return True
    except Exception:
        return False


def delete_all_master_by_group(반: str) -> bool:
    try:
        get_supabase().table("model_master").delete().eq("반", 반).execute()
        return True
    except Exception:
        return False


def sync_master_to_session():
    """DB model_master → session_state group_master_models/items 동기화"""
    df = load_model_master()
    if df.empty:
        return
    models_map = {g: [] for g in _PRODUCTION_GROUPS}
    items_map  = {g: {} for g in _PRODUCTION_GROUPS}
    valid_df = df[df['반'].isin(_PRODUCTION_GROUPS)].copy()
    valid_df['반']      = valid_df['반'].astype(str)
    valid_df['모델명']   = valid_df['모델명'].astype(str)
    valid_df['품목코드'] = valid_df['품목코드'].astype(str)
    for g, gdf in valid_df.groupby('반'):
        for m, mdf in gdf.groupby('모델명'):
            models_map[g].append(m)
            items_map[g][m] = [pn for pn in mdf['품목코드'].unique() if pn and pn != 'nan']
    for g in _PRODUCTION_GROUPS:
        for m in models_map[g]:
            if m not in st.session_state.group_master_models[g]:
                st.session_state.group_master_models[g].append(m)
            if m not in st.session_state.group_master_items[g]:
                st.session_state.group_master_items[g][m] = []
            for pn in items_map[g].get(m, []):
                if pn not in st.session_state.group_master_items[g][m]:
                    st.session_state.group_master_items[g][m].append(pn)


# =================================================================
# 생산 계획
# =================================================================

@st.cache_data(ttl=300)
def load_production_plan() -> dict:
    try:
        res = get_supabase().table("production_plan").select("*").execute()
        if res.data:
            return {f"{r['반']}_{r['월']}": int(r.get('계획수량', 0)) for r in res.data}
        return {}
    except Exception:
        return {}


def save_production_plan(반: str, 월: str, 계획수량: int) -> bool:
    try:
        get_supabase().table("production_plan").upsert({
            "반": 반, "월": 월, "계획수량": 계획수량
        }, on_conflict="반,월").execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 저장 실패: {e}")
        return False


def delete_production_plan_row(반: str, 월: str) -> bool:
    try:
        get_supabase().table("production_plan").delete().eq("반", 반).eq("월", 월).execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 삭제 실패: {e}"); return False


def delete_all_production_plan() -> bool:
    try:
        get_supabase().table("production_plan").delete().neq("반", "").execute()
        return True
    except Exception as e:
        st.error(f"계획 수량 전체 삭제 실패: {e}"); return False


# =================================================================
# 생산 계획 변경 로그
# =================================================================

def insert_plan_change_log(반: str, 월: str, 이전수량: int, 변경수량: int,
                            변경사유: str, 사유상세: str, 작업자: str) -> bool:
    try:
        get_supabase().table("plan_change_log").insert({
            "시간":     get_now_kst_str(),
            "반":       반,
            "월":       월,
            "이전수량": 이전수량,
            "변경수량": 변경수량,
            "증감":     변경수량 - 이전수량,
            "변경사유": 변경사유,
            "사유상세": 사유상세,
            "작업자":   작업자,
        }).execute()
        return True
    except Exception:
        return False


@st.cache_data(ttl=60)
def load_plan_change_log(limit: int = _DEFAULT_PAGE_SIZE) -> pd.DataFrame:
    try:
        res = get_supabase().table("plan_change_log").select("*").order("시간", desc=True).limit(limit).execute()
        if res.data:
            return pd.DataFrame(res.data).drop(columns=['id'], errors='ignore')
        return pd.DataFrame(columns=['시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])
    except Exception:
        return pd.DataFrame(columns=['시간','반','월','이전수량','변경수량','증감','변경사유','사유상세','작업자'])


def delete_all_plan_change_log() -> bool:
    try:
        get_supabase().table("plan_change_log").delete().gte("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"계획변경이력 삭제 실패: {e}"); return False


def delete_plan_change_log_row(row_id) -> bool:
    try:
        get_supabase().table("plan_change_log").delete().eq("id", row_id).execute()
        return True
    except Exception as e:
        st.error(f"계획변경이력 행 삭제 실패: {e}"); return False
