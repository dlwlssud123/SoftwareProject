from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_topic_requests import parallel

from app.api import community
from app.core.auth import AuthContext, current_auth, token_digest
from app.core.database import get_db
from app.models import CommunityBlock, CommunityPost, CommunityReport, User
from app.models.auth import AuthSession
from app.schemas.community import PostCreate

BASE = "/api/v1/community"
ADMIN = "/api/v1/admin/community"


def proposal(**changes):
    return {
        "submission_id": str(uuid4()),
        "category": "meal",
        "title": "오늘 만든 두부 요리",
        "body": "두부를 부드럽게 익혔어요.",
        **changes,
    }


def read(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers["Cache-Control"] == "no-store"
    if status == 204:
        assert not response.content
        return None
    return response.json()["error" if status >= 400 else "data"]


@pytest.fixture
def community_db(pg_connection, client):
    with Session(bind=pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        yield client, db


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"title": "가" * 61},
        {"body": "가" * 2001},
        {"body": "\x00"},
        {"body": "\ud800"},
        {"category": "medical"},
        {"author_id": str(uuid4())},
        {"status": "published"},
        {"submission_id": str(UUID(int=0))},
    ],
)
def test_post_contract_rejects_invalid_content_and_authority_fields(changes):
    with pytest.raises(ValidationError):
        PostCreate.model_validate(proposal(**changes))


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/posts", None),
        ("POST", "/posts", proposal()),
        ("GET", "/blocks", None),
        ("GET", f"/posts/{uuid4()}", None),
        (
            "PATCH",
            f"/posts/{uuid4()}",
            {"expected_version": 1, "category": "meal", "title": "글", "body": "내용"},
        ),
    ],
)
def test_community_requires_session(client, method, path, body):
    read(client.request(method, BASE + path, json=body), 401)


def test_post_create_replay_edit_and_delete_do_not_restore_text(community_db):
    client, db = community_db
    _, headers = guest(client)
    payload = proposal()
    created = read(client.post(BASE + "/posts", json=payload, headers=headers), 201)
    post = created["post"]
    assert not created["replayed"]
    assert post["is_mine"] and post["version"] == 1
    assert not {"author_id", "user_id", "submission_id", "fingerprint"} & post.keys()
    replay = read(client.post(BASE + "/posts", json=payload, headers=headers))
    assert replay["replayed"] and replay["post"]["id"] == post["id"]
    read(
        client.post(
            BASE + "/posts", json={**payload, "body": "다른 내용"}, headers=headers
        ),
        409,
    )
    edited = read(
        client.patch(
            f"{BASE}/posts/{post['id']}",
            json={
                "expected_version": 1,
                "category": "daily",
                "title": "수정한 글",
                "body": "새 내용",
            },
            headers=headers,
        )
    )
    assert edited["version"] == 2
    read(
        client.patch(
            f"{BASE}/posts/{post['id']}",
            json={
                "expected_version": 1,
                "category": "daily",
                "title": "낡은 수정",
                "body": "내용",
            },
            headers=headers,
        ),
        409,
    )
    read(
        client.request(
            "DELETE",
            f"{BASE}/posts/{post['id']}",
            json={"expected_version": 2},
            headers=headers,
        ),
        204,
    )
    read(client.get(f"{BASE}/posts/{post['id']}", headers=headers), 404)
    read(client.post(BASE + "/posts", json=payload, headers=headers), 404)
    stored = db.get(CommunityPost, UUID(post["id"]))
    assert stored.status == "deleted" and stored.title == stored.body == ""
    assert db.scalar(select(func.count()).select_from(CommunityPost)) == 1


def test_other_users_cannot_edit_or_delete_posts(community_db):
    client, _ = community_db
    _, owner = guest(client)
    _, other = guest(client)
    post = read(client.post(BASE + "/posts", json=proposal(), headers=owner), 201)[
        "post"
    ]
    result = read(client.get(f"{BASE}/posts/{post['id']}", headers=other))
    assert result["is_mine"] is False
    edit = {"expected_version": 1, "category": "meal", "title": "변경", "body": "변경"}
    read(client.patch(f"{BASE}/posts/{post['id']}", json=edit, headers=other), 403)
    read(
        client.request(
            "DELETE",
            f"{BASE}/posts/{post['id']}",
            json={"expected_version": 1},
            headers=other,
        ),
        403,
    )
    assert read(client.get(f"{BASE}/posts/{post['id']}", headers=owner))["version"] == 1


