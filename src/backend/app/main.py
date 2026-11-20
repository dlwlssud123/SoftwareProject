import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.admin_data import router as admin_data_router
from app.api.admin_guides import router as admin_guides_router
from app.api.auth import router as auth_router
from app.api.content import router as content_router
from app.api.foods import router as foods_router
from app.api.health import router as health_router
from app.api.meal import router as meal_router
from app.api.meal_plans import router as meal_plans_router
from app.api.meals import router as meals_router
from app.api.profile import router as profile_router
from app.api.recipes import router as recipes_router
from app.api.saved_recipes import router as saved_recipes_router
from app.api.saved_welfare import router as saved_welfare_router
from app.api.shopping import router as shopping_router
from app.api.welfare import router as welfare_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import error_response, register_error_handlers

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    register_error_handlers(app)

    @app.middleware("http")
    async def track_request(request: Request, call_next):
        request.state.request_id = str(uuid4())

        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - Keep internal failures out of API responses.
            logger.error(
                "Unhandled error request_id=%s exception_type=%s",
                request.state.request_id,
                type(exc).__name__,
            )

            response = error_response(
                request,
                status_code=500,
                code="INTERNAL_SERVER_ERROR",
                message="서버 오류가 발생했습니다.",
            )

        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/v1/admin/"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/api/v1/shopping-lists/"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/api/v1/meals" or request.url.path.startswith(
            "/api/v1/meals/"
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(foods_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(admin_data_router, prefix="/api/v1")
    app.include_router(admin_guides_router, prefix="/api/v1")
    app.include_router(content_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(recipes_router, prefix="/api/v1")
    app.include_router(meal_router, prefix="/api/v1")
    app.include_router(meals_router, prefix="/api/v1")
    app.include_router(shopping_router, prefix="/api/v1")
    app.include_router(meal_plans_router, prefix="/api/v1")
    app.include_router(saved_recipes_router, prefix="/api/v1")
    app.include_router(welfare_router, prefix="/api/v1")
    app.include_router(saved_welfare_router, prefix="/api/v1")

    return app


app = create_app()
