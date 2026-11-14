"""Typed handoff contracts for catalog APIs; these do not register routes."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from app.schemas.common import SuccessResponse


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Allergen = Literal[
    "알류",
    "우유",
    "메밀",
    "땅콩",
    "대두",
    "밀",
    "고등어",
    "게",
    "새우",
    "돼지고기",
    "복숭아",
    "토마토",
    "아황산류",
    "호두",
    "닭고기",
    "쇠고기",
    "오징어",
    "조개류",
    "잣",
]


class PageQuery(ContractModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    q: str | None = Field(default=None, min_length=1, max_length=100)


class RecipeListQuery(PageQuery):
    category: str | None = Field(default=None, min_length=1, max_length=50)
    cooking_method: str | None = Field(default=None, min_length=1, max_length=50)
    exclude_allergens: list[Allergen] = Field(default_factory=list, max_length=19)


class RecipeRecommendationRequest(ContractModel):
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"]
    health_conditions: list[Literal["hypertension", "diabetes"]] = Field(
        default_factory=list, max_length=2
    )
    soft_food: bool = False
    exclude_allergens: list[Allergen] = Field(default_factory=list, max_length=19)
    exclude_ingredients: list[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
        ]
    ] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=5, ge=1, le=20)


class RecipeImages(ContractModel):
    small: str | None
    large: str | None


class RecipeIngredient(ContractModel):
    order_no: int = Field(ge=1)
    section: str | None
    name: str
    name_raw: str
    amount_text: str | None
    amount: float | None
    unit: str | None
    amount_kind: Literal["measured", "qualitative", "none"]


class RecipeStep(ContractModel):
    no: int = Field(ge=1, le=20)
    text: str
    image: str | None
    source_field: str


class RecipeNutrition(ContractModel):
    basis: Literal["per_serving_unverified"]
    serving_weight_g: float | None
    ingredient_servings: float | None
    energy_kcal: float | None
    carbohydrate_g: float | None
    protein_g: float | None
    fat_g: float | None
    sodium_mg: float | None
    energy_from_macros_kcal: float | None
    energy_ratio: float | None
    suspect: bool


class AllergenEvidence(ContractModel):
    ingredient: str
    term: str
    kind: Literal["direct", "usually"]
    from_: str | None = Field(default=None, alias="from")


class DetectedAllergen(ContractModel):
    allergen: Allergen
    kind: Literal["direct", "usually"]
    evidence: list[AllergenEvidence]


class UncertainAllergen(ContractModel):
    ingredient: str
    term: str
    candidates: list[Allergen]


class RecipeAllergens(ContractModel):
    basis: Literal["ingredient_name"]
    detected: list[DetectedAllergen]
    needs_check: list[UncertainAllergen]
    not_determinable: list[Allergen]
    complete: bool


class QualityIssue(ContractModel):
    code: str
    severity: Literal["warning", "error"]
    label: str
    detail: dict[str, JsonValue]


class RecipeQuality(ContractModel):
    status: Literal["ok", "flagged", "hold"]
    issues: list[QualityIssue]
    info_codes: list[str]
    missing_fields: list[str]


class RecipeSource(ContractModel):
    provider: str | None
    service: Literal["COOKRCP01"]
    source_id: str
    fetched_at: AwareDatetime | None
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: UUID | None = None


class RecipeRecord(ContractModel):
    # Preserve the data team's public source ID, independent of internal DB UUIDs.
    recipe_id: str = Field(pattern=r"^[0-9]+$")
    name: str
    category: str | None
    cooking_method: str | None
    hashtag: str | None
    images: RecipeImages
    ingredients_text: str | None
    ingredients: list[RecipeIngredient]
    steps: list[RecipeStep]
    missing_step_nos: list[int]
    nutrition: RecipeNutrition
    sodium_tip: str | None
    allergens: RecipeAllergens
    quality: RecipeQuality
    source: RecipeSource


WelfareScope = Literal["central_nationwide", "local"]


class WelfareListQuery(PageQuery):
    # None lists central and local services. With region (and district), order is
    # the district's services, then province-wide, then nationwide (data services_for).
    scope: WelfareScope | None = None
    region: str | None = Field(default=None, min_length=1, max_length=50)
    district: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def district_requires_region(self):
        if self.district is not None and self.region is None:
            raise ValueError("district requires region")
        return self


class WelfareRecommendationRequest(ContractModel):
    age: int = Field(ge=0, le=120)
    region: str = Field(min_length=1, max_length=50)
    district: str | None = Field(default=None, min_length=1, max_length=50)
    lives_alone: bool | None = None
    limit: int = Field(default=5, ge=1, le=20)


class WelfareApplication(ContractModel):
    method: str
    description: str


class WelfareContact(ContractModel):
    name: str
    contact: str


class WelfareSource(ContractModel):
    provider: str
    source_id: str
    source_url: str
    checked_at: AwareDatetime
    detail_checked_at: AwareDatetime | None
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: UUID | None = None


class WelfareRecord(ContractModel):
    service_id: str = Field(pattern=r"^WLF[0-9]+$")
    scope: WelfareScope
    # Region from the normalized record: central services are national, local ones
    # are province-wide (sgg null) or district services.
    region_scope: Literal["national", "province", "district"] = "national"
    ctpv: str | None = None
    sgg: str | None = None
    title: str
    summary: str
    target_text: str
    selection_text: str
    benefit_text: str
    application: list[WelfareApplication]
    contacts: list[WelfareContact]
    criteria_year: str | None
    application_status: Literal["unknown"]
    detail_state: Literal["ready", "pending"]
    quality_status: Literal["ok", "flagged", "hold"]
    issues: list[str]
    source: WelfareSource


class Page[T](ContractModel):
    items: list[T]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


class Recommendation[T](ContractModel):
    item: T
    reasons: list[str]


class RecommendationResult[T](ContractModel):
    items: list[Recommendation[T]]
    evaluated_at: AwareDatetime
    rules_version: str
    warnings: list[str]


class SeasonalMatch(ContractModel):
    name: str
    source_url: str
    shopping_search_url: str


class RecipeRecommendation(Recommendation[RecipeRecord]):
    seasonal_ingredients: list[SeasonalMatch] = Field(default_factory=list)


class RecipeRecommendationResult(RecommendationResult[RecipeRecord]):
    recommendation_id: UUID | None = None
    items: list[RecipeRecommendation]


RecipeListResponse = SuccessResponse[Page[RecipeRecord]]
RecipeDetailResponse = SuccessResponse[RecipeRecord]
RecipeRecommendationResponse = SuccessResponse[RecipeRecommendationResult]
WelfareListResponse = SuccessResponse[Page[WelfareRecord]]
WelfareDetailResponse = SuccessResponse[WelfareRecord]
WelfareRecommendationResponse = SuccessResponse[RecommendationResult[WelfareRecord]]
