from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    FieldError,
    build_meta,
)


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.headers = headers


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    fields: list[FieldError] | None = None,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            fields=fields or [],
            retryable=retryable,
        ),
        meta=build_meta(request),
    )

    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(
        request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        fields = [
            FieldError(
                field=".".join(str(part) for part in item["loc"]),
                reason=item["type"],
            )
            for item in exc.errors()
        ]

        return error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="입력값을 확인해 주세요.",
            fields=fields,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
            message="요청을 처리할 수 없습니다.",
            headers=exc.headers,
        )
