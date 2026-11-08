from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_public_data_import import corrections, snapshot

from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import Recipe, RecipeRevision


@pytest.fixture
def api_db(pg_connection, client):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        yield client, db


def test_profile_requires_consent_and_keeps_users_separate(api_db):
    client, _ = api_db
    _, headers = guest(client)
    _, other_headers = guest(client)
    assert client.get("/api/v1/profile").status_code == 401
    assert client.get("/api/v1/profile", headers=headers).json()["data"] is None
    assert (
        client.patch(
            "/api/v1/profile",
            headers=headers,
            json={
                "preferences": {"age": 70},
            },
        ).status_code
        == 409
    )
    created = client.patch(
        "/api/v1/profile",
        headers=headers,
        json={
            "consent": True,
            "preferences": {"age": 70, "region": "대구", "exclude_allergens": ["우유"]},
        },
    )
    assert created.status_code == 200
    assert created.headers["Cache-Control"] == "no-store"
    initial = created.json()["data"]
    assert initial["preferences"]["age"] == 70
    assert client.get("/api/v1/profile", headers=other_headers).json()["data"] is None
    updated = client.patch(
        "/api/v1/profile",
        headers=headers,
        json={
            "preferences": {"age": None, "district": "남구", "exclude_allergens": []},
        },
    ).json()["data"]
    assert updated["preferences"]["age"] is None
    assert updated["preferences"]["region"] == "대구"
    assert updated["preferences"]["exclude_allergens"] == []
    assert updated["consented_at"] == initial["consented_at"]
    assert client.delete("/api/v1/profile", headers=other_headers).status_code == 200
    assert client.get("/api/v1/profile", headers=headers).json()["data"] == updated
    assert (
        client.patch(
            "/api/v1/profile", headers=headers, json={"consent": False}
        ).json()["data"]
        is None
    )
    assert client.get("/api/v1/profile", headers=headers).json()["data"] is None
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert (
        client.patch(
            "/api/v1/profile", headers=headers, json={"preferences": {"age": 70}}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"preferences": {}},
        {"consent": "true"},
        {"user_id": "someone"},
        {"consent": False, "preferences": {"age": 70}},
        {"preferences": {"age": 121}},
        {"preferences": {"age": True}},
        {"preferences": {"region": "   "}},
        {"preferences": {"exclude_allergens": ["달걀"]}},
        {"preferences": {"user_id": "someone"}},
    ],
)
def test_profile_rejects_invalid_or_ambiguous_writes(api_db, payload):
    client, _ = api_db
    _, headers = guest(client)
    assert (
        client.patch("/api/v1/profile", headers=headers, json=payload).status_code
        == 422
    )
    assert client.get("/api/v1/profile", headers=headers).json()["data"] is None


def test_recipe_routes_use_active_revision_and_keep_missing_nutrients(api_db, tmp_path):
    client, db = api_db
    rows = [
        {
            "RCP_SEQ": "1",
            "RCP_NM": "쌀죽",
            "RCP_PARTS_DTLS": "쌀 100g, 물 200ml",
            "MANUAL01": "1. 끓인다.",
            "INFO_ENG": "0",
            "RCP_PAT2": "밥",
        },
        {
            "RCP_SEQ": "2",
            "RCP_NM": "우유죽",
            "RCP_PARTS_DTLS": "우유 100ml, 쌀 100g",
            "MANUAL01": "1. 끓인다.",
            "RCP_PAT2": "밥",
        },
        {"RCP_SEQ": "3", "RCP_NM": "보류", "RCP_PARTS_DTLS": "쌀 100g"},
    ]
    path = snapshot(tmp_path, rows=rows)
    plan = prepare_import("recipes", path, corrections_path=corrections(tmp_path))
    apply_import(db, plan)
    db.commit()
    listed = client.get("/api/v1/recipes")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert [item["recipe_id"] for item in data["items"]] == ["1", "2"]
    assert data["total"] == 2
    detail = client.get("/api/v1/recipes/1").json()["data"]
    assert detail["nutrition"]["energy_kcal"] == 0
    assert detail["nutrition"]["protein_g"] is None
    assert detail["source"]["revision_id"]
    assert client.get("/api/v1/recipes/3").status_code == 404
    assert client.get("/api/v1/recipes/999").status_code == 404
    assert client.get("/api/v1/recipes?offset=2").json()["data"]["items"] == []
    assert client.get("/api/v1/recipes?q=%25").json()["data"]["total"] == 0
    assert client.get("/api/v1/recipes?q=우유&category=밥").json()["data"]["total"] == 1
    filtered = client.get("/api/v1/recipes?exclude_allergens=우유").json()["data"]
    assert [item["recipe_id"] for item in filtered["items"]] == ["1"]
    assert (
        client.get("/api/v1/recipes?exclude_allergens=아황산류").json()["data"]["total"]
        == 0
    )
    rows[0]["RCP_NM"] = "새 쌀죽"
    snapshot(tmp_path, rows=rows)
    apply_import(
        db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
    )
    db.commit()
    assert client.get("/api/v1/recipes/1").json()["data"]["name"] == "새 쌀죽"
    recipe = db.scalar(select(Recipe).where(Recipe.source_id == "1"))
    revision = db.get(RecipeRevision, recipe.active_revision_id)
    revision.quality_status = "hold"
    db.commit()
    assert client.get("/api/v1/recipes/1").status_code == 404


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "q=", "exclude_allergens=달걀", "unknown=1"],
)
def test_recipe_query_validation(client, query):
    assert client.get(f"/api/v1/recipes?{query}").status_code == 422


