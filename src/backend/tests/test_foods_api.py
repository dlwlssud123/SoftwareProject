from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot

from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import Food


@pytest.fixture
def foods_db(pg_connection, client, tmp_path):
    rows = [
        {
            "FOOD_CD": "RICE",
            "FOOD_NM_KR": "쌀밥",
            "SERVING_SIZE": "100g",
            "AMT_NUM1": "150",
            "AMT_NUM3": "3",
            "AMT_NUM13": "0",
            "DISH_ONE_SERVING": "200g",
            "FOOD_CAT1_NM": "밥류",
        },
        {
            "FOOD_CD": "MILK",
            "FOOD_NM_KR": "우유",
            "SERVING_SIZE": "100mL",
            "AMT_NUM1": "60",
            "AMT_NUM3": "3",
            "AMT_NUM13": "40",
        },
        {"FOOD_CD": "UNKNOWN", "FOOD_NM_KR": "기준 불명", "SERVING_SIZE": "?"},
    ]
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        path = snapshot(tmp_path, dataset="foods", rows=rows)
        correction_path = corrections(tmp_path)
        apply_import(
            db, prepare_import("foods", path, corrections_path=correction_path)
        )
        db.commit()
        yield client, db, rows, path, correction_path


def choice(client, name, amount=100, unit="g"):
    food = client.get("/api/v1/foods", params={"q": name}).json()["data"]["items"][0]
    return {
        "food_id": food["food_id"],
        "revision_id": food["source"]["revision_id"],
        "amount": amount,
        "unit": unit,
    }


def test_food_catalog_returns_active_sources_nulls_zero_and_literal_search(foods_db):
    client, db, _, _, _ = foods_db
    listed = client.get("/api/v1/foods?limit=1").json()["data"]
    assert listed["total"] == 3
    assert len(listed["items"]) == 1
    assert client.get("/api/v1/foods?q=%25").json()["data"]["total"] == 0
    assert client.get("/api/v1/foods?q=_").json()["data"]["total"] == 0
    assert client.get("/api/v1/foods?offset=3").json()["data"]["items"] == []
    selected = choice(client, "쌀밥")
    record = client.get(f"/api/v1/foods/{selected['food_id']}").json()["data"]
    assert record["basis"] == {"amount": 100, "unit": "g", "text": "100g"}
    assert record["nutrients"]["sodium_mg"] == 0
    assert record["nutrients"]["fat_g"] is None
    assert record["category"] == "밥류"
    assert record["source"]["food_code"] == "RICE"
    assert record["source"]["imported_at"]
    assert len(record["source"]["raw_sha256"]) == 64
    assert client.get(f"/api/v1/foods/{uuid4()}").status_code == 404
    food = db.scalar(select(Food).where(Food.food_code == "RICE"))
    food.active_revision_id = None
    db.commit()
    assert client.get(f"/api/v1/foods/{selected['food_id']}").status_code == 404
    assert client.get("/api/v1/foods?q=쌀밥").json()["data"]["total"] == 0


