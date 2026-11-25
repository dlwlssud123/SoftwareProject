"""User-confirmed input context; nutrition sources are derived separately on the server."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.catalog import ContractModel

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]


class PortionOrigin(ContractModel):
    method: Literal["manual", "photo", "similar_food", "ingredient_estimate"]
    quantity_basis: Literal[
        "user_entered", "source_serving", "ai_estimate", "user_adjusted"
    ]
    recognized_name: Name | None = None
    ingredient_name: Name | None = None
    reference_recipe_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
        ]
        | None
    ) = None

    @field_validator("recognized_name", "ingredient_name", "reference_recipe_name")
    @classmethod
    def valid_text(cls, value):
        if value is not None:
            if "\x00" in value:
                raise ValueError("Invalid text")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Invalid text encoding") from None
        return value

    @model_validator(mode="after")
    def coherent(self):
        if self.method != "manual" and self.recognized_name is None:
            raise ValueError("Recognized dish name is required")
        if self.method == "ingredient_estimate" and self.ingredient_name is None:
            raise ValueError("Ingredient name is required")
        if self.method != "ingredient_estimate" and (
            self.ingredient_name or self.reference_recipe_name
        ):
            raise ValueError("Recipe context requires ingredient estimation")
        return self


class ExcludedIngredient(ContractModel):
    dish_name: Name
    ingredient_name: Name
    reason: Literal["user_excluded", "unmatched", "water"]

    @field_validator("dish_name", "ingredient_name")
    @classmethod
    def valid_text(cls, value):
        return PortionOrigin.valid_text(value)


class AnalysisContext(ContractModel):
    excluded_ingredients: list[ExcludedIngredient] = Field(
        default_factory=list, max_length=48
    )
