from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.catalog import ContractModel
from app.schemas.nutrition import FoodRecord

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]


class ExternalProcessing(ContractModel):
    allow_external_processing: Annotated[bool, Field(strict=True)]

    @field_validator("allow_external_processing")
    @classmethod
    def consent_required(cls, value):
        if not value:
            raise ValueError("External processing consent is required")
        return value


class ChatRequest(ExternalProcessing):
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]

    @field_validator("message")
    @classmethod
    def valid_text(cls, value):
        if "\x00" in value:
            raise ValueError("Invalid text")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid text encoding") from None
        return value


class ChatAnswer(ContractModel):
    answer: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]

    @field_validator("answer")
    @classmethod
    def valid_answer(cls, value):
        return ChatRequest.valid_text(value)


class ChatResult(ChatAnswer):
    provider: Literal["NVIDIA"] = "NVIDIA"
    model: str
    notice: str = (
        "AI가 만든 참고 답변이에요. 개인 건강 상담이나 진료를 대신하지 않아요."
    )


class PhotoRequest(ExternalProcessing):
    image_base64: Annotated[str, StringConstraints(min_length=32, max_length=2800000)]


class RecognizedDish(ContractModel):
    name: ShortText
    confidence: Literal["high", "medium", "low"]
    standard_serving_grams: Annotated[int, Field(strict=True, ge=10, le=1500)]

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return ChatRequest.valid_text(value)


class FoodInference(ContractModel):
    is_food: Annotated[bool, Field(strict=True)]
    foods: list[RecognizedDish] = Field(max_length=6)

    @model_validator(mode="after")
    def consistent(self):
        if self.is_food != bool(self.foods):
            raise ValueError("Food presence and candidates disagree")
        if len({food.name.casefold() for food in self.foods}) != len(self.foods):
            raise ValueError("Duplicate dishes")
        return self


class ServingSuggestion(ContractModel):
    amount: Annotated[float, Field(strict=True, gt=0, le=10000)]
    unit: Literal["g", "mL"]
    basis: Literal["source_serving", "ai_estimate"]
    description: str


class MatchedFood(ContractModel):
    food: FoodRecord
    serving: ServingSuggestion
    match_basis: Literal["name", "similar"] = "name"


class PhotoDish(RecognizedDish):
    matches: list[MatchedFood]


class PhotoResult(ContractModel):
    is_food: bool
    foods: list[PhotoDish]
    provider: Literal["NVIDIA"] = "NVIDIA"
    model: str
    notice: str = "사진으로 찾은 음식 후보예요. 기본 1인분의 예상 양을 확인하거나 바꿔 주세요. 사진에서 실제 중량을 측정한 값은 아니에요."


class IngredientRequest(ExternalProcessing):
    dish_name: ShortText
    standard_serving_grams: Annotated[int, Field(strict=True, ge=10, le=1500)]

    @field_validator("dish_name")
    @classmethod
    def valid_name(cls, value):
        return ChatRequest.valid_text(value)


class IngredientGuess(ContractModel):
    name: ShortText
    amount_g: Annotated[float, Field(strict=True, gt=0, le=1500, multiple_of=0.001)]

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return ChatRequest.valid_text(value)


class IngredientInference(ContractModel):
    ingredients: list[IngredientGuess] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded(self):
        names = ["".join(item.name.split()).casefold() for item in self.ingredients]
        if (
            len(set(names)) != len(names)
            or sum(item.amount_g for item in self.ingredients) > 2500
        ):
            raise ValueError("Duplicate ingredients or oversized serving")
        return self


class IngredientCandidate(IngredientGuess):
    matches: list[MatchedFood]
    is_water: bool = False


class RecipeReference(ContractModel):
    recipe_id: str
    revision_id: UUID
    name: str


class IngredientResult(ContractModel):
    dish_name: str
    ingredients: list[IngredientCandidate]
    reference_recipe: RecipeReference | None = None
    notice: str = "음식 이름과 일반적인 조리법으로 예상한 1인분 재료와 양이에요. 사진에서 확인한 실제 재료·중량이 아니며, 기름·양념이 빠지거나 양이 다를 수 있어요. 재료를 확인한 뒤 참고값으로 계산해 주세요."
