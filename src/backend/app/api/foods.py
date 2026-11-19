"""Query imported active foods and reuse the data team's portion calculator."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import DbSession
from app.core.errors import AppError
from app.models import Food, FoodRevision
from app.schemas.catalog import NutrientAmounts, Page, PageQuery
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.nutrition import (
    FoodDetailResponse,
    FoodListResponse,
    FoodRecord,
    NutritionCalculationRequest,
    NutritionCalculationResponse,
)
from app.services.food_nutrition import active_foods, calculate_portions, source_record

router = APIRouter(
    tags=["nutrition"],
    responses={code: {"model": ErrorResponse} for code in (404, 422, 503)},
)
NO_STORE = {"Cache-Control": "no-store"}


def food_record(food, revision, imported_at):
    normalized = revision.normalized
    return FoodRecord(
        food_id=food.id,
        name=revision.name,
        category=normalized.get("category1"),
        basis={
            "amount": revision.basis_amount,
            "unit": revision.basis_unit,
            "text": revision.basis_text,
        },
        nutrients={
            key: revision.nutrients.get(key) for key in NutrientAmounts.model_fields
        },
        serving_ref_text=normalized.get("serving_ref_text"),
        dish_serving_text=normalized.get("dish_serving_text"),
        quality_flags=revision.quality_flags,
        source=source_record(food, revision, imported_at),
    )


def unavailable():
    return AppError(
        503,
        "FOODS_UNAVAILABLE",
        "식품 정보를 불러올 수 없습니다.",
        retryable=True,
        headers=NO_STORE,
    )


@router.get("/foods", response_model=FoodListResponse)
def list_foods(request: Request, query: Annotated[PageQuery, Query()], db: DbSession):
    stmt = active_foods()
    if query.q:
        stmt = stmt.where(FoodRevision.name.icontains(query.q, autoescape=True))
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.execute(
            stmt.order_by(FoodRevision.name, Food.food_code, Food.id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
    except SQLAlchemyError:
        raise unavailable() from None
    return FoodListResponse(
        data=Page(
            items=[food_record(*row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        ),
        meta=build_meta(request),
    )


@router.get("/foods/{food_id}", response_model=FoodDetailResponse)
def get_food(request: Request, food_id: UUID, db: DbSession):
    try:
        row = db.execute(active_foods().where(Food.id == food_id)).one_or_none()
    except SQLAlchemyError:
        raise unavailable() from None
    if row is None:
        raise AppError(404, "FOOD_NOT_FOUND", "식품을 찾을 수 없습니다.")
    return FoodDetailResponse(data=food_record(*row), meta=build_meta(request))


@router.post(
    "/nutrition/calculate",
    response_model=NutritionCalculationResponse,
    responses={409: {"model": ErrorResponse}},
)
def calculate_nutrition(
    request: Request,
    response: Response,
    body: NutritionCalculationRequest,
    db: DbSession,
):
    response.headers.update(NO_STORE)
    try:
        calculation = calculate_portions(db, body.items)
    except SQLAlchemyError:
        raise unavailable() from None
    return NutritionCalculationResponse(
        data=calculation,
        meta=build_meta(request),
    )
