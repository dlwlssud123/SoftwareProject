from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_public_data_import import corrections, snapshot

from alembic import command
from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import MealPlanEntry, RecipeIngredient, ShoppingCheck, User
from app.services.shopping import _display, shopping_url

DAY = "2026-11-20"
BASE = f"/api/v1/shopping-lists/{DAY}"


@pytest.fixture
def shopping_env(pg_connection, client, tmp_path):
    rows = [
        {
            "RCP_SEQ": "1",
            "RCP_NM": "쌀죽",
            "RCP_PARTS_DTLS": "쌀 100g, 물 100ml, 소금 약간, 대파(다진 것) 10g",
            "MANUAL01": "1. 끓인다.",
        },
        {
            "RCP_SEQ": "2",
            "RCP_NM": "쌀밥",
            "RCP_PARTS_DTLS": "쌀 0.2kg, 물 0.1L, 소금 2g, 대파 20g",
            "MANUAL01": "1. 끓인다.",
        },
    ]
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        path = snapshot(tmp_path, rows=rows)
        apply_import(
            db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
        )
        db.commit()
        owner, headers = guest(client)
        _, other = guest(client)
        for slot, recipe in [("breakfast", "1"), ("lunch", "2")]:
            assert (
                client.put(
                    f"/api/v1/meal-plans/{DAY}/{slot}",
                    headers=headers,
                    json={"recipe_id": recipe},
                ).status_code
                == 200
            )
        yield client, db, headers, other, owner, rows, path


