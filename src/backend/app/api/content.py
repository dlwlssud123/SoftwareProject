from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.recipes import active_recipes, recipe_record
from app.core.auth import DbSession
from app.core.errors import AppError
from app.models import (
    LifeGuide,
    MealFacility,
    Recipe,
    RecipeRevision,
    SeasonalFood,
    SeasonalRecipeLink,
)
from app.schemas.catalog import Page, PageQuery, RecipeListResponse
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.content import (
    FacilityPage,
    FacilityQuery,
    FacilityRecord,
    GuideDetail,
    GuideSummary,
    SeasonalDetail,
    SeasonalQuery,
    SeasonalSummary,
)
from app.services.content_catalog import (
    facility_candidates,
    facility_record,
    matching_facilities,
)

router = APIRouter(
    tags=["content"],
    responses={code: {"model": ErrorResponse} for code in (422, 503)},
)
KST = timezone(timedelta(hours=9))


def _unavailable() -> AppError:
    return AppError(
        503, "CONTENT_UNAVAILABLE", "안내 자료를 잠시 불러올 수 없어요.", retryable=True
    )


def _not_found() -> AppError:
    return AppError(404, "CONTENT_NOT_FOUND", "안내 자료를 찾을 수 없어요.")


def _page(db, stmt, query, order, record_type):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(*order).offset(query.offset).limit(query.limit)
    ).all()
    return Page(
        items=[record_type.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        offset=query.offset,
        limit=query.limit,
    )


def _seasonal(food: SeasonalFood | None) -> SeasonalFood:
    if food is None or not food.is_published or food.detail_status != "ok":
        raise _not_found()
    return food


@router.get("/meal-facilities", response_model=SuccessResponse[FacilityPage])
def list_facilities(
    request: Request, query: Annotated[FacilityQuery, Query()], db: DbSession
):
    stmt = select(MealFacility).where(MealFacility.is_published.is_(True))
    if query.q:
        stmt = stmt.where(
            or_(
                MealFacility.name.icontains(query.q, autoescape=True),
                MealFacility.address.icontains(query.q, autoescape=True),
            )
        )
    try:
        notes, items = matching_facilities(
            db.scalars(stmt).all(), query, datetime.now(KST).date()
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(
        data=FacilityPage(
            items=items[query.offset : query.offset + query.limit],
            total=len(items),
            limit=query.limit,
            offset=query.offset,
            warnings=notes,
        ),
        meta=build_meta(request),
    )


@router.get(
    "/meal-facilities/{facility_id}",
    response_model=SuccessResponse[FacilityRecord],
    responses={404: {"model": ErrorResponse}},
)
def get_facility(facility_id: UUID, request: Request, db: DbSession):
    try:
        row = db.get(MealFacility, facility_id)
    except SQLAlchemyError:
        raise _unavailable() from None
    if row is None or not row.is_published:
        raise _not_found()
    candidates = facility_candidates([row], datetime.now(KST).date())
    if not candidates:
        raise _not_found()
    return SuccessResponse(
        data=facility_record(candidates[0]), meta=build_meta(request)
    )


@router.get("/seasonal-foods", response_model=SuccessResponse[Page[SeasonalSummary]])
def list_seasonal(
    request: Request, query: Annotated[SeasonalQuery, Query()], db: DbSession
):
    month = query.month or datetime.now(KST).month
    stmt = select(SeasonalFood).where(
        SeasonalFood.is_published.is_(True),
        SeasonalFood.detail_status == "ok",
        SeasonalFood.month == month,
    )
    if query.q:
        stmt = stmt.where(SeasonalFood.name.icontains(query.q, autoescape=True))
    try:
        page = _page(
            db, stmt, query, (SeasonalFood.name, SeasonalFood.id), SeasonalSummary
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=page, meta=build_meta(request))


@router.get(
    "/seasonal-foods/{food_id}",
    response_model=SuccessResponse[SeasonalDetail],
    responses={404: {"model": ErrorResponse}},
)
def get_seasonal(food_id: UUID, request: Request, db: DbSession):
    try:
        row = _seasonal(db.get(SeasonalFood, food_id))
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(
        data=SeasonalDetail.model_validate(row, from_attributes=True),
        meta=build_meta(request),
    )


@router.get(
    "/seasonal-foods/{food_id}/recipes",
    response_model=RecipeListResponse,
    responses={404: {"model": ErrorResponse}},
)
def list_seasonal_recipes(
    food_id: UUID, request: Request, query: Annotated[PageQuery, Query()], db: DbSession
):
    try:
        _seasonal(db.get(SeasonalFood, food_id))
        stmt = (
            active_recipes()
            .join(
                SeasonalRecipeLink,
                (SeasonalRecipeLink.recipe_id == Recipe.id)
                & (SeasonalRecipeLink.recipe_revision_id == RecipeRevision.id),
            )
            .join(SeasonalFood, SeasonalFood.id == SeasonalRecipeLink.seasonal_food_id)
            .where(
                SeasonalFood.id == food_id,
                SeasonalFood.is_published.is_(True),
                SeasonalFood.detail_status == "ok",
            )
        )
        if query.q:
            stmt = stmt.where(RecipeRevision.name.icontains(query.q, autoescape=True))
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.execute(
            stmt.order_by(Recipe.source_id).offset(query.offset).limit(query.limit)
        ).all()
    except SQLAlchemyError:
        raise _unavailable() from None
    return RecipeListResponse(
        data=Page(
            items=[recipe_record(*row) for row in rows],
            total=total,
            offset=query.offset,
            limit=query.limit,
        ),
        meta=build_meta(request),
    )


@router.get("/life-guides", response_model=SuccessResponse[Page[GuideSummary]])
def list_guides(request: Request, query: Annotated[PageQuery, Query()], db: DbSession):
    stmt = select(LifeGuide).where(LifeGuide.is_published.is_(True))
    if query.q:
        stmt = stmt.where(LifeGuide.title.icontains(query.q, autoescape=True))
    try:
        page = _page(db, stmt, query, (LifeGuide.title, LifeGuide.slug), GuideSummary)
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=page, meta=build_meta(request))


@router.get(
    "/life-guides/{slug}",
    response_model=SuccessResponse[GuideDetail],
    responses={404: {"model": ErrorResponse}},
)
def get_guide(
    slug: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
    db: DbSession,
):
    try:
        row = db.scalar(
            select(LifeGuide).where(
                LifeGuide.slug == slug, LifeGuide.is_published.is_(True)
            )
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    if row is None:
        raise _not_found()
    return SuccessResponse(
        data=GuideDetail.model_validate(row, from_attributes=True),
        meta=build_meta(request),
    )
