from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints

from app.schemas.catalog import Allergen, ContractModel
from app.schemas.common import SuccessResponse

PreferenceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class Preferences(ContractModel):
    age: int | None = Field(default=None, ge=0, le=120, strict=True)
    region: PreferenceText | None = None
    district: PreferenceText | None = None
    lives_alone: bool | None = Field(default=None, strict=True)
    soft_food: bool | None = Field(default=None, strict=True)
    preferred_ingredients: list[PreferenceText] = Field(
        default_factory=list, max_length=30
    )
    excluded_ingredients: list[PreferenceText] = Field(
        default_factory=list, max_length=30
    )
    exclude_allergens: list[Allergen] = Field(default_factory=list, max_length=19)


class ProfilePatch(ContractModel):
    consent: bool | None = Field(default=None, strict=True)
    preferences: Preferences | None = None


class ProfileData(ContractModel):
    preferences: Preferences
    consented_at: AwareDatetime
    updated_at: AwareDatetime


ProfileResponse = SuccessResponse[ProfileData | None]
