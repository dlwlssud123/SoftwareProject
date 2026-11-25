from datetime import UTC, date
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.schemas.catalog import ContractModel, NutrientAmounts, Page
from app.schemas.common import SuccessResponse
from app.schemas.intake_evidence import AnalysisContext
from app.schemas.nutrition import CalculatedPortion, FoodPortionRequest, NutritionTotal


class MealCreate(ContractModel):
    eaten_at: AwareDatetime
    items: list[FoodPortionRequest] = Field(min_length=1, max_length=30)
    analysis_context: AnalysisContext | None = None

    @field_validator("eaten_at")
    @classmethod
    def utc_time(cls, value):
        try:
            return value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Timestamp is outside the supported UTC range") from None


class MealUpdate(ContractModel):
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    eaten_at: AwareDatetime | None = None
    items: list[FoodPortionRequest] | None = Field(
        default=None, min_length=1, max_length=30
    )
    analysis_context: AnalysisContext | None = None

    @field_validator("eaten_at")
    @classmethod
    def utc_time(cls, value):
        try:
            return value.astimezone(UTC) if value is not None else None
        except OverflowError:
            raise ValueError("Timestamp is outside the supported UTC range") from None

    @model_validator(mode="after")
    def require_update(self):
        changed = self.model_fields_set - {"expected_version"}
        if not changed or any(getattr(self, key) is None for key in changed):
            raise ValueError("Provide eaten_at or items; null is not an update")
        return self


class MealListQuery(ContractModel):
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)
    day: date | None = Field(default=None, le=date(9999, 12, 30))


class MealItemRecord(ContractModel):
    food_id: UUID
    revision_id: UUID
    food_code: str
    name: str
    order_no: int | None
    amount: float
    amount_unit: str
    nutrients: NutrientAmounts
    calculation_version: str
    # Old records retain their stored nutrients; absent evidence is not reconstructed as fact.
    calculation: CalculatedPortion | None


class MealSummary(ContractModel):
    id: UUID
    eaten_at: AwareDatetime
    created_at: AwareDatetime
    version: int
    total: NutritionTotal
    legacy_snapshot_missing: bool
    analysis_context: AnalysisContext | None = None
    contains_estimates: bool = False


class MealRecord(MealSummary):
    items: list[MealItemRecord]


class MealCreateResult(ContractModel):
    meal: MealRecord
    replayed: bool


MealResponse = SuccessResponse[MealRecord]
MealCreateResponse = SuccessResponse[MealCreateResult]
MealListResponse = SuccessResponse[Page[MealSummary]]
