"""Food selection and a calculation preview; no intake record is created here."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.catalog import ContractModel, NutrientAmounts, Page
from app.schemas.common import SuccessResponse


class FoodSource(ContractModel):
    provider: str
    food_code: str
    revision_id: UUID
    raw_sha256: str
    imported_at: AwareDatetime


class FoodBasis(ContractModel):
    amount: float | None
    unit: str | None
    text: str | None


class FoodRecord(ContractModel):
    food_id: UUID
    name: str
    category: str | None
    basis: FoodBasis
    nutrients: NutrientAmounts
    serving_ref_text: str | None
    dish_serving_text: str | None
    quality_flags: list[str]
    source: FoodSource


class FoodPortionRequest(ContractModel):
    food_id: UUID
    revision_id: UUID
    amount: Annotated[float, Field(strict=True, gt=0, le=10000)]
    amount_is_estimate: Annotated[bool, Field(strict=True)] = False
    unit: Literal[
        "g",
        "kg",
        "mL",
        "ml",
        "cc",
        "L",
        "인분",
        "그릇",
        "공기",
        "접시",
        "대접",
        "회분",
        "개",
        "조각",
    ]


class NutritionCalculationRequest(ContractModel):
    items: list[FoodPortionRequest] = Field(min_length=1, max_length=30)


class ServingReference(ContractModel):
    field: str
    label: str
    text: str


class PortionInput(ContractModel):
    amount: float
    unit: str


class CalculatedPortion(ContractModel):
    food_id: UUID
    source: FoodSource
    status: Literal["computed", "approx_ml", "unconvertible", "invalid"]
    food_code: str
    food_name: str
    input: PortionInput
    amount: float | None
    amount_unit: str | None
    serving: ServingReference | None
    basis: FoodBasis | None
    factor: float | None
    approx_ml: bool
    amount_is_estimate: bool = False
    nutrients: NutrientAmounts | None
    missing: list[str]
    note: str


class ExcludedPortion(ContractModel):
    index: int
    food_code: str | None
    status: str
    note: str


class NutritionTotal(ContractModel):
    items: int
    items_calculated: int
    excluded: list[ExcludedPortion]
    complete: bool
    approx_ml_items: int
    nutrients: NutrientAmounts
    missing_items: dict[str, int]


class NutritionCalculation(ContractModel):
    calculation_version: Literal["food-portion-v1"] = "food-portion-v1"
    items: list[CalculatedPortion]
    total: NutritionTotal


FoodListResponse = SuccessResponse[Page[FoodRecord]]
FoodDetailResponse = SuccessResponse[FoodRecord]
NutritionCalculationResponse = SuccessResponse[NutritionCalculation]
