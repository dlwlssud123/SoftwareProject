from datetime import date
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BeforeValidator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.jobs.import_public_data import RECIPE_PROVIDER
from app.models import MealPlanEntry, Recipe, RecipeRevision
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.meal_plan import (
    DayMealPlan,
    MealPlanResponse,
    MealPlanSave,
    MealSlot,
    PlannedMeal,
    PlannedMealResponse,
)

router = APIRouter(
    prefix="/meal-plans",
    tags=["meal-plans"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 503)},
)


def _iso_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("Use YYYY-MM-DD")
    return parsed


PlanDate = Annotated[date, BeforeValidator(_iso_date)]


def _unavailable() -> AppError:
    return AppError(
        503,
        "MEAL_PLAN_UNAVAILABLE",
        "식단표를 잠시 처리할 수 없습니다.",
        retryable=True,
    )


@router.get("/{plan_date}", response_model=MealPlanResponse)
def get_meal_plan(
    plan_date: PlanDate,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    table = MealPlanEntry
    try:
        rows = db.execute(
            select(
                table.meal_slot,
                Recipe.source_id,
                RecipeRevision.id,
                RecipeRevision.name,
                Recipe.active_revision_id,
            )
            .select_from(table)
            .join(RecipeRevision, RecipeRevision.id == table.recipe_revision_id)
            .join(Recipe, Recipe.id == RecipeRevision.recipe_id)
            .where(table.user_id == auth.user.id, table.plan_date == plan_date)
        ).all()
    except SQLAlchemyError:
        raise _unavailable() from None
    items = {
        slot: PlannedMeal(
            meal_slot=slot,
            recipe_id=recipe_id,
            recipe_revision_id=revision_id,
            name=name,
            is_active=revision_id == active_id,
        )
        for slot, recipe_id, revision_id, name, active_id in rows
    }
    response.headers["Cache-Control"] = "no-store"
    return MealPlanResponse(
        data=DayMealPlan(
            plan_date=plan_date,
            items=[items[slot] for slot in MealSlot if slot in items],
        ),
        meta=build_meta(request),
    )


@router.put(
    "/{plan_date}/{meal_slot}",
    response_model=PlannedMealResponse,
    responses={code: {"model": ErrorResponse} for code in (404, 409)},
)
def save_meal(
    plan_date: PlanDate,
    meal_slot: MealSlot,
    payload: MealPlanSave,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        active = db.execute(
            select(RecipeRevision.id, RecipeRevision.name)
            .join(Recipe, Recipe.active_revision_id == RecipeRevision.id)
            .where(
                Recipe.provider == RECIPE_PROVIDER,
                Recipe.source_id == payload.recipe_id,
                RecipeRevision.quality_status != "hold",
            )
            .with_for_update(read=True, of=Recipe)
        ).one_or_none()
        if active is None:
            raise AppError(404, "RECIPE_NOT_FOUND", "저장할 레시피를 찾을 수 없습니다.")
        revision_id, name = active
        if (
            payload.recipe_revision_id is not None
            and payload.recipe_revision_id != revision_id
        ):
            raise AppError(
                409,
                "RECIPE_REVISION_CHANGED",
                "레시피가 갱신됐어요. 새 내용을 확인하고 다시 저장해 주세요.",
            )
        statement = insert(MealPlanEntry).values(
            user_id=auth.user.id,
            plan_date=plan_date,
            meal_slot=meal_slot,
            recipe_revision_id=revision_id,
        )
        db.execute(
            statement.on_conflict_do_update(
                constraint="uq_meal_plan_user_date_slot",
                set_={"recipe_revision_id": statement.excluded.recipe_revision_id},
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return PlannedMealResponse(
        data=PlannedMeal(
            meal_slot=meal_slot,
            recipe_id=payload.recipe_id,
            recipe_revision_id=revision_id,
            name=name,
            is_active=True,
        ),
        meta=build_meta(request),
    )


def _delete_entries(
    plan_date: date, auth: CurrentAuth, db: DbSession, meal_slot: MealSlot | None = None
) -> Response:
    statement = delete(MealPlanEntry).where(
        MealPlanEntry.user_id == auth.user.id, MealPlanEntry.plan_date == plan_date
    )
    if meal_slot is not None:
        statement = statement.where(MealPlanEntry.meal_slot == meal_slot)
    try:
        db.execute(statement)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.delete("/{plan_date}", status_code=204)
def delete_meal_plan(plan_date: PlanDate, auth: CurrentAuth, db: DbSession) -> Response:
    return _delete_entries(plan_date, auth, db)


@router.delete("/{plan_date}/{meal_slot}", status_code=204)
def delete_meal(
    plan_date: PlanDate, meal_slot: MealSlot, auth: CurrentAuth, db: DbSession
) -> Response:
    return _delete_entries(plan_date, auth, db, meal_slot)