def test_feed_filters_pages_and_does_not_include_disabled_authors(community_db):
    client, db = community_db
    author, owner = guest(client)
    _, viewer = guest(client)
    for category, title in [
        ("meal", "두부 % 요리"),
        ("daily", "오늘 산책"),
        ("meal", "달걀 요리"),
    ]:
        read(
            client.post(
                BASE + "/posts",
                json=proposal(category=category, title=title),
                headers=owner,
            ),
            201,
        )
    page = read(client.get(BASE + "/posts?category=meal&limit=1", headers=viewer))
    assert page["total"] == 2 and len(page["items"]) == 1
    next_page = read(
        client.get(BASE + "/posts?category=meal&limit=1&offset=1", headers=viewer)
    )
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    literal = read(client.get(BASE + "/posts", params={"q": "%"}, headers=viewer))
    assert literal["total"] == 1 and literal["items"][0]["title"] == "두부 % 요리"
    db.get(User, UUID(author["user_id"])).disabled_at = datetime.now(UTC)
    db.commit()
    assert read(client.get(BASE + "/posts", headers=viewer))["total"] == 0


def test_block_is_private_idempotent_and_applies_to_detail_and_both_directions(
    community_db,
):
    client, db = community_db
    _, first = guest(client)
    _, second = guest(client)
    _, outsider = guest(client)
    a = read(client.post(BASE + "/posts", json=proposal(), headers=first), 201)["post"]
    b = read(client.post(BASE + "/posts", json=proposal(), headers=second), 201)["post"]
    read(client.post(f"{BASE}/posts/{a['id']}/block-author", headers=first), 422)
    block = read(client.post(f"{BASE}/posts/{a['id']}/block-author", headers=second))
    assert (
        read(client.post(f"{BASE}/posts/{a['id']}/block-author", headers=second))["id"]
        == block["id"]
    )
    assert "blocked_id" not in block and "viewer_id" not in block
    assert db.scalar(select(func.count()).select_from(CommunityBlock)) == 1
    assert read(client.get(BASE + "/posts", headers=second))["total"] == 1
    read(client.get(f"{BASE}/posts/{a['id']}", headers=second), 404)
    read(client.get(f"{BASE}/posts/{b['id']}", headers=first), 404)
    assert read(client.get(BASE + "/blocks", headers=first))["total"] == 0
    read(client.delete(f"{BASE}/blocks/{block['id']}", headers=outsider), 404)
    read(client.delete(f"{BASE}/blocks/{block['id']}", headers=second), 204)
    assert read(client.get(BASE + "/posts", headers=second))["total"] == 2


def test_reports_are_private_and_only_admin_can_hide_without_author_republishing(
    community_db,
):
    client, db = community_db
    _, owner = guest(client)
    _, reporter = guest(client)
    admin_data, admin = guest(client)
    db.get(User, UUID(admin_data["user_id"])).role = "admin"
    db.commit()
    post = read(client.post(BASE + "/posts", json=proposal(), headers=owner), 201)[
        "post"
    ]
    url = f"{BASE}/posts/{post['id']}/reports"
    read(client.post(url, json={"reason": "spam"}, headers=owner), 422)
    report = read(
        client.post(
            url,
            json={"reason": "privacy", "note": "비공개 신고 메모"},
            headers=reporter,
        )
    )
    assert set(report) == {"id", "status"}
    assert (
        read(client.post(url, json={"reason": "abuse"}, headers=reporter))["id"]
        == report["id"]
    )
    assert db.scalar(select(func.count()).select_from(CommunityReport)) == 1
    assert (
        "비공개 신고 메모"
        not in client.get(f"{BASE}/posts/{post['id']}", headers=owner).text
    )
    read(client.get(ADMIN + "/reports", headers=owner), 403)
    queue = read(client.get(ADMIN + "/reports?status=received", headers=admin))
    assert queue["total"] == 1 and queue["items"][0]["note"] == "비공개 신고 메모"
    decision = {
        "decision": "hide",
        "expected_post_version": 1,
        "resolution": "개인정보 포함으로 숨김",
    }
    read(
        client.patch(f"{ADMIN}/reports/{report['id']}", json=decision, headers=owner),
        403,
    )
    result = read(
        client.patch(f"{ADMIN}/reports/{report['id']}", json=decision, headers=admin)
    )
    assert result["status"] == "actioned" and result["post"]["status"] == "hidden"
    assert result["post"]["version"] == 2
    read(client.get(f"{BASE}/posts/{post['id']}", headers=reporter), 404)
    assert read(client.get(BASE + "/posts", headers=owner))["total"] == 0
    assert (
        read(client.get(BASE + "/posts/mine", headers=owner))["items"][0]["status"]
        == "hidden"
    )
    edited = read(
        client.patch(
            f"{BASE}/posts/{post['id']}",
            json={
                "expected_version": 2,
                "category": "meal",
                "title": "수정",
                "body": "다시 게시 시도",
            },
            headers=owner,
        )
    )
    assert edited["status"] == "hidden" and edited["version"] == 3
    read(
        client.patch(f"{ADMIN}/reports/{report['id']}", json=decision, headers=admin),
        409,
    )


