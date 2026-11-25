import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, BoundedSemaphore, Event
from unittest.mock import Mock

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command
from app.api import admin_login
from app.core import passwords
from app.core.database import get_db
from app.jobs.provision_admin import disable, provision
from app.main import create_app
from app.models import AdminCredential, AdminLoginBucket, AuthSession, User
from app.schemas.auth import AdminLoginRequest

PATH = "/api/v1/admin/login"
PASSWORD = "a deterministic test phrase only"


def test_password_hashes_are_salted_bounded_and_exact():
    first = passwords.hash_password(PASSWORD)
    second = passwords.hash_password(PASSWORD)
    assert first != second and PASSWORD not in first
    assert passwords.verify_password(PASSWORD, first)
    assert not passwords.verify_password(PASSWORD + "!", first)
    assert not passwords.verify_password(PASSWORD, None)
    assert not passwords.verify_password(PASSWORD, "scrypt-v999$invalid")
    secret = AdminLoginRequest(username="Admin.Test", password=PASSWORD)
    assert secret.username == "admin.test"
    assert PASSWORD not in repr(secret)


@pytest.mark.parametrize("value", ["", "short", " " * 15, "x" * 129, "\ud800" * 16])
def test_password_provisioning_policy_rejects_invalid_values_without_echo(value):
    with pytest.raises(ValueError) as error:
        passwords.hash_password(value)
    assert value not in str(error.value) if value else True


@pytest.mark.parametrize(
    "value", ["x", "../admin", "a b", "관리자", "a@b.example", "x" * 65]
)
def test_admin_usernames_are_canonical_and_not_paths_or_email(value):
    with pytest.raises(ValueError):
        passwords.normalize_username(value)


@pytest.mark.parametrize(
    "body",
    [
        {"username": "admin", "password": ""},
        {"username": "admin", "password": "x" * 129},
        {"username": "a", "password": PASSWORD},
        {"username": "../path", "password": PASSWORD},
        {"username": "admin", "password": PASSWORD, "role": "admin"},
    ],
)
def test_login_validation_hides_passwords(client, body):
    response = client.post(PATH, json=body)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert PASSWORD not in response.text


def test_failed_sql_releases_hash_slot_and_returns_no_connection_details(
    client, monkeypatch
):
    db = Mock()
    db.execute.side_effect = OperationalError(
        None, None, RuntimeError("private-database-details")
    )
    client.app.dependency_overrides[get_db] = lambda: db
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(admin_login, "_HASH_SLOTS", slots)
    response = client.post(PATH, json={"username": "admin", "password": PASSWORD})
    assert (
        response.status_code == 503 and "private-database-details" not in response.text
    )
    assert PASSWORD not in response.text
    assert slots.acquire(blocking=False)
    slots.release()
    db.rollback.assert_called_once()


