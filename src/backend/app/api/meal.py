from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.recipes import active_recipes, matches_allergies, recipe_record
from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import FoodRevision, MealLog, MealLogItem, Profile
from app.schemas.catalog import (
    RecipeRecommendationRequest,
    RecipeRecommendationResponse,
    RecipeRecord,
    Recommendation,
    RecommendationResult,
)
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.profile import Preferences
from app.services.meal_recommendations import RULES_VERSION, recommend

router = APIRouter(
    prefix="/meal",
    tags=["meal"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 503)},
)


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
        records = (recipe_record(*row) for row in db.execute(active_recipes()))
        items = recommend(
            (
                record
                for record in records
                if not excluded_allergens
                or matches_allergies(record, excluded_allergens)
            ),
            payload,
            preferences,
            recent,
        )
    except SQLAlchemyError:
        raise AppError(
            503,
            "MEAL_RECOMMENDATION_UNAVAILABLE",
            "식단 추천을 잠시 불러올 수 없습니다.",
            retryable=True,
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return RecipeRecommendationResponse(
        data=RecommendationResult[RecipeRecord](
            items=[
                Recommendation[RecipeRecord](item=record, reasons=reasons)
                for record, reasons in items
            ],
            evaluated_at=now,
            rules_version=RULES_VERSION,
            warnings=["식단 추천은 의료적 식이 판단을 대신할 수 없습니다."],
        ),
        meta=build_meta(request),
    )
