from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_auth import auth_db, guest  # noqa: F401

from app.api import usage
from app.models import AuthSession, UsageEvent, User

BASE = "/api/v1/usage-events"
ADMIN = "/api/v1/admin/usage-events"


@pytest.fixture
def usage_db(request):
    return request.getfixturevalue("auth_db")


def event(**changes):
    return {
        "event_id": str(uuid4()),
        "event": "request_finished",
        "feature": "meal",
        "action": "recommend",
        "outcome": "success",
        "app_version": "0.1.0",
        "platform": "android",
        "duration_ms": 120,
        **changes,
    }


def body(*items):
    return {"consent_version": "usage-v1", "events": list(items)}


def admin(client, db):
    account, headers = guest(client)
    db.get(User, UUID(account["user_id"])).role = "admin"
    db.commit()
    return headers


def test_authentication_roles_and_revocation(usage_db):
    client, db = usage_db
    assert client.post(BASE, json=body(event())).status_code == 401
    _, user = guest(client)
    assert client.get(ADMIN, headers=user).status_code == 403
    assert client.post(ADMIN + "/prune", headers=user).status_code == 403
    headers = admin(client, db)
    assert client.get(ADMIN, headers=headers).status_code == 200
    client.delete("/api/v1/auth/session", headers=headers)
    assert client.get(ADMIN, headers=headers).status_code == 401
    assert client.post(BASE, headers=headers, json=body(event())).status_code == 401


def test_deduplication_and_no_identity_or_payload_in_admin_output(usage_db):
    client, db = usage_db
    identity, headers = guest(client)
    one = event(request_id=str(uuid4()))
    first = client.post(BASE, headers=headers, json=body(one, one))
    assert first.status_code == 200 and first.json()["data"]["accepted"] == 1
    assert (
        client.post(BASE, headers=headers, json=body(one)).json()["data"]["accepted"]
        == 0
    )
    _, other = guest(client)
    assert (
        client.post(BASE, headers=other, json=body(one)).json()["data"]["accepted"] == 1
    )
    response = client.get(ADMIN, headers=admin(client, db))
    assert (
        response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    )
    page = response.json()["data"]
    assert page["total"] == 2 and len(page["items"]) == 2
    assert page["features"][0]["requests"] == 2
    assert page["features"][0]["avg_ms"] == 120
    for item in page["items"]:
        assert set(item) == {
            "event_id",
            "created_at",
            "event",
            "feature",
            "action",
            "outcome",
            "app_version",
            "platform",
            "duration_ms",
            "error_kind",
            "request_id",
            "result_count",
            "result_kind",
            "setting_kind",
            "setting_value",
        }
    stored = list(db.scalars(select(UsageEvent)))
    auth_ids = {str(s.id) for s in db.scalars(select(AuthSession))}
    assert all(
        len(row.collector_key) == 64 and row.collector_key not in auth_ids
        for row in stored
    )
    assert identity["access_token"] not in repr(page) and identity[
        "user_id"
    ] not in repr(page)


@pytest.mark.parametrize(
    "changes",
    [
        {"message": "private question"},
        {"photo": "private image"},
        {"health": "private condition"},
        {"feature": "private condition"},
        {"error_kind": "raw exception with secret"},
        {"app_version": "token=private"},
        {"duration_ms": -1},
        {"duration_ms": True},
        {"request_id": "private account"},
        {"result_kind": "private answer"},
        {"event": "arbitrary event"},
        {"outcome": "started"},
        {"event": "request_started", "outcome": "success"},
        {"setting_kind": "voice", "setting_value": "enabled"},
        {
            "event": "setting_changed",
            "setting_kind": "text_size",
            "setting_value": "enabled",
        },
    ],
)
def test_rejects_free_text_and_inconsistent_fields_without_persisting(
    usage_db, changes
):
    client, db = usage_db
    _, headers = guest(client)
    response = client.post(BASE, headers=headers, json=body(event(**changes)))
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 0
    assert "private" not in response.text