def test_overloaded_login_returns_retry_without_starting_a_hash(client, monkeypatch):
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(admin_login, "_HASH_SLOTS", slots)
    verify = Mock()
    monkeypatch.setattr(admin_login, "verify_password", verify)
    response = client.post(PATH, json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 503 and response.headers["Retry-After"] == "2"
    verify.assert_not_called()
    slots.release()


@pytest.fixture
def environment(pg_connection, client):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        user_id = provision(db, "operator", PASSWORD)
        yield client, db, user_id, pg_connection


def login(client, password=PASSWORD, username="operator"):
    return client.post(PATH, json={"username": username, "password": password})


def headers(response):
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["role"] == "admin"
    return {"Authorization": f"Bearer {data['access_token']}"}


def test_offline_account_login_identity_and_absolute_expiry(environment):
    client, db, user_id, _ = environment
    assert db.scalar(select(func.count()).select_from(User)) == 1
    credential = db.get(AdminCredential, "operator")
    assert PASSWORD not in credential.password_hash and credential.user_id == user_id
    response = login(client, username=" OPERATOR ")
    auth = headers(response)
    token = response.json()["data"]["access_token"]
    session = db.scalar(select(AuthSession))
    assert len(token) == 43 and token != session.token_hash
    assert session.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert session.expires_at == session.reauthenticate_at
    assert (session.expires_at - session.created_at).total_seconds() == 3600
    identity = client.get("/api/v1/admin/me", headers=auth)
    assert identity.status_code == 200 and identity.json()["data"]["user_id"] == str(
        user_id
    )
    assert "password" not in identity.text and "token" not in identity.text
    assert client.get("/api/v1/admin/data-jobs", headers=auth).status_code == 200
    refreshed = client.post("/api/v1/auth/refresh", headers=auth)
    new_headers = headers(refreshed)
    updated = db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
    assert updated.reauthenticate_at == session.reauthenticate_at
    assert updated.expires_at <= session.reauthenticate_at
    assert client.get("/api/v1/admin/me", headers=auth).status_code == 401
    assert client.delete("/api/v1/auth/session", headers=new_headers).status_code == 200
    assert client.get("/api/v1/admin/me", headers=new_headers).status_code == 401


def test_unknown_wrong_disabled_locked_and_demoted_are_indistinguishable(environment):
    client, db, user_id, _ = environment
    wrong = login(client, password="wrong test phrase")
    unknown = login(client, username="missing-admin")
    credential = db.get(AdminCredential, "operator")
    credential.enabled = False
    db.commit()
    disabled = login(client)
    credential.enabled = True
    credential.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()
    locked = login(client)
    credential.locked_until = None
    db.get(User, user_id).role = "user"
    db.commit()
    demoted = login(client)
    for response in (wrong, unknown, disabled, locked, demoted):
        assert (
            response.status_code == 401
            and response.headers["Cache-Control"] == "no-store"
        )
        assert response.json()["error"] == wrong.json()["error"]
        assert PASSWORD not in response.text
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_failed_attempts_are_committed_locked_and_recover_only_after_window(
    environment,
):
    client, db, _, _ = environment
    credential = db.get(AdminCredential, "operator")
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    db.refresh(credential)
    assert credential.failed_attempts == 5 and credential.locked_until > datetime.now(
        UTC
    )
    locked_until = credential.locked_until
    assert login(client).status_code == 401
    db.refresh(credential)
    assert credential.locked_until == locked_until
    credential.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    headers(login(client))
    db.refresh(credential)
    assert credential.failed_attempts == 0 and credential.locked_until is None


def test_per_peer_limit_does_not_store_raw_ip_username_or_password(
    environment, monkeypatch
):
    client, db, _, _ = environment
    peer = "testclient"
    key = hashlib.sha256(("valueflow-admin-login:" + peer).encode()).hexdigest()
    db.add(
        AdminLoginBucket(bucket_key=key, attempts=30, window_start=datetime.now(UTC))
    )
    db.add(
        AdminLoginBucket(
            bucket_key="f" * 64,
            attempts=1,
            window_start=datetime.now(UTC) - timedelta(days=2),
        )
    )
    db.commit()
    verify = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(admin_login, "verify_password", verify)
        response = login(client)
    assert (
        response.status_code == 429 and 0 < int(response.headers["Retry-After"]) <= 300
    )
    verify.assert_not_called()
    bucket = db.get(AdminLoginBucket, key)
    bucket.window_start -= timedelta(minutes=6)
    db.commit()
    headers(login(client))
    db.refresh(bucket)
    assert bucket.attempts == 1
    keys = list(db.scalars(select(AdminLoginBucket.bucket_key)))
    assert keys == [key] and peer not in str(keys) and PASSWORD not in str(keys)


def test_password_reset_and_disable_revoke_existing_sessions_and_keep_identity(
    environment,
):
    client, db, user_id, _ = environment
    first = headers(login(client))
    replacement = "another deterministic test phrase"
    with pytest.raises(ValueError):
        provision(db, "operator", replacement)
    assert client.get("/api/v1/admin/me", headers=first).status_code == 200
    assert provision(db, "operator", replacement, replace=True) == user_id
    assert client.get("/api/v1/admin/me", headers=first).status_code == 401
    assert login(client).status_code == 401
    current = headers(login(client, password=replacement))
    disable(db, "operator")
    assert client.get("/api/v1/admin/me", headers=current).status_code == 401
    assert login(client, password=replacement).status_code == 401
    assert db.get(AdminCredential, "operator").enabled is False


def test_role_provisioning_never_reactivates_or_elevates_a_demoted_identity(
    environment,
):
    _, db, user_id, _ = environment
    user = db.get(User, user_id)
    user.role = "user"
    db.commit()
    with pytest.raises(ValueError):
        provision(db, "operator", PASSWORD, replace=True)
    assert db.get(User, user_id).role == "user"
    with pytest.raises(ValueError):
        provision(db, "missing-admin", PASSWORD, replace=True)
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_old_user_sessions_and_no_default_admin_survive_migration(
    pg_connection, client
):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    command.downgrade(config, "20261120_03")
    pg_connection.commit()
    # Use SQL for the pre-migration shape; the new ORM already includes the new column.
    pg_connection.execute(
        text(
            "INSERT INTO users (id, role) VALUES ('00000000-0000-4000-8000-000000000099', 'user')"
        )
    )
    pg_connection.execute(
        text(
            "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at) VALUES ('00000000-0000-4000-8000-000000000098', '00000000-0000-4000-8000-000000000099', :hash, now(), now() + interval '1 day')"
        ),
        {"hash": hashlib.sha256(b"T" * 43).hexdigest()},
    )
    pg_connection.commit()
    command.upgrade(config, "head")
    pg_connection.commit()
    command.check(config)
    pg_connection.rollback()
    with Session(pg_connection) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer " + "T" * 43}
            ).status_code
            == 200
        )
        assert db.scalar(select(func.count()).select_from(AdminCredential)) == 0
        assert db.scalar(select(AuthSession)).reauthenticate_at is None


