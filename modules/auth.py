"""
인증 / 권한 모듈
- 비밀번호 해시/검증 (bcrypt + SHA-256 fallback)
- 마스터 비밀번호 로드
- 커스텀 권한 파싱 및 확인
"""

import hashlib
import os
import streamlit as st

try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _BCRYPT_AVAILABLE = False

PERM_ACTIONS = ["read", "write", "edit"]


# =================================================================
# 비밀번호 유틸
# =================================================================

def hash_pw(password: str) -> str:
    """bcrypt 사용 가능 시 bcrypt, 아니면 SHA-256 (fallback)"""
    if _BCRYPT_AVAILABLE:
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_pw(plain: str, hashed: str) -> bool:
    """bcrypt 해시($2b$)와 SHA-256 해시(64자 hex) 모두 검증"""
    if _BCRYPT_AVAILABLE and hashed.startswith("$2"):
        try:
            return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, AttributeError):
            return False
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == hashed


def get_master_pw_hash() -> str | None:
    """
    마스터 비밀번호 해시 로드
    우선순위: Supabase system_config → st.secrets → 환경변수
    """
    from modules.database import get_supabase
    try:
        sb = get_supabase()
        result = sb.table("system_config").select("master_hash").eq("key", "master_password").execute()
        if result.data and len(result.data) > 0:
            return result.data[0].get("master_hash")
    except Exception:
        pass

    try:
        secrets_hash = st.secrets.get("master_admin_pw_hash") or st.secrets.get("MASTER_PASSWORD_HASH")
        if not secrets_hash:
            try:
                secrets_hash = st.secrets["connections"]["gsheets"].get("master_admin_pw_hash")
            except Exception:
                pass
        if secrets_hash:
            return secrets_hash
    except Exception:
        pass

    try:
        env_hash = os.getenv("MASTER_PASSWORD_HASH")
        if env_hash:
            return env_hash
    except Exception:
        pass

    return None


# =================================================================
# 권한 파싱 / 확인
# =================================================================

def _parse_custom_perms(raw):
    """커스텀 권한 파싱 — 구형(list) / 신형(dict{"pages":…,"levels":…}) 모두 지원.
    Returns (pages: list | None, levels: dict[str, set])
    """
    if raw is None:
        return None, {}
    if isinstance(raw, list):
        return raw, {p: set(PERM_ACTIONS) for p in raw}
    if isinstance(raw, dict) and "pages" in raw:
        pages  = raw.get("pages", [])
        levels = {k: set(v) for k, v in raw.get("levels", {}).items()}
        for p in pages:
            if p not in levels and not any(p.startswith(k + "::") for k in levels):
                levels[p] = set(PERM_ACTIONS)
        return pages, levels
    return None, {}


def check_perm(page_key: str, action: str = "read") -> bool:
    """현재 로그인 사용자의 페이지·동작 권한 확인.
    page_key: 메뉴명 또는 "라인::반" 형식
    action  : "read" | "write" | "edit"
    """
    role = st.session_state.get("user_role")
    if role in ("master", "admin"):
        return True
    levels = st.session_state.get("user_permission_levels", {})
    if not levels:
        return True
    if page_key in levels:
        return action in levels[page_key]
    for key, actions in levels.items():
        if page_key.startswith(key + "::"):
            return action in actions
    return False  # 명시적으로 허용된 페이지·동작이 아니면 거부
