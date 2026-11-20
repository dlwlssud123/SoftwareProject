from typing import Annotated

from fastapi import APIRouter, Path, Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import ShoppingCheck
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.meal_plan import PlanDate
from app.schemas.shopping import (
    ShoppingCheckResponse,
    ShoppingCheckState,
    ShoppingCheckUpdate,
    ShoppingResponse,
)
from app.services.meal_plan_storage import lock_plan_owner
from app.services.shopping import build_shopping_list

router = APIRouter(
    prefix="/shopping-lists",
    tags=["shopping"],
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 503)},
)
ItemKey = Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]
NO_STORE = {"Cache-Control": "no-store"}


def unavailable():
    return AppError(
        503,
        "SHOPPING_UNAVAILABLE",
        "장보기 목록을 잠시 처리할 수 없어요.",
        retryable=True,
        headers=NO_STORE,
    )


@router.get("/{plan_date}", response_model=ShoppingResponse)
def get_shopping(
    plan_date: PlanDate, request: Request, auth: CurrentAuth, db: DbSession
):
    try:
        lock_plan_owner(db, auth.user.id, read=True)
        data = build_shopping_list(db, auth.user.id, plan_date)
    except SQLAlchemyError:
        raise unavailable() from None
    return ShoppingResponse(data=data, meta=build_meta(request))


@router.patch("/{plan_date}/items/{item_key}", response_model=ShoppingCheckResponse)
def check_shopping(
    plan_date: PlanDate,
    item_key: ItemKey,
    payload: ShoppingCheckUpdate,
    request: Request,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        lock_plan_owner(db, auth.user.id)
        current = next(
            (
                item
                for item in build_shopping_list(db, auth.user.id, plan_date).items
                if item.item_key == item_key
            ),
            None,
        )
        if current is None:
            raise AppError(
                404,
                "SHOPPING_ITEM_NOT_FOUND",
                "장보기 항목을 찾을 수 없어요.",
                headers=NO_STORE,
            )
        if current.source_hash != payload.source_hash:
            raise AppError(
                409,
                "SHOPPING_LIST_CHANGED",
                "식단이나 재료가 바뀌었어요. 목록을 다시 확인해 주세요.",
                headers=NO_STORE,
            )
        db.execute(
            insert(ShoppingCheck)
            .values(
                user_id=auth.user.id,
                plan_date=plan_date,
                item_key=item_key,
                source_hash=payload.source_hash,
                checked=payload.checked,
            )
            .on_conflict_do_update(
                index_elements=[
                    ShoppingCheck.user_id,
                    ShoppingCheck.plan_date,
                    ShoppingCheck.item_key,
                ],
                set_={"source_hash": payload.source_hash, "checked": payload.checked},
            )
        )
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    return ShoppingCheckResponse(
        data=ShoppingCheckState(
            item_key=item_key, source_hash=payload.source_hash, checked=payload.checked
        ),
        meta=build_meta(request),
    )
