from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import (
    CurrentAuth,
    DbSession,
    auth_unavailable,
    new_session,
    unauthenticated,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.kakao import verify_kakao_token
from app.models.auth import AuthSession, KakaoIdentity, User
from app.schemas.auth import (
    GuestRequest,
    IdentityData,
    KakaoRequest,
    RevokedData,
    SessionData,
)
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 500, 503)},
)


def issued_response(
    request: Request,
    user: User,
    session: AuthSession,
    token: str,
    status: int,
    *,
    kakao_linked: bool = False,
):
    # SecretStr protects logs/repr; unwrap only at the issuing HTTP boundary.
    data = SessionData(
        user_id=user.id,
        role=user.role,
        expires_at=session.expires_at,
        kakao_linked=kakao_linked,
        access_token=token,
    )
    body = SuccessResponse(data=data, meta=build_meta(request)).model_dump(mode="json")
    body["data"]["access_token"] = data.access_token.get_secret_value()
    return JSONResponse(
        status_code=status, content=body, headers={"Cache-Control": "no-store"}
    )


@router.post("/guest", status_code=201, response_model=SuccessResponse[SessionData])
def create_guest(payload: GuestRequest, request: Request, db: DbSession):
    try:
        user = User(role="user")
        db.add(user)
        db.flush()
        session, token = new_session(user.id, datetime.now(UTC))
        db.add(session)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    return issued_response(request, user, session, token, 201)


def _linked_identity(db: DbSession, user: User) -> KakaoIdentity | None:
    return db.scalar(select(KakaoIdentity).where(KakaoIdentity.user_id == user.id))


def _identity_response(
    request: Request, response: Response, auth: CurrentAuth, *, kakao_linked: bool
) -> SuccessResponse[IdentityData]:
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=IdentityData(
            user_id=auth.user.id,
            role=auth.user.role,
            expires_at=auth.session.expires_at,
            kakao_linked=kakao_linked,
        ),
        meta=build_meta(request),
    )


@router.get("/me", response_model=SuccessResponse[IdentityData])
def identity(request: Request, response: Response, auth: CurrentAuth, db: DbSession):
    try:
        linked = _linked_identity(db, auth.user) is not None
    except SQLAlchemyError:
        raise auth_unavailable() from None
    return _identity_response(request, response, auth, kakao_linked=linked)


def _verified_kakao_identity(payload: KakaoRequest) -> tuple[int, int]:
    app_id = get_settings().kakao_app_id
    if app_id is None:
        raise AppError(503, "KAKAO_DISABLED", "카카오 로그인은 아직 사용할 수 없어요.")
    return app_id, verify_kakao_token(payload.access_token.get_secret_value(), app_id)


def _lock_kakao_identity(db: DbSession, app_id: int, subject: int) -> None:
    # Both login and linking must see the same owner when a new identity is claimed.
    key = f"valueflow:kakao:{app_id}:{subject}"
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


@router.post("/kakao", response_model=SuccessResponse[SessionData])
def login_with_kakao(payload: KakaoRequest, request: Request, db: DbSession):
    app_id, subject = _verified_kakao_identity(payload)
    try:
        _lock_kakao_identity(db, app_id, subject)
        identity = db.get(KakaoIdentity, (app_id, subject))
        if identity is None:
            user = User(role="user")
            db.add(user)
            db.flush()
            db.add(KakaoIdentity(app_id=app_id, subject=subject, user_id=user.id))
        else:
            user = db.get(User, identity.user_id, with_for_update=True)
            if user is None or user.disabled_at is not None or user.role != "user":
                raise unauthenticated()
        session, token = new_session(user.id, datetime.now(UTC))
        db.add(session)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    return issued_response(request, user, session, token, 200, kakao_linked=True)


@router.post(
    "/kakao/link",
    response_model=SuccessResponse[IdentityData],
    responses={409: {"model": ErrorResponse}},
)
def link_kakao(
    payload: KakaoRequest,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    app_id, subject = _verified_kakao_identity(payload)
    try:
        _lock_kakao_identity(db, app_id, subject)
        owner = db.scalar(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                User.id == auth.user.id,
                User.role == "user",
                User.disabled_at.is_(None),
                AuthSession.id == auth.session.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        if owner is None:
            raise unauthenticated()
        existing = db.get(KakaoIdentity, (app_id, subject))
        linked = _linked_identity(db, owner)
        if existing is not None and existing.user_id != owner.id:
            raise AppError(
                409,
                "KAKAO_ALREADY_LINKED",
                "이미 다른 오늘동행 계정에 연결된 카카오 계정이에요.",
            )
        if linked is not None and (linked.app_id, linked.subject) != (app_id, subject):
            raise AppError(
                409, "USER_ALREADY_LINKED", "이미 카카오 계정이 연결되어 있어요."
            )
        if existing is None:
            db.add(KakaoIdentity(app_id=app_id, subject=subject, user_id=owner.id))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    return _identity_response(request, response, auth, kakao_linked=True)


@router.post("/refresh", response_model=SuccessResponse[SessionData])
def refresh(request: Request, db: DbSession, auth: CurrentAuth):
    try:
        # Use the same identity-first lock as account reset/disable. Otherwise a
        # replacement committed while their session UPDATE waits can escape it.
        owner = db.scalar(
            select(User)
            .where(User.id == auth.user.id, User.disabled_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if owner is None:
            raise unauthenticated()
        now = datetime.now(UTC)
        # A conditional UPDATE serializes competing refreshes: exactly one wins.
        consumed = db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == auth.session.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .values(revoked_at=now)
            .returning(AuthSession.id)
        ).scalar_one_or_none()
        if consumed is None:
            raise unauthenticated()
        session, token = new_session(
            auth.user.id, now, reauthenticate_at=auth.session.reauthenticate_at
        )
        db.add(session)
        linked = _linked_identity(db, auth.user) is not None
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    return issued_response(request, auth.user, session, token, 200, kakao_linked=linked)


@router.delete("/session", response_model=SuccessResponse[RevokedData])
def revoke(request: Request, response: Response, db: DbSession, auth: CurrentAuth):
    try:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == auth.session.id)
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(data=RevokedData(), meta=build_meta(request))
