from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest

from alembic import command
from app.api.admin_guides import _command
from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.core.errors import AppError
from app.main import create_app
from app.models import GuideAuditEvent, LifeGuide, User
from app.schemas.guide_management import GuideCommand

BASE = "/api/v1/admin/life-guides"


def content(**changes):
    body = dict(
        title="앱 시작 안내",
        source_reference="팀 사용 안내",
        checked_on="2026-11-18",
        steps=[
            {"text": "앱을 열어 주세요."},
            {"text": "메뉴를 선택해 주세요.", "title": "선택"},
        ],
    )
    body.update(changes)
    return body


def draft(**changes):
    return {"slug": "getting-started", **content(**changes)}


def data(response, expected=200):
    assert response.status_code == expected, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data"]


@pytest.fixture
def admin_db(pg_connection, client):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        user, headers = guest(client)
        db.get(User, UUID(user["user_id"])).role = "admin"
        db.commit()
        yield SimpleNamespace(
            client=client, db=db, headers=headers, user=user, connection=pg_connection
        )


def create(env, **changes):
    return data(env.client.post(BASE, json=draft(**changes), headers=env.headers), 201)


def action(env, guide, name, **extra):
    return env.client.post(
        f"{BASE}/{guide['id']}/actions",
        headers=env.headers,
        json={"expected_version": guide["version"], "action": name, **extra},
    )


def published(env):
    guide = create(env)
    for name in ("submit", "approve", "publish"):
        guide = data(action(env, guide, name))
    return guide


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "", None),
        ("POST", "", draft()),
        ("GET", f"/{uuid4()}", None),
        ("PUT", f"/{uuid4()}", {"expected_version": 1, **content()}),
        ("POST", f"/{uuid4()}/actions", {"expected_version": 1, "action": "submit"}),
        ("GET", f"/{uuid4()}/audit", None),
    ],
)
def test_all_admin_guide_routes_require_server_role(client, method, path, body):
    db = Mock()
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.request(method, BASE + path, json=body)
    assert response.status_code == 401
    auth = AuthContext(
        user=SimpleNamespace(id=uuid4(), role="user"), session=SimpleNamespace()
    )
    client.app.dependency_overrides[current_auth] = lambda: auth
    response = client.request(method, BASE + path, json=body)
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    db.scalar.assert_not_called()
    db.commit.assert_not_called()


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
        {"title": "  "},
        {"title": "x" * 201},
        {"source_reference": " "},
        {"steps": []},
        {"steps": [{"text": "  "}]},
        {"steps": [{"text": "x", "html": "unsafe"}]},
        {"steps": [{"text": "x" * 3001}]},
        {"steps": [{"text": "x"}] * 31},
        {"is_published": True},
        {"review_status": "approved"},
        {"slug": "../unsafe"},
        {"slug": "UPPER"},
        {"checked_on": (datetime.now(UTC) + timedelta(days=2)).date().isoformat()},
    ],
)
def test_draft_validation_cannot_smuggle_publication_or_empty_content(
    mocked_admin, changes
):
    client, db = mocked_admin
    response = client.post(BASE, json={**draft(), **changes})
    assert response.status_code == 422, response.text
    assert response.headers["Cache-Control"] == "no-store"
    db.add.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": True, "action": "submit"},
        {"expected_version": 0, "action": "submit"},
        {"expected_version": "1", "action": "submit"},
        {"expected_version": 1, "action": "delete"},
        {"expected_version": 1, "action": "reject"},
        {"expected_version": 1, "action": "reject", "note": " "},
        {"expected_version": 1, "action": "publish", "note": "ignored"},
    ],
)
def test_commands_validate_expected_version_and_rejection_reason(mocked_admin, body):
    client, db = mocked_admin
    assert client.post(f"{BASE}/{uuid4()}/actions", json=body).status_code == 422
    db.scalar.assert_not_called()


def test_sql_failure_rolls_back_and_does_not_return_secrets(mocked_admin):
    client, db = mocked_admin
    db.flush.side_effect = OperationalError(
        None, None, RuntimeError("private-connection-details")
    )
    response = client.post(BASE, json=draft())
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-connection-details" not in response.text
    db.rollback.assert_called_once()


@pytest.mark.parametrize(
    "status,published_flag,name",
    [
        ("draft", False, "approve"),
        ("draft", False, "reject"),
        ("draft", False, "publish"),
        ("draft", False, "unpublish"),
        ("review", False, "submit"),
        ("review", False, "publish"),
        ("approved", False, "approve"),
        ("approved", False, "reject"),
        ("approved", True, "submit"),
        ("approved", True, "approve"),
        ("approved", True, "reject"),
        ("approved", True, "publish"),
        ("rejected", False, "approve"),
        ("rejected", False, "publish"),
    ],
)
def test_invalid_review_transitions_do_not_mutate_the_guide(
    status, published_flag, name
):
    row = LifeGuide(
        **draft(), version=7, review_status=status, is_published=published_flag
    )
    body = GuideCommand(
        expected_version=7, action=name, note="검수 의견" if name == "reject" else None
    )
    with pytest.raises(AppError) as caught:
        _command(row, body, uuid4(), datetime.now(UTC))
    assert caught.value.status_code == 409
    assert (
        row.version == 7
        and row.review_status == status
        and row.is_published == published_flag
    )


