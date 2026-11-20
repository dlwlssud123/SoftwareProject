import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from agetech_data.textutil import sha256_json
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_welfare_import import node, snapshot

from alembic import command
from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.jobs.import_welfare import apply_import, prepare_import
from app.models import SavedWelfareService, WelfareRevision, WelfareService

BASE = "/api/v1/welfare"
SAVED = "/api/v1/saved-welfare"


def catalog_snapshot(tmp_path, source):
    ids = (
        ("WLF100", "WLF101")
        if source == "central"
        else ("WLF200", "WLF201", "WLF202", "WLF203")
    )
    path = snapshot(tmp_path, ids=ids, source=source)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["items"]:
        sid = item["servId"]
        listing, detail = item["list"], item["detail"]
        title = {
            "WLF100": "전국 일반 안내",
            "WLF101": "전국 독거 지원",
            "WLF200": "남구 일반 안내",
            "WLF201": "대구 전체 안내",
            "WLF202": "다른 지역 안내",
            "WLF203": "종료 사업",
        }[sid]
        listing["servNm"] = detail["servNm"] = title
        if sid == "WLF101":
            detail["tgtrDtlCn"] = "만 65세 이상 독거노인. 소득 기준 등은 문의"
        if sid == "WLF201":
            listing["sggNm"] = ""
        if sid == "WLF202":
            listing.update(ctpvNm="부산광역시", sggNm="남구")
        if sid == "WLF203":
            listing["enfcEndYmd"] = "20000101"
        item["detail_xml"] = node("wantedDtl", detail)
    payload["meta"]["items_sha256"] = sha256_json(payload["items"])
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def welfare_db(pg_connection, client, tmp_path):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        for source in ("central", "local"):
            apply_import(
                db, prepare_import(catalog_snapshot(tmp_path, source), source=source)
            )
        db.commit()
        yield client, db


def ids(response):
    assert response.status_code == 200, response.text
    return [item["service_id"] for item in response.json()["data"]["items"]]


def test_welfare_lists_active_regions_pages_and_literal_search(welfare_db):
    client, _ = welfare_db
    assert len(ids(client.get(BASE))) == 5
    local = client.get(BASE, params={"region": "대구", "district": "남구"})
    assert ids(local) == ["WLF200", "WLF201", "WLF101", "WLF100"]
    assert local.json()["data"]["total"] == 4
    assert ids(client.get(BASE, params={"region": "대구"})) == [
        "WLF201",
        "WLF101",
        "WLF100",
    ]
    assert ids(client.get(BASE, params={"region": "대구", "district": "없는구"})) == [
        "WLF201",
        "WLF101",
        "WLF100",
    ]
    assert len(ids(client.get(BASE, params={"scope": "local"}))) == 3
    assert len(ids(client.get(BASE, params={"scope": "central_nationwide"}))) == 2
    assert ids(client.get(BASE, params={"q": "%"})) == []
    assert ids(client.get(BASE, params={"q": "독거"})) == ["WLF101"]
    assert (
        client.get(BASE, params={"limit": 1, "offset": 1}).json()["data"]["total"] == 5
    )
    assert ids(client.get(BASE, params={"offset": 10})) == []
    assert client.get(BASE, params={"district": "남구"}).status_code == 422
    assert client.get(BASE, params={"limit": 101}).status_code == 422


