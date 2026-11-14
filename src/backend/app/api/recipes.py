from typing import Annotated

from agetech_data.recipes.contract import to_api_record
from agetech_data.recipes.validate import check_recipe
from fastapi import APIRouter, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import DbSession
from app.core.errors import AppError
from app.jobs.import_public_data import RECIPE_PROVIDER
from app.models import DataImportRun, Recipe, RecipeRevision
from app.schemas.catalog import (
    Page,
    RecipeDetailResponse,
    RecipeListQuery,
    RecipeListResponse,
    RecipeRecord,
)
from app.schemas.common import ErrorResponse, build_meta

router = APIRouter(
    prefix="/recipes",
    tags=["recipes"],
    responses={code: {"model": ErrorResponse} for code in (422, 503)},
)


def active_recipes():
    return (
        select(Recipe, RecipeRevision, DataImportRun.inputs)
        .join(RecipeRevision, Recipe.active_revision_id == RecipeRevision.id)
        .join(DataImportRun, RecipeRevision.import_run_id == DataImportRun.id)
        .where(
            Recipe.provider == RECIPE_PROVIDER, RecipeRevision.quality_status != "hold"
        )
    )


def recipe_record(recipe: Recipe, revision: RecipeRevision, inputs: dict) -> RecipeRecord:
    source_meta = inputs.get("recipes", {}).get("meta", {})
    checked = check_recipe(revision.effective)
    data = to_api_record(checked, revision.effective, source_meta)
    data["source"].update(
        provider=recipe.provider,
        raw_sha256=revision.raw_sha256,
        revision_id=revision.id,
    )
    data["quality"]["status"] = revision.quality_status
    return RecipeRecord.model_validate(data)


def matches_allergies(record: RecipeRecord, excluded: set[str]) -> bool:
    allergens = record.allergens
    possible = {d.allergen for d in allergens.detected}
    possible.update(a for item in allergens.needs_check for a in item.candidates)
    possible.update(allergens.not_determinable)
    return allergens.complete and not excluded.intersection(possible)


def _unavailable() -> AppError:
    return AppError(
        503, "DATABASE_UNAVAILABLE", "레시피를 잠시 불러올 수 없습니다.", retryable=True
    )


@router.get("", response_model=RecipeListResponse)
def list_recipes(
    request: Request, query: Annotated[RecipeListQuery, Query()], db: DbSession
):
    stmt = active_recipes()
    if query.q:
        stmt = stmt.where(RecipeRevision.name.icontains(query.q, autoescape=True))
    if query.category:
        stmt = stmt.where(RecipeRevision.category == query.category)
    if query.cooking_method:
        stmt = stmt.where(RecipeRevision.method == query.cooking_method)
    ordered = stmt.order_by(Recipe.source_id)
    try:
        if query.exclude_allergens:
            excluded = set(query.exclude_allergens)
            matches = [
                record
                for row in db.execute(ordered)
                if matches_allergies(record := recipe_record(*row), excluded)
            ]
            total = len(matches)
            items = matches[query.offset : query.offset + query.limit]
        else:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            items = [
                recipe_record(*row)
                for row in db.execute(ordered.offset(query.offset).limit(query.limit))
            ]
    except SQLAlchemyError:
        raise _unavailable() from None
    return RecipeListResponse(
        data=Page(items=items, limit=query.limit, offset=query.offset, total=total),
        meta=build_meta(request),
    )


@router.get(
    "/{recipe_id}",
    response_model=RecipeDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_recipe(
    request: Request,
    recipe_id: Annotated[str, Path(pattern=r"^[0-9]+$", max_length=64)],
    db: DbSession,
):
    try:
        row = db.execute(
            active_recipes().where(Recipe.source_id == recipe_id)
        ).one_or_none()
    except SQLAlchemyError:
        raise _unavailable() from None
    if row is None:
        raise AppError(404, "RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다.")
    return RecipeDetailResponse(data=recipe_record(*row), meta=build_meta(request))
