from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.recipes import active_recipes, matches_allergies, recipe_record
from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import (
    FoodRevision,
    MealLog,
    MealLogItem,
    Profile,
    Recipe,
    RecommendationItem,
    RecommendationRun,
    SeasonalFood,
    SeasonalRecipeLink,
)
from app.schemas.catalog import (
    RecipeRecommendation,
    RecipeRecommendationRequest,
    RecipeRecommendationResponse,
    RecipeRecommendationResult,
    SeasonalMatch,
)
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.profile import Preferences
from app.services.meal_recommendations import RULES_VERSION, recommend

router = APIRouter(
    prefix="/meal",
    tags=["meal"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 503)},
)
KOREA_TIMEZONE = timezone(timedelta(hours=9))


@router.post("/recommendations", response_model=RecipeRecommendationResponse)
def recommend_meal(
    payload: RecipeRecommendationRequest,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    now = datetime.now(UTC)
    try:
        profile = db.get(Profile, auth.user.id)
        preferences = (
            Preferences.model_validate(profile.preferences)
            if profile
            else Preferences()
        )
        recent = db.scalars(
            select(FoodRevision.name)
            .join(MealLogItem, FoodRevision.id == MealLogItem.food_revision_id)
            .join(MealLog, MealLogItem.meal_log_id == MealLog.id)
            .where(
                MealLog.user_id == auth.user.id,
                MealLog.eaten_at >= now - timedelta(days=7),
                MealLog.eaten_at <= now,
            )
            .distinct()
        ).all()
        excluded_allergens = set(payload.exclude_allergens) | set(
            preferences.exclude_allergens
        )
        seasonal = defaultdict(list)
        for revision_id, name, source_url, shopping_url in db.execute(
            select(
                SeasonalRecipeLink.recipe_revision_id,
                SeasonalFood.name,
                SeasonalFood.source_url,
                SeasonalFood.shopping_search_url,
            )
            .join(SeasonalFood, SeasonalFood.id == SeasonalRecipeLink.seasonal_food_id)
            .join(
                Recipe,
                Recipe.active_revision_id == SeasonalRecipeLink.recipe_revision_id,
            )
            .where(
                SeasonalFood.is_published.is_(True),
                SeasonalFood.month == now.astimezone(KOREA_TIMEZONE).month,
            )
            .order_by(SeasonalFood.name, SeasonalFood.source_id)
        ):
            seasonal[revision_id].append(
                SeasonalMatch(
                    name=name, source_url=source_url, shopping_search_url=shopping_url
                )
            )
        records = (recipe_record(*row) for row in db.execute(active_recipes()))
        ranked = recommend(
            (
                record
                for record in records
                if not excluded_allergens
                or matches_allergies(record, excluded_allergens)
            ),
            payload,
            preferences,
            recent,
            seasonal,
        )
        items = [
            RecipeRecommendation(
                item=record,
                reasons=reasons,
                seasonal_ingredients=seasonal.get(record.source.revision_id, []),
            )
            for record, reasons in ranked
        ]
        run = RecommendationRun(
            user_id=auth.user.id,
            meal_time=payload.meal_time,
            rules_version=RULES_VERSION,
            evaluated_at=now,
        )
        db.add(run)
        db.flush()
        for rank, item in enumerate(items, 1):
            db.add(
                RecommendationItem(
                    run_id=run.id,
                    rank=rank,
                    recipe_revision_id=item.item.source.revision_id,
                    reasons=item.reasons,
                    seasonal_ingredients=[
                        match.model_dump() for match in item.seasonal_ingredients
                    ],
                )
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise AppError(
            503,
            "MEAL_RECOMMENDATION_UNAVAILABLE",
            "식단 추천을 잠시 불러올 수 없습니다.",
            retryable=True,
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return RecipeRecommendationResponse(
        data=RecipeRecommendationResult(
            recommendation_id=run.id,
            items=items,
            evaluated_at=now,
            rules_version=RULES_VERSION,
            warnings=[
                "식단 추천은 의료적 식이 판단을 대신할 수 없습니다.",
                *(
                    [
                        "건강 조건은 공개 영양 표기량으로 비교해요. 실제 한 끼 섭취량과 다를 수 있어요."
                    ]
                    if payload.health_conditions
                    else []
                ),
            ],
        ),
        meta=build_meta(request),
    )