def test_missing_guide_is_404_and_corrupted_old_content_cannot_be_published(
    mocked_admin,
):
    client, db = mocked_admin
    db.scalar.return_value = None
    missing = client.get(f"{BASE}/{uuid4()}")
    assert missing.status_code == 404
    row = LifeGuide(
        **draft(steps=[]), version=1, review_status="draft", is_published=False
    )
    with pytest.raises(AppError) as caught:
        _command(
            row,
            GuideCommand(expected_version=1, action="submit"),
            uuid4(),
            datetime.now(UTC),
        )
    assert caught.value.code == "GUIDE_CONTENT_INVALID"
    assert row.review_status == "draft" and row.version == 1


def test_guide_review_publish_edit_and_audit_are_one_workflow(admin_db):
    env = admin_db
    guide = create(env)
    path = f"{BASE}/{guide['id']}"
    public = "/api/v1/life-guides/getting-started"
    assert guide["review_status"] == "draft" and guide["version"] == 1
    assert env.client.get(public).status_code == 404
    assert action(env, guide, "publish").status_code == 409
    guide = data(action(env, guide, "submit"))
    guide = data(action(env, guide, "reject", note="확인일 근거를 확인해 주세요"))
    assert (
        guide["review_status"] == "rejected"
        and guide["reviewed_by"] == env.user["user_id"]
    )
    assert env.client.get(public).status_code == 404
    guide = data(action(env, guide, "submit"))
    assert guide["review_note"] is None and guide["reviewed_at"] is None
    guide = data(action(env, guide, "approve", note="검수 완료"))
    assert env.client.get(public).status_code == 404  # Approval alone never publishes.
    guide = data(action(env, guide, "publish"))
    public_data = env.client.get(public).json()["data"]
    assert public_data["steps"][0]["text"] == "앱을 열어 주세요."
    assert not ({"review_note", "reviewed_by", "version"} & public_data.keys())
    guide = data(
        env.client.put(
            path,
            headers=env.headers,
            json={
                "expected_version": guide["version"],
                **content(title="수정된 가이드"),
            },
        )
    )
    assert guide["review_status"] == "draft" and not guide["is_published"]
    assert guide["review_note"] is None and guide["reviewed_by"] is None
    assert env.client.get(public).status_code == 404
    audits = data(env.client.get(path + "/audit", headers=env.headers))["items"]
    assert {row["action"] for row in audits} == {
        "create",
        "submit",
        "reject",
        "approve",
        "publish",
        "edit",
    }
    assert len(audits) == 7
    assert sorted(row["after_state"]["version"] for row in audits) == list(range(1, 8))
    assert all(row["actor_id"] == env.user["user_id"] for row in audits)
    assert all(
        set(row["after_state"]) == {"version", "review_status", "is_published"}
        for row in audits
    )
    assert all(UUID(row["request_id"]) for row in audits)
    assert "확인일 근거" not in str(audits) and "검수 완료" not in str(audits)
    assert env.user["access_token"] not in str(audits)


def test_stale_content_and_review_commands_never_overwrite_newer_work(admin_db):
    env = admin_db
    guide = create(env)
    old_version = guide["version"]
    path = f"{BASE}/{guide['id']}"
    guide = data(
        env.client.put(
            path,
            headers=env.headers,
            json={"expected_version": old_version, **content(title="새 내용")},
        )
    )
    for response in [
        env.client.put(
            path,
            headers=env.headers,
            json={"expected_version": old_version, **content(title="오래된 화면")},
        ),
        env.client.post(
            path + "/actions",
            headers=env.headers,
            json={"expected_version": old_version, "action": "submit"},
        ),
    ]:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "GUIDE_VERSION_CHANGED"
    current = data(env.client.get(path, headers=env.headers))
    assert current["title"] == "새 내용" and current["version"] == guide["version"]
    assert env.db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 2