def test_welfare_source_revision_publication_and_check_times(welfare_db):
    client, db = welfare_db
    service = db.scalar(
        select(WelfareService).where(WelfareService.source_id == "WLF100")
    )
    original = service.active_revision_id
    service.last_checked_at = datetime(2026, 11, 18, tzinfo=UTC)
    service.last_detail_checked_at = service.last_checked_at - timedelta(days=1)
    db.commit()
    record = client.get(f"{BASE}/WLF100").json()["data"]
    assert record["source"]["revision_id"] == str(original)
    assert record["source"]["checked_at"] == "2026-11-18T00:00:00Z"
    assert record["source"]["detail_checked_at"] == "2026-11-17T00:00:00Z"
    assert record["application_status"] == "unknown"
    assert record["scope"] == "central_nationwide"
    assert client.get(f"{BASE}/WLF999").status_code == 404
    assert client.get(f"{BASE}/invalid").status_code == 422
    service.publication_status = "withdrawn"
    db.commit()
    assert client.get(f"{BASE}/WLF100").status_code == 404
    assert "WLF100" not in ids(client.get(BASE))
    service.publication_status = "published"
    revision = db.get(WelfareRevision, original)
    revision.quality_status = "hold"
    db.commit()
    assert client.get(f"{BASE}/WLF100").status_code == 404
    assert "WLF100" not in ids(client.get(BASE))


def test_legacy_central_revision_and_latest_import_remain_readable(
    welfare_db, tmp_path
):
    client, db = welfare_db
    service = db.scalar(
        select(WelfareService).where(WelfareService.source_id == "WLF100")
    )
    old_revision = service.active_revision_id
    revision = db.get(WelfareRevision, old_revision)
    revision.normalized = {"scope": "central_nationwide", "list": {}, "detail": {}}
    db.commit()
    assert client.get(f"{BASE}/WLF100").json()["data"]["region_scope"] == "national"
    assert "WLF100" in ids(client.get(BASE, params={"region": "대구"}))
    assert (
        client.post(
            f"{BASE}/recommendations", json={"age": 70, "region": "대구"}
        ).status_code
        == 200
    )
    updated = snapshot(tmp_path, day=1, ids=("WLF100",), changed=True)
    apply_import(db, prepare_import(updated))
    db.commit()
    latest = client.get(f"{BASE}/WLF100").json()["data"]
    assert latest["source"]["revision_id"] != str(old_revision)
    assert latest["title"] == "사업"


