"""AI responses are previews. Food identity and portions require user confirmation."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from threading import BoundedSemaphore

from agetech_data.nutrition.foods import FoodRecord as DataFoodRecord
from agetech_data.nutrition.match import FoodIndex, match_ingredient, search_dishes
from agetech_data.nutrition.portion import serving_reference
from fastapi import APIRouter, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.api.foods import food_record
from app.api.recipes import active_recipes
from app.core.auth import CurrentAuth, DbSession, unauthenticated
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    AIUsageBucket,
    AuthSession,
    Food,
    FoodRevision,
    Recipe,
    RecipeRevision,
    User,
)
from app.schemas.ai import (
    ChatRequest,
    ChatResult,
    IngredientCandidate,
    IngredientRequest,
    IngredientResult,
    MatchedFood,
    PhotoDish,
    PhotoRequest,
    PhotoResult,
    RecipeReference,
    ServingSuggestion,
)
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.welfare_chat import WelfareChatRequest, WelfareChatResult
from app.services import nvidia_ai, rag_embedding, welfare_rag
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
def _request_slot(*, check_provider=True):
    if check_provider:
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


@router.post("/welfare-chat", response_model=SuccessResponse[WelfareChatResult])
def welfare_chat(
    request: Request, payload: WelfareChatRequest, db: DbSession, auth: CurrentAuth
):
    rag_embedding.check_enabled()
    with _request_slot(check_provider=False):
        _budget(db, auth)
        response = welfare_rag.answer(db, payload)
        try:
            _active(db, auth)
        except SQLAlchemyError:
            raise rag_embedding.unavailable() from None
    return SuccessResponse(data=response, meta=build_meta(request))


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


def _photo_foods():
    return active_foods().where(
        FoodRevision.basis_unit.in_(("g", "mL")),
        FoodRevision.basis_amount > 0,
        FoodRevision.nutrients["energy_kcal"].as_float().is_not(None),
    )


def _similar_food_index(db):
    # Read compact matching metadata, not thousands of full nutrition/source JSON records.
    rows = db.execute(
        _photo_foods()
        .where(FoodRevision.normalized["db_group"].as_string() == "음식")
        .with_only_columns(
            Food.food_code.label("food_code"),
            FoodRevision.name.label("name"),
            FoodRevision.normalized["db_group"].as_string().label("db_group"),
            FoodRevision.basis_unit.label("basis_unit"),
            FoodRevision.normalized["ref_name"].as_string().label("ref_name"),
        )
    ).mappings()
    return FoodIndex([dict(row) for row in rows], ("음식",))


def _matches(db, dish, fallback_index):
    # Names are search terms, never trusted SQL or automatically confirmed food IDs.
    stmt = (
        _photo_foods()
        .where(FoodRevision.name.icontains(dish.name, autoescape=True))
        .where(
            or_(
                FoodRevision.normalized["db_group"]
                .as_string()
                .is_distinct_from("원재료성"),
                # A raw apple may match '사과, 생것'; shrimp must not replace shrimp fried rice.
                func.trim(func.split_part(FoodRevision.name, ",", 1)) == dish.name,
            )
        )
        .order_by(
            (FoodRevision.name == dish.name).desc(),
            FoodRevision.name,
            Food.id,
        )
        .limit(5)
    )
    rows = list(db.execute(stmt))
    similar = not rows
    if similar:
        codes = [
            candidate["food_code"]
            for candidate in search_dishes(dish.name, fallback_index(), limit=5)[:5]
        ]
        if codes:
            found = {
                food.food_code: (food, revision, imported_at)
                for food, revision, imported_at in db.execute(
                    _photo_foods().where(
                        Food.food_code.in_(codes),
                        FoodRevision.normalized["db_group"].as_string() == "음식",
                    )
                )
            }
            rows = [found[code] for code in codes if code in found]
    return [
        MatchedFood(
            food=food_record(food, revision, imported_at),
            serving=_serving(revision, dish.standard_serving_grams),
            match_basis="name" if revision.name == dish.name else "similar",
        )
        for food, revision, imported_at in rows
    ]


@router.post("/food-photo", response_model=SuccessResponse[PhotoResult])
def photo(request: Request, payload: PhotoRequest, db: DbSession, auth: CurrentAuth):
    with _request_slot():
        clean = nvidia_ai.sanitize_photo(payload.image_base64)
        _budget(db, auth)
        inference = nvidia_ai.recognize(clean)
        try:
            _active(db, auth)
            index = None

            def fallback_index():
                nonlocal index
                if index is None:
                    index = _similar_food_index(db)
                return index

            result = PhotoResult(
                is_food=inference.is_food,
                foods=[
                    PhotoDish(
                        **dish.model_dump(), matches=_matches(db, dish, fallback_index)
                    )
                    for dish in inference.foods
                ],
                model=get_settings().nvidia_model,
            )
        except (SQLAlchemyError, TypeError, ValueError):
            raise nvidia_ai.unavailable("AI_MATCH_UNAVAILABLE") from None
    # No photo, prompt, meal log or guessed nutrient value is stored by this endpoint.
    return SuccessResponse(data=result, meta=build_meta(request))


def _ingredient_index(db):
    rows = db.execute(
        _photo_foods()
        .where(
            FoodRevision.normalized["db_group"]
            .as_string()
            .in_(("원재료성", "가공식품"))
        )
        .with_only_columns(
            Food.food_code.label("food_code"),
            FoodRevision.name.label("name"),
            FoodRevision.normalized["db_group"].as_string().label("db_group"),
            FoodRevision.basis_unit.label("basis_unit"),
            FoodRevision.normalized["ref_name"].as_string().label("ref_name"),
        )
    ).mappings()
    return FoodIndex([dict(row) for row in rows])


def _ingredient_candidate(db, ingredient, index):
    match = match_ingredient(ingredient.name, index)
    exact = match.usable and match.food_code in index.by_code
    codes = (
        [match.food_code]
        if exact
        else [
            row["food_code"]
            for row in index.candidates(ingredient.name, limit=3, min_score=0.8)
        ]
    )
    if match.status == "water":
        codes = []
    found = (
        {
            food.food_code: (food, revision, imported_at)
            for food, revision, imported_at in db.execute(
                _photo_foods().where(
                    Food.food_code.in_(codes),
                    FoodRevision.normalized["db_group"]
                    .as_string()
                    .in_(("원재료성", "가공식품")),
                )
            )
        }
        if codes
        else {}
    )
    return IngredientCandidate(
        **ingredient.model_dump(),
        is_water=match.status == "water",
        matches=[
            MatchedFood(
                food=food_record(*found[code]),
                match_basis="name" if exact else "similar",
                serving=ServingSuggestion(
                    amount=ingredient.amount_g,
                    unit="g",
                    basis="ai_estimate",
                    description="일반적인 조리법의 1인분 예상 재료량 · 실제 사용량을 확인해 주세요",
                ),
            )
            for code in codes
            if code in found
        ],
    )


def _reference_recipe(db, name):
    row = db.execute(
        active_recipes()
        .where(RecipeRevision.name.icontains(name, autoescape=True))
        .order_by((RecipeRevision.name == name).desc(), Recipe.source_id)
        .limit(1)
    ).first()
    if row is None:
        return None, None
    recipe, revision, _, _ = row
    text = revision.effective.get("RCP_PARTS_DTLS")
    if not isinstance(text, str) or not text.strip():
        return None, None
    ref = RecipeReference(
        recipe_id=recipe.source_id, revision_id=revision.id, name=revision.name
    )
    return ref, {"name": ref.name, "ingredients_text": text[:2000]}


@router.post("/food-ingredients", response_model=SuccessResponse[IngredientResult])
def ingredients(
    request: Request, payload: IngredientRequest, db: DbSession, auth: CurrentAuth
):
    with _request_slot():
        _budget(db, auth)
        try:
            reference, context = _reference_recipe(db, payload.dish_name)
        except SQLAlchemyError:
            raise nvidia_ai.unavailable("AI_MATCH_UNAVAILABLE") from None
        inferred = nvidia_ai.estimate_ingredients(
            payload.dish_name, payload.standard_serving_grams, context
        )
        try:
            _active(db, auth)
            index = _ingredient_index(db)
            result = IngredientResult(
                dish_name=payload.dish_name,
                reference_recipe=reference,
                ingredients=[
                    _ingredient_candidate(db, item, index)
                    for item in inferred.ingredients
                ],
            )
        except (SQLAlchemyError, TypeError, ValueError):
            raise nvidia_ai.unavailable("AI_MATCH_UNAVAILABLE") from None
    return SuccessResponse(data=result, meta=build_meta(request))