def test_concurrent_attempts_cannot_exceed_a_peer_bucket(environment):
    client, db, _, connection = environment
    key = hashlib.sha256(b"valueflow-admin-login:testclient").hexdigest()
    db.add(
        AdminLoginBucket(bucket_key=key, attempts=29, window_start=datetime.now(UTC))
    )
    db.commit()
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    barrier = Barrier(2)

    def attempt(_):
        app = create_app()

        def own_db():
            with connection.engine.connect() as other:
                other.execute(text(f'SET search_path TO "{schema}"'))
                other.commit()
                try:
                    with Session(other, expire_on_commit=False) as session:
                        yield session
                finally:
                    other.rollback()
                    other.execute(text("SET search_path TO public"))
                    other.commit()

        app.dependency_overrides[get_db] = own_db
        with TestClient(app) as http:
            barrier.wait(timeout=10)
            return login(http, username="unknown-admin").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert sorted(statuses) == [401, 429]
    db.expire_all()
    assert db.get(AdminLoginBucket, key).attempts == 30


@pytest.mark.parametrize("operation", ["disable", "reset"])
def test_refresh_identity_lock_serializes_account_revocation(environment, operation):
    client, db, user_id, connection = environment
    original = headers(login(client))
    schema = connection.scalar(text("SELECT current_schema()"))
    connection.commit()
    consuming, resume = Event(), Event()

    def refreshed():
        app = create_app()

        def own_db():
            with connection.engine.connect() as other:
                other.execute(text(f'SET search_path TO "{schema}"'))
                other.commit()

                def pause_before_consuming(
                    conn, cursor, statement, params, context, many
                ):
                    if statement.startswith("UPDATE sessions"):
                        consuming.set()
                        assert resume.wait(timeout=10)

                event.listen(other, "before_cursor_execute", pause_before_consuming)
                try:
                    with Session(other, expire_on_commit=False) as session:
                        yield session
                finally:
                    event.remove(other, "before_cursor_execute", pause_before_consuming)
                    other.rollback()
                    other.execute(text("SET search_path TO public"))
                    other.commit()

        app.dependency_overrides[get_db] = own_db
        with TestClient(app) as http:
            return http.post("/api/v1/auth/refresh", headers=original)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(refreshed)
        try:
            assert consuming.wait(timeout=10)
            # CLI must not reach its session UPDATE until refresh releases the
            # identity lock. NOWAIT proves the lock, without elapsed-time claims.
            with pytest.raises(OperationalError) as error:
                db.execute(
                    select(User).where(User.id == user_id).with_for_update(nowait=True)
                )
            assert error.value.orig.sqlstate == "55P03"
            db.rollback()
        finally:
            resume.set()
        replacement = headers(pending.result(timeout=10))
    if operation == "disable":
        disable(db, "operator")
    else:
        provision(db, "operator", "a different deterministic phrase", replace=True)
    assert client.get("/api/v1/admin/me", headers=replacement).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=replacement).status_code == 401
