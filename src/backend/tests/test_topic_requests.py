import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_auth import guest

from alembic import command
from app.api import topic_requests
from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.main import create_app
from app.models import ContentTopicRequest, LifeGuide, Profile, TopicRequestAudit, User
from app.schemas.topic_requests import TopicCreate, TopicReview

BASE = "/api/v1/content-topic-requests"
ADMIN = "/api/v1/admin/content-topic-requests"


def proposal(**changes):
    return {
        "submission_id": str(uuid4()),
        "kind": "life_guide",
        "topic": "전화 글씨 크게 보기",
        **changes,
    }


def data(response, expected=200):
    assert response.status_code == expected, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    if expected >= 400:
        assert body["error"]["code"]
        return body["error"]
    return body["data"]


@pytest.mark.parametrize(
    "changes",
    [
        {"topic": ""},
        {"topic": " "},
        {"topic": "가" * 61},
        {"topic": "가\n나"},
        {"topic": "가\x00나"},
        {"topic": "\ud800"},
        {"kind": "unknown"},
        {"submission_id": "bad"},
        {"submission_id": "00000000-0000-0000-0000-000000000000"},
        {"status": "completed"},
        {"user_id": str(uuid4())},
    ],
)
def test_create_contract_rejects_invalid_or_authority_fields(changes):
    with pytest.raises(ValidationError):
        TopicCreate.model_validate(proposal(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "completed"},
        {"status": "declined", "reply": " "},
        {"status": "received"},
        {"expected_version": True},
        {"expected_version": 0},
        {"status": "reviewing", "guide_id": str(uuid4())},
        {"reply": "가" * 1001},
        {"reply": "\x00"},
        {"reply": "\ud800"},
    ],
)
def test_review_contract_rejects_incomplete_decisions(changes):
    with pytest.raises(ValidationError):
        TopicReview.model_validate(
            {"expected_version": 1, "status": "reviewing", **changes}
        )


def test_fingerprint_ignores_submission_id_but_preserves_kind_and_normalized_topic():
    first = TopicCreate.model_validate(proposal(topic="  전화 글씨 크게 보기  "))
    second = TopicCreate.model_validate(proposal())
    assert first.submission_id != second.submission_id
    assert topic_requests._fingerprint(first) == topic_requests._fingerprint(second)
    third = TopicCreate.model_validate(proposal(kind="video"))
    assert topic_requests._fingerprint(first) != topic_requests._fingerprint(third)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", BASE, proposal()),
        ("GET", BASE, None),
        ("GET", f"{BASE}/{uuid4()}", None),
        ("DELETE", f"{BASE}/{uuid4()}", None),
        ("GET", ADMIN, None),
        ("GET", f"{ADMIN}/{uuid4()}", None),
        ("PUT", f"{ADMIN}/{uuid4()}", {"expected_version": 1, "status": "reviewing"}),
        ("GET", f"{ADMIN}/{uuid4()}/audit", None),
    ],
)
def test_all_routes_require_auth_and_never_cache_private_responses(
    client, method, path, body
):
    data(client.request(method, path, json=body), 401)


