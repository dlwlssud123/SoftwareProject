import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.set_user_role import set_role
from app.models.auth import AuthSession, User


@pytest.fixture
def auth_db(pg_connection, client):
    with Session(bind=pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        yield client, db


def guest(client):
    response = client.post("/api/v1/auth/guest", json={})
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert len(data["access_token"]) == 43
    assert data["role"] == "user"
    return data, {"Authorization": f"Bearer {data['access_token']}"}


def test_sessions_persist_only_hash_and_keep_users_separate(auth_db):
    client, db = auth_db
    first, first_headers = guest(client)
    second, second_headers = guest(client)
    assert first["user_id"] != second["user_id"]
    hashes = list(db.scalars(select(AuthSession.token_hash)))
    assert hashlib.sha256(first["access_token"].encode()).hexdigest() in hashes
    assert first["access_token"] not in repr(hashes)
    assert (
        client.get("/api/v1/auth/me", headers=first_headers).json()["data"]["user_id"]
        == first["user_id"]
    )
    assert (
        client.get("/api/v1/auth/me", headers=second_headers).json()["data"]["user_id"]
        == second["user_id"]
    )


def test_kakao_link_preserves_guest_profile_and_rejects_other_owner(
    auth_db, monkeypatch
):
    from types import SimpleNamespace

    from app.api import auth
    from app.models.auth import KakaoIdentity

    client, db = auth_db
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(kakao_app_id=42))
    monkeypatch.setattr(auth, "verify_kakao_token", lambda token, app_id: 123)
    original, headers = guest(client)
    other, other_headers = guest(client)
    profile = client.patch(
        "/api/v1/profile",
        headers=headers,
        json={"consent": True},
    )
    assert profile.status_code == 200
    credentials = {"access_token": "test-kakao-token"}

    link = client.post("/api/v1/auth/kakao/link", headers=headers, json=credentials)
    assert link.status_code == 200
    assert link.json()["data"]["user_id"] == original["user_id"]
    assert link.json()["data"]["kakao_linked"] is True
    assert "access_token" not in link.json()["data"]
    assert (
        client.post(
            "/api/v1/auth/kakao/link", headers=headers, json=credentials
        ).status_code
        == 200
    )

    rejected = client.post(
        "/api/v1/auth/kakao/link", headers=other_headers, json=credentials
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "KAKAO_ALREADY_LINKED"
    assert (
        client.get("/api/v1/auth/me", headers=other_headers).json()["data"]["user_id"]
        == other["user_id"]
    )
    assert len(list(db.scalars(select(KakaoIdentity)))) == 1

    login = client.post("/api/v1/auth/kakao", json=credentials)
    assert login.status_code == 200
    signed_in = login.json()["data"]
    assert signed_in["user_id"] == original["user_id"]
    assert signed_in["access_token"] != original["access_token"]
    signed_in_headers = {"Authorization": f"Bearer {signed_in['access_token']}"}
    assert (
        client.get("/api/v1/profile", headers=signed_in_headers).json()["data"]
        == profile.json()["data"]
    )
    assert (
        client.get("/api/v1/auth/me", headers=headers).json()["data"]["kakao_linked"]
        is True
    )


def test_kakao_first_login_reuses_one_identity(auth_db, monkeypatch):
    from types import SimpleNamespace

    from app.api import auth
    from app.models.auth import KakaoIdentity

    client, db = auth_db
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(kakao_app_id=42))
    monkeypatch.setattr(auth, "verify_kakao_token", lambda token, app_id: 321)

    credentials = {"access_token": "test-kakao-token"}
    first = client.post("/api/v1/auth/kakao", json=credentials)
    second = client.post("/api/v1/auth/kakao", json=credentials)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["user_id"] == second.json()["data"]["user_id"]
    assert first.json()["data"]["access_token"] != second.json()["data"]["access_token"]
    assert len(list(db.scalars(select(KakaoIdentity)))) == 1