def test_daily_limit_counts_deleted_posts_and_replays_are_not_charged(community_db):
    client, _ = community_db
    _, owner = guest(client)
    first = proposal()
    for index in range(10):
        payload = first if index == 0 else proposal()
        post = read(client.post(BASE + "/posts", json=payload, headers=owner), 201)[
            "post"
        ]
        if index == 1:
            read(
                client.request(
                    "DELETE",
                    f"{BASE}/posts/{post['id']}",
                    json={"expected_version": 1},
                    headers=owner,
                ),
                204,
            )
    read(client.post(BASE + "/posts", json=proposal(), headers=owner), 429)
    assert read(client.post(BASE + "/posts", json=first, headers=owner))["replayed"]


def test_failed_commit_rolls_back_post_and_hides_database_details(
    community_db, monkeypatch
):
    client, db = community_db
    _, owner = guest(client)
    monkeypatch.setattr(
        db,
        "commit",
        Mock(
            side_effect=OperationalError(
                "write", {}, Exception("private-database-detail")
            )
        ),
    )
    response = client.post(BASE + "/posts", json=proposal(), headers=owner)
    assert read(response, 503)["retryable"]
    assert "private-database-detail" not in response.text
    assert db.scalar(select(func.count()).select_from(CommunityPost)) == 0


def test_revocation_after_initial_authentication_prevents_post_write(community_db):
    client, db = community_db
    identity, owner = guest(client)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(identity["access_token"])
        )
    )
    context = AuthContext(user=db.get(User, UUID(identity["user_id"])), session=session)
    session.revoked_at = datetime.now(UTC)
    db.commit()
    # Simulate authentication completing before a concurrent session revocation.
    client.app.dependency_overrides[current_auth] = lambda: context
    read(client.post(BASE + "/posts", json=proposal(), headers=owner), 401)
    assert db.scalar(select(func.count()).select_from(CommunityPost)) == 0


def test_mutual_blocking_does_not_deadlock_foreign_key_checks(
    community_db, pg_connection, monkeypatch
):
    client, _ = community_db
    _, first = guest(client)
    _, second = guest(client)
    a = read(client.post(BASE + "/posts", json=proposal(), headers=first), 201)["post"]
    b = read(client.post(BASE + "/posts", json=proposal(), headers=second), 201)["post"]
    original = community._read_post
    both_visible = Barrier(2)

    def visible_before_insert(*args, **kwargs):
        result = original(*args, **kwargs)
        both_visible.wait(timeout=10)
        return result

    monkeypatch.setattr(community, "_read_post", visible_before_insert)
    responses = parallel(
        SimpleNamespace(connection=pg_connection),
        [
            lambda http: http.post(
                f"{BASE}/posts/{b['id']}/block-author", headers=first
            ),
            lambda http: http.post(
                f"{BASE}/posts/{a['id']}/block-author", headers=second
            ),
        ],
    )
    assert [response.status_code for response in responses] == [200, 200]


def test_session_revocation_is_serialized_with_accepted_write(
    community_db, pg_connection
):
    client, db = community_db
    identity, _ = guest(client)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(identity["access_token"])
        )
    )
    context = AuthContext(user=db.get(User, UUID(identity["user_id"])), session=session)
    community._lock_user(db, context)
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    with pg_connection.engine.connect() as other:
        other.execute(text(f'SET search_path TO "{schema}"'))
        other.commit()
        try:
            other.execute(text("SET LOCAL lock_timeout = '150ms'"))
            with pytest.raises(OperationalError) as failure:
                other.execute(
                    update(AuthSession)
                    .where(AuthSession.id == session.id)
                    .values(revoked_at=datetime.now(UTC))
                )
            assert failure.value.orig.sqlstate == "55P03"
            other.rollback()
            db.commit()
            # Once the accepted write commits, the same revocation can complete.
            other.execute(
                update(AuthSession)
                .where(AuthSession.id == session.id)
                .values(revoked_at=datetime.now(UTC))
            )
            other.commit()
        finally:
            other.rollback()
            other.execute(text("SET search_path TO public"))
            other.commit()
