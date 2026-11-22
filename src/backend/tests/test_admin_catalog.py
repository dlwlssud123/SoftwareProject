from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_admin_guides import admin_db as admin_db
from test_admin_guides import data
from test_content_api import facility
from test_meal_seasonal_import import (
    DAY2,
    NAMGU,
    facility_snapshot,
    import_recipes,
    seasonal_items,
    seasonal_snapshot,
)

from alembic import command
from app.api.admin_catalog import _can_approve, _command, _revision
from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.core.errors import AppError
from app.jobs import import_meal_facilities, import_seasonal
from app.main import create_app
from app.models import CatalogAuditEvent, MealFacility, SeasonalFood
from app.schemas.catalog_management import CatalogReviewCommand
from app.services.catalog_review import review_allows

BASE = "/api/v1/admin/catalog"
KINDS = ("meal-facilities", "seasonal-foods")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("GET", "", None),
        ("GET", f"/{uuid4()}", None),
        ("GET", f"/{uuid4()}/audit", None),
        (
            "POST",
            f"/{uuid4()}/actions",
            {"expected_version": 1, "expected_revision": "a" * 64, "action": "submit"},
        ),
    ],
)
def test_catalog_roles_are_enforced_before_queries(client, kind, method, suffix, body):
    db = Mock()
    client.app.dependency_overrides[get_db] = lambda: db
    path = f"{BASE}/{kind}{suffix}"
    assert client.request(method, path, json=body).status_code == 401
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        user=SimpleNamespace(id=uuid4(), role="user"), session=SimpleNamespace()
    )
    response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    db.scalar.assert_not_called()
    db.execute.assert_not_called()


@pytest.fixture
def mocked_admin(client):
    db = Mock()
    client.app.dependency_overrides[get_db] = lambda: db
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        user=SimpleNamespace(id=uuid4(), role="admin"), session=SimpleNamespace()
    )
    return client, db


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_version": True},
        {"expected_version": "1"},
        {"expected_version": 0},
        {"expected_revision": "not-a-hash"},
        {"expected_revision": "A" * 64},
        {"action": "delete"},
        {"action": "reject"},
        {"is_published": True},
        {"action": "publish", "note": "ignored"},
    ],
)
def test_invalid_review_input_does_not_acquire_import_lock(mocked_admin, changes):
    client, db = mocked_admin
    response = client.post(
        f"{BASE}/meal-facilities/{uuid4()}/actions",
        json={
            "expected_version": 1,
            "expected_revision": "a" * 64,
            "action": "submit",
            **changes,
        },
    )
    assert response.status_code == 422, response.text
    assert response.headers["Cache-Control"] == "no-store"
    db.execute.assert_not_called()


def row_for_review(**changes):
    return facility(
        content_sha256="a" * 64,
        review_version=1,
        review_status="legacy",
        review_is_published=True,
        review_updated_at=datetime.now(UTC),
        **changes,
    )


@pytest.mark.parametrize(
    "status,visible,action",
    [
        ("legacy", True, "approve"),
        ("legacy", True, "publish"),
        ("legacy", False, "unpublish"),
        ("review", False, "submit"),
        ("review", False, "publish"),
        ("approved", False, "reject"),
        ("approved", True, "submit"),
        ("rejected", False, "approve"),
    ],
)
def test_invalid_transitions_leave_source_and_review_unchanged(status, visible, action):
    row = row_for_review()
    row.review_status, row.review_is_published = status, visible
    row.reviewed_content_sha256 = row.content_sha256
    before = (
        row.review_status,
        row.review_is_published,
        row.is_published,
        row.review_version,
    )
    body = CatalogReviewCommand(
        expected_version=1,
        expected_revision=_revision(row, KINDS[0]),
        action=action,
        note="수정 필요" if action == "reject" else None,
    )
    with pytest.raises(AppError) as exc:
        _command(row, KINDS[0], body, uuid4(), datetime.now(UTC))
    assert exc.value.code == "CATALOG_STATE_CHANGED"
    assert before == (
        row.review_status,
        row.review_is_published,
        row.is_published,
        row.review_version,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "http://example.org"},
        {"source_url": "https://example.org:8443"},
        {"checked_on": (datetime.now(UTC) + timedelta(days=2)).date()},
        {"is_published": False},
        {"content_sha256": None},
        {"quality_flags": ["operation_ended"]},
        {"normalized": {"close_date": "2000-01-01"}},
    ],
)
def test_source_eligibility_cannot_be_overridden_by_approval(changes):
    row = row_for_review()
    for name, value in changes.items():
        setattr(row, name, value)
    with pytest.raises(AppError) as exc:
        _can_approve(row, KINDS[0])
    assert exc.value.code == "CATALOG_SOURCE_UNAVAILABLE"