def test_kakao_link_and_relogin_preserve_meal_plan_and_saved_recipes(
    auth_db, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from test_public_data_import import corrections, snapshot

    from app.api import auth
    from app.jobs.import_public_data import apply_import, prepare_import

    client, db = auth_db
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(kakao_app_id=42))
    monkeypatch.setattr(auth, "verify_kakao_token", lambda token, app_id: 123)
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
    original, headers = guest(client)
    day = "/api/v1/meal-plans/2026-11-18"
    assert (
        client.put(
            day + "/breakfast", headers=headers, json={"recipe_id": "1"}
        ).status_code
        == 200
    )
    assert client.put("/api/v1/saved-recipes/1", headers=headers).status_code == 200
    credentials = {"access_token": "test-kakao-token"}
    assert (
        client.post(
            "/api/v1/auth/kakao/link", headers=headers, json=credentials
        ).status_code
        == 200
    )
    assert client.delete("/api/v1/auth/session", headers=headers).status_code == 200
    login = client.post("/api/v1/auth/kakao", json=credentials).json()["data"]
    assert login["user_id"] == original["user_id"]
    signed_in = {"Authorization": f"Bearer {login['access_token']}"}
    assert (
        client.get(day, headers=signed_in).json()["data"]["items"][0]["recipe_id"]
        == "1"
    )
    assert client.get("/api/v1/saved-recipes", headers=signed_in).json()["data"][
        "items"
    ] == [{"recipe_id": "1", "name": "쌀죽"}]


@pytest.mark.parametrize("app_id, expires_in", [(42, 120), (43, 120), (42, 0)])
def test_kakao_token_must_belong_to_our_app_and_be_active(
    monkeypatch, app_id, expires_in
):
    import json
    from io import BytesIO
    from unittest.mock import Mock

    from app.core import kakao
    from app.core.errors import AppError

    payload = BytesIO(
        json.dumps({"app_id": app_id, "expires_in": expires_in, "id": 123}).encode()
    )
    opener = Mock()
    opener.open.return_value = payload
    monkeypatch.setattr(kakao, "build_opener", lambda handler: opener)
    if app_id == 42 and expires_in > 0:
        assert kakao.verify_kakao_token("test-kakao-token", 42) == 123
    else:
        with pytest.raises(AppError) as error:
            kakao.verify_kakao_token("test-kakao-token", 42)
        assert error.value.code == "KAKAO_TOKEN_INVALID"
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://kapi.kakao.com/v1/user/access_token_info"
    assert request.get_header("Authorization") == "Bearer test-kakao-token"


