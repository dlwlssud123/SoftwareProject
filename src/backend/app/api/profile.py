from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import Profile, User
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.profile import Preferences, ProfileData, ProfilePatch, ProfileResponse

router = APIRouter(
    prefix="/profile",
    tags=["profile"],
    responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
)


def _result(
    request: Request, response: Response, profile: Profile | None
) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    data = (
        None
        if profile is None
        else ProfileData(
            preferences=Preferences.model_validate(profile.preferences),
            consented_at=profile.consented_at,
            updated_at=profile.updated_at,
        )
    )
    return ProfileResponse(data=data, meta=build_meta(request))


def _unavailable() -> AppError:
    return AppError(
        503, "PROFILE_UNAVAILABLE", "프로필을 잠시 처리할 수 없습니다.", retryable=True
    )


def _lock_owner(db: DbSession, auth: CurrentAuth) -> None:
    db.execute(
        select(User.id).where(User.id == auth.user.id).with_for_update()
    ).scalar_one()


@router.get("", response_model=ProfileResponse)
def get_profile(request: Request, response: Response, auth: CurrentAuth, db: DbSession):
    try:
        profile = db.get(Profile, auth.user.id)
    except SQLAlchemyError:
        raise _unavailable() from None
    return _result(request, response, profile)


@router.patch("", response_model=ProfileResponse)
def patch_profile(
    payload: ProfilePatch,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    if payload.consent is False:
        if payload.preferences is not None:
            raise AppError(
                422,
                "CONSENT_WITHDRAWAL_ONLY",
                "동의 철회와 프로필 변경은 따로 요청해 주세요.",
            )
        return delete_profile(request, response, auth, db)
    changes = (
        {}
        if payload.preferences is None
        else payload.preferences.model_dump(exclude_unset=True)
    )
    if payload.consent is None and not changes:
        raise AppError(
            422, "EMPTY_PROFILE_UPDATE", "변경할 프로필 항목을 입력해 주세요."
        )
    try:
        _lock_owner(db, auth)
        profile = db.get(Profile, auth.user.id)
        if profile is None and payload.consent is not True:
            raise AppError(
                409, "PROFILE_CONSENT_REQUIRED", "프로필을 저장하려면 동의해 주세요."
            )
        now = datetime.now(UTC)
        current = {} if profile is None else profile.preferences
        updated = Preferences.model_validate({**current, **changes})
        if profile is None:
            profile = Profile(user_id=auth.user.id, consented_at=now)
            db.add(profile)
        profile.preferences = updated.model_dump(mode="json")
        profile.updated_at = now
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _result(request, response, profile)


@router.delete("", response_model=ProfileResponse)
def delete_profile(
    request: Request, response: Response, auth: CurrentAuth, db: DbSession
):
    try:
        _lock_owner(db, auth)
        db.execute(delete(Profile).where(Profile.user_id == auth.user.id))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _result(request, response, None)
