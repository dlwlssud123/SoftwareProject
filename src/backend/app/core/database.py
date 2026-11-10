from collections.abc import Generator

from sqlalchemy import create_engine  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import (  # pyright: ignore[reportMissingImports]
    Session,
    sessionmaker,
)

from app.core.base import Base  # noqa: F401 - preserve the existing import path
from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url.get_secret_value(),
    pool_pre_ping=True,
    pool_timeout=5,
    connect_args={"connect_timeout": 5},
    hide_parameters=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


# engine: DB 연결 풀 관리
# pool_pre_ping: 연결을 사용하기 전에 유효한지 확인
# SessionLocal: 요청마다 독립적 세션 생성
# get_db(): 요청 처리가 끝나면 세션을 닫고, 예외가 발생하면 롤백
# Base: 이후 사용자/레시피 등의 ORM 모델이 상속할 공통 부모
# 저장이 필요한 서비스에서 명시적으로 session.commit() 호출하는 방식
# 요청이 성공했다는 이유만으로 자동 커밋 X
# 구현 단순화를 위해 SQLAlchemy 사용
