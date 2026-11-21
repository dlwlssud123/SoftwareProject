from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from agetech_data.nutrition.api import computed_nutrition_block
from agetech_data.recipes.contract import to_api_record
from agetech_data.recipes.validate import check_recipe
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import guest
from test_public_data_import import corrections, snapshot

from app.api.meal import KOREA_TIMEZONE
from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import (
    FoodRevision,
    MealLog,
    MealLogItem,
    Recipe,
    RecipeComputedNutrition,
    RecipeRevision,
    RecommendationItem,
    RecommendationRun,
    SeasonalFood,
    SeasonalRecipeLink,
)
from app.schemas.catalog import (
    ComputedNutrition,
    RecipeRecommendationRequest,
    RecipeRecord,
)
from app.schemas.profile import Preferences
from app.services.meal_recommendations import recommend

PATH = "/api/v1/meal/recommendations"


def test_recommendations_require_a_session(client):
    response = client.post(PATH, json={"meal_time": "lunch"})
    assert response.status_code == 401


def test_cooking_preferences_get_priority_and_only_label_matching_recipes():
    def record(recipe_id, name, method, ingredients, steps):
        row = {
            "RCP_SEQ": recipe_id,
            "RCP_NM": name,
            "RCP_PAT2": "일품",
            "RCP_WAY2": method,
            "RCP_PARTS_DTLS": ingredients,
            **{f"MANUAL{no:02}": f"{no}. 재료를 익힌다." for no in steps},
        }
        return RecipeRecord.model_validate(to_api_record(check_recipe(row), row, None))

    recipes = [
        record("1", "오이 양념 볶음", "볶기", "오이 100g", [1, 3]),
        record("2", "달걀찜", "찌기", "달걀 100g", [1, 2]),
        record("3", "오이전", "굽기", "오이 100g", [1, 2]),
        record("4", "새우죽", "끓이기", "새우 50g, 쌀 100g", [1, 2, 3, 4, 5]),
        record("5", "오이 반죽", "기타", "오이 100g", [1, 2, 3, 4, 5]),
    ]
    soup = record("6", "호박 수프", "끓이기", "호박 100g", [1, 2])
    soup.steps[1].text = "삶은 호박을 믹서에 넣어 곱게 간다."
    recipes.append(soup)
    payload = RecipeRecommendationRequest(
        meal_time="lunch",
        soft_food=True,
        simple_cooking=True,
        preferred_ingredients=["오이"],
        limit=6,
    )
    ranked = recommend(recipes, payload, Preferences(), [], {}, [], set())
    assert [
        (match.record.recipe_id, match.soft_match, match.simple_match)
        for match in ranked
    ] == [
        ("2", True, True),
        ("6", True, True),
        ("3", False, True),
        ("4", True, False),
        ("1", False, False),
        ("5", False, False),
    ]


def _with_density(recipe_id, source_sodium, sodium=None, carbohydrate=None):
    row = {
        "RCP_SEQ": recipe_id,
        "RCP_NM": f"메뉴{recipe_id}",
        "RCP_PAT2": "일품",
        "RCP_PARTS_DTLS": "쌀 100g",
        "MANUAL01": "1. 익힌다.",
        "INFO_ENG": "300",
        "INFO_NA": source_sodium,
    }
    record = RecipeRecord.model_validate(to_api_record(check_recipe(row), row, None))
    if sodium is None and carbohydrate is None:
        return record
    summary = {
        "computed": {"energy_kcal": 500.0},
        "computed_missing": {},
        "coverage": {"complete": True},
        "complete": True,
        "mapper_version": "test",
        "sodium_mg_per_1000kcal": sodium,
        "carbohydrate_energy_pct": carbohydrate,
    }
    computed = ComputedNutrition.model_validate(computed_nutrition_block(summary))
    return record.model_copy(update={"computed_nutrition": computed})


def test_health_conditions_compare_ingredient_density_not_source_amounts():
    recipes = [
        # The source per-serving sodium says the opposite of the computed density.
        _with_density("1", "900", sodium=300, carbohydrate=70),
        _with_density("2", "100", sodium=1500, carbohydrate=40),
        _with_density("3", "100", sodium=1000, carbohydrate=50),
        _with_density("4", "50"),  # not mapped yet: left out of the comparison
    ]

    def reasons(condition):
        payload = RecipeRecommendationRequest(
            meal_time="lunch", health_conditions=[condition], limit=4
        )
        ranked = recommend(recipes, payload, Preferences(), [], {}, [], set())
        return {
            match.record.recipe_id: [
                reason for reason in match.reasons if "재료로 계산했을 때" in reason
            ]
            for match in ranked
        }

    assert reasons("hypertension") == {
        "1": ["재료로 계산했을 때 같은 열량에 든 나트륨이 적은 편이에요."],
        "2": [],
        "3": [],
        "4": [],
    }
    assert reasons("diabetes") == {
        "1": [],
        "2": ["재료로 계산했을 때 열량 중 탄수화물 비율이 낮은 편이에요."],
        "3": [],
        "4": [],
    }


