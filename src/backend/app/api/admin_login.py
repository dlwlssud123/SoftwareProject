import hashlib
import math
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore

from fastapi import APIRouter, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import issued_response
from app.core.auth import DbSession, auth_unavailable, new_session
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.passwords import verify_password
from app.models import AdminCredential, AdminLoginBucket, User
from app.schemas.auth import AdminLoginRequest, SessionData
from app.schemas.common import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/admin", tags=["admin"])
_HASH_SLOTS = BoundedSemaphore(2)
_WINDOW = timedelta(minutes=5)
_MAX_PER_IP = 30
_MAX_FAILURES = 5
_ACCOUNT_LOCK = timedelta(minutes=15)


def _invalid():
    # Missing, disabled, locked and incorrect accounts have the same response.
    return AppError(
        401,
        "ADMIN_LOGIN_FAILED",
        "아이디 또는 비밀번호를 확인해 주세요. 연속으로 실패했다면 잠시 후 다시 시도해 주세요.",
        headers={"Cache-Control": "no-store"},
    )


def _consume_attempt(db, peer: str, now: datetime):
    key = hashlib.sha256(("valueflow-admin-login:" + peer).encode("utf-8")).hexdigest()
    db.execute(
        delete(AdminLoginBucket).where(
            AdminLoginBucket.window_start < now - timedelta(days=1)
        )
    )
    db.execute(
        insert(AdminLoginBucket)
        .values(bucket_key=key, window_start=now, attempts=0)
        .on_conflict_do_nothing()
    )
    bucket = db.scalar(
        select(AdminLoginBucket)
        .where(AdminLoginBucket.bucket_key == key)
        .with_for_update()
    )
    if now >= bucket.window_start + _WINDOW:
        bucket.window_start, bucket.attempts = now, 0
    if bucket.attempts >= _MAX_PER_IP:
        retry_after = max(
            1, math.ceil((bucket.window_start + _WINDOW - now).total_seconds())
        )
        db.rollback()
        raise AppError(
            429,
            "ADMIN_LOGIN_RATE_LIMITED",
            "로그인 시도가 많아요. 잠시 후 다시 시도해 주세요.",
            retryable=True,
            headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
        )
    bucket.attempts += 1
    # The rate counter survives an invalid credential or later authentication failure.
    db.commit()


@router.post(
    "/login",
    response_model=SuccessResponse[SessionData],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 429, 503)},
)
def login(body: AdminLoginRequest, request: Request, db: DbSession):
    if not _HASH_SLOTS.acquire(blocking=False):
        raise AppError(
            503,
            "ADMIN_LOGIN_BUSY",
            "로그인 요청을 처리 중이에요. 잠시 후 다시 시도해 주세요.",
            retryable=True,
            headers={"Retry-After": "2"},
        )
    try:
        now = datetime.now(UTC)
        _consume_attempt(db, request.client.host if request.client else "unknown", now)
        row = db.execute(
            select(AdminCredential, User)
            .join(User, User.id == AdminCredential.user_id)
            .where(AdminCredential.username == body.username)
            .with_for_update(of=(AdminCredential, User))
        ).one_or_none()
        credential, user = row if row is not None else (None, None)
        usable = (
            credential is not None
            and credential.enabled
            and user.disabled_at is None
            and user.role == "admin"
        )
        if (
            usable
            and credential.locked_until is not None
            and now >= credential.locked_until
        ):
            credential.failed_attempts, credential.locked_until = 0, None
        unlocked = usable and credential.locked_until is None
        valid = verify_password(
            body.password.get_secret_value(),
            credential.password_hash if unlocked else None,
        )
        if not valid or not unlocked:
            if unlocked:
                credential.failed_attempts += 1
                if credential.failed_attempts >= _MAX_FAILURES:
                    credential.locked_until = now + _ACCOUNT_LOCK
            db.commit()
            raise _invalid()
        credential.failed_attempts, credential.locked_until = 0, None
        session, token = new_session(
            user.id,
            now,
            reauthenticate_at=now
            + timedelta(seconds=get_settings().admin_session_ttl_seconds),
        )
        db.add(session)
        db.commit()
        return issued_response(request, user, session, token, 200)
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    except (ValueError, MemoryError):
        db.rollback()
        # OpenSSL/memory failures must not expose a password, hash or salt.
        raise AppError(
            503,
            "ADMIN_LOGIN_UNAVAILABLE",
            "로그인을 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
            retryable=True,
        ) from None
    finally:
        _HASH_SLOTS.release()