def test_recommendations_rank_source_cues_without_determining_eligibility(welfare_db):
    client, _ = welfare_db
    response = client.post(
        f"{BASE}/recommendations",
        json={"age": 70, "region": "대구", "district": "남구", "lives_alone": True},
    )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert [item["item"]["service_id"] for item in data["items"]] == [
        "WLF200",
        "WLF201",
        "WLF101",
        "WLF100",
    ]
    assert all(
        item["item"]["application_status"] == "unknown" for item in data["items"]
    )
    assert any("65" in reason for reason in data["items"][2]["reasons"])
    assert any("1인" in reason for reason in data["items"][2]["reasons"])
    assert any("확정하지" in warning for warning in data["warnings"])
    assert data["rules_version"] == "welfare-candidates-v1"
    under_age = client.post(
        f"{BASE}/recommendations", json={"age": 50, "region": "대구"}
    ).json()["data"]
    assert len(under_age["items"]) == 3
    assert any("노년층" in warning for warning in under_age["warnings"])
    assert not any(
        "65" in reason for item in under_age["items"] for reason in item["reasons"]
    )
    unknown = client.post(
        f"{BASE}/recommendations", json={"age": 70, "region": "없는지역", "limit": 1}
    ).json()["data"]
    assert len(unknown["items"]) == 1
    assert unknown["items"][0]["item"]["region_scope"] == "national"
    assert any("알 수 없는" in warning for warning in unknown["warnings"])


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", SAVED),
        ("GET", f"{SAVED}/WLF100"),
        ("PUT", f"{SAVED}/WLF100"),
        ("DELETE", f"{SAVED}/WLF100"),
    ],
)
def test_saved_welfare_requires_authentication(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_saved_welfare_owner_idempotency_and_withdrawn_removal(welfare_db):
    client, db = welfare_db
    _, owner = guest(client)
    _, other = guest(client)
    assert not client.get(f"{SAVED}/WLF100", headers=owner).json()["data"]["saved"]
    for _ in range(2):
        saved = client.put(f"{SAVED}/WLF100", headers=owner)
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["saved"] is True
        assert saved.headers["Cache-Control"] == "no-store"
    assert len(db.scalars(select(SavedWelfareService)).all()) == 1
    assert client.get(SAVED, headers=other).json()["data"]["total"] == 0
    assert not client.get(f"{SAVED}/WLF100", headers=other).json()["data"]["saved"]
    listed = client.get(SAVED, headers=owner)
    assert listed.headers["Cache-Control"] == "no-store"
    assert listed.json()["data"]["items"] == [
        {"service_id": "WLF100", "title": "전국 일반 안내"}
    ]
    assert (
        client.get(SAVED, params={"offset": 1}, headers=owner).json()["data"]["items"]
        == []
    )
    assert (
        client.get(SAVED, params={"q": "%"}, headers=owner).json()["data"]["total"] == 0
    )
    assert client.put(f"{SAVED}/WLF999", headers=owner).status_code == 404
    assert client.delete(f"{SAVED}/WLF100", headers=other).status_code == 204
    assert client.get(SAVED, headers=owner).json()["data"]["total"] == 1
    service = db.scalar(
        select(WelfareService).where(WelfareService.source_id == "WLF100")
    )
    service.publication_status = "withdrawn"
    db.commit()
    assert client.put(f"{SAVED}/WLF100", headers=owner).status_code == 404
    assert client.get(SAVED, headers=owner).json()["data"]["items"][0]["title"] is None
    for _ in range(2):
        assert client.delete(f"{SAVED}/WLF100", headers=owner).status_code == 204
    assert client.get(SAVED, headers=owner).json()["data"]["total"] == 0


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", BASE, None),
        ("GET", f"{BASE}/WLF100", None),
        ("POST", f"{BASE}/recommendations", {"age": 70, "region": "대구"}),
    ],
)
def test_welfare_database_error_is_retryable(client, method, path, body):
    db = Mock()
    db.execute.side_effect = OperationalError(None, None, RuntimeError("private"))
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.request(method, path, json=body)
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private" not in response.text


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_welfare_note_requires_authentication(client, method):
    response = client.request(
        method, f"{SAVED}/WLF100/note", json={"note": "서류 준비"}
    )
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_welfare_note_is_private_and_survives_repeated_save(welfare_db):
    client, _ = welfare_db
    _, owner = guest(client)
    _, other = guest(client)
    path = f"{SAVED}/WLF100/note"
    assert client.get(path, headers=owner).status_code == 404
    assert client.patch(path, headers=owner, json={"note": "메모"}).status_code == 404
    assert client.get(SAVED, headers=owner).json()["data"]["total"] == 0
    assert client.put(f"{SAVED}/WLF100", headers=owner).status_code == 200
    assert client.get(path, headers=owner).json()["data"] == {
        "service_id": "WLF100",
        "note": None,
        "updated_at": None,
    }
    saved = client.patch(
        path, headers=owner, json={"note": "  주민센터에 준비 서류 문의  "}
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["note"] == "주민센터에 준비 서류 문의"
    assert datetime.fromisoformat(data["updated_at"]).tzinfo is not None
    assert saved.headers["Cache-Control"] == "no-store"
    assert client.get(path, headers=owner).json()["data"] == data
    for method in ("GET", "PATCH"):
        response = client.request(
            method, path, headers=other, json={"note": "다른 사람 메모"}
        )
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"
        assert "주민센터" not in response.text
    assert client.put(f"{SAVED}/WLF100", headers=owner).status_code == 200
    assert client.get(path, headers=owner).json()["data"] == data
    # Neither public details nor the summary list exposes the private note.
    assert "주민센터" not in client.get(f"{BASE}/WLF100").text
    assert "note" not in client.get(SAVED, headers=owner).json()["data"]["items"][0]


@pytest.mark.parametrize("value", [None, "", " \n\t "])
def test_welfare_note_can_be_cleared_without_removing_saved_service(welfare_db, value):
    client, _ = welfare_db
    _, owner = guest(client)
    path = f"{SAVED}/WLF100/note"
    client.put(f"{SAVED}/WLF100", headers=owner)
    client.patch(path, headers=owner, json={"note": "기존 메모"})
    response = client.patch(path, headers=owner, json={"note": value})
    assert response.status_code == 200
    assert response.json()["data"]["note"] is None
    assert response.json()["data"]["updated_at"] is not None
    assert client.get(path, headers=owner).json()["data"]["note"] is None
    assert client.get(f"{SAVED}/WLF100", headers=owner).json()["data"]["saved"]


def test_withdrawn_welfare_note_remains_private_and_saved_removal_deletes_it(
    welfare_db,
):
    client, db = welfare_db
    _, owner = guest(client)
    path = f"{SAVED}/WLF100/note"
    client.put(f"{SAVED}/WLF100", headers=owner)
    service = db.scalar(
        select(WelfareService).where(WelfareService.source_id == "WLF100")
    )
    service.publication_status = "withdrawn"
    db.commit()
    note = "<b>공식 문의 필요</b>"
    assert client.patch(path, headers=owner, json={"note": note}).status_code == 200
    assert client.get(path, headers=owner).json()["data"]["note"] == note
    assert client.delete(f"{SAVED}/WLF100", headers=owner).status_code == 204
    assert client.get(path, headers=owner).status_code == 404
    service.publication_status = "published"
    db.commit()
    client.put(f"{SAVED}/WLF100", headers=owner)
    assert client.get(path, headers=owner).json()["data"]["note"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"note": "가" * 2001},
        {"note": 1},
        {"note": []},
        {"note": "수정", "user_id": "other"},
    ],
)
def test_welfare_note_rejects_invalid_patch_without_changing_existing_note(
    welfare_db, body
):
    client, _ = welfare_db
    _, owner = guest(client)
    path = f"{SAVED}/WLF100/note"
    client.put(f"{SAVED}/WLF100", headers=owner)
    client.patch(path, headers=owner, json={"note": "기존 메모"})
    assert client.patch(path, headers=owner, json=body).status_code == 422
    assert client.get(path, headers=owner).json()["data"]["note"] == "기존 메모"
    bounded = "가" * 2000
    assert client.patch(path, headers=owner, json={"note": bounded}).status_code == 200
    assert client.get(path, headers=owner).json()["data"]["note"] == bounded


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_welfare_note_storage_failure_is_private_and_retryable(client, method):
    db = Mock()
    db.execute.side_effect = OperationalError(None, None, RuntimeError("private-note"))
    client.app.dependency_overrides[get_db] = lambda: db
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        user=Mock(), session=Mock()
    )
    response = client.request(
        method, f"{SAVED}/WLF100/note", json={"note": "비공개 메모"}
    )
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "SAVED_WELFARE_UNAVAILABLE"
    assert response.json()["error"]["retryable"]
    assert "private-note" not in response.text and "비공개 메모" not in response.text
    if method == "PATCH":
        db.rollback.assert_called_once()


def test_welfare_note_migration_preserves_existing_saved_rows(
    welfare_db, pg_connection
):
    client, db = welfare_db
    _, owner = guest(client)
    client.put(f"{SAVED}/WLF100", headers=owner)
    saved_at = db.scalar(select(SavedWelfareService.saved_at))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    command.downgrade(config, "20261118_01")
    pg_connection.commit()
    assert (
        pg_connection.scalar(text("SELECT count(*) FROM saved_welfare_services")) == 1
    )
    command.upgrade(config, "head")
    pg_connection.commit()
    db.expire_all()
    assert db.scalar(select(SavedWelfareService.saved_at)) == saved_at
    response = client.get(f"{SAVED}/WLF100/note", headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["note"] is None
