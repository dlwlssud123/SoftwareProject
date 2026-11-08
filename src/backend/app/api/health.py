from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(
    prefix="/health",
    tags=["health"],
    responses={500: {"model": ErrorResponse, "description": "Unexpected server error"}},
)

DatabaseSession = Annotated[Session, Depends(get_db)]


class HealthData(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"] | None = None


@router.get(
    "/live",
    summary="서버 생존 상태 확인",
    response_model=SuccessResponse[HealthData],
)
def check_liveness(request: Request):
    return SuccessResponse(
        data=HealthData(status="ok"),
        meta=build_meta(request),
    )


@router.get(
    "/ready",
    summary="PostgreSQL 연결 상태 확인",
    response_model=SuccessResponse[HealthData],
    responses={503: {"model": ErrorResponse, "description": "Database unavailable"}},
)
def check_readiness(
    request: Request,
    db: DatabaseSession,
):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise AppError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="데이터베이스 연결을 확인해 주세요.",
            retryable=True,
        ) from None

    return SuccessResponse(
        data=HealthData(status="ok", database="ok"),
        meta=build_meta(
            request,
            checked_at=datetime.now(UTC),
        ),
    )
