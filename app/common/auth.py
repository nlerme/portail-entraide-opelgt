from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, Response

from app.common.config import secret, section

MEMBER_COOKIE = "opelgt_member"
ADMIN_COOKIE = "opelgt_admin"
_CSRF_HEADER = "x-csrf-token"
_LOCK = threading.RLock()
_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16)


@dataclass
class Session:
    subject: str
    expires_at: float
    csrf_token: str
    created_at: float
    closing_at: float | None = None


_MEMBER_SESSIONS: dict[str, Session] = {}
_ADMIN_SESSIONS: dict[str, Session] = {}
_ATTEMPTS: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _trusted_proxy(address: str) -> bool:
    configured = section("server").get("trusted_proxies", [])
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    for item in configured if isinstance(configured, list) else []:
        try:
            if ip in ipaddress.ip_network(str(item), strict=False):
                return True
        except ValueError:
            continue
    return False


def client_key(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _trusted_proxy(direct):
        return forwarded.split(",", 1)[0].strip()
    return direct


def enforce_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    window = max(1, int(window_seconds))
    key = (bucket, client_key(request))
    with _LOCK:
        attempts = _ATTEMPTS[key]
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        if len(attempts) >= max(1, int(limit)):
            remaining = max(1, int(window - (now - attempts[0])))
            minutes = max(1, (remaining + 59) // 60)
            raise HTTPException(
                status_code=429,
                detail=f"Trop de tentatives de connexion. Réessayez dans {minutes} minute(s).",
            )
        attempts.append(now)


def _cookie_secure(request: Request) -> bool:
    auth = section("authentication")
    public_url = str(section("server").get("public_url") or "")
    return bool(auth.get("https_only_cookies")) or request.url.scheme == "https" or public_url.startswith("https://")


def session_duration_minutes() -> int:
    return max(1, int(section("sessions").get("duration_minutes", 30)))


def _create_session(store: dict[str, Session], subject: str, duration_minutes: int) -> tuple[str, Session]:
    sid = secrets.token_urlsafe(32)
    now = time.time()
    session = Session(
        subject=subject,
        created_at=now,
        expires_at=now + duration_minutes * 60,
        csrf_token=secrets.token_urlsafe(32),
    )
    with _LOCK:
        store[sid] = session
    return sid, session


def create_member_session(username: str, response: Response, request: Request) -> Session:
    duration_minutes = session_duration_minutes()
    sid, session = _create_session(_MEMBER_SESSIONS, username, duration_minutes)
    response.set_cookie(
        MEMBER_COOKIE,
        sid,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path="/",
    )
    return session


def create_admin_session(username: str, response: Response, request: Request) -> Session:
    duration_minutes = session_duration_minutes()
    sid, session = _create_session(_ADMIN_SESSIONS, username, duration_minutes)
    response.set_cookie(
        ADMIN_COOKIE,
        sid,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path="/",
    )
    return session


def _get_session(request: Request, cookie: str, store: dict[str, Session]) -> Session | None:
    sid = request.cookies.get(cookie)
    if not sid:
        return None
    with _LOCK:
        session = store.get(sid)
        if session is None:
            return None
        now = time.time()
        if session.expires_at <= now or (session.closing_at is not None and session.closing_at <= now):
            store.pop(sid, None)
            return None
        return session


def _mark_closing(
    request: Request,
    cookie: str,
    store: dict[str, Session],
    csrf_token: str,
    grace_seconds: float = 5.0,
) -> bool:
    sid = request.cookies.get(cookie)
    if not sid or not csrf_token:
        return False
    with _LOCK:
        session = store.get(sid)
        if session is None or session.expires_at <= time.time():
            return False
        if not hmac.compare_digest(csrf_token, session.csrf_token):
            return False
        session.closing_at = time.time() + max(1.0, float(grace_seconds))
        return True


def _cancel_closing(request: Request, cookie: str, store: dict[str, Session]) -> Session | None:
    session = _get_session(request, cookie, store)
    if session is None:
        return None
    with _LOCK:
        session.closing_at = None
    return session


def mark_member_closing(request: Request, csrf_token: str) -> bool:
    return _mark_closing(request, MEMBER_COOKIE, _MEMBER_SESSIONS, csrf_token)


def mark_admin_closing(request: Request, csrf_token: str) -> bool:
    return _mark_closing(request, ADMIN_COOKIE, _ADMIN_SESSIONS, csrf_token)


def keep_member_alive(request: Request) -> Session | None:
    return _cancel_closing(request, MEMBER_COOKIE, _MEMBER_SESSIONS)


def keep_admin_alive(request: Request) -> Session | None:
    return _cancel_closing(request, ADMIN_COOKIE, _ADMIN_SESSIONS)


def member_session(request: Request) -> Session | None:
    return _get_session(request, MEMBER_COOKIE, _MEMBER_SESSIONS)


def admin_session(request: Request) -> Session | None:
    return _get_session(request, ADMIN_COOKIE, _ADMIN_SESSIONS)


def require_member(request: Request) -> Session:
    session = member_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Session membre expirée. Veuillez vous reconnecter.")
    return session


def require_admin(request: Request) -> Session:
    session = admin_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Session administrateur expirée.")
    return session


def require_csrf(request: Request, *, admin: bool = False) -> Session:
    session = require_admin(request) if admin else require_member(request)
    provided = request.headers.get(_CSRF_HEADER, "")
    if not provided or not hmac.compare_digest(provided, session.csrf_token):
        raise HTTPException(status_code=403, detail="Jeton CSRF absent ou invalide.")
    origin = request.headers.get("origin")
    if origin:
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if origin.rstrip("/") != expected.rstrip("/"):
            raise HTTPException(status_code=403, detail="Origine de requête non autorisée.")
    return session


def revoke_member(request: Request, response: Response) -> None:
    sid = request.cookies.get(MEMBER_COOKIE)
    with _LOCK:
        if sid:
            _MEMBER_SESSIONS.pop(sid, None)
    response.delete_cookie(MEMBER_COOKIE, path="/")


def revoke_admin(request: Request, response: Response) -> None:
    sid = request.cookies.get(ADMIN_COOKIE)
    with _LOCK:
        if sid:
            _ADMIN_SESSIONS.pop(sid, None)
    response.delete_cookie(ADMIN_COOKIE, path="/")


def cleanup_sessions() -> int:
    now = time.time()
    removed = 0
    with _LOCK:
        for store in (_MEMBER_SESSIONS, _ADMIN_SESSIONS):
            for sid in [
                key
                for key, value in store.items()
                if value.expires_at <= now or (value.closing_at is not None and value.closing_at <= now)
            ]:
                store.pop(sid, None)
                removed += 1
    return removed


def hash_admin_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 16:
        errors.append("au moins 16 caractères")
    if not any(char.islower() for char in password):
        errors.append("une lettre minuscule")
    if not any(char.isupper() for char in password):
        errors.append("une lettre majuscule")
    if not any(char.isdigit() for char in password):
        errors.append("un chiffre")
    if not any(not char.isalnum() and not char.isspace() for char in password):
        errors.append("un caractère spécial")
    return errors


def verify_admin_password(password: str) -> bool:
    encoded = secret("admin_password_hash")
    if not encoded:
        return False
    if encoded.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    if encoded.startswith("pbkdf2_sha256$"):
        try:
            _, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(raw_salt), int(raw_iterations))
            return hmac.compare_digest(digest, base64.b64decode(raw_digest))
        except (ValueError, TypeError):
            return False
    return False


def app_secret() -> str:
    configured = secret("app_secret")
    return configured or os.environ.get("PORTAIL_APP_SECRET", "")