@pytest.mark.parametrize(
    "value",
    [
        "http://www.coupang.com/np/search?q=무",
        "https://evil.example/np/search?q=무",
        "https://www.coupang.com/np/search?q=다른재료",
        "https://www.coupang.com/np/search?q=무&q=무",
        "https://www.coupang.com/np/search?q=무&profile=x",
        "https://www.coupang.com/np/search?q=%FF",
        "https://www.coupang.com/np/search?q=무#other",
    ],
)
def test_seasonal_approval_rejects_non_ingredient_shopping_urls(value):
    row = SeasonalFood(
        name="무",
        checked_on=datetime.now(UTC).date(),
        is_published=True,
        detail_status="ok",
        source_url="https://www.nics.go.kr/",
        content_sha256="a" * 64,
        shopping_search_url=value,
    )
    with pytest.raises(AppError):
        _can_approve(row, KINDS[1])


def test_db_failure_does_not_expose_connection_or_commit(mocked_admin):
    client, db = mocked_admin
    db.execute.side_effect = OperationalError(
        None, None, RuntimeError("private-db-details")
    )
    result = client.post(
        f"{BASE}/meal-facilities/{uuid4()}/actions",
        json={"expected_version": 1, "expected_revision": "a" * 64, "action": "submit"},
    )
    assert result.status_code == 503
    assert result.headers["Cache-Control"] == "no-store"
    assert "private-db-details" not in result.text
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def seed(env, tmp_path):
    import_recipes(env.db, tmp_path)
    facility_plan = import_meal_facilities.prepare_import(
        facility_snapshot(tmp_path, rows=(NAMGU,))
    )
    import_meal_facilities.apply_import(env.db, facility_plan)
    import_seasonal.apply_import(
        env.db, import_seasonal.prepare_import(seasonal_snapshot(tmp_path))
    )
    env.db.commit()
    return facility_plan


def target(env, kind):
    stmt = (
        select(MealFacility)
        if kind == KINDS[0]
        else select(SeasonalFood).where(SeasonalFood.month == 12)
    )
    return env.db.scalar(stmt)


def detail(env, kind, row):
    return data(env.client.get(f"{BASE}/{kind}/{row.id}", headers=env.headers))


def action(env, kind, item, name, **extra):
    return env.client.post(
        f"{BASE}/{kind}/{item['id']}/actions",
        headers=env.headers,
        json={
            "action": name,
            "expected_version": item["review_version"],
            "expected_revision": item["source_revision"],
            **extra,
        },
    )