def test_portions_reuse_source_servings_and_mark_missing_totals(foods_db):
    client, _, _, _, _ = foods_db
    response = client.post(
        "/api/v1/nutrition/calculate",
        json={
            "items": [
                choice(client, "쌀밥", 1, "인분"),
                choice(client, "우유", 250, "mL"),
            ]
        },
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["calculation_version"] == "food-portion-v1"
    rice, milk = data["items"]
    assert rice["amount"] == 200
    assert rice["serving"]["field"] == "DISH_ONE_SERVING"
    assert rice["nutrients"]["energy_kcal"] == 300
    assert milk["nutrients"]["energy_kcal"] == 150
    assert data["total"]["nutrients"]["energy_kcal"] == 450
    assert data["total"]["nutrients"]["sodium_mg"] == 100
    assert data["total"]["nutrients"]["fat_g"] is None
    assert data["total"]["missing_items"]["fat_g"] == 2
    assert data["total"]["complete"] is True


def test_mixed_units_are_explicit_approximations_and_no_serving_is_invented(foods_db):
    client, _, _, _, _ = foods_db
    data = client.post(
        "/api/v1/nutrition/calculate",
        json={
            "items": [
                choice(client, "우유", 100, "g"),
                choice(client, "우유", 1, "그릇"),
                choice(client, "쌀밥", 1, "개"),
                choice(client, "기준 불명", 100, "g"),
            ]
        },
    ).json()["data"]
    assert [p["status"] for p in data["items"]] == [
        "approx_ml",
        "unconvertible",
        "unconvertible",
        "invalid",
    ]
    assert data["items"][0]["approx_ml"] is True
    assert "1mL≈1g" in data["items"][0]["note"]
    assert data["total"]["approx_ml_items"] == 1
    assert data["total"]["items_calculated"] == 1
    assert data["total"]["complete"] is False
    assert [p["index"] for p in data["total"]["excluded"]] == [1, 2, 3]
    assert data["total"]["nutrients"]["energy_kcal"] == 60


def test_all_unconvertible_keeps_totals_null(foods_db):
    client, _, _, _, _ = foods_db
    data = client.post(
        "/api/v1/nutrition/calculate",
        json={
            "items": [
                choice(client, "우유", 1, "인분"),
            ]
        },
    ).json()["data"]["total"]
    assert data["items_calculated"] == 0
    assert data["complete"] is False
    assert all(value is None for value in data["nutrients"].values())


def test_reimport_rejects_stale_selection_instead_of_silently_recalculating(foods_db):
    client, db, rows, path, correction_path = foods_db
    old = choice(client, "쌀밥")
    rows[0]["AMT_NUM1"] = "200"
    snapshot(path.parent, dataset="foods", rows=rows)
    apply_import(db, prepare_import("foods", path, corrections_path=correction_path))
    db.commit()
    response = client.post("/api/v1/nutrition/calculate", json={"items": [old]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FOOD_REVISION_CHANGED"
    assert response.headers["Cache-Control"] == "no-store"
    current = choice(client, "쌀밥")
    assert current["food_id"] == old["food_id"]
    assert current["revision_id"] != old["revision_id"]
    assert (
        client.post("/api/v1/nutrition/calculate", json={"items": [current]}).json()[
            "data"
        ]["total"]["nutrients"]["energy_kcal"]
        == 200
    )


def test_unknown_and_unsupported_provider_cannot_be_calculated(foods_db):
    client, db, _, _, _ = foods_db
    item = choice(client, "쌀밥")
    food = db.scalar(select(Food).where(Food.food_code == "RICE"))
    food.provider = "unsupported"
    db.commit()
    assert client.get("/api/v1/foods?q=쌀밥").json()["data"]["items"] == []
    for payload in (item, {**item, "food_id": str(uuid4())}):
        response = client.post("/api/v1/nutrition/calculate", json={"items": [payload]})
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        {"amount": 0},
        {"amount": -1},
        {"amount": 10001},
        {"amount": True},
        {"amount": "100"},
        {"amount": None},
        {"unit": "컵"},
        {"revision_id": "bad"},
        {"food_id": "bad"},
        {"user_id": "someone"},
    ],
)
def test_calculation_rejects_invalid_input(client, change):
    item = {
        "food_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "amount": 100,
        "unit": "g",
    }
    response = client.post(
        "/api/v1/nutrition/calculate", json={"items": [{**item, **change}]}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("items", [[], [{}] * 31])
def test_calculation_bounds_batch_size(client, items):
    assert (
        client.post("/api/v1/nutrition/calculate", json={"items": items}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path", ["/api/v1/foods", f"/api/v1/foods/{uuid4()}", "/api/v1/nutrition/calculate"]
)
def test_database_failure_has_retryable_public_error(client, path):
    db = Mock()
    db.execute.side_effect = db.scalar.side_effect = OperationalError(
        "private database query", {}, Exception("private")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    if path.endswith("calculate"):
        response = client.post(
            path,
            json={
                "items": [
                    {
                        "food_id": str(uuid4()),
                        "revision_id": str(uuid4()),
                        "amount": 100,
                        "unit": "g",
                    }
                ]
            },
        )
    else:
        response = client.get(path)
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert response.headers["Cache-Control"] == "no-store"
    assert "private" not in response.text