def test_recipe_database_failure_returns_retryable_error(client):
    db = Mock(spec=Session)
    db.scalar.side_effect = OperationalError(
        "SELECT", {}, Exception("private-password")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/v1/recipes")
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-password" not in response.text


@pytest.mark.parametrize("action", ["update", "withdraw", "delete"])
def test_profile_storage_failure_preserves_existing_consent(
    api_db, monkeypatch, action
):
    # Value: protects=profile and consent survive failed writes; fails_when=rollback is missing;
    # why_new=auth rollback does not cover profiles; seam=none; no_claim=hardware crash recovery.
    client, db = api_db
    _, headers = guest(client)
    initial = client.patch(
        "/api/v1/profile",
        headers=headers,
        json={
            "consent": True,
            "preferences": {"age": 70},
        },
    ).json()["data"]

    def fail_commit():
        raise OperationalError("COMMIT", {}, Exception("private-storage-error"))

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        if action == "delete":
            response = client.delete("/api/v1/profile", headers=headers)
        else:
            payload = (
                {"consent": False}
                if action == "withdraw"
                else {"preferences": {"age": 71}}
            )
            response = client.patch("/api/v1/profile", headers=headers, json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-storage-error" not in response.text
    assert client.get("/api/v1/profile", headers=headers).json()["data"] == initial


def test_recipe_filter_blocks_uncertain_and_incomplete_allergens(api_db, tmp_path):
    # Value: protects=uncertain allergens are excluded; fails_when=candidates or completeness is ignored;
    # why_new=direct detections do not cover uncertainty; seam=none; no_claim=cross-contact assessment.
    client, db = api_db
    rows = [
        {
            "RCP_SEQ": str(i),
            "RCP_NM": "검증",
            "RCP_PARTS_DTLS": ingredients,
            "MANUAL01": "1. 끓인다.",
        }
        for i, ingredients in enumerate(
            ["쌀 100g", "갈비 100g", "쌀 100g (국내산"], start=1
        )
    ]
    plan = prepare_import(
        "recipes", snapshot(tmp_path, rows=rows), corrections_path=corrections(tmp_path)
    )
    apply_import(db, plan)
    db.commit()
    all_items = client.get("/api/v1/recipes").json()["data"]["items"]
    assert len(all_items) == 3
    assert all_items[1]["allergens"]["needs_check"]
    assert all_items[2]["allergens"]["complete"] is False
    filtered = client.get("/api/v1/recipes?exclude_allergens=쇠고기").json()["data"]
    assert filtered["total"] == 1
    assert [item["recipe_id"] for item in filtered["items"]] == ["1"]


def test_concurrent_profile_changes_preserve_fields_and_withdrawal(
    api_db, pg_connection
):
    # Value: protects=concurrent writes preserve fields and consent withdrawal; fails_when=owner lock is removed;
    # why_new=sequential tests cannot exercise write races; seam=none; no_claim=distributed failover.
    from app.main import create_app

    client, _ = api_db
    _, headers = guest(client)
    assert (
        client.patch(
            "/api/v1/profile", headers=headers, json={"consent": True}
        ).status_code
        == 200
    )
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44

    def run_pair(payloads):
        barrier = Barrier(2)

        def attempt(payload):
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
            with TestClient(app) as concurrent_client:
                barrier.wait(timeout=10)
                return concurrent_client.patch(
                    "/api/v1/profile", headers=headers, json=payload
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, payloads))

    assert run_pair(
        [{"preferences": {"region": "대구"}}, {"preferences": {"district": "남구"}}]
    ) == [200, 200]
    preferences = client.get("/api/v1/profile", headers=headers).json()["data"][
        "preferences"
    ]
    assert preferences["region"] == "대구" and preferences["district"] == "남구"
    result = run_pair([{"preferences": {"age": 71}}, {"consent": False}])
    assert result[0] in (200, 409) and result[1] == 200
    assert client.get("/api/v1/profile", headers=headers).json()["data"] is None
