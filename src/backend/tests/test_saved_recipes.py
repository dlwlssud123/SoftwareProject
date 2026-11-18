import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import guest
from test_public_data_import import corrections, snapshot

from app.core.database import get_db
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import Recipe, RecipeRevision

BASE = "/api/v1/saved-recipes"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", BASE),
        ("GET", f"{BASE}/1"),
        ("PUT", f"{BASE}/1"),
        ("DELETE", f"{BASE}/1"),
    ],
)
def test_saved_recipes_require_authentication(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_saved_recipes_are_persistent_idempotent_and_private(
    pg_connection, client, tmp_path
):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        path = snapshot(
            tmp_path,
            rows=[
                {
                    "RCP_SEQ": "1",
                    "RCP_NM": "쌀죽",
                    "RCP_PARTS_DTLS": "쌀 100g, 물 200ml",
                    "MANUAL01": "1. 익힌다.",
                }
            ],
        )
        apply_import(
            db, prepare_import("recipes", path, corrections_path=corrections(tmp_path))
        )
        _, owner = guest(client)
        _, other = guest(client)
        assert client.get(f"{BASE}/1", headers=owner).json()["data"] == {"saved": False}
        for _ in range(2):
            response = client.put(f"{BASE}/1", headers=owner)
            assert response.status_code == 200
            assert response.json()["data"] == {"saved": True}
            assert response.headers["Cache-Control"] == "no-store"
        assert client.get(f"{BASE}/1", headers=other).json()["data"] == {"saved": False}
        assert client.get(BASE, headers=other).json()["data"]["total"] == 0
        page = client.get(BASE, headers=owner).json()["data"]
        assert page["total"] == 1
        assert page["items"] == [{"recipe_id": "1", "name": "쌀죽"}]
        assert (
            client.get(f"{BASE}?offset=1", headers=owner).json()["data"]["items"] == []
        )
        assert client.put(f"{BASE}/999", headers=owner).status_code == 404
        assert client.put(f"{BASE}/abc", headers=owner).status_code == 422
        assert client.get(f"{BASE}?limit=0", headers=owner).status_code == 422
        assert client.delete(f"{BASE}/1", headers=other).status_code == 204
        assert client.get(f"{BASE}/1", headers=owner).json()["data"]["saved"]
        recipe = db.scalar(select(Recipe).where(Recipe.source_id == "1"))
        revision = db.get(RecipeRevision, recipe.active_revision_id)
        revision.quality_status = "hold"
        db.commit()
        assert client.put(f"{BASE}/1", headers=owner).status_code == 404
        assert (
            client.get(BASE, headers=owner).json()["data"]["items"][0]["name"] is None
        )
        recipe.active_revision_id = None
        db.commit()
        assert (
            client.get(BASE, headers=owner).json()["data"]["items"][0]["name"] is None
        )
        for _ in range(2):
            assert client.delete(f"{BASE}/1", headers=owner).status_code == 204
        assert client.get(BASE, headers=owner).json()["data"]["total"] == 0