@pytest.mark.parametrize("kind", KINDS)
def test_real_import_review_publish_and_hidden_refresh_workflow(
    admin_db, tmp_path, kind
):
    env = admin_db
    seed(env, tmp_path)
    row = target(env, kind)
    public = f"/api/v1/{kind}/{row.id}"
    item = detail(env, kind, row)
    assert (
        item["review_status"] == "legacy"
        and item["review_required"]
        and item["is_published"]
    )
    assert item["reviewed_by"] is None and item["reviewed_at"] is None
    assert env.client.get(public).status_code == 200
    item = data(action(env, kind, item, "submit"))
    assert not item["is_published"] and env.client.get(public).status_code == 404
    item = data(
        action(env, kind, item, "reject", note="원천 내용을 다시 확인해 주세요")
    )
    item = data(action(env, kind, item, "submit"))
    assert item["review_note"] is None
    item = data(action(env, kind, item, "approve", note="확인했습니다"))
    assert not item["is_published"] and env.client.get(public).status_code == 404
    item = data(action(env, kind, item, "publish"))
    assert item["is_published"] and not item["review_required"]
    visible = env.client.get(public)
    assert visible.status_code == 200
    assert (
        not {"review_note", "reviewed_by", "review_status"}
        & visible.json()["data"].keys()
    )
    item = data(action(env, kind, item, "unpublish"))
    if kind == KINDS[0]:
        refreshed = import_meal_facilities.prepare_import(
            facility_snapshot(tmp_path, rows=(NAMGU,), fetched_at=DAY2)
        )
        import_meal_facilities.apply_import(env.db, refreshed)
        assert import_meal_facilities.verify_import(env.db, refreshed)["verified"]
    else:
        import_seasonal.apply_import(
            env.db,
            import_seasonal.prepare_import(
                seasonal_snapshot(tmp_path, fetched_at=DAY2)
            ),
        )
    env.db.commit()
    assert row.is_published and not row.review_is_published
    assert env.client.get(public).status_code == 404
    if kind == KINDS[0]:
        result = env.client.get("/api/v1/meal-facilities").json()["data"]
        near = env.client.post(
            "/api/v1/meal-facilities/nearby",
            json={"latitude": 35.85, "longitude": 128.59},
        ).json()["data"]
        assert result["total"] == near["total"] == 0
    else:
        assert (
            env.client.get("/api/v1/seasonal-foods", params={"month": 12}).json()[
                "data"
            ]["total"]
            == 0
        )
        assert env.client.get(public + "/recipes").status_code == 404
    audits = data(env.client.get(f"{BASE}/{kind}/{row.id}/audit", headers=env.headers))[
        "items"
    ]
    assert len(audits) == 6
    assert {event["action"] for event in audits} == {
        "submit",
        "reject",
        "approve",
        "publish",
        "unpublish",
    }
    assert sorted(event["after_state"]["version"] for event in audits) == list(
        range(2, 8)
    )
    assert all(event["actor_id"] == env.user["user_id"] for event in audits)
    assert "다시 확인" not in str(audits) and "확인했습니다" not in str(audits)
    assert env.user["access_token"] not in str(audits)


@pytest.mark.parametrize("kind", KINDS)
def test_changed_source_requires_fresh_review_and_stale_commands_do_not_write(
    admin_db, tmp_path, kind
):
    env = admin_db
    seed(env, tmp_path)
    row = target(env, kind)
    item = detail(env, kind, row)
    for step in ("submit", "approve", "publish"):
        item = data(action(env, kind, item, step))
    if kind == KINDS[0]:
        import_meal_facilities.apply_import(
            env.db,
            import_meal_facilities.prepare_import(
                facility_snapshot(
                    tmp_path,
                    rows=({**NAMGU, "mlsvTime": "변경된 급식시간"},),
                    fetched_at=DAY2,
                )
            ),
        )
    else:
        import_seasonal.apply_import(
            env.db,
            import_seasonal.prepare_import(
                seasonal_snapshot(
                    tmp_path, items=seasonal_items("변경된 원천 글"), fetched_at=DAY2
                )
            ),
        )
    env.db.commit()
    assert row.is_published and row.review_is_published and not review_allows(row)
    assert env.client.get(f"/api/v1/{kind}/{row.id}").status_code == 404
    before = env.db.scalar(select(func.count()).select_from(CatalogAuditEvent))
    stale = action(env, kind, item, "unpublish")
    assert (
        stale.status_code == 409
        and stale.json()["error"]["code"] == "CATALOG_VERSION_CHANGED"
    )
    assert env.db.scalar(select(func.count()).select_from(CatalogAuditEvent)) == before
    fresh = detail(env, kind, row)
    assert fresh["review_required"] and not fresh["is_published"]
    for step in ("submit", "approve", "publish"):
        fresh = data(action(env, kind, fresh, step))
    assert env.client.get(f"/api/v1/{kind}/{row.id}").status_code == 200
    # An older administrator view cannot undo a newer decision, even at the same source.
    assert action(env, kind, item, "unpublish").status_code == 409


def test_admin_search_pagination_escaped_query_and_nonapplicable_month(
    admin_db, tmp_path
):
    env = admin_db
    seed(env, tmp_path)
    page = data(
        env.client.get(
            f"{BASE}/seasonal-foods",
            params={"month": 12, "limit": 1},
            headers=env.headers,
        )
    )
    assert page["total"] == 1 and page["items"][0]["name"] == "시금치"
    assert "content" not in page["items"][0]
    assert (
        data(
            env.client.get(
                f"{BASE}/seasonal-foods", params={"q": "%"}, headers=env.headers
            )
        )["total"]
        == 0
    )
    assert (
        data(
            env.client.get(
                f"{BASE}/seasonal-foods",
                params={"review_status": "review"},
                headers=env.headers,
            )
        )["total"]
        == 0
    )
    assert (
        env.client.get(
            f"{BASE}/meal-facilities", params={"month": 12}, headers=env.headers
        ).status_code
        == 422
    )
    assert env.client.get(f"{BASE}/unknown", headers=env.headers).status_code == 422
    assert (
        env.client.get(
            f"{BASE}/seasonal-foods/{uuid4()}", headers=env.headers
        ).status_code
        == 404
    )


