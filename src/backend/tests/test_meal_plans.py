from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from test_auth import guest
from test_public_data_import import corrections, snapshot

from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import AuthSession, Recipe, User

DAY = "/api/v1/meal-plans/2026-11-18"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", DAY, None),
        ("PUT", f"{DAY}/lunch", {"recipe_id": "1"}),
        ("DELETE", f"{DAY}/lunch", None),
        ("DELETE", DAY, None),
    ],
)
def test_plan_routes_require_authentication(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


@pytest.fixture
def plan_session(client):
    user = User(id=uuid4())
    db = Mock(spec=Session)
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        user, AuthSession()
    )
    client.app.dependency_overrides[get_db] = lambda: db
    return user, db


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/meal-plans/20261118/lunch", {"recipe_id": "1"}),
        ("/api/v1/meal-plans/2026-02-30/lunch", {"recipe_id": "1"}),
        (f"{DAY}/midnight", {"recipe_id": "1"}),
        (f"{DAY}/lunch", {"recipe_id": "abc"}),
        (f"{DAY}/lunch", {"recipe_id": "1", "user_id": "another-user"}),
    ],
)
def test_plan_rejects_invalid_inputs_without_writing(client, plan_session, path, body):
    _, db = plan_session
    assert client.put(path, json=body).status_code == 422
    db.execute.assert_not_called()


def test_put_inserts_or_replaces_only_the_authenticated_slot(client, plan_session):
    user, db = plan_session
    revision_id = uuid4()
    db.execute.return_value.one_or_none.return_value = (revision_id, "단호박죽")
    payload = {"recipe_id": "1", "recipe_revision_id": str(revision_id)}
    response = client.put(f"{DAY}/lunch", json=payload)
    assert response.status_code == 200
    assert response.json()["data"] == {
        **payload,
        "meal_slot": "lunch",
        "name": "단호박죽",
        "is_active": True,
    }
    upsert = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT ON CONSTRAINT uq_meal_plan_user_date_slot" in str(upsert)
    assert upsert.params["user_id"] == user.id
    assert upsert.params["plan_date"] == date(2026, 11, 18)
    assert upsert.params["meal_slot"] == "lunch"
    assert upsert.params["recipe_revision_id"] == revision_id
    db.commit.assert_called_once()


def test_plan_rejects_stale_recipe_revision_before_replacing_slot(client, plan_session):
    _, db = plan_session
    db.execute.return_value.one_or_none.return_value = (uuid4(), "단호박죽")
    response = client.put(
        f"{DAY}/lunch", json={"recipe_id": "1", "recipe_revision_id": str(uuid4())}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECIPE_REVISION_CHANGED"
    db.execute.assert_called_once()
    db.commit.assert_not_called()


def test_read_plan_preserves_saved_revision_and_orders_slots(client, plan_session):
    user, db = plan_session
    breakfast_id, lunch_id = uuid4(), uuid4()
    db.execute.return_value.all.return_value = [
        ("lunch", "2", lunch_id, "단호박죽", None),
        ("breakfast", "1", breakfast_id, "쌀죽", breakfast_id),
    ]
    response = client.get(DAY)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {
        "plan_date": "2026-11-18",
        "items": [
            {
                "meal_slot": "breakfast",
                "recipe_id": "1",
                "recipe_revision_id": str(breakfast_id),
                "name": "쌀죽",
                "is_active": True,
            },
            {
                "meal_slot": "lunch",
                "recipe_id": "2",
                "recipe_revision_id": str(lunch_id),
                "name": "단호박죽",
                "is_active": False,
            },
        ],
    }
    query = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert query.params == {"user_id_1": user.id, "plan_date_1": date(2026, 11, 18)}


def test_delete_slot_uses_the_same_owner_and_date(client, plan_session):
    user, db = plan_session
    response = client.delete(f"{DAY}/lunch")
    assert response.status_code == 204
    assert response.content == b""
    query = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert query.params == {
        "user_id_1": user.id,
        "plan_date_1": date(2026, 11, 18),
        "meal_slot_1": "lunch",
    }
    db.commit.assert_called_once()


def test_plan_persists_replaces_and_deletes_only_owners_entries(
    pg_connection, client, tmp_path
):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        data = [
            {
                "RCP_SEQ": str(i),
                "RCP_NM": name,
                "RCP_PARTS_DTLS": "쌀 100g, 물 200ml",
                "MANUAL01": "1. 익힌다.",
            }
            for i, name in enumerate(("쌀죽", "단호박죽"), 1)
        ]
        path = snapshot(tmp_path, rows=data)
        apply_import(
            db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
        )
        _, owner_headers = guest(client)
        _, other_headers = guest(client)
        responses = [
            client.put(f"{DAY}/{slot}", headers=headers, json={"recipe_id": recipe_id})
            for headers, slot, recipe_id in (
                (owner_headers, "lunch", "1"),
                (owner_headers, "lunch", "2"),
                (owner_headers, "breakfast", "1"),
                (other_headers, "lunch", "1"),
            )
        ]
        assert all(response.status_code == 200 for response in responses)

        recipe = db.scalar(select(Recipe).where(Recipe.source_id == "2"))
        recipe.active_revision_id = None
        db.commit()
        result = client.get(DAY, headers=owner_headers)
        assert result.headers["Cache-Control"] == "no-store"
        meals = result.json()["data"]["items"]
        assert [
            (meal["meal_slot"], meal["recipe_id"], meal["is_active"]) for meal in meals
        ] == [
            ("breakfast", "1", True),
            ("lunch", "2", False),
        ]
        assert (
            client.put(
                f"{DAY}/lunch", headers=owner_headers, json={"recipe_id": "2"}
            ).status_code
            == 404
        )
        assert (
            client.delete(f"{DAY}/breakfast", headers=owner_headers).status_code == 204
        )
        assert len(client.get(DAY, headers=owner_headers).json()["data"]["items"]) == 1
        for _ in range(2):
            assert client.delete(DAY, headers=owner_headers).status_code == 204
        assert client.get(DAY, headers=owner_headers).json()["data"]["items"] == []
        assert (
            client.get(DAY, headers=other_headers).json()["data"]["items"][0][
                "recipe_id"
            ]
            == "1"
        )
