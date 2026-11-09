import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.jobs.export_api_contract import PLANNED, handoff_schema
from app.schemas.catalog import (
    RecipeDetailResponse,
    RecipeListQuery,
    RecipeListResponse,
    RecipeRecommendationRequest,
    RecipeRecord,
    WelfareDetailResponse,
    WelfareListResponse,
    WelfareRecommendationRequest,
)

ROOT = Path(__file__).resolve().parents[3]


def test_all_data_team_samples_fit_without_losing_unknown_nutrition():
    payload = json.loads(
        (ROOT / "docs/data/samples/recipe_api_sample.json").read_text(encoding="utf-8")
    )
    for sample in payload["samples"]:
        recipe = RecipeRecord.model_validate(sample["recipe"])
        source = sample["recipe"]
        assert recipe.recipe_id == source["recipe_id"]
        assert (
            recipe.nutrition.serving_weight_g == source["nutrition"]["serving_weight_g"]
        )
        assert recipe.missing_step_nos == source["missing_step_nos"]
        assert recipe.allergens.complete == source["allergens"]["complete"]
        assert recipe.quality.status == source["quality"]["status"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"q": ""},
        {"exclude_allergens": ["달걀"]},
        {"unexpected": True},
    ],
)
def test_list_query_rejects_invalid_limits_and_noncanonical_allergens(kwargs):
    with pytest.raises(ValidationError):
        RecipeListQuery(**kwargs)


def test_recommendation_requests_reject_impersonation_and_out_of_range_values():
    assert (
        RecipeRecommendationRequest(meal_time="lunch", exclude_allergens=["알류"]).limit
        == 5
    )
    with pytest.raises(ValidationError):
        RecipeRecommendationRequest(meal_time="lunch", user_id="somebody-else")
    with pytest.raises(ValidationError):
        WelfareRecommendationRequest(age=121, region="대구")
    with pytest.raises(ValidationError):
        WelfareRecommendationRequest(age=70, region="")


def test_planned_contract_references_resolve_and_do_not_register_routes(client):
    schema = handoff_schema()

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert node["$ref"].startswith("#/components/schemas/")
                assert node["$ref"].split("/")[-1] in schema["components"]["schemas"]
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    runtime = client.get("/openapi.json").json()
    for path, method, _, _ in PLANNED:
        assert schema["paths"][path][method]["x-implementation-status"] == "planned"
        assert path not in runtime["paths"]
    assert client.get("/api/v1/welfare").status_code == 404


def test_runtime_openapi_matches_committed_snapshot(client):
    saved = json.loads((ROOT / "docs/설계/openapi.json").read_text(encoding="utf-8"))
    assert client.get("/openapi.json").json() == saved


def test_planned_openapi_matches_committed_snapshot():
    saved = json.loads(
        (ROOT / "docs/설계/catalog.openapi.json").read_text(encoding="utf-8")
    )
    assert handoff_schema() == saved


def test_committed_response_examples_validate_and_preserve_unknown_application_status():
    examples = json.loads(
        (ROOT / "docs/설계/api_examples.json").read_text(encoding="utf-8")
    )
    responses = examples["responses"]
    RecipeDetailResponse.model_validate(responses["recipe_detail"])
    RecipeListResponse.model_validate(responses["recipe_list"])
    welfare = WelfareDetailResponse.model_validate(responses["welfare_detail"])
    WelfareListResponse.model_validate(responses["welfare_list"])
    RecipeListResponse.model_validate(responses["empty_list"])
    assert welfare.data.application_status == "unknown"
    assert welfare.data.source.detail_checked_at is not None
    assert welfare.data.source.revision_id is None


@pytest.mark.parametrize("ingredient", ["", "   ", "x" * 101])
def test_excluded_ingredient_names_are_bounded(ingredient):
    with pytest.raises(ValidationError):
        RecipeRecommendationRequest(meal_time="lunch", exclude_ingredients=[ingredient])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"meal_time": "midnight"},
        {"meal_time": "lunch", "limit": 0},
        {"meal_time": "lunch", "limit": 21},
        {"meal_time": "lunch", "exclude_allergens": ["알류"] * 20},
        {"meal_time": "lunch", "exclude_ingredients": ["당근"] * 31},
    ],
)
def test_recipe_recommendation_boundaries(kwargs):
    with pytest.raises(ValidationError):
        RecipeRecommendationRequest(**kwargs)


def test_welfare_recommendation_age_lower_bound():
    with pytest.raises(ValidationError):
        WelfareRecommendationRequest(age=-1, region="대구")