def test_catalog_migration_preserves_visibility_without_inventing_approval(
    admin_db, tmp_path
):
    env = admin_db
    seed(env, tmp_path)
    identity = target(env, KINDS[0]).id
    env.db.commit()
    env.db.expunge_all()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = env.connection
    command.downgrade(config, "20261120_06")
    env.connection.commit()
    command.upgrade(config, "head")
    env.connection.commit()
    command.check(config)
    env.connection.rollback()
    row = env.db.get(MealFacility, identity)
    assert (
        row.is_published and row.review_is_published and row.review_status == "legacy"
    )
    assert (
        row.reviewed_at is None and row.reviewed_by is None and row.review_version == 1
    )
    assert env.db.scalar(select(func.count()).select_from(CatalogAuditEvent)) == 0


def test_audit_failure_rolls_back_publication_decision(admin_db, tmp_path, monkeypatch):
    env = admin_db
    seed(env, tmp_path)
    row = target(env, KINDS[0])
    item = detail(env, KINDS[0], row)
    original_flush = env.db.flush

    def failing_flush(*args, **kwargs):
        if any(isinstance(value, CatalogAuditEvent) for value in env.db.new):
            raise OperationalError(None, None, RuntimeError("private-audit-error"))
        return original_flush(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(env.db, "flush", failing_flush)
        result = action(env, KINDS[0], item, "unpublish")
    assert result.status_code == 503 and "private-audit-error" not in result.text
    assert detail(env, KINDS[0], row)["is_published"]
    assert env.db.scalar(select(func.count()).select_from(CatalogAuditEvent)) == 0


def test_hidden_seasonal_source_is_removed_from_actual_recommendations(
    admin_db, tmp_path, monkeypatch
):
    from app.api import meal

    class DecemberClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 1, tzinfo=UTC).astimezone(tz)

    env = admin_db
    seed(env, tmp_path)
    monkeypatch.setattr(meal, "datetime", DecemberClock)

    def recommended():
        return data(
            env.client.post(
                "/api/v1/meal/recommendations",
                headers=env.headers,
                json={"meal_time": "lunch", "limit": 20},
            )
        )["items"]

    before = recommended()
    assert any(item["seasonal_ingredients"] for item in before)
    row = target(env, KINDS[1])
    assert (
        data(action(env, KINDS[1], detail(env, KINDS[1], row), "unpublish"))[
            "is_published"
        ]
        is False
    )
    after = recommended()
    assert after and all(not item["seasonal_ingredients"] for item in after)


def test_simultaneous_catalog_decisions_have_one_winner(admin_db, tmp_path):
    env = admin_db
    seed(env, tmp_path)
    row = target(env, KINDS[0])
    item = data(action(env, KINDS[0], detail(env, KINDS[0], row), "submit"))
    schema = env.connection.scalar(text("SELECT current_schema()"))
    env.db.commit()
    barrier = Barrier(2)

    def decide(name):
        app = create_app()

        def connection_db():
            with env.connection.engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                connection.commit()
                try:
                    with Session(connection, expire_on_commit=False) as db:
                        yield db
                finally:
                    connection.rollback()
                    connection.execute(text("SET search_path TO public"))
                    connection.commit()

        app.dependency_overrides[get_db] = connection_db
        with TestClient(app) as http:
            barrier.wait(timeout=10)
            return http.post(
                f"{BASE}/{KINDS[0]}/{item['id']}/actions",
                headers=env.headers,
                json={
                    "action": name,
                    "expected_version": item["review_version"],
                    "expected_revision": item["source_revision"],
                    "note": "검수 의견",
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(decide, ("approve", "reject")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    env.db.expire_all()
    assert row.review_version == 3
    assert env.db.scalar(select(func.count()).select_from(CatalogAuditEvent)) == 2
