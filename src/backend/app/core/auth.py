"""Server-owned identity and role checks for all future private resources."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.auth import AuthSession, User

bearer = HTTPBearer(auto_error=False, scheme_name="ServiceSession")
DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True, repr=False)
class AuthContext:
    user: User
    session: AuthSession


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def unauthenticated() -> AppError:
    return AppError(
        401,
        "AUTH_REQUIRED",
        "유효한 인증 정보가 필요합니다.",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def auth_unavailable() -> AppError:
    return AppError(
        503,
        "AUTH_UNAVAILABLE",
        "인증 서비스를 잠시 사용할 수 없습니다.",
        retryable=True,
        headers={"Cache-Control": "no-store"},
    )


def new_session(user_id, now: datetime) -> tuple[AuthSession, str]:
    token = secrets.token_urlsafe(32)
    return AuthSession(
        user_id=user_id,
        token_hash=token_digest(token),
        created_at=now,
        expires_at=now + timedelta(seconds=get_settings().session_ttl_seconds),
    ), token


def current_auth(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthContext:
    if credentials is None or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", credentials.credentials
    ):
        raise unauthenticated()
    try:
        row = db.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == token_digest(credentials.credentials),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
                User.disabled_at.is_(None),
            )
        ).first()
    except SQLAlchemyError:
        raise auth_unavailable() from None
    if row is None:
        raise unauthenticated()
    return AuthContext(user=row[0], session=row[1])


CurrentAuth = Annotated[AuthContext, Depends(current_auth)]


def require_admin(auth: CurrentAuth) -> AuthContext:
    if auth.user.role != "admin":
        raise AppError(
            403,
            "ADMIN_REQUIRED",
            "관리자 권한이 필요합니다.",
            headers={"Cache-Control": "no-store"},
        )
    return auth


AdminAuth = Annotated[AuthContext, Depends(require_admin)]