def test_consent_batch_and_streamed_body_limits(usage_db):
    client, _ = usage_db
    _, headers = guest(client)
    assert (
        client.post(BASE, headers=headers, json={"events": [event()]}).status_code
        == 422
    )
    assert client.post(BASE, headers=headers, json=body()).status_code == 422
    assert (
        client.post(
            BASE, headers=headers, json=body(*[event() for _ in range(21)])
        ).status_code
        == 422
    )
    response = client.post(
        BASE,
        headers={**headers, "Content-Type": "application/json"},
        content=iter([b" " * 20000, b" " * 20000]),
    )
    assert (
        response.status_code == 413
        and response.json()["error"]["code"] == "USAGE_BODY_TOO_LARGE"
    )


def test_counts_filters_pagination_and_weighted_duration(usage_db):
    client, db = usage_db
    _, headers = guest(client)
    a = event()
    assert (
        client.post(
            BASE,
            headers=headers,
            json=body(
                a,
                event(duration_ms=280),
                event(outcome="failure", error_kind="timeout", duration_ms=800),
                event(event="request_started", outcome="started", duration_ms=None),
                event(
                    feature="shorts",
                    event="video_open",
                    action="open",
                    duration_ms=None,
                ),
            ),
        ).status_code
        == 200
    )
    auth = admin(client, db)
    page = client.get(ADMIN + "?feature=meal&limit=2", headers=auth).json()["data"]
    assert page["total"] == 4 and len(page["items"]) == 2
    stats = page["features"][0]
    assert (stats["requests"], stats["success"], stats["failure"], stats["avg_ms"]) == (
        3,
        2,
        1,
        400,
    )
    assert sum(day["count"] for day in page["daily"]) == 4
    failed = client.get(ADMIN + "?outcome=failure", headers=auth).json()["data"]
    assert failed["total"] == 1 and failed["items"][0]["error_kind"] == "timeout"
    assert client.get(ADMIN + "?offset=5", headers=auth).json()["data"]["items"] == []
    assert client.get(ADMIN + "?days=31", headers=auth).status_code == 422
    assert client.get(ADMIN + "?feature=private", headers=auth).status_code == 422


def test_rate_limit_is_atomic_per_auth_session_and_replay_is_safe(
    usage_db, monkeypatch
):
    client, db = usage_db
    monkeypatch.setattr(usage, "DAILY_LIMIT", 2)
    _, headers = guest(client)
    items = [event(), event()]
    assert (
        client.post(BASE, headers=headers, json=body(*items)).json()["data"]["accepted"]
        == 2
    )
    assert (
        client.post(BASE, headers=headers, json=body(*items)).json()["data"]["accepted"]
        == 0
    )
    response = client.post(BASE, headers=headers, json=body(event()))
    assert response.status_code == 429 and response.headers["Retry-After"] == "3600"
    _, other = guest(client)
    assert client.post(BASE, headers=other, json=body(event())).status_code == 200
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 3


def test_retention_only_removes_expired_usage_rows(usage_db):
    client, db = usage_db
    identity, headers = guest(client)
    item = event()
    client.post(BASE, headers=headers, json=body(item))
    stored = db.scalar(select(UsageEvent))
    stored.created_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()
    auth = admin(client, db)
    assert client.get(ADMIN, headers=auth).json()["data"]["total"] == 0
    assert client.post(ADMIN + "/prune", headers=auth).json()["data"]["removed"] == 1
    assert db.get(User, UUID(identity["user_id"])) is not None
    client.post(BASE, headers=headers, json=body(event()))
    assert client.post(ADMIN + "/prune", headers=auth).json()["data"]["removed"] == 0


def test_operational_request_log_is_correlatable_without_raw_path_or_query(
    client, caplog
):
    import logging

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = client.get("/private-person-name?health=secret-health")
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] in caplog.text
    assert "route=unmatched status=404" in caplog.text
    assert "secret-health" not in caplog.text
    assert "private-person-name" not in caplog.text


