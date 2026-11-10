import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_invalid_database_driver_does_not_expose_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://user:private-password@localhost/db")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert "DATABASE_URL must start with postgresql+psycopg://" in str(error.value)
    assert "private-password" not in str(error.value)


def test_environment_overrides_dotenv_and_masks_database_url(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=From file\nUNRELATED_KEY=ignored\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "From environment")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:private-password@localhost/db"
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "From environment"
    assert "private-password" not in repr(settings)


@pytest.mark.parametrize("ttl", [0, 299, 2592001])
def test_session_expiry_configuration_has_bounds(monkeypatch, ttl):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("SESSION_TTL_SECONDS", str(ttl))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
