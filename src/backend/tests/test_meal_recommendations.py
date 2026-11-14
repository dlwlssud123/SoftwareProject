from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

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
    RecipeRevision,
    RecommendationItem,
    RecommendationRun,
    SeasonalFood,
    SeasonalRecipeLink,
)

PATH = "/api/v1/meal/recommendations"


def test_recommendations_require_a_session(client):
    response = client.post(PATH, json={"meal_time": "lunch"})
    assert response.status_code == 401


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
                "INFO_NA": "50" if source_id == "1" else "300",
            }
            for source_id, name, ingredients, category in rows
        ],
    )
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        apply_import(
            db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
        )
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
            name="오이",
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
        assert data["rules_version"] == "meal-rules-2"
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
        assert "좋아하는 재료가 들어 있어요." in data["items"][0]["reasons"]
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
        assert by_recipe["7"]["seasonal_ingredients"][0]["name"] == "오이"
        assert "2" not in by_recipe
        seasonal.is_published = False
        db.commit()
        result = client.post(PATH, json=payload, headers=headers).json()["data"]
        assert all(not item["seasonal_ingredients"] for item in result["items"])


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
