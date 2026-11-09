import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


@pytest.fixture
def client(monkeypatch):
    # Unit tests must never connect to the developer's database.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://test:test@127.0.0.1:1/valueflow_test",
    )
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173"]')
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def pg_connection():
    import os
    import uuid
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from alembic import command

    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip(
            "Set RUN_DB_TESTS=1 to test local PostgreSQL in a disposable schema"
        )
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    engine = create_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    schema = f"import_test_{uuid.uuid4().hex}"
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
        connection.commit()
        try:
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            yield connection
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            # Only the fresh UUID-named schema created by this fixture is disposable.
            assert schema.startswith("import_test_") and len(schema) == 44
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()
