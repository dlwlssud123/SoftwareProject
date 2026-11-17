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
    RecipeIngredientFood,
    RecipeRevision,
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
        recent = db.execute(
            select(FoodRevision.food_id, FoodRevision.name)
            .join(MealLogItem, FoodRevision.id == MealLogItem.food_revision_id)
            .join(MealLog, MealLogItem.meal_log_id == MealLog.id)
            .where(
                MealLog.user_id == auth.user.id,
                MealLog.eaten_at >= now - timedelta(days=7),
                MealLog.eaten_at <= now,
            )
            .distinct()
        ).all()
        recently_eaten_revisions = set()
        if recent:
            recently_eaten_revisions.update(
                db.scalars(
                    select(RecipeIngredientFood.recipe_revision_id)
                    .join(
                        Recipe,
                        Recipe.active_revision_id
                        == RecipeIngredientFood.recipe_revision_id,
                    )
                    .where(
                        RecipeIngredientFood.food_id.in_(
                            {food_id for food_id, _ in recent}
                        )
                    )
                    .distinct()
                )
            )
        excluded_allergens = set(payload.exclude_allergens) | set(
            preferences.exclude_allergens
        )
        recent_runs = (
            select(RecommendationRun.id)
            .where(
                RecommendationRun.user_id == auth.user.id,
                RecommendationRun.meal_time == payload.meal_time,
                RecommendationRun.evaluated_at >= now - timedelta(days=2),
                RecommendationRun.evaluated_at <= now,
                select(RecommendationItem.run_id)
                .where(RecommendationItem.run_id == RecommendationRun.id)
                .exists(),
            )
            .order_by(
                RecommendationRun.evaluated_at.desc(), RecommendationRun.id.desc()
            )
            .limit(2)
        )
        recently_featured = db.execute(
            select(Recipe.source_id, RecipeRevision.name)
            .join(RecipeRevision, Recipe.id == RecipeRevision.recipe_id)
            .join(
                RecommendationItem,
                RecipeRevision.id == RecommendationItem.recipe_revision_id,
            )
            .where(
                RecommendationItem.run_id.in_(recent_runs),
                RecommendationItem.rank <= 3,
            )
        ).all()
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
            (name for _, name in recent),
            seasonal,
            recently_featured,
            recently_eaten_revisions,
        )
        items = [
            RecipeRecommendation(
                item=match.record,
                reasons=match.reasons or ["현재 공개된 레시피예요."],
                seasonal_ingredients=seasonal.get(match.record.source.revision_id, []),
                matched_preferences=[
                    *(["soft_food"] if match.soft_match else []),
                    *(["simple_cooking"] if match.simple_match else []),
                ],
            )
            for match in ranked
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
                *(
                    [
                        "건강 조건은 재료로 계산한 영양을 같은 열량 기준으로 비교해요. 한 끼에 드시는 양은 알 수 없어 참고용이에요."
                    ]
                    if payload.health_conditions
                    else []
                ),
                *(
                    [
                        "부드러운 메뉴는 이름과 조리법으로 골라요. 씹기 편한지는 재료와 조리 방법을 확인해 주세요."
                    ]
                    if payload.soft_food or preferences.soft_food
                    else []
                ),
            ],
        ),
        meta=build_meta(request),
    )