def test_refresh_rotates_once_and_logout_revokes_only_current_session(auth_db):
    client, _ = auth_db
    first, headers = guest(client)
    _, other_headers = guest(client)
    response = client.post("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 200
    refreshed = response.json()["data"]
    assert refreshed["user_id"] == first["user_id"]
    assert refreshed["access_token"] != first["access_token"]
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    rotated_headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
    assert client.delete("/api/v1/auth/session", headers=rotated_headers).json()[
        "data"
    ] == {"revoked": True}
    assert client.get("/api/v1/auth/me", headers=rotated_headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=other_headers).status_code == 200


def test_admin_role_is_server_owned_and_demotion_takes_effect(auth_db):
    client, db = auth_db
    assert client.post("/api/v1/auth/guest", json={"role": "admin"}).status_code == 422
    assert (
        client.post("/api/v1/auth/guest", json={"user_id": str(uuid4())}).status_code
        == 422
    )
    data, headers = guest(client)
    assert client.get("/api/v1/admin/me", headers=headers).status_code == 403
    from uuid import UUID

    set_role(db, UUID(data["user_id"]), "admin")
    response = client.get("/api/v1/admin/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "admin"
    assert "access_token" not in response.json()["data"]
    set_role(db, UUID(data["user_id"]), "user")
    assert client.get("/api/v1/admin/me", headers=headers).status_code == 403
    with pytest.raises(ValueError, match="Active user not found"):
        set_role(db, uuid4(), "admin")
    with pytest.raises(ValueError, match="Role must"):
        set_role(db, UUID(data["user_id"]), "owner")


@pytest.mark.parametrize("state", ["expired", "revoked", "disabled"])
def test_invalid_session_states_are_rejected(auth_db, state):
    client, db = auth_db
    _, headers = guest(client)
    session = db.scalar(select(AuthSession))
    now = datetime.now(UTC)
    if state == "expired":
        session.created_at = now - timedelta(days=2)
        session.expires_at = now - timedelta(days=1)
    elif state == "revoked":
        session.revoked_at = now
    else:
        db.get(User, session.user_id).disabled_at = now
    db.commit()
    for path in ("/api/v1/auth/me", "/api/v1/admin/me"):
        assert client.get(path, headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic abc", "Bearer short", "Bearer 한글", "Bearer " + "a" * 44],
)
def test_missing_and_malformed_tokens_do_not_need_database(client, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    if authorization == "Bearer 한글":
        headers = {"Authorization": authorization.encode("utf-8")}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.headers["Cache-Control"] == "no-store"


def test_unknown_token_is_rejected_and_not_logged(auth_db, caplog):
    client, _ = auth_db
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer " + "x" * 43}
    )
    assert response.status_code == 401
    assert "x" * 43 not in response.text + caplog.text


def test_storage_failure_uses_safe_retryable_error(client):
    from unittest.mock import Mock

    from sqlalchemy.exc import OperationalError

    db = Mock(spec=Session)
    db.execute.side_effect = OperationalError(
        "SELECT secret", {}, Exception("private-db-secret")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer " + "x" * 43}
    )
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-db-secret" not in response.text


def test_token_is_masked_outside_issuing_response():
    from app.schemas.auth import SessionData

    data = SessionData(
        user_id=uuid4(),
        role="user",
        expires_at=datetime.now(UTC),
        access_token="private-session",
    )
    assert "private-session" not in repr(data)
    assert "private-session" not in data.model_dump_json()


def test_guest_storage_failure_rolls_back_and_openapi_matches_error_envelope(client):
    from unittest.mock import Mock

    from sqlalchemy.exc import OperationalError

    db = Mock(spec=Session)
    db.flush.side_effect = OperationalError(
        "INSERT", {}, Exception("private-db-secret")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/v1/auth/guest", json={})
    assert response.status_code == 503
    db.rollback.assert_called_once()
    assert "private-db-secret" not in response.text
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/auth/guest"]["post"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.parametrize("action", ["refresh", "revoke"])
def test_session_write_failure_keeps_original_token_valid(auth_db, monkeypatch, action):
    from sqlalchemy.exc import OperationalError

    client, db = auth_db
    _, headers = guest(client)
    before = len(list(db.scalars(select(AuthSession.id))))

    def fail_commit():
        raise OperationalError("COMMIT", {}, Exception("private-storage-error"))

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        if action == "refresh":
            response = client.post("/api/v1/auth/refresh", headers=headers)
        else:
            response = client.delete("/api/v1/auth/session", headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-storage-error" not in response.text
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert len(list(db.scalars(select(AuthSession.id)))) == before


def test_concurrent_refresh_only_issues_one_replacement(auth_db, pg_connection):
    from sqlalchemy import text

    from app.main import create_app

    client, _ = auth_db
    _, headers = guest(client)
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44

    def attempt(_):
        app = create_app()

        def connection_for_request():
            with pg_connection.engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                connection.commit()
                try:
                    with Session(bind=connection, expire_on_commit=False) as db:
                        yield db
                finally:
                    connection.rollback()
                    connection.execute(text("SET search_path TO public"))
                    connection.commit()

        app.dependency_overrides[get_db] = connection_for_request
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                "/api/v1/auth/refresh", headers=headers
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 401]
