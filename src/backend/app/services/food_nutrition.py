"""Shared calculation preview and immutable snapshot for confirmed intake records."""

from agetech_data.nutrition.foods import FoodRecord as DataFoodRecord
from agetech_data.nutrition.portion import meal_total, portion_nutrients
from sqlalchemy import select

from app.core.errors import AppError
from app.jobs.import_public_data import FOOD_PROVIDER
from app.models import DataImportRun, Food, FoodRevision
from app.schemas.nutrition import FoodSource, NutritionCalculation

NO_STORE = {"Cache-Control": "no-store"}


def active_foods():
    return (
        select(Food, FoodRevision, DataImportRun.completed_at)
        .join(FoodRevision, Food.active_revision_id == FoodRevision.id)
        .join(DataImportRun, FoodRevision.import_run_id == DataImportRun.id)
        .where(Food.provider == FOOD_PROVIDER)
    )


def source_record(food, revision, imported_at):
    return FoodSource(
        provider=food.provider,
        food_code=food.food_code,
        revision_id=revision.id,
        raw_sha256=revision.raw_sha256,
        imported_at=imported_at,
    )


def calculate_portions(db, selections, *, lock=False) -> NutritionCalculation:
    statement = (
        active_foods()
        .where(Food.id.in_({item.food_id for item in selections}))
        .order_by(Food.id)
    )
    if lock:
        # Serialize confirmation against source refresh without locking immutable revisions.
        statement = statement.with_for_update(read=True, of=Food)
    rows = db.execute(statement).all()
    by_id = {row[0].id: row for row in rows}
    portions, items = [], []
    for item in selections:
        row = by_id.get(item.food_id)
        if row is None:
            raise AppError(
                404, "FOOD_NOT_FOUND", "식품을 다시 선택해 주세요.", headers=NO_STORE
            )
        food, revision, imported_at = row
        if revision.id != item.revision_id:
            raise AppError(
                409,
                "FOOD_REVISION_CHANGED",
                "식품 정보가 갱신되었습니다. 다시 선택해 주세요.",
                headers=NO_STORE,
            )
        portion = portion_nutrients(
            DataFoodRecord(**revision.normalized), item.amount, item.unit
        )
        portions.append(portion)
        items.append(
            {
                **portion.to_dict(),
                "food_id": food.id,
                "source": source_record(food, revision, imported_at),
            }
        )
    return NutritionCalculation(items=items, total=meal_total(portions))
