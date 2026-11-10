from functools import lru_cache
from pathlib import Path

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
