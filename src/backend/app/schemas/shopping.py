from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.schemas.catalog import ContractModel
from app.schemas.common import SuccessResponse
from app.schemas.meal_plan import MealSlot


class ShoppingSource(ContractModel):
    plan_entry_id: UUID
    meal_slot: MealSlot
    recipe_id: str
    recipe_name: str
    recipe_revision_id: UUID
    ingredient_id: UUID
    section: str | None
    name_raw: str
    amount_text: str | None
    is_active: bool


class ShoppingItem(ContractModel):
    item_key: str
    source_hash: str
    name: str
    amount: float | None
    unit: str | None
    amount_text: str
    combined: bool
    checked: bool = False
    shopping_search_url: str
    sources: list[ShoppingSource]


class ShoppingList(ContractModel):
    plan_date: date
    planned_meals: int
    items: list[ShoppingItem]
    warnings: list[str]


class ShoppingCheckUpdate(ContractModel):
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    checked: Annotated[bool, Field(strict=True)]


class ShoppingCheckState(ContractModel):
    item_key: str
    source_hash: str
    checked: bool


ShoppingResponse = SuccessResponse[ShoppingList]
ShoppingCheckResponse = SuccessResponse[ShoppingCheckState]