def _computed_row(db, source_id, sodium_per_1000kcal):
    recipe, revision = db.execute(
        select(Recipe, RecipeRevision)
        .join(RecipeRevision, Recipe.active_revision_id == RecipeRevision.id)
        .where(Recipe.source_id == source_id)
    ).one()
    db.add(
        RecipeComputedNutrition(
            recipe_id=recipe.id,
            recipe_revision_id=revision.id,
            computed={"energy_kcal": 500.0, "sodium_mg": sodium_per_1000kcal / 2},
            computed_missing={},
            coverage={"complete": True},
            complete=True,
            items=1,
            items_used=1,
            sodium_mg_per_1000kcal=Decimal(sodium_per_1000kcal),
            mapper_version="test",
            ingredient_map_sha256="0" * 64,
            mapping_sha256="0" * 64,
            mapping_run_id=revision.import_run_id,
        )
    )


def test_recommendations_use_own_profile_and_confirmed_history(
    pg_connection, client, tmp_path
):
    rows = [
        ("1", "쌀죽", "쌀 100g, 물 200ml", "밥"),
        ("2", "우유죽", "우유 100ml, 쌀 100g", "밥"),
        ("3", "두부구이", "두부 100g", "반찬"),
        ("4", "오이볶음", "오이 100g", "반찬"),
        ("5", "당근밥", "당근 100g", "밥"),
        ("6", "쌀 죽", "쌀 100g, 물 200ml", "밥"),
        ("7", "오이밥", "쌀 100g, 오이 100g", "밥"),
    ]
    path = snapshot(
        tmp_path,
        rows=[
            {
                "RCP_SEQ": source_id,
                "RCP_NM": name,
                "RCP_PARTS_DTLS": ingredients,
                "RCP_PAT2": category,
                "MANUAL01": "1. 재료를 익힌다.",
                # Source per-serving sodium is no longer what the health rule reads.
                "INFO_NA": "900" if source_id == "1" else "300",
            }
            for source_id, name, ingredients, category in rows
        ],
    )
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        apply_import(
            db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
        )
        # Recipe 4 is not mapped yet, so it has no computed nutrition.
        for source_id in ("1", "2", "3", "5", "6", "7"):
            _computed_row(db, source_id, 300 if source_id == "1" else 1000)
        other, other_headers = guest(client)
        user, headers = guest(client)
        response = client.patch(
            "/api/v1/profile",
            headers=headers,
            json={
                "consent": True,
                "preferences": {
                    "exclude_allergens": ["우유"],
                    "excluded_ingredients": ["당 근"],
                    "preferred_ingredients": ["오이"],
                },
            },
        )
        assert response.status_code == 200

        sample = db.scalar(select(RecipeRevision).limit(1))
        food = FoodRevision(
            food_id=_food_id(db),
            import_run_id=sample.import_run_id,
            fingerprint="0" * 64,
            raw_sha256="0" * 64,
            raw={},
            normalized={},
            name="오이, 생것",
            nutrients={},
            quality_flags=[],
        )
        db.add(food)
        db.flush()
        _log_food(db, other["user_id"], food, days_ago=1)
        _log_food(db, user["user_id"], food, days_ago=8)
        db.commit()

        payload = {"meal_time": "lunch", "exclude_ingredients": ["두부"], "limit": 5}
        response = client.post(PATH, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        data = response.json()["data"]
        assert data["rules_version"] == "meal-rules-5"
        run_id = UUID(data["recommendation_id"])
        run = db.get(RecommendationRun, run_id)
        assert run.user_id == UUID(user["user_id"])
        assert run.rules_version == data["rules_version"]
        assert [
            row.rank
            for row in db.scalars(
                select(RecommendationItem)
                .where(RecommendationItem.run_id == run_id)
                .order_by(RecommendationItem.rank)
            )
        ] == [1, 2, 3]
        assert [item["item"]["recipe_id"] for item in data["items"]] == ["7", "4", "1"]
        assert "좋아하는 재료 오이가 들어 있어요." in data["items"][0]["reasons"]
        assert all(
            "최근 식사 기록" not in " ".join(item["reasons"]) for item in data["items"]
        )

        _log_food(db, user["user_id"], food, days_ago=1)
        db.commit()
        data = client.post(PATH, json=payload, headers=headers).json()["data"]
        assert [item["item"]["recipe_id"] for item in data["items"]] == ["1", "4", "7"]
        assert any("최근 식사 기록" in reason for reason in data["items"][0]["reasons"])
        assert "2" in {
            item["item"]["recipe_id"]
            for item in client.post(PATH, json=payload, headers=other_headers).json()[
                "data"
            ]["items"]
        }
        empty = client.post(
            PATH,
            json={"meal_time": "lunch", "exclude_ingredients": ["쌀", "오이", "두부"]},
            headers=headers,
        )
        assert empty.json()["data"]["items"] == []
        assert db.get(
            RecommendationRun, UUID(empty.json()["data"]["recommendation_id"])
        )

        recipe, revision = db.execute(
            select(Recipe, RecipeRevision)
            .join(RecipeRevision, Recipe.active_revision_id == RecipeRevision.id)
            .where(Recipe.source_id == "7")
        ).one()
        now = datetime.now(KOREA_TIMEZONE)
        seasonal = SeasonalFood(
            provider="test",
            source_id="7",
            month=now.month,
            fdmt_sn="7",
            name="오이",
            terms=[],
            detail={},
            detail_status="ok",
            official_related_recipes=[],
            normalized={},
            shopping_search_url="https://www.coupang.com/np/search?q=오이",
            source_url="https://example.test/seasonal",
            checked_on=now.date(),
            content_sha256="0" * 64,
            links_sha256="0" * 64,
            is_published=True,
            last_seen_at=now,
            last_seen_run_id=revision.import_run_id,
        )
        db.add(seasonal)
        db.flush()
        db.add(
            SeasonalRecipeLink(
                seasonal_food_id=seasonal.id,
                recipe_id=recipe.id,
                recipe_revision_id=revision.id,
                ingredient_names=["오이"],
            )
        )
        db.commit()
        health = client.post(
            PATH,
            json={**payload, "health_conditions": ["hypertension"]},
            headers=headers,
        ).json()["data"]
        by_recipe = {item["item"]["recipe_id"]: item for item in health["items"]}
        assert any("나트륨" in reason for reason in by_recipe["1"]["reasons"])
        assert [
            recipe_id
            for recipe_id, item in by_recipe.items()
            if any("나트륨" in reason for reason in item["reasons"])
        ] == ["1"]
        computed = by_recipe["1"]["item"]["computed_nutrition"]
        assert computed["density"]["sodium_mg_per_1000kcal"] == 300
        assert by_recipe["4"]["item"]["computed_nutrition"] is None
        assert "같은 열량 기준" in health["warnings"][0]
        assert by_recipe["7"]["seasonal_ingredients"][0]["name"] == "오이"
        evidence = by_recipe["7"]["seasonal_ingredients"][0]
        assert evidence["seasonal_food_id"] == str(seasonal.id)
        assert evidence["month"] == now.month
        assert evidence["source_url"] == seasonal.source_url
        assert "2" not in by_recipe
        seasonal.detail_status = "failed"
        db.commit()
        result = client.post(PATH, json=payload, headers=headers).json()["data"]
        assert all(not item["seasonal_ingredients"] for item in result["items"])
        seasonal.detail_status = "ok"
        seasonal.is_published = False
        db.commit()
        result = client.post(PATH, json=payload, headers=headers).json()["data"]
        assert all(not item["seasonal_ingredients"] for item in result["items"])

        other_payload = {
            "meal_time": "snack",
            "preferred_ingredients": ["두부"],
            "simple_cooking": True,
            "limit": 1,
        }
        first = client.post(PATH, json=other_payload, headers=other_headers).json()[
            "data"
        ]
        first_choice = first["items"][0]
        assert first_choice["item"]["recipe_id"] == "3"
        assert "좋아하는 재료 두부가 들어 있어요." in first_choice["reasons"]
        assert "재료 1가지, 조리 1단계예요." in first_choice["reasons"]
        assert first_choice["matched_preferences"] == ["simple_cooking"]
        excluded = client.post(
            PATH,
            json={**other_payload, "exclude_allergens": ["대두"]},
            headers=other_headers,
        ).json()["data"]
        assert excluded["items"]
        assert excluded["items"][0]["item"]["recipe_id"] != "3"

        neutral = {"meal_time": "breakfast", "limit": 1}
        first_id = client.post(PATH, json=neutral, headers=other_headers).json()[
            "data"
        ]["items"][0]["item"]["recipe_id"]
        next_id = client.post(PATH, json=neutral, headers=other_headers).json()["data"][
            "items"
        ][0]["item"]["recipe_id"]
        third_id = client.post(PATH, json=neutral, headers=other_headers).json()[
            "data"
        ]["items"][0]["item"]["recipe_id"]
        assert len({first_id, next_id, third_id}) == 3


def _food_id(db):
    from app.models import Food

    food = Food(provider="test", food_code="cucumber")
    db.add(food)
    db.flush()
    return food.id


def _log_food(db, user_id, food, *, days_ago):
    log = MealLog(
        user_id=UUID(user_id), eaten_at=datetime.now(UTC) - timedelta(days=days_ago)
    )
    db.add(log)
    db.flush()
    db.add(
        MealLogItem(
            meal_log_id=log.id,
            food_revision_id=food.id,
            amount=Decimal(100),
            amount_unit="g",
            nutrients={},
            calculation_version="test",
        )
    )
