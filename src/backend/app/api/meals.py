"""User-confirmed intake records, calculated on the server and isolated by owner."""

import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from agetech_data.nutrition.portion import Portion, meal_total
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import Food, FoodRevision, MealCreateRequest, MealLog, MealLogItem
from app.schemas.catalog import NutrientAmounts, Page
from app.schemas.common import ErrorResponse, build_meta
from app.schemas.meal_record import (
    MealCreate,
    MealCreateResponse,
    MealCreateResult,
    MealItemRecord,
    MealListQuery,
    MealListResponse,
    MealRecord,
    MealResponse,
    MealSummary,
    MealUpdate,
)
from app.services.food_nutrition import calculate_portions

router = APIRouter(
    prefix="/meals",
    tags=["meals"],
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 503)},
)
NO_STORE = {"Cache-Control": "no-store"}
IdempotencyKey = Annotated[
    str, Header(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


def unavailable():
    return AppError(
        503,
        "MEALS_UNAVAILABLE",
        "식사 기록을 잠시 처리할 수 없습니다.",
        retryable=True,
        headers=NO_STORE,
    )


def not_found():
    return AppError(
        404, "MEAL_NOT_FOUND", "식사 기록을 찾을 수 없습니다.", headers=NO_STORE
    )


def owned_meal(db, user_id, meal_id, *, read=False):
    meal = db.scalar(
        select(MealLog)
        .where(MealLog.id == meal_id, MealLog.user_id == user_id)
        .with_for_update(read=read)
        .execution_options(populate_existing=True)
    )
    if meal is None:
        raise not_found()
    return meal


def check_version(meal, expected):
    if meal.version != expected:
        raise AppError(
            409,
            "MEAL_VERSION_CHANGED",
            "식사 기록이 변경되었습니다. 다시 열어 주세요.",
            headers=NO_STORE,
        )


def record_items(db, meal_ids):
    grouped = {meal_id: [] for meal_id in meal_ids}
    if not grouped:
        return grouped
    rows = db.execute(
        select(MealLogItem, FoodRevision, Food)
        .join(FoodRevision, FoodRevision.id == MealLogItem.food_revision_id)
        .join(Food, Food.id == FoodRevision.food_id)
        .where(MealLogItem.meal_log_id.in_(meal_ids))
        .order_by(MealLogItem.order_no.asc().nulls_last(), MealLogItem.id)
    )
    for item, revision, food in rows:
        grouped[item.meal_log_id].append(
            MealItemRecord(
                food_id=food.id,
                revision_id=revision.id,
                food_code=food.food_code,
                name=revision.name,
                order_no=item.order_no,
                amount=item.amount,
                amount_unit=item.amount_unit,
                nutrients={
                    key: item.nutrients.get(key) for key in NutrientAmounts.model_fields
                },
                calculation_version=item.calculation_version,
                calculation=item.portion_snapshot,
            )
        )
    return grouped


def record(meal, items):
    portions = [
        Portion(
            "computed",
            item.food_code,
            item.name,
            {"amount": item.amount, "unit": item.amount_unit},
            nutrients=item.nutrients.model_dump(),
            approx_ml=bool(item.calculation and item.calculation.approx_ml),
        )
        for item in items
    ]
    return MealRecord(
        id=meal.id,
        eaten_at=meal.eaten_at,
        created_at=meal.created_at,
        version=meal.version,
        items=items,
        total=meal_total(portions),
        legacy_snapshot_missing=any(item.calculation is None for item in items),
    )


def replace_items(db, meal, selections):
    calculation = calculate_portions(db, selections, lock=True)
    for portion in calculation.items:
        amount = Decimal(str(portion.amount)) if portion.amount is not None else None
        if (
            portion.status not in ("computed", "approx_ml")
            or amount is None
            or not Decimal("0.001") <= amount <= Decimal("9999999.999")
            or amount != amount.quantize(Decimal("0.001"))
        ):
            raise AppError(
                422,
                "PORTION_NOT_RECORDABLE",
                "분량을 g 또는 mL로 다시 확인해 주세요.",
                headers=NO_STORE,
            )
    db.execute(delete(MealLogItem).where(MealLogItem.meal_log_id == meal.id))
    for order_no, portion in enumerate(calculation.items, 1):
        db.add(
            MealLogItem(
                meal_log_id=meal.id,
                food_revision_id=portion.source.revision_id,
                amount=Decimal(str(portion.amount)),
                amount_unit=portion.amount_unit,
                nutrients=portion.nutrients.model_dump(),
                calculation_version=calculation.calculation_version,
                order_no=order_no,
                portion_snapshot=portion.model_dump(mode="json"),
            )
        )
    db.flush()


@router.post("", status_code=201, response_model=MealCreateResponse)
def create_meal(
    request: Request,
    response: Response,
    body: MealCreate,
    idempotency_key: IdempotencyKey,
    auth: CurrentAuth,
    db: DbSession,
):
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    request_hash = hashlib.sha256(
        json.dumps(
            body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    try:
        claimed = db.scalar(
            insert(MealCreateRequest)
            .values(
                user_id=auth.user.id,
                key_hash=key_hash,
                request_hash=request_hash,
            )
            .on_conflict_do_nothing()
            .returning(MealCreateRequest.key_hash)
        )
        replayed = claimed is None
        receipt = db.get(
            MealCreateRequest, (auth.user.id, key_hash), populate_existing=True
        )
        if replayed:
            if receipt.request_hash != request_hash:
                raise AppError(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "변경된 식사는 새 저장 요청으로 보내 주세요.",
                    headers=NO_STORE,
                )
            if receipt.meal_log_id is None:
                raise AppError(
                    409,
                    "MEAL_ALREADY_DELETED",
                    "이미 삭제한 기록의 저장 요청입니다.",
                    headers=NO_STORE,
                )
            # Do not hold a receipt row lock while locking the meal: deletion updates its FK.
            try:
                meal = owned_meal(db, auth.user.id, receipt.meal_log_id, read=True)
            except AppError:
                raise AppError(
                    409,
                    "MEAL_ALREADY_DELETED",
                    "이미 삭제한 기록의 저장 요청입니다.",
                    headers=NO_STORE,
                ) from None
        else:
            meal = MealLog(user_id=auth.user.id, eaten_at=body.eaten_at)
            db.add(meal)
            db.flush()
            replace_items(db, meal, body.items)
            receipt.meal_log_id = meal.id
            db.flush()
        data = record(meal, record_items(db, [meal.id])[meal.id])
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    response.status_code = 200 if replayed else 201
    return MealCreateResponse(
        data=MealCreateResult(meal=data, replayed=replayed), meta=build_meta(request)
    )


@router.get("", response_model=MealListResponse)
def list_meals(
    request: Request,
    query: Annotated[MealListQuery, Query()],
    auth: CurrentAuth,
    db: DbSession,
):
    stmt = select(MealLog).where(MealLog.user_id == auth.user.id)
    if query.day:
        start = datetime.combine(query.day, time.min, tzinfo=ZoneInfo("Asia/Seoul"))
        stmt = stmt.where(
            MealLog.eaten_at >= start, MealLog.eaten_at < start + timedelta(days=1)
        )
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        meals = db.scalars(
            stmt.order_by(MealLog.eaten_at.desc(), MealLog.id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        items = record_items(db, [meal.id for meal in meals])
        summaries = [
            MealSummary.model_validate(
                record(meal, items[meal.id]).model_dump(exclude={"items"})
            )
            for meal in meals
        ]
    except SQLAlchemyError:
        raise unavailable() from None
    return MealListResponse(
        data=Page(items=summaries, total=total, limit=query.limit, offset=query.offset),
        meta=build_meta(request),
    )


@router.get("/{meal_id}", response_model=MealResponse)
def get_meal(request: Request, meal_id: UUID, auth: CurrentAuth, db: DbSession):
    try:
        meal = owned_meal(db, auth.user.id, meal_id, read=True)
        data = record(meal, record_items(db, [meal.id])[meal.id])
    except SQLAlchemyError:
        raise unavailable() from None
    return MealResponse(data=data, meta=build_meta(request))


@router.patch("/{meal_id}", response_model=MealResponse)
def update_meal(
    request: Request, meal_id: UUID, body: MealUpdate, auth: CurrentAuth, db: DbSession
):
    try:
        meal = owned_meal(db, auth.user.id, meal_id)
        check_version(meal, body.expected_version)
        if body.items is not None:
            replace_items(db, meal, body.items)
        if body.eaten_at is not None:
            meal.eaten_at = body.eaten_at
        meal.version += 1
        db.flush()
        data = record(meal, record_items(db, [meal.id])[meal.id])
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    return MealResponse(data=data, meta=build_meta(request))


@router.delete("/{meal_id}", status_code=204)
def delete_meal(
    meal_id: UUID,
    version: Annotated[int, Query(ge=1)],
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        meal = owned_meal(db, auth.user.id, meal_id)
        check_version(meal, version)
        db.delete(meal)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    return Response(status_code=204, headers=NO_STORE)