def items(client, headers):
    response = client.get(BASE, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data"]


def check(client, headers, item, checked=True):
    return client.patch(
        f"{BASE}/items/{item['item_key']}",
        headers=headers,
        json={"source_hash": item["source_hash"], "checked": checked},
    )


@pytest.mark.parametrize(
    "method,path", [("GET", BASE), ("PATCH", BASE + "/items/" + "a" * 64)]
)
def test_shopping_requires_auth(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_aggregates_verified_units_preserves_uncertain_amounts_and_preparation(
    shopping_env,
):
    client, _, headers, _, _, _, _ = shopping_env
    page = items(client, headers)
    assert page["planned_meals"] == 2
    by_name = {}
    for item in page["items"]:
        by_name.setdefault(item["name"], []).append(item)
        uri = urlsplit(item["shopping_search_url"])
        assert (
            uri.scheme == "https"
            and uri.netloc == "www.coupang.com"
            and uri.path == "/np/search"
        )
        assert parse_qs(uri.query) == {"q": [item["name"]]}
        assert not item["checked"]
        assert all(source["recipe_revision_id"] for source in item["sources"])
    assert by_name["쌀"][0]["amount"] == 300
    assert by_name["쌀"][0]["amount_text"] == "300 g"
    assert by_name["물"][0]["amount"] == 200
    assert by_name["물"][0]["unit"] == "mL"
    assert len(by_name["소금"]) == 2
    unknown = next(item for item in by_name["소금"] if not item["combined"])
    assert unknown["amount"] is None and unknown["amount_text"] == "약간"
    assert by_name["대파(다진 것)"][0]["amount"] == 10
    assert by_name["대파"][0]["amount"] == 20


def test_checks_persist_are_owner_and_date_scoped_and_can_be_unchecked(shopping_env):
    client, db, headers, other, _, _, _ = shopping_env
    item = items(client, headers)["items"][0]
    assert check(client, headers, item).status_code == 200
    assert next(
        row
        for row in items(client, headers)["items"]
        if row["item_key"] == item["item_key"]
    )["checked"]
    assert check(client, headers, item).status_code == 200
    assert db.scalar(select(func.count()).select_from(ShoppingCheck)) == 1
    assert items(client, other)["items"] == []
    assert check(client, other, item).status_code == 404
    assert (
        client.get("/api/v1/shopping-lists/2026-11-21", headers=headers).json()["data"][
            "items"
        ]
        == []
    )
    assert check(client, headers, item, False).status_code == 200
    assert all(not row["checked"] for row in items(client, headers)["items"])


def test_plan_change_invalidates_checks_and_stale_check_updates(shopping_env):
    client, _, headers, _, _, _, _ = shopping_env
    rice = next(row for row in items(client, headers)["items"] if row["name"] == "쌀")
    assert check(client, headers, rice).status_code == 200
    assert (
        client.put(
            f"/api/v1/meal-plans/{DAY}/dinner", headers=headers, json={"recipe_id": "1"}
        ).status_code
        == 200
    )
    current = next(
        row for row in items(client, headers)["items"] if row["name"] == "쌀"
    )
    assert current["amount"] == 400 and current["checked"] is False
    assert check(client, headers, rice).status_code == 409
    assert check(client, headers, current).status_code == 200
    assert (
        client.put(
            f"/api/v1/meal-plans/{DAY}/dinner", headers=headers, json={"recipe_id": "1"}
        ).status_code
        == 200
    )
    assert next(row for row in items(client, headers)["items"] if row["name"] == "쌀")[
        "checked"
    ]


def test_source_refresh_does_not_replace_saved_recipe_quantities(
    shopping_env, tmp_path
):
    client, db, headers, _, _, rows, path = shopping_env
    before = next(row for row in items(client, headers)["items"] if row["name"] == "쌀")
    assert check(client, headers, before).status_code == 200
    rows[0]["RCP_PARTS_DTLS"] = "쌀 900g"
    snapshot(tmp_path, rows=rows)
    apply_import(
        db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
    )
    db.commit()
    page = items(client, headers)
    after = next(row for row in page["items"] if row["name"] == "쌀")
    assert after["amount"] == 300
    assert after["checked"] is False
    assert any(not source["is_active"] for source in after["sources"])
    assert page["warnings"]
    assert check(client, headers, before).status_code == 409


def test_mass_volume_and_fractional_counts_keep_their_verified_units(
    shopping_env, tmp_path
):
    client, db, headers, _, _, rows, path = shopping_env
    rows[0]["RCP_PARTS_DTLS"] = "물 100g, 물 100ml, 물 약간, 무 1/2개, 무 1/2개"
    snapshot(tmp_path, rows=rows)
    apply_import(
        db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
    )
    db.commit()
    assert (
        client.put(
            f"/api/v1/meal-plans/{DAY}/breakfast",
            headers=headers,
            json={"recipe_id": "1"},
        ).status_code
        == 200
    )
    page = items(client, headers)
    water = [item for item in page["items"] if item["name"] == "물"]
    assert {item["unit"]: item["amount"] for item in water} == {
        "g": 100,
        "mL": 200,
        None: None,
    }
    radish = next(item for item in page["items"] if item["name"] == "무")
    assert radish["amount"] == 1 and radish["amount_text"] == "1 개"


def test_last_plan_removal_and_user_removal_delete_check_state(shopping_env):
    client, db, headers, _, owner, _, _ = shopping_env
    assert check(client, headers, items(client, headers)["items"][0]).status_code == 200
    assert (
        client.delete(f"/api/v1/meal-plans/{DAY}", headers=headers).status_code == 204
    )
    assert items(client, headers)["items"] == []
    assert db.scalar(select(func.count()).select_from(ShoppingCheck)) == 0
    assert (
        client.put(
            f"/api/v1/meal-plans/{DAY}/breakfast",
            headers=headers,
            json={"recipe_id": "1"},
        ).status_code
        == 200
    )
    assert check(client, headers, items(client, headers)["items"][0]).status_code == 200
    assert (
        client.delete(
            f"/api/v1/meal-plans/{DAY}/breakfast", headers=headers
        ).status_code
        == 204
    )
    assert db.scalar(select(func.count()).select_from(ShoppingCheck)) == 0
    assert (
        client.put(
            f"/api/v1/meal-plans/{DAY}/lunch", headers=headers, json={"recipe_id": "2"}
        ).status_code
        == 200
    )
    assert check(client, headers, items(client, headers)["items"][0]).status_code == 200
    db.execute(delete(User).where(User.id == UUID(owner["user_id"])))
    db.commit()
    assert db.scalar(select(func.count()).select_from(ShoppingCheck)) == 0


def test_failed_check_write_rolls_back_and_can_be_retried(shopping_env, monkeypatch):
    client, db, headers, _, _, _, _ = shopping_env
    item = items(client, headers)["items"][0]
    with monkeypatch.context() as patch:
        patch.setattr(
            db,
            "commit",
            Mock(side_effect=OperationalError("private sql", {}, Exception("private"))),
        )
        response = check(client, headers, item)
    assert response.status_code == 503 and "private" not in response.text
    assert all(not row["checked"] for row in items(client, headers)["items"])
    assert check(client, headers, item).status_code == 200


def test_missing_ingredients_are_reported_and_migration_preserves_plans(
    shopping_env, pg_connection
):
    client, db, headers, _, _, _, _ = shopping_env
    count = db.scalar(select(func.count()).select_from(MealPlanEntry))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    db.commit()
    command.downgrade(config, "20261120_01")
    pg_connection.commit()
    assert pg_connection.scalar(text("SELECT count(*) FROM meal_plan_entries")) == count
    command.upgrade(config, "head")
    pg_connection.commit()
    db.execute(delete(RecipeIngredient))
    db.commit()
    page = items(client, headers)
    assert (
        page["planned_meals"] == 2
        and page["items"] == []
        and len(page["warnings"]) == 2
    )


def test_concurrent_plan_delete_and_check_leave_no_orphan_state(
    shopping_env, pg_connection
):
    from app.main import create_app

    client, db, headers, _, _, _, _ = shopping_env
    item = items(client, headers)["items"][0]
    db.commit()
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    pg_connection.commit()
    barrier = Barrier(2)

    def attempt(args):
        app = create_app()

        def request_db():
            with pg_connection.engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                connection.commit()
                try:
                    with Session(connection, expire_on_commit=False) as session:
                        yield session
                finally:
                    connection.rollback()
                    connection.execute(text("SET search_path TO public"))
                    connection.commit()

        app.dependency_overrides[get_db] = request_db
        with TestClient(app) as other_client:
            barrier.wait(timeout=10)
            return other_client.request(**args).status_code

    requests = [
        {"method": "DELETE", "url": f"/api/v1/meal-plans/{DAY}", "headers": headers},
        {
            "method": "PATCH",
            "url": f"{BASE}/items/{item['item_key']}",
            "headers": headers,
            "json": {"source_hash": item["source_hash"], "checked": True},
        },
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, requests))
    assert results[0] == 204 and results[1] in (200, 404)
    assert db.scalar(select(func.count()).select_from(ShoppingCheck)) == 0
    assert items(client, headers)["items"] == []


@pytest.mark.parametrize(
    "value,text_value",
    [
        (Fraction(100), "100"),
        (Fraction(1, 2), "0.5"),
        (Fraction(2, 3), "2/3"),
        (Fraction(3, 1000), "0.003"),
    ],
)
def test_exact_shopping_quantities_are_not_rounded_or_turned_into_estimates(
    value, text_value
):
    assert _display(value) == text_value


def test_vendor_url_encodes_only_the_public_ingredient_name():
    name = "소금 & 간장? # + /"
    url = urlsplit(shopping_url(name))
    assert url.netloc == "www.coupang.com" and url.fragment == ""
    assert parse_qs(url.query) == {"q": [name]}
