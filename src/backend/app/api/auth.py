from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import (
    CurrentAuth,
    DbSession,
    auth_unavailable,
    new_session,
    unauthenticated,
)
from app.models.auth import AuthSession, User
from app.schemas.auth import GuestRequest, IdentityData, RevokedData, SessionData
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 500, 503)},
)


def issued_response(
    request: Request, user: User, session: AuthSession, token: str, status: int
):
    # SecretStr protects logs/repr; unwrap only at the issuing HTTP boundary.
    data = SessionData(
        user_id=user.id,
        role=user.role,
        expires_at=session.expires_at,
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


@router.get("/me", response_model=SuccessResponse[IdentityData])
def identity(request: Request, response: Response, auth: CurrentAuth):
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=IdentityData(
            user_id=auth.user.id,
            role=auth.user.role,
            expires_at=auth.session.expires_at,
        ),
        meta=build_meta(request),
    )


@router.post("/refresh", response_model=SuccessResponse[SessionData])
def refresh(request: Request, db: DbSession, auth: CurrentAuth):
    now = datetime.now(UTC)
    try:
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
        session, token = new_session(auth.user.id, now)
        db.add(session)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise auth_unavailable() from None
    return issued_response(request, auth.user, session, token, 200)


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