@pytest.mark.parametrize("path", [BASE, ADMIN])
def test_database_failure_has_no_proposal_or_connection_details(client, path):
    identity = SimpleNamespace(id=uuid4(), role="admin")
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        identity, SimpleNamespace()
    )
    db = Mock()
    db.scalar.side_effect = OperationalError(
        None, None, RuntimeError("private-connection-detail")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.get(path)
    data(response, 503)
    assert response.json()["error"]["retryable"] is True
    assert "private-connection-detail" not in response.text


def test_http_validation_does_not_echo_a_private_proposal(client):
    identity = SimpleNamespace(id=uuid4(), role="user")
    client.app.dependency_overrides[current_auth] = lambda: AuthContext(
        identity, SimpleNamespace()
    )
    db = Mock()
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.post(BASE, json=proposal(topic="private-proposal-marker\x00"))
    data(response, 422)
    assert "private-proposal-marker" not in response.text
    db.scalar.assert_not_called()


@pytest.fixture
def env(pg_connection, client):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        owner, own_headers = guest(client)
        other, other_headers = guest(client)
        moderator, admin_headers = guest(client)
        db.get(User, UUID(moderator["user_id"])).role = "admin"
        db.commit()
        yield SimpleNamespace(
            client=client,
            db=db,
            connection=pg_connection,
            owner=UUID(owner["user_id"]),
            other=UUID(other["user_id"]),
            moderator=UUID(moderator["user_id"]),
            own=own_headers,
            other_headers=other_headers,
            admin=admin_headers,
        )


def create(env, **changes):
    return data(env.client.post(BASE, json=proposal(**changes), headers=env.own), 201)[
        "request"
    ]


def review(env, row, **changes):
    return env.client.put(
        f"{ADMIN}/{row['id']}",
        headers=env.admin,
        json={"expected_version": row["version"], "status": "reviewing", **changes},
    )


def published_guide(env, *, published=True):
    row = LifeGuide(
        slug=f"guide-{uuid4().hex}",
        title="검수한 글씨 설정 안내",
        steps=[{"text": "설정을 열어요."}],
        source_reference="팀 검수 자료",
        checked_on=date(2026, 11, 19),
        is_published=published,
        review_status="approved" if published else "draft",
    )
    env.db.add(row)
    env.db.commit()
    return row


def test_submit_owner_isolation_filters_and_admin_access(env):
    first = create(env)
    second = create(env, kind="video", topic="가을 산책")
    assert first["status"] == "received" and first["version"] == 1
    assert (
        not {"user_id", "reviewed_by", "fingerprint", "submission_id", "guide_id"}
        & first.keys()
    )
    assert data(env.client.get(BASE, headers=env.other_headers))["items"] == []
    for method in ("GET", "DELETE"):
        data(
            env.client.request(
                method, f"{BASE}/{first['id']}", headers=env.other_headers
            ),
            404,
        )
    data(env.client.get(ADMIN, headers=env.own), 403)
    page = data(
        env.client.get(
            BASE, headers=env.own, params={"kind": "video", "q": "산책", "limit": 1}
        )
    )
    assert page["total"] == 1 and page["items"][0]["id"] == second["id"]
    assert data(env.client.get(BASE, headers=env.own, params={"q": "%"}))["total"] == 0
    queue = data(env.client.get(ADMIN, headers=env.admin))
    assert queue["total"] == 2 and all("user_id" not in item for item in queue["items"])
    assert (
        data(env.client.get(BASE, headers=env.own, params={"offset": 2}))["items"] == []
    )


def test_retries_are_idempotent_and_cannot_change_payload_or_restore_withdrawal(env):
    body = proposal()
    first = data(env.client.post(BASE, headers=env.own, json=body), 201)
    again = data(env.client.post(BASE, headers=env.own, json=body))
    assert first["replayed"] is False and again["replayed"] is True
    assert first["request"] == again["request"]
    data(
        env.client.post(BASE, headers=env.own, json={**body, "topic": "다른 내용"}), 409
    )
    data(env.client.post(BASE, headers=env.own, json={**body, "kind": "video"}), 409)
    row = first["request"]
    cancelled = data(env.client.delete(f"{BASE}/{row['id']}", headers=env.own))
    replayed = data(env.client.post(BASE, headers=env.own, json=body))
    assert replayed["request"] == cancelled and cancelled["status"] == "withdrawn"
    assert (
        cancelled["topic"] is None
        and cancelled["reply"] is None
        and cancelled["guide"] is None
    )
    assert data(env.client.delete(f"{BASE}/{row['id']}", headers=env.own)) == cancelled
    assert env.db.scalar(select(func.count()).select_from(ContentTopicRequest)) == 1
    assert env.db.scalar(select(func.count()).select_from(TopicRequestAudit)) == 2
    data(env.client.get(f"{ADMIN}/{row['id']}", headers=env.admin), 404)
    data(env.client.get(f"{ADMIN}/{row['id']}/audit", headers=env.admin), 404)
    assert data(env.client.get(ADMIN, headers=env.admin))["total"] == 0
    stored = env.db.get(ContentTopicRequest, UUID(row["id"]))
    assert stored.topic is None and stored.reply is None


def test_the_same_submission_uuid_is_isolated_between_owners(env):
    body = proposal()
    first = data(env.client.post(BASE, headers=env.own, json=body), 201)
    second = data(env.client.post(BASE, headers=env.other_headers, json=body), 201)
    assert first["request"]["id"] != second["request"]["id"]
    assert first["replayed"] is False and second["replayed"] is False
    own = data(env.client.get(BASE, headers=env.own))["items"]
    other = data(env.client.get(BASE, headers=env.other_headers))["items"]
    assert [item["id"] for item in own] == [first["request"]["id"]]
    assert [item["id"] for item in other] == [second["request"]["id"]]


def test_rolling_quota_counts_withdrawn_requests_but_not_replays(env):
    body = proposal()
    first = data(env.client.post(BASE, headers=env.own, json=body), 201)["request"]
    for _ in range(4):
        create(env)
    response = env.client.post(BASE, headers=env.own, json=proposal())
    data(response, 429)
    assert 0 < int(response.headers["Retry-After"]) <= 86400
    data(env.client.delete(f"{BASE}/{first['id']}", headers=env.own))
    data(env.client.post(BASE, headers=env.own, json=proposal()), 429)
    assert data(env.client.post(BASE, headers=env.own, json=body))["replayed"] is True
    for row in env.db.scalars(select(ContentTopicRequest)):
        row.created_at -= timedelta(days=2)
    env.db.commit()
    create(env)


def test_review_reply_version_and_published_link_are_visible_to_only_the_owner(env):
    row = create(env)
    guide = published_guide(env)
    progressed = data(review(env, row))
    assert progressed["status"] == "reviewing" and progressed["version"] == 2
    data(review(env, row), 409)
    done = data(
        review(
            env,
            progressed,
            status="completed",
            reply="가이드를 확인해 주세요.",
            guide_id=str(guide.id),
        )
    )
    own = data(env.client.get(f"{BASE}/{row['id']}", headers=env.own))
    assert own["guide"]["slug"] == guide.slug and own["reply"] == done["reply"]
    audit = data(env.client.get(f"{ADMIN}/{row['id']}/audit", headers=env.admin))
    assert audit["total"] == 3
    assert all(
        set(item["after_state"]) == {"status", "version", "guide_id"}
        for item in audit["items"]
    )
    assert row["topic"] not in json.dumps(audit, ensure_ascii=False) and done[
        "reply"
    ] not in json.dumps(audit, ensure_ascii=False)
    guide.is_published = False
    env.db.commit()
    own = data(env.client.get(f"{BASE}/{row['id']}", headers=env.own))
    assert own["guide"] is None and "guide_id" not in own
    assert data(env.client.get(f"{ADMIN}/{row['id']}", headers=env.admin))[
        "guide_id"
    ] == str(guide.id)
    data(review(env, done, status="declined", reply="다른 결정"), 409)
    reopened = data(review(env, done))
    assert (
        reopened["status"] == "reviewing"
        and reopened["reply"] is None
        and reopened["guide_id"] is None
    )


def test_draft_missing_or_wrong_kind_guide_cannot_be_linked(env):
    row = create(env)
    data(review(env, row, status="completed", reply="완료 안내"), 422)
    draft = published_guide(env, published=False)
    for guide_id in (str(draft.id), str(uuid4())):
        data(
            review(
                env, row, status="completed", reply="준비했습니다.", guide_id=guide_id
            ),
            409,
        )
    guide = published_guide(env)
    video = create(env, kind="video")
    data(
        review(
            env,
            video,
            status="completed",
            reply="준비했습니다.",
            guide_id=str(guide.id),
        ),
        422,
    )
    done = data(
        review(
            env,
            video,
            status="completed",
            reply="주신 의견을 영상 주제에 반영했습니다.",
        )
    )
    assert done["guide"] is None


def test_audit_failure_rolls_back_creation_review_and_withdrawal(env, monkeypatch):
    row = create(env)
    before_count = env.db.scalar(select(func.count()).select_from(ContentTopicRequest))
    failure = OperationalError(None, None, RuntimeError("private-connection-detail"))
    monkeypatch.setattr(topic_requests, "_audit", Mock(side_effect=failure))
    for method, path, body in [
        ("POST", BASE, proposal()),
        ("PUT", f"{ADMIN}/{row['id']}", {"expected_version": 1, "status": "reviewing"}),
        ("DELETE", f"{BASE}/{row['id']}", None),
    ]:
        response = env.client.request(
            method, path, headers=env.admin if method == "PUT" else env.own, json=body
        )
        data(response, 503)
        assert "private-connection-detail" not in response.text
    env.db.expire_all()
    assert (
        env.db.scalar(select(func.count()).select_from(ContentTopicRequest))
        == before_count
    )
    stored = env.db.get(ContentTopicRequest, UUID(row["id"]))
    assert (
        stored.version == 1
        and stored.status == "received"
        and stored.topic == row["topic"]
    )


def test_deleting_moderator_preserves_requests_but_deleting_owner_cascades(env):
    row = create(env)
    data(
        review(env, row, status="declined", reply="현재 제공 범위에 포함하기 어려워요.")
    )
    env.db.execute(delete(User).where(User.id == env.moderator))
    env.db.commit()
    env.db.expire_all()
    stored = env.db.get(ContentTopicRequest, UUID(row["id"]))
    assert stored.reviewed_by is None and stored.reply is not None
    assert env.db.scalar(select(func.count()).select_from(TopicRequestAudit)) == 2
    env.db.execute(delete(User).where(User.id == env.owner))
    env.db.commit()
    assert env.db.scalar(select(func.count()).select_from(ContentTopicRequest)) == 0
    assert env.db.scalar(select(func.count()).select_from(TopicRequestAudit)) == 0


def test_migration_preserves_existing_users_profiles_and_guides(env):
    guide = published_guide(env)
    env.db.add(
        Profile(
            user_id=env.owner,
            preferences={},
            consented_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    env.db.commit()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = env.connection
    command.downgrade(config, "20261120_04")
    env.connection.commit()
    command.upgrade(config, "head")
    env.connection.commit()
    command.check(config)
    env.connection.rollback()
    env.db.expire_all()
    assert (
        env.db.get(User, env.owner) is not None
        and env.db.get(Profile, env.owner) is not None
    )
    assert env.db.get(LifeGuide, guide.id).is_published
    assert env.db.scalar(select(func.count()).select_from(ContentTopicRequest)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "other"},
        {"topic": None},
        {"version": 0},
        {"status": "completed"},
        {"status": "withdrawn", "topic": "남은 내용"},
    ],
)
def test_database_rejects_invalid_request_states(env, changes):
    row = ContentTopicRequest(
        user_id=env.owner,
        submission_id=uuid4(),
        fingerprint="f" * 64,
        kind="life_guide",
        topic="새 요청",
        status="received",
    )
    for key, value in changes.items():
        setattr(row, key, value)
    env.db.add(row)
    with pytest.raises(IntegrityError):
        env.db.commit()
    env.db.rollback()


def parallel(env, actions):
    schema = env.connection.scalar(text("SELECT current_schema()"))
    env.connection.commit()
    barrier = Barrier(len(actions))

    def invoke(action):
        app = create_app()

        def own_db():
            with env.connection.engine.connect() as other:
                other.execute(text(f'SET search_path TO "{schema}"'))
                other.commit()
                try:
                    with Session(other, expire_on_commit=False) as db:
                        yield db
                finally:
                    other.rollback()
                    other.execute(text("SET search_path TO public"))
                    other.commit()

        app.dependency_overrides[get_db] = own_db
        with TestClient(app) as http:
            barrier.wait(timeout=10)
            return action(http)

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_simultaneous_duplicate_submissions_create_one_request_and_one_audit(env):
    body = proposal()
    responses = parallel(
        env, [lambda http: http.post(BASE, headers=env.own, json=body)] * 2
    )
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert (
        len({response.json()["data"]["request"]["id"] for response in responses}) == 1
    )
    assert env.db.scalar(select(func.count()).select_from(ContentTopicRequest)) == 1
    assert env.db.scalar(select(func.count()).select_from(TopicRequestAudit)) == 1


def test_simultaneous_quota_cannot_exceed_five(env):
    for _ in range(4):
        create(env)
    responses = parallel(
        env, [lambda http: http.post(BASE, headers=env.own, json=proposal())] * 2
    )
    assert sorted(response.status_code for response in responses) == [201, 429]
    assert env.db.scalar(select(func.count()).select_from(ContentTopicRequest)) == 5


def test_competing_reviews_only_accept_one_expected_version(env):
    row = create(env, kind="video")
    responses = parallel(
        env,
        [
            lambda http: http.put(
                f"{ADMIN}/{row['id']}",
                headers=env.admin,
                json={
                    "expected_version": 1,
                    "status": "completed",
                    "reply": "확인했어요.",
                },
            )
        ]
        * 2,
    )
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_withdrawal_cannot_be_overwritten_by_a_competing_review(env):
    row = create(env, kind="video")
    responses = parallel(
        env,
        [
            lambda http: http.delete(f"{BASE}/{row['id']}", headers=env.own),
            lambda http: http.put(
                f"{ADMIN}/{row['id']}",
                headers=env.admin,
                json={
                    "expected_version": 1,
                    "status": "completed",
                    "reply": "완료했어요.",
                },
            ),
        ],
    )
    assert responses[0].status_code == 200 and responses[1].status_code in (200, 404)
    final = data(env.client.get(f"{BASE}/{row['id']}", headers=env.own))
    assert (
        final["status"] == "withdrawn"
        and final["topic"] is None
        and final["reply"] is None
    )
