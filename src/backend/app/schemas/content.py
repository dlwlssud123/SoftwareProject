from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from app.schemas.catalog import Allergen, ContractModel, Page, PageQuery


class FacilityQuery(PageQuery):
    region: str | None = Field(default=None, min_length=1, max_length=50)
    district: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def district_requires_region(self):
        if self.district is not None and self.region is None:
            raise ValueError("district requires region")
        return self


class FacilityRecord(ContractModel):
    id: UUID
    name: str
    sido: str
    sigungu: str
    address: str | None
    latitude: float | None
    longitude: float | None
    eligibility_text: str | None
    hours_text: str | None
    contact_text: str | None
    source_url: str
    checked_on: date
    reference_date: date | None
    provider: str | None
    source_id: str | None
    quality_flags: list[str]
    cautions: list[str]


class FacilityPage(Page[FacilityRecord]):
    warnings: list[str] = Field(default_factory=list)


class FacilityNearbyQuery(FacilityQuery):
    latitude: float = Field(ge=-90, le=90, strict=True)
    longitude: float = Field(ge=-180, le=180, strict=True)
    radius_km: float = Field(default=5.0, ge=0.5, le=50, strict=True)


class NearbyFacilityRecord(FacilityRecord):
    match: Literal["district", "nearby", "district_no_coords"]
    distance_km: float | None = Field(default=None, ge=0)


class NearbyFacilityPage(Page[NearbyFacilityRecord]):
    warnings: list[str] = Field(default_factory=list)


class SeasonalQuery(PageQuery):
    month: int | None = Field(default=None, ge=1, le=12)


class SeasonalRecipeQuery(PageQuery):
    exclude_allergens: list[Allergen] = Field(default_factory=list, max_length=19)


class SeasonalSummary(ContractModel):
    id: UUID
    source_id: str
    month: int = Field(ge=1, le=12)
    name: str
    image_url: str | None
    shopping_search_url: str
    source_url: str
    provider: str
    checked_on: date
    content_sha256: str


class SeasonalDetail(SeasonalSummary):
    terms: list[str]
    detail: dict[str, str | None]
    official_related_recipes: list[str]


class GuideSummary(ContractModel):
    id: UUID
    slug: str
    title: str
    source_reference: str
    checked_on: date


class GuideDetail(GuideSummary):
    steps: list[dict[str, JsonValue]]


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class DataJobQuery(PageQuery):
    status: JobStatus | None = None


class DataJobRecord(ContractModel):
    id: UUID
    kind: str
    status: JobStatus
    attempts: int = Field(ge=0)
    next_run_at: datetime
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
