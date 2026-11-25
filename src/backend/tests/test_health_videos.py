import json

import pytest

from app.services import health_videos


def test_public_video_catalog_has_reviewed_sources_and_detail(client):
    from app.core.database import get_db

    def no_database():
        raise AssertionError("Public video catalog must not query a user database")

    client.app.dependency_overrides[get_db] = no_database
    response = client.get("/api/v1/health-videos")
    assert response.status_code == 200
    page = response.json()["data"]
    assert page["total"] == 3
    assert page["items"][0]["id"] == "chair-stretching"
    assert "active" not in page["items"][0]
    for video in page["items"]:
        assert video["source_url"].startswith("https://")
        assert video["checked_on"] == "2026-11-25"
        detail = client.get(f"/api/v1/health-videos/{video['id']}")
        assert detail.json()["data"] == video
    assert client.get("/api/v1/health-videos?topic=hands").json()["data"]["total"] == 1
    assert client.get("/api/v1/health-videos?offset=3").json()["data"]["items"] == []
    assert client.get("/api/v1/health-videos?limit=1").json()["data"]["total"] == 3


@pytest.mark.parametrize("query", ["topic=unknown", "offset=-1", "limit=0"])
def test_invalid_video_queries_are_validation_errors(client, query):
    assert client.get(f"/api/v1/health-videos?{query}").status_code == 422


def test_unpublished_video_cannot_be_opened_from_a_stale_list(
    client, tmp_path, monkeypatch
):
    rows = json.loads(health_videos.CATALOG.read_text(encoding="utf-8"))
    rows[0]["active"] = False
    path = tmp_path / "videos.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(health_videos, "CATALOG", path)
    assert client.get("/api/v1/health-videos").json()["data"]["total"] == 2
    response = client.get("/api/v1/health-videos/chair-stretching")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VIDEO_NOT_FOUND"


@pytest.mark.parametrize(
    "change",
    [
        {"video_id": "../wrong"},
        {"source_url": "http://www.youtube.com/watch"},
        {"source_url": "https://www.youtube.com.example.test/watch"},
    ],
)
def test_catalog_refuses_unsafe_links_without_exposing_raw_data(
    client, tmp_path, monkeypatch, change
):
    rows = json.loads(health_videos.CATALOG.read_text(encoding="utf-8"))
    rows[0].update(change)
    path = tmp_path / "videos.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(health_videos, "CATALOG", path)
    response = client.get("/api/v1/health-videos")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VIDEO_CATALOG_UNAVAILABLE"
    assert str(path) not in response.text
    assert "example.test" not in response.text


def test_missing_corrupt_or_duplicate_catalog_is_not_an_empty_success(
    client, tmp_path, monkeypatch
):
    rows = json.loads(health_videos.CATALOG.read_text(encoding="utf-8"))
    path = tmp_path / "videos.json"
    monkeypatch.setattr(health_videos, "CATALOG", path)
    assert client.get("/api/v1/health-videos").status_code == 503
    path.write_text("not json", encoding="utf-8")
    assert client.get("/api/v1/health-videos").status_code == 503
    path.write_text("[]", encoding="utf-8")
    assert client.get("/api/v1/health-videos").json()["data"]["total"] == 0
    path.write_text(json.dumps([rows[0], rows[0]]), encoding="utf-8")
    assert client.get("/api/v1/health-videos").status_code == 503
