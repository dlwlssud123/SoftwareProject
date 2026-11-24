"""AI responses are previews. Food identity and portions require user confirmation."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from threading import BoundedSemaphore

from agetech_data.nutrition.foods import FoodRecord as DataFoodRecord
from agetech_data.nutrition.portion import serving_reference
from fastapi import APIRouter, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.api.foods import food_record
from app.core.auth import CurrentAuth, DbSession, unauthenticated
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AIUsageBucket, AuthSession, Food, FoodRevision, User
from app.schemas.ai import (
    ChatRequest,
    ChatResult,
    MatchedFood,
    PhotoDish,
    PhotoRequest,
    PhotoResult,
    ServingSuggestion,
)
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.services import nvidia_ai
from app.services.food_nutrition import active_foods

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
    responses={code: {"model": ErrorResponse} for code in (401, 413, 422, 429, 503)},
)
_slots = BoundedSemaphore(2)
KST = timezone(timedelta(hours=9))


def _active(db, auth):
    exists = db.scalar(
        select(AuthSession.id)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.id == auth.session.id,
            AuthSession.user_id == auth.user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            User.disabled_at.is_(None),
        )
    )
    if exists is None:
        raise unauthenticated()


def _budget(db, auth):
    settings = get_settings()
    today = datetime.now(KST).date()
    owner = "u-" + hashlib.sha256(str(auth.user.id).encode()).hexdigest()
    try:
        _active(db, auth)
        db.execute(
            delete(AIUsageBucket).where(
                AIUsageBucket.usage_date < today - timedelta(days=7)
            )
        )
        # One consistent order prevents counter deadlocks; rollback keeps both counters atomic.
        for identifier, limit in (
            ("global", settings.ai_daily_global_limit),
            (owner, settings.ai_daily_user_limit),
        ):
            statement = insert(AIUsageBucket).values(
                bucket_id=identifier, usage_date=today, calls=1
            )
            statement = statement.on_conflict_do_update(
                index_elements=[AIUsageBucket.bucket_id, AIUsageBucket.usage_date],
                set_={"calls": AIUsageBucket.calls + 1},
                where=AIUsageBucket.calls < limit,
            ).returning(AIUsageBucket.calls)
            if db.scalar(statement) is None:
                raise AppError(
                    429,
                    "AI_DAILY_LIMIT",
                    "오늘 AI 이용 한도에 도달했어요. 직접 입력은 계속 이용할 수 있어요.",
                )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise nvidia_ai.unavailable() from None
    except AppError:
        db.rollback()
        raise


@contextmanager
def _request_slot():
    nvidia_ai.check_enabled()
    if not _slots.acquire(blocking=False):
        raise AppError(
            429,
            "AI_BUSY",
            "AI가 다른 요청을 처리 중이에요. 잠시 뒤 다시 시도해 주세요.",
            retryable=True,
            headers={"Retry-After": "3"},
        )
    try:
        yield
    finally:
        _slots.release()


@router.post("/chat", response_model=SuccessResponse[ChatResult])
def chat(request: Request, payload: ChatRequest, db: DbSession, auth: CurrentAuth):
    with _request_slot():
        _budget(db, auth)
        answer = nvidia_ai.chat(payload.message)
        try:
            _active(db, auth)
        except SQLAlchemyError:
            raise nvidia_ai.unavailable() from None
    return SuccessResponse(
        data=ChatResult(answer=answer.answer, model=get_settings().nvidia_model),
        meta=build_meta(request),
    )


def _serving(revision, estimate):
    reference = serving_reference(DataFoodRecord(**revision.normalized))
    if reference is not None and reference[0] <= 1500:
        amount, unit, source = reference
        return ServingSuggestion(
            amount=float(amount),
            unit=unit,
            basis="source_serving",
            description=f"원천 1회분량 참고값: {source['text']}",
        )
    return ServingSuggestion(
        amount=float(estimate),
        unit="g",
        basis="ai_estimate",
        description=f"AI가 제안한 보통 1인분 약 {estimate}g · 실제 중량 측정값이 아니에요",
    )


def _matches(db, dish):
    # Names are search terms, never trusted SQL or automatically confirmed food IDs.
    stmt = (
        active_foods()
        .where(FoodRevision.name.icontains(dish.name, autoescape=True))
        .order_by(
            (FoodRevision.name == dish.name).desc(),
            FoodRevision.name,
            Food.id,
        )
        .limit(5)
    )
    return [
        MatchedFood(
            food=food_record(food, revision, imported_at),
            serving=_serving(revision, dish.standard_serving_grams),
        )
        for food, revision, imported_at in db.execute(stmt)
    ]


@router.post("/food-photo", response_model=SuccessResponse[PhotoResult])
def photo(request: Request, payload: PhotoRequest, db: DbSession, auth: CurrentAuth):
    with _request_slot():
        clean = nvidia_ai.sanitize_photo(payload.image_base64)
        _budget(db, auth)
        inference = nvidia_ai.recognize(clean)
        try:
            _active(db, auth)
            result = PhotoResult(
                is_food=inference.is_food,
                foods=[
                    PhotoDish(**dish.model_dump(), matches=_matches(db, dish))
                    for dish in inference.foods
                ],
                model=get_settings().nvidia_model,
            )
        except (SQLAlchemyError, TypeError, ValueError):
            raise nvidia_ai.unavailable("AI_MATCH_UNAVAILABLE") from None
    # No photo, prompt, meal log or guessed nutrient value is stored by this endpoint.
    return SuccessResponse(data=result, meta=build_meta(request))
