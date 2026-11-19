from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_foods_api import choice, foods_db  # noqa: F401 - shared real-import fixture
from test_public_data_import import snapshot

from alembic import command
from app.core.auth import current_auth
from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import Food, MealCreateRequest, MealLog, MealLogItem, User

BASE = "/api/v1/meals"


@pytest.fixture
def meal_env(foods_db):  # noqa: F811 - pytest injects the imported real-DB fixture
    client, db, rows, path = foods_db
    owner, headers = guest(client)
    other, other_headers = guest(client)
    return SimpleNamespace(
        client=client,
        db=db,
        rows=rows,
        path=path,
        owner=owner,
        headers=headers,
        other=other,
        other_headers=other_headers,
    )


def meal_body(client, **changes):
    return {
        "eaten_at": "2026-11-20T08:00:00+09:00",
        "items": [choice(client, "쌀밥")],
        **changes,
    }


def save(env, *, body=None, key=None, headers=None):
    return env.client.post(
        BASE,
        headers={**(headers or env.headers), "Idempotency-Key": key or str(uuid4())},
        json=body or meal_body(env.client),
    )


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", BASE),
        ("POST", BASE),
        ("GET", f"{BASE}/{uuid4()}"),
        ("PATCH", f"{BASE}/{uuid4()}"),
        ("DELETE", f"{BASE}/{uuid4()}"),
    ],
)
def test_meal_routes_require_auth(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_create_uses_server_calculation_and_records_source_evidence(meal_env):
    env = meal_env
    body = meal_body(
        env.client,
        items=[
            choice(env.client, "쌀밥", 1, "인분"),
            choice(env.client, "우유", 250, "mL"),
        ],
    )
    response = save(env, body=body)
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["replayed"] is False
    meal = data["meal"]
    assert meal["version"] == 1
    assert meal["eaten_at"] == "2026-11-19T23:00:00Z"
    assert [p["order_no"] for p in meal["items"]] == [1, 2]
    assert meal["items"][0]["amount"] == 200
    assert meal["items"][0]["calculation"]["serving"]["field"] == "DISH_ONE_SERVING"
    assert meal["total"]["nutrients"]["energy_kcal"] == 450
    assert meal["total"]["nutrients"]["fat_g"] is None
    assert meal["total"]["missing_items"]["fat_g"] == 2
    assert meal["legacy_snapshot_missing"] is False
    assert count(env.db, MealLog) == 1
    assert count(env.db, MealLogItem) == 2
    stored = env.db.scalar(select(MealLogItem).where(MealLogItem.order_no == 1))
    assert stored.amount == Decimal("200.000")
    assert stored.calculation_version == "food-portion-v1"
    assert (
        stored.portion_snapshot["source"]["revision_id"]
        == body["items"][0]["revision_id"]
    )


def test_retries_are_scoped_to_owner_and_equivalent_utc_times(meal_env):
    env = meal_env
    body, key = meal_body(env.client), str(uuid4())
    first = save(env, body=body, key=key).json()["data"]["meal"]
    retried = save(env, body={**body, "eaten_at": "2026-11-19T23:00:00Z"}, key=key)
    assert retried.status_code == 200
    assert retried.json()["data"]["replayed"] is True
    assert retried.json()["data"]["meal"] == first
    assert (
        save(
            env, body={**body, "eaten_at": "2026-11-20T08:01:00+09:00"}, key=key
        ).status_code
        == 409
    )
    second = save(env, body=body, key=key, headers=env.other_headers)
    assert second.status_code == 201
    assert second.json()["data"]["meal"]["id"] != first["id"]
    assert count(env.db, MealLog) == 2
    hashes = list(env.db.scalars(select(MealCreateRequest.key_hash)))
    assert (
        len(hashes) == 2
        and key not in hashes
        and all(len(item) == 64 for item in hashes)
    )


def test_owner_is_enforced_for_read_update_delete_and_listing(meal_env):
    env = meal_env
    meal = save(env).json()["data"]["meal"]
    path = f"{BASE}/{meal['id']}"
    assert env.client.get(BASE, headers=env.other_headers).json()["data"]["total"] == 0
    for method, suffix, payload in [
        ("GET", "", None),
        ("PATCH", "", {"expected_version": 1, "eaten_at": "2026-11-20T09:00:00+09:00"}),
        ("DELETE", "?version=1", None),
    ]:
        response = env.client.request(
            method, path + suffix, headers=env.other_headers, json=payload
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MEAL_NOT_FOUND"
        assert response.headers["Cache-Control"] == "no-store"
    assert env.client.get(path, headers=env.headers).json()["data"] == meal


def test_update_recalculates_and_stale_changes_cannot_overwrite(meal_env):
    env = meal_env
    meal = save(env).json()["data"]["meal"]
    path = f"{BASE}/{meal['id']}"
    changed = env.client.patch(
        path,
        headers=env.headers,
        json={
            "expected_version": 1,
            "items": [choice(env.client, "우유", 100, "g")],
        },
    )
    assert changed.status_code == 200
    data = changed.json()["data"]
    assert data["version"] == 2
    assert data["total"]["nutrients"]["energy_kcal"] == 60
    assert data["total"]["approx_ml_items"] == 1
    assert len(data["items"]) == 1 and data["items"][0]["calculation"]["approx_ml"]
    stale = env.client.patch(
        path,
        headers=env.headers,
        json={"expected_version": 1, "eaten_at": "2026-11-21T00:00:00Z"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "MEAL_VERSION_CHANGED"
    changed_time = env.client.patch(
        path,
        headers=env.headers,
        json={"expected_version": 2, "eaten_at": "2026-11-21T00:00:00Z"},
    ).json()["data"]
    assert changed_time["version"] == 3
    assert changed_time["items"] == data["items"]
    failed = env.client.patch(
        path,
        headers=env.headers,
        json={"expected_version": 3, "items": [choice(env.client, "우유", 1, "개")]},
    )
    assert failed.status_code == 422
    assert env.client.get(path, headers=env.headers).json()["data"] == changed_time


def test_deleted_meal_is_not_resurrected_by_a_delayed_create_retry(meal_env):
    env = meal_env
    body, key = meal_body(env.client), str(uuid4())
    meal = save(env, body=body, key=key).json()["data"]["meal"]
    path = f"{BASE}/{meal['id']}"
    assert (
        env.client.delete(path + "?version=2", headers=env.headers).status_code == 409
    )
    assert (
        env.client.delete(path + "?version=1", headers=env.headers).status_code == 204
    )
    assert count(env.db, MealLogItem) == count(env.db, MealLog) == 0
    env.db.expire_all()
    assert env.db.scalar(select(MealCreateRequest)).meal_log_id is None
    replay = save(env, body=body, key=key)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "MEAL_ALREADY_DELETED"
    assert env.client.get(path, headers=env.headers).status_code == 404
    assert env.client.get(BASE, headers=env.headers).json()["data"]["total"] == 0
    assert save(env, body=body, key=str(uuid4())).status_code == 201


def test_source_refresh_preserves_history_and_requires_reselection_to_recalculate(
    meal_env,
):
    env = meal_env
    original_selection = choice(env.client, "쌀밥")
    meal = save(env).json()["data"]["meal"]
    path = f"{BASE}/{meal['id']}"
    env.rows[0]["AMT_NUM1"] = "200"
    env.rows[0]["FOOD_NM_KR"] = "새 쌀밥"
    snapshot(env.path.parent, "nutrition", rows=env.rows)
    apply_import(env.db, prepare_import("nutrition", nutrition_path=env.path))
    env.db.commit()
    assert env.client.get(path, headers=env.headers).json()["data"] == meal
    stale = env.client.patch(
        path,
        headers=env.headers,
        json={"expected_version": 1, "items": [original_selection]},
    )
    assert stale.status_code == 409
    assert env.client.get(path, headers=env.headers).json()["data"] == meal
    current = env.client.patch(
        path,
        headers=env.headers,
        json={"expected_version": 1, "items": [choice(env.client, "새 쌀밥")]},
    )
    assert current.status_code == 200
    assert current.json()["data"]["items"][0]["name"] == "새 쌀밥"
    assert current.json()["data"]["total"]["nutrients"]["energy_kcal"] == 200


@pytest.mark.parametrize("amount,unit", [(1, "개"), (0.00001, "g"), (10000, "kg")])
def test_unrecordable_quantities_are_atomic_and_do_not_consume_retry_keys(
    meal_env, amount, unit
):
    env, key = meal_env, str(uuid4())
    body = meal_body(
        env.client,
        items=[choice(env.client, "쌀밥"), choice(env.client, "우유", amount, unit)],
    )
    response = save(env, body=body, key=key)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PORTION_NOT_RECORDABLE"
    assert (
        count(env.db, MealLog)
        == count(env.db, MealLogItem)
        == count(env.db, MealCreateRequest)
        == 0
    )
    assert save(env, key=key).status_code == 201


def test_day_query_uses_korean_midnight_and_summary_has_no_item_details(meal_env):
    env = meal_env
    for stamp in ("2026-11-19T14:59:59Z", "2026-11-19T15:00:00Z"):
        assert save(env, body=meal_body(env.client, eaten_at=stamp)).status_code == 201
    page = env.client.get(BASE + "?day=2026-11-20", headers=env.headers).json()["data"]
    assert page["total"] == 1
    assert "items" not in page["items"][0]
    assert page["items"][0]["eaten_at"] == "2026-11-19T15:00:00Z"
    assert (
        env.client.get(BASE + "?day=2026-11-19", headers=env.headers).json()["data"][
            "total"
        ]
        == 1
    )
    assert (
        env.client.get(BASE + "?offset=2", headers=env.headers).json()["data"]["items"]
        == []
    )
    for query in ("limit=51", "offset=-1", "day=bad", "day=9999-12-31"):
        assert (
            env.client.get(BASE + "?" + query, headers=env.headers).status_code == 422
        )


def test_commit_failure_rolls_back_receipt_meal_and_items(meal_env, monkeypatch):
    env, key = meal_env, str(uuid4())
    body = meal_body(env.client)
    original_commit = env.db.commit
    monkeypatch.setattr(
        env.db,
        "commit",
        Mock(side_effect=OperationalError("private sql", {}, Exception("private"))),
    )
    response = save(env, body=body, key=key)
    assert response.status_code == 503 and "private" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    monkeypatch.setattr(env.db, "commit", original_commit)
    assert (
        count(env.db, MealLog)
        == count(env.db, MealLogItem)
        == count(env.db, MealCreateRequest)
        == 0
    )
    assert save(env, body=body, key=key).status_code == 201


def test_legacy_records_keep_stored_values_and_migration_preserves_existing_rows(
    meal_env, pg_connection
):
    env = meal_env
    food = env.db.scalar(select(Food).where(Food.food_code == "RICE"))
    legacy = MealLog(
        user_id=UUID(env.owner["user_id"]), eaten_at=datetime(2026, 11, 19, tzinfo=UTC)
    )
    env.db.add(legacy)
    env.db.flush()
    env.db.add(
        MealLogItem(
            meal_log_id=legacy.id,
            food_revision_id=food.active_revision_id,
            amount=Decimal("123.456"),
            amount_unit="g",
            nutrients={"energy_kcal": 222.2},
            calculation_version="legacy-test",
        )
    )
    env.db.commit()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    command.downgrade(config, "20261119_01")
    pg_connection.commit()
    assert pg_connection.scalar(text("SELECT count(*) FROM meal_logs")) == 1
    command.upgrade(config, "head")
    pg_connection.commit()
    env.db.expire_all()
    response = env.client.get(f"{BASE}/{legacy.id}", headers=env.headers)
    assert response.status_code == 200
    meal = response.json()["data"]
    assert meal["version"] == 1 and meal["legacy_snapshot_missing"] is True
    assert meal["items"][0]["calculation"] is None
    assert meal["total"]["nutrients"]["energy_kcal"] == 222.2


def test_user_deletion_cascades_private_history_and_receipts_without_deleting_foods(
    meal_env,
):
    env = meal_env
    assert save(env).status_code == 201
    env.db.execute(delete(User).where(User.id == UUID(env.owner["user_id"])))
    env.db.commit()
    assert (
        count(env.db, MealLog)
        == count(env.db, MealLogItem)
        == count(env.db, MealCreateRequest)
        == 0
    )
    assert count(env.db, Food) == 3


def test_concurrent_save_and_edit_are_serialized(meal_env, pg_connection):
    from app.main import create_app

    env = meal_env
    body, key = meal_body(env.client), str(uuid4())
    env.db.commit()
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    pg_connection.commit()

    def run_pair(requests):
        barrier = Barrier(2)

        def attempt(args):
            app = create_app()

            def request_db():
                with pg_connection.engine.connect() as connection:
                    connection.execute(text(f'SET search_path TO "{schema}"'))
                    connection.commit()
                    try:
                        with Session(connection, expire_on_commit=False) as db:
                            yield db
                    finally:
                        connection.rollback()
                        connection.execute(text("SET search_path TO public"))
                        connection.commit()

            app.dependency_overrides[get_db] = request_db
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.request(**args)

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, requests))

    responses = run_pair(
        [
            {
                "method": "POST",
                "url": BASE,
                "headers": {**env.headers, "Idempotency-Key": key},
                "json": body,
            }
        ]
        * 2
    )
    assert sorted(r.status_code for r in responses) == [200, 201]
    meal = responses[0].json()["data"]["meal"]
    assert meal["id"] == responses[1].json()["data"]["meal"]["id"]
    assert count(env.db, MealLog) == count(env.db, MealCreateRequest) == 1
    env.db.commit()
    path = f"{BASE}/{meal['id']}"
    selections = [choice(env.client, "쌀밥", amount) for amount in (200, 300)]
    env.db.commit()
    responses = run_pair(
        [
            {
                "method": "PATCH",
                "url": path,
                "headers": env.headers,
                "json": {"expected_version": 1, "items": [item]},
            }
            for item in selections
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    current = env.client.get(path, headers=env.headers).json()["data"]
    assert current["version"] == 2
    assert current["total"]["nutrients"]["energy_kcal"] in (300, 450)
    env.db.commit()
    responses = run_pair(
        [
            {"method": "DELETE", "url": path + "?version=2", "headers": env.headers},
            {
                "method": "POST",
                "url": BASE,
                "headers": {**env.headers, "Idempotency-Key": key},
                "json": body,
            },
        ]
    )
    assert responses[0].status_code == 204
    assert responses[1].status_code in (200, 409)
    assert count(env.db, MealLog) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"eaten_at": "2026-11-20T12:00:00"},
        {"eaten_at": "0001-01-01T00:00:00+09:00"},
        {"items": []},
        {"items": None},
        {"user_id": str(uuid4())},
        {"nutrients": {"energy_kcal": 0}},
    ],
)
def test_invalid_create_input_is_rejected_without_database_access(client, changes):
    client.app.dependency_overrides[current_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=uuid4())
    )
    body = {
        "eaten_at": "2026-11-20T00:00:00Z",
        "items": [
            {
                "food_id": str(uuid4()),
                "revision_id": str(uuid4()),
                "amount": 100,
                "unit": "g",
            }
        ],
        **changes,
    }
    response = client.post(BASE, headers={"Idempotency-Key": str(uuid4())}, json=body)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_version": 1},
        {"expected_version": True, "items": []},
        {"expected_version": 1, "eaten_at": None},
    ],
)
def test_invalid_update_input_is_rejected(client, payload):
    client.app.dependency_overrides[current_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=uuid4())
    )
    assert client.patch(f"{BASE}/{uuid4()}", json=payload).status_code == 422
