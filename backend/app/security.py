"""Authentication and role-based authorization.

Roles live in the database and are bound to the session server-side. The
client never supplies its own role; every protected route resolves the actor
from the session cookie.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import timedelta

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import AuthSession, User
from app.timeutil import as_utc, utcnow

CLIENT_HEADER = "X-CuraLink-Client"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_hex, digest_hex = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, request: Request, response: Response, user: User) -> None:
    """Every sign-in gets a NEW server session; any session this browser already held is revoked first,
    so switching accounts can never keep the previous identity alive."""
    settings = get_settings()
    old = request.cookies.get(settings.session_cookie_name)
    if old:
        row = db.get(AuthSession, _token_hash(old))
        if row and row.revoked_at is None:
            row.revoked_at = utcnow()
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, expires_at=utcnow() + timedelta(minutes=settings.session_ttl_minutes)))
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        # No max_age: a browser-session cookie (kept across refreshes, gone when the browser closes), so a
        # shared demo machine doesn't silently reopen the last person's portal. The server TTL still applies.
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        row = db.get(AuthSession, _token_hash(token))
        if row and row.revoked_at is None:
            row.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")


def user_for_token(db: Session, token: str | None) -> User | None:
    """Session-cookie lookup shared by HTTP routes and the voice WebSocket."""
    if not token:
        return None
    row = db.get(AuthSession, _token_hash(token))
    if row is None or row.revoked_at is not None or as_utc(row.expires_at) <= utcnow():
        return None
    return db.get(User, row.user_id)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    row = db.get(AuthSession, _token_hash(token))
    if row is None or row.revoked_at is not None or as_utc(row.expires_at) <= utcnow():
        raise ApiError(401, "SESSION_EXPIRED", "Your session has ended. Please sign in again.")
    user = db.get(User, row.user_id)
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    return user


def require_role(role: str) -> Callable[..., User]:
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role != role:
            # Deliberately generic: no hint about what exists behind the route.
            raise ApiError(403, "FORBIDDEN", "You don't have access to this area.", recoverable=False)
        if role == "clinician" and not user.clinician_verified:
            raise ApiError(403, "CLINICIAN_NOT_VERIFIED", "Clinician access requires a verified account.", recoverable=False)
        return user

    return dependency


require_student = require_role("student")
require_clinician = require_role("clinician")


def permissions_for(user: User) -> list[str]:
    if user.role == "student":
        return ["intake:write", "calendar:write", "appointments:confirm", "cases:request", "consent:manage"]
    if user.role == "clinician":
        return ["encounters:read_assigned", "absence:decide", "documents:sign", "documents:deliver", "signature:manage"]
    return []
