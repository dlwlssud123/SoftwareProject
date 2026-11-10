from datetime import datetime

from fastapi import Request
from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    request_id: str
    revision: int | None = None
    checked_at: datetime | None = None


class SuccessResponse[T](BaseModel):
    data: T
    meta: ResponseMeta


class FieldError(BaseModel):
    field: str
    reason: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[FieldError] = Field(default_factory=list)
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorDetail
    meta: ResponseMeta


def build_meta(
    request: Request,
    *,
    revision: int | None = None,
    checked_at: datetime | None = None,
) -> ResponseMeta:
    return ResponseMeta(
        request_id=request.state.request_id,
        revision=revision,
        checked_at=checked_at,
    )


# successResponse[T] 자리에 기능별 응답 모델 넣으면 됨
