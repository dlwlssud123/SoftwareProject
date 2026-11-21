from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_content_api import catalog_db as catalog_db
from test_meal_seasonal_import import seasonal_snapshot
from test_public_data_import import corrections, snapshot

from app.core.database import get_db
from app.jobs import import_public_data, import_seasonal
from app.models import SeasonalFood
from app.schemas.catalog import SeasonalMatch


def test_previous_seasonal_match_contract_remains_valid():
    value = SeasonalMatch(
        name="시금치",
        source_url="https://www.nongsaro.go.kr/",
        shopping_search_url="https://www.coupang.com/np/search?q=시금치",
    )
    assert value.seasonal_food_id is None and value.month is None


@pytest.mark.parametrize(
    "query",
    [
        {"exclude_allergens": "달걀"},
        {"exclude_allergens": "모르는 알레르기"},
        {"exclude_allergens": ["우유"] * 20},
        {"exclude_allergens": "우유", "limit": 0},
        {"exclude_allergens": "우유", "offset": 10001},
    ],
)
def test_invalid_allergen_queries_are_rejected_without_caching(catalog_db, query):
    client, db = catalog_db
    response = client.get(f"/api/v1/seasonal-foods/{uuid4()}/recipes", params=query)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    db.execute.assert_not_called()


def test_filtered_errors_and_removed_seasonal_food_are_not_cached(catalog_db):
    client, db = catalog_db
    path = f"/api/v1/seasonal-foods/{uuid4()}/recipes"
    response = client.get(path, params={"exclude_allergens": "우유"})
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    db.get.side_effect = OperationalError(None, None, RuntimeError("private detail"))
    response = client.get(path, params={"exclude_allergens": "우유"})
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert "private" not in response.text


def test_postgres_filters_before_count_and_pagination_and_keeps_live_links(
    pg_connection, client, tmp_path
):
    rows = [
        ("1", "시금치 맑은국", "시금치 100g, 물 100ml"),
        ("2", "시금치 달걀국", "시금치 100g, 달걀 50g"),
        ("3", "시금치 간장무침", "시금치 100g, 간장 5g"),
        ("4", "시금치 볶음", "시금치 100g, 참기름 2g"),
    ]
    path = snapshot(
        tmp_path,
        rows=[
            {
                "RCP_SEQ": code,
                "RCP_NM": name,
                "RCP_PARTS_DTLS": ingredients,
                "MANUAL01": "1. 익힌다.",
            }
            for code, name, ingredients in rows
        ],
    )
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        import_public_data.apply_import(
            db,
            import_public_data.prepare_import(
                "recipes", path, corrections_path=corrections(tmp_path)
            ),
        )
        import_seasonal.apply_import(
            db, import_seasonal.prepare_import(seasonal_snapshot(tmp_path))
        )
        db.commit()
        food = db.scalar(select(SeasonalFood).where(SeasonalFood.month == 12))
        url = f"/api/v1/seasonal-foods/{food.id}/recipes"
        assert client.get(url).json()["data"]["total"] == 4
        query = [("exclude_allergens", "알류"), ("exclude_allergens", "밀")]
        first = client.get(url, params=[*query, ("limit", 1)])
        assert first.status_code == 200, first.text
        assert first.headers["Cache-Control"] == "no-store"
        assert first.json()["data"]["total"] == 2
        assert first.json()["data"]["items"][0]["recipe_id"] == "1"
        second = client.get(url, params=[*query, ("limit", 1), ("offset", 1)])
        assert second.json()["data"]["items"][0]["recipe_id"] == "4"
        last = client.get(url, params=[*query, ("offset", 2)])
        assert last.json()["data"]["items"] == []
        named = client.get(url, params=[*query, ("q", "볶음")]).json()["data"]
        assert named["total"] == 1 and named["items"][0]["recipe_id"] == "4"
        # Public query never writes a user profile or changes facility/recipe data.
        assert not db.new and not db.dirty
        food.is_published = False
        db.commit()
        assert client.get(url, params=query).status_code == 404
