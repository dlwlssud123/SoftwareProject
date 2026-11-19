from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator, Field

from app.schemas.catalog import ContractModel
from app.schemas.common import SuccessResponse


def _iso_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("Use YYYY-MM-DD")
    return parsed


PlanDate = Annotated[date, BeforeValidator(_iso_date)]


class MealSlot(StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"
    special = "special"


class MealPlanSave(ContractModel):
    recipe_id: str = Field(pattern=r"^[0-9]+$", max_length=64)
    recipe_revision_id: UUID | None = None


class PlannedMeal(ContractModel):
    meal_slot: MealSlot
    recipe_id: str
    recipe_revision_id: UUID
    name: str
    is_active: bool


class DayMealPlan(ContractModel):
    plan_date: date
    items: list[PlannedMeal]


MealPlanResponse = SuccessResponse[DayMealPlan]
PlannedMealResponse = SuccessResponse[PlannedMeal]