# Value: protects=quota across independent concurrent requests;
# fails_when=concurrent collectors exceed the session quota;
# why_new=the existing quota test is sequential; seam=none;
# no_claim=distributed production load.
def test_concurrent_collectors_enforce_session_quota(
    usage_db, pg_connection, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.core.database import get_db
    from app.main import create_app

    client, db = usage_db
    _, headers = guest(client)
    monkeypatch.setattr(usage, "DAILY_LIMIT", 1)
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    ready = Barrier(2)

    def attempt(_):
        app = create_app()

        def request_db():
            with pg_connection.engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                connection.commit()
                try:
                    with Session(bind=connection, expire_on_commit=False) as session:
                        yield session
                finally:
                    connection.rollback()
                    connection.execute(text("SET search_path TO public"))
                    connection.commit()

        app.dependency_overrides[get_db] = request_db
        with TestClient(app) as concurrent_client:
            ready.wait(timeout=10)
            return concurrent_client.post(BASE, headers=headers, json=body(event()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 429]
    rejected = next(response for response in responses if response.status_code == 429)
    assert rejected.headers["Retry-After"] == "3600"
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1


# Value: protects=rollback and safe retryable responses during usage DB failure;
# fails_when=failed commits leave rows or expose DB details;
# why_new=existing usage tests never fail a transaction; seam=none;
# no_claim=physical database outage recovery.
def test_usage_commit_outages_rollback_collect_dashboard_and_prune(
    usage_db, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    client, db = usage_db
    _, headers = guest(client)
    auth = admin(client, db)
    client.post(BASE, headers=headers, json=body(event()))
    stored = db.scalar(select(UsageEvent))
    stored.created_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()
    rollback = db.rollback
    rolled_back = []

    def fail_commit():
        raise OperationalError("COMMIT", {}, Exception("private-db-detail"))

    def track_rollback():
        rolled_back.append(True)
        rollback()

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        patch.setattr(db, "rollback", track_rollback)
        responses = [
            client.post(BASE, headers=headers, json=body(event())),
            client.get(ADMIN, headers=auth),
            client.post(ADMIN + "/prune", headers=auth),
        ]
    assert len(rolled_back) == 3
    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "USAGE_UNAVAILABLE"
        assert response.json()["error"]["retryable"] is True
        assert response.headers["Cache-Control"] == "no-store"
        assert "private-db-detail" not in response.text
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1
    assert client.get(ADMIN, headers=auth).status_code == 200


# Value: protects=Korean calendar date filters and day buckets;
# fails_when=UTC dates or exclusive midnight bounds replace the Korean day.
def test_usage_dates_include_korean_midnight_and_exclude_previous_day(
    usage_db, monkeypatch
):
    client, db = usage_db
    _, headers = guest(client)
    first, second = event(), event()
    client.post(BASE, headers=headers, json=body(first, second))
    rows = {str(row.event_id): row for row in db.scalars(select(UsageEvent))}
    rows[first["event_id"]].created_at = datetime(2026, 11, 25, 14, 59, 59, tzinfo=UTC)
    rows[second["event_id"]].created_at = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
    db.commit()
    auth = admin(client, db)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 25, 15, 30, tzinfo=UTC)

    monkeypatch.setattr(usage, "datetime", Clock)
    today = client.get(ADMIN + "?days=1", headers=auth).json()["data"]
    assert today["total"] == 1
    assert today["items"][0]["event_id"] == second["event_id"]
    assert today["daily"] == [{"day": "2026-11-26", "count": 1}]
    two_days = client.get(ADMIN + "?days=2", headers=auth).json()["data"]
    assert two_days["total"] == 2
    assert two_days["daily"] == [
        {"day": "2026-11-25", "count": 1},
        {"day": "2026-11-26", "count": 1},
    ]


# Value: protects=the scheduled CLI actually commits expiry cleanup, not just plan wiring.
def test_usage_cleanup_command_commits_only_expired_rows(
    usage_db, pg_connection, monkeypatch, capsys
):
    import json

    from app.jobs import prune_usage_events

    client, db = usage_db
    _, headers = guest(client)
    client.post(BASE, headers=headers, json=body(event(), event()))
    rows = list(db.scalars(select(UsageEvent)))
    rows[0].created_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()
    monkeypatch.setattr(prune_usage_events, "engine", pg_connection)
    assert prune_usage_events.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"removed": 1, "retention_days": 30}
    assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1
