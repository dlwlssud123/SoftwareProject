from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.jobs.import_public_data import RECIPE_PROVIDER
from app.models import Recipe, RecipeRevision, SavedRecipe
from app.schemas.catalog import ContractModel, Page, PageQuery
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(
    prefix="/saved-recipes",
    tags=["saved-recipes"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 503)},
)
RecipeId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=64)]


class SavedRecipeItem(ContractModel):
    recipe_id: str
    name: str | None


class SavedRecipeState(ContractModel):
    saved: bool


def _recipe_key(recipe_id: str):
    return (Recipe.provider == RECIPE_PROVIDER, Recipe.source_id == recipe_id)


def _unavailable() -> AppError:
    return AppError(
        503,
        "SAVED_RECIPES_UNAVAILABLE",
        "저장한 레시피를 잠시 처리할 수 없어요.",
        retryable=True,
    )


def _state(
    request: Request, response: Response, saved: bool
) -> SuccessResponse[SavedRecipeState]:
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(data=SavedRecipeState(saved=saved), meta=build_meta(request))


@router.get("", response_model=SuccessResponse[Page[SavedRecipeItem]])
def list_saved_recipes(
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
    query: Annotated[PageQuery, Query()],
):
    stmt = (
        select(Recipe.source_id, RecipeRevision.name)
        .select_from(SavedRecipe)
        .join(Recipe, Recipe.id == SavedRecipe.recipe_id)
        .outerjoin(
            RecipeRevision,
            (RecipeRevision.id == Recipe.active_revision_id)
            & (RecipeRevision.quality_status != "hold"),
        )
        .where(SavedRecipe.user_id == auth.user.id, Recipe.provider == RECIPE_PROVIDER)
    )
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.execute(
            stmt.order_by(SavedRecipe.saved_at.desc(), Recipe.source_id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
    except SQLAlchemyError:
        raise _unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=Page(
            items=[
                SavedRecipeItem(recipe_id=recipe_id, name=name)
                for recipe_id, name in rows
            ],
            total=total,
            limit=query.limit,
            offset=query.offset,
        ),
        meta=build_meta(request),
    )


@router.get("/{recipe_id}", response_model=SuccessResponse[SavedRecipeState])
def get_saved_state(
    recipe_id: RecipeId,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        saved = (
            db.scalar(
                select(SavedRecipe.recipe_id)
                .join(Recipe, Recipe.id == SavedRecipe.recipe_id)
                .where(SavedRecipe.user_id == auth.user.id, *_recipe_key(recipe_id))
            )
            is not None
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return _state(request, response, saved)


@router.put(
    "/{recipe_id}",
    response_model=SuccessResponse[SavedRecipeState],
    responses={404: {"model": ErrorResponse}},
)
def save_recipe(
    recipe_id: RecipeId,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        active_id = db.scalar(
            select(Recipe.id)
            .join(RecipeRevision, RecipeRevision.id == Recipe.active_revision_id)
            .where(*_recipe_key(recipe_id), RecipeRevision.quality_status != "hold")
            .with_for_update(read=True, of=Recipe)
        )
        if active_id is None:
            raise AppError(404, "RECIPE_NOT_FOUND", "저장할 레시피를 찾을 수 없어요.")
        db.execute(
            insert(SavedRecipe)
            .values(user_id=auth.user.id, recipe_id=active_id)
            .on_conflict_do_nothing()
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _state(request, response, True)


@router.delete("/{recipe_id}", status_code=204)
def remove_recipe(recipe_id: RecipeId, auth: CurrentAuth, db: DbSession) -> Response:
    recipe_key = select(Recipe.id).where(*_recipe_key(recipe_id)).scalar_subquery()
    try:
        db.execute(
            delete(SavedRecipe).where(
                SavedRecipe.user_id == auth.user.id, SavedRecipe.recipe_id == recipe_key
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