def test_slug_is_unique_immutable_and_unpublish_preserves_content(admin_db):
    env = admin_db
    guide = published(env)
    duplicate = env.client.post(
        BASE, headers=env.headers, json=draft(title="다른 안내")
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "GUIDE_SLUG_EXISTS"
    path = f"{BASE}/{guide['id']}"
    assert (
        env.client.put(
            path,
            headers=env.headers,
            json={"expected_version": guide["version"], **draft()},
        ).status_code
        == 422
    )
    guide = data(action(env, guide, "unpublish"))
    assert guide["review_status"] == "approved" and not guide["is_published"]
    assert env.client.get("/api/v1/life-guides/getting-started").status_code == 404
    guide = data(action(env, guide, "publish"))
    assert guide["is_published"]
    assert env.client.get("/api/v1/life-guides/getting-started").status_code == 200


def test_admin_queries_filter_and_page_without_exposing_draft_steps(admin_db):
    env = admin_db
    create(env, title="검토 100%")
    other = data(
        env.client.post(
            BASE,
            headers=env.headers,
            json={**draft(title="다른 문서"), "slug": "other"},
        ),
        201,
    )
    data(action(env, other, "submit"))
    page = data(
        env.client.get(BASE, headers=env.headers, params={"q": "%", "limit": 1})
    )
    assert page["total"] == 1 and page["items"][0]["title"] == "검토 100%"
    assert "steps" not in page["items"][0] and "review_note" not in page["items"][0]
    page = data(
        env.client.get(BASE, headers=env.headers, params={"review_status": "review"})
    )
    assert page["total"] == 1 and page["items"][0]["id"] == other["id"]
    assert (
        data(env.client.get(BASE, headers=env.headers, params={"is_published": True}))[
            "total"
        ]
        == 0
    )


def test_audit_failure_cannot_leave_a_created_or_changed_guide(admin_db, monkeypatch):
    env = admin_db
    original_flush = env.db.flush

    def fail_audit(*args, **kwargs):
        if any(isinstance(row, GuideAuditEvent) for row in env.db.new):
            raise OperationalError(None, None, RuntimeError("private-audit-failure"))
        return original_flush(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(env.db, "flush", fail_audit)
        response = env.client.post(BASE, headers=env.headers, json=draft())
    assert response.status_code == 503
    assert "private-audit-failure" not in response.text
    assert env.db.scalar(select(func.count()).select_from(LifeGuide)) == 0
    assert env.db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 0
    guide = create(env)
    with monkeypatch.context() as patch:
        patch.setattr(env.db, "flush", fail_audit)
        response = action(env, guide, "submit")
    assert response.status_code == 503
    current = data(env.client.get(f"{BASE}/{guide['id']}", headers=env.headers))
    assert current["version"] == 1 and current["review_status"] == "draft"
    assert env.db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 1


def test_audit_retains_events_when_actor_removed_and_missing_target_is_safe(admin_db):
    env = admin_db
    guide = published(env)
    env.db.delete(env.db.get(User, UUID(env.user["user_id"])))
    env.db.commit()
    env.db.expire_all()
    assert env.db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 4
    assert all(row.actor_id is None for row in env.db.scalars(select(GuideAuditEvent)))
    stored = env.db.get(LifeGuide, UUID(guide["id"]))
    assert stored.is_published and stored.reviewed_by is None
    assert (
        env.client.get(f"{BASE}/{guide['id']}", headers=env.headers).status_code == 401
    )


def test_losing_admin_role_immediately_blocks_new_operations(admin_db):
    env = admin_db
    guide = create(env)
    env.db.get(User, UUID(env.user["user_id"])).role = "user"
    env.db.commit()
    assert action(env, guide, "submit").status_code == 403
    assert env.db.get(LifeGuide, UUID(guide["id"])).version == 1


def test_review_migration_preserves_existing_public_guides(pg_connection):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    command.downgrade(config, "20261120_02")
    pg_connection.commit()
    ids = [uuid4(), uuid4()]
    for guide_id, published_flag in zip(ids, (True, False), strict=True):
        pg_connection.execute(
            text(
                "INSERT INTO life_guides (id, slug, title, steps, source_reference, checked_on, is_published) VALUES (:id, :slug, 'legacy', '[{\"text\":\"first\"}]'::jsonb, 'manual', '2026-11-18', :published)"
            ),
            {"id": guide_id, "slug": str(guide_id), "published": published_flag},
        )
    pg_connection.commit()
    command.upgrade(config, "head")
    pg_connection.commit()
    command.check(config)
    pg_connection.rollback()
    with Session(pg_connection) as db:
        public, draft_row = (db.get(LifeGuide, key) for key in ids)
        assert (
            public.is_published
            and public.review_status == "approved"
            and public.version == 1
        )
        assert public.reviewed_by is None and public.reviewed_at is None
        assert not draft_row.is_published and draft_row.review_status == "draft"
        assert db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 0


def test_concurrent_review_decisions_have_one_winner_and_one_audit(admin_db):
    env = admin_db
    guide = data(action(env, create(env), "submit"))
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
                f"{BASE}/{guide['id']}/actions",
                headers=env.headers,
                json={
                    "action": name,
                    "expected_version": guide["version"],
                    "note": "review result",
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(decide, ("approve", "reject")))
    assert sorted(row.status_code for row in responses) == [200, 409]
    env.db.expire_all()
    assert env.db.get(LifeGuide, UUID(guide["id"])).version == 3
    assert env.db.scalar(select(func.count()).select_from(GuideAuditEvent)) == 3
