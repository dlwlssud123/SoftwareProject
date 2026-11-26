from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "ValueFlow API"
    database_url: SecretStr
    cors_origins: list[str] = Field(default_factory=list)
    session_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    admin_session_ttl_seconds: int = Field(default=3600, ge=300, le=28800)
    kakao_app_id: int | None = Field(default=None, gt=0)
    nvidia_api_key: SecretStr | None = None
    nvidia_ai_enabled: bool = False
    welfare_rag_enabled: bool = False
    rag_embedding_url: str | None = None
    rag_embedding_token: SecretStr | None = Field(default=None, min_length=32)
    rag_embedding_timeout_seconds: float = Field(default=5, ge=1, le=15)

    @field_validator("rag_embedding_url", mode="before")
    @classmethod
    def embedding_origin(cls, value):
        if value in (None, ""):
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError(
                "RAG_EMBEDDING_URL must be an HTTP(S) origin without credentials"
            )
        _ = parts.port
        return value.rstrip("/")

    @field_validator("rag_embedding_token", mode="before")
    @classmethod
    def empty_embedding_token(cls, value):
        return None if value == "" else value

    nvidia_model: str = Field(
        default="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    nvidia_timeout_seconds: float = Field(default=25, ge=3, le=60)
    ai_daily_user_limit: int = Field(default=30, ge=1, le=1000)
    ai_daily_global_limit: int = Field(default=100, ge=1, le=10000)

    @field_validator("nvidia_api_key", mode="before")
    @classmethod
    def empty_ai_key_is_disabled(cls, value):
        return None if value == "" else value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must start with postgresql+psycopg://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


# .env를 실행 위치와 관계없이 항상 불러오기
# 필수 DB 설정이 없거나 드라이버 형식이 다르면 시작 단계에서 알려줌
# SecretStr로 설정 객체를 출력할 때 DB 비밀번호가 그대로 보이는 것을 줄임
# get_settings() 결과를 재사용함
