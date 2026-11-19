from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import AwareDatetime, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.api.welfare import ServiceId
from app.core.auth import CurrentAuth, DbSession
from app.core.errors import AppError
from app.models import SavedWelfareService, WelfareRevision, WelfareService
from app.schemas.catalog import ContractModel, Page, PageQuery
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.services.welfare_catalog import active_welfare, welfare_sources

router = APIRouter(
    prefix="/saved-welfare",
    tags=["saved-welfare"],
    responses={code: {"model": ErrorResponse} for code in (401, 422, 503)},
)


class SavedWelfareItem(ContractModel):
    service_id: str
    title: str | None


class SavedWelfareState(ContractModel):
    saved: bool


class WelfareNotePatch(ContractModel):
    note: str | None = Field(..., max_length=2000)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class WelfareNote(ContractModel):
    service_id: str
    note: str | None
    updated_at: AwareDatetime | None


def _key(service_id: str):
    return welfare_sources(), WelfareService.source_id == service_id


def _unavailable() -> AppError:
    return AppError(
        503,
        "SAVED_WELFARE_UNAVAILABLE",
        "저장한 복지 정보를 잠시 처리할 수 없어요.",
        retryable=True,
        headers={"Cache-Control": "no-store"},
    )


def _state(request: Request, response: Response, saved: bool):
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=SavedWelfareState(saved=saved), meta=build_meta(request)
    )


def _note_result(request, response, service_id, row):
    if row is None:
        raise AppError(
            404,
            "SAVED_WELFARE_NOT_FOUND",
            "먼저 본인 목록에 복지 서비스를 저장해 주세요.",
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=WelfareNote(service_id=service_id, note=row[0], updated_at=row[1]),
        meta=build_meta(request),
    )


@router.get(
    "/{service_id}/note",
    response_model=SuccessResponse[WelfareNote],
    responses={404: {"model": ErrorResponse}},
)
def get_welfare_note(
    service_id: ServiceId,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        row = db.execute(
            select(
                SavedWelfareService.progress_note, SavedWelfareService.note_updated_at
            )
            .join(WelfareService, WelfareService.id == SavedWelfareService.service_id)
            .where(SavedWelfareService.user_id == auth.user.id, *_key(service_id))
        ).one_or_none()
    except SQLAlchemyError:
        raise _unavailable() from None
    return _note_result(request, response, service_id, row)


@router.patch(
    "/{service_id}/note",
    response_model=SuccessResponse[WelfareNote],
    responses={404: {"model": ErrorResponse}},
)
def update_welfare_note(
    service_id: ServiceId,
    payload: WelfareNotePatch,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    # Notes belong to an existing saved row, even after the source is withdrawn.
    service_keys = select(WelfareService.id).where(*_key(service_id))
    try:
        row = db.execute(
            update(SavedWelfareService)
            .where(
                SavedWelfareService.user_id == auth.user.id,
                SavedWelfareService.service_id.in_(service_keys),
            )
            .values(progress_note=payload.note, note_updated_at=datetime.now(UTC))
            .returning(
                SavedWelfareService.progress_note, SavedWelfareService.note_updated_at
            )
        ).one_or_none()
        if row is None:
            db.rollback()
        else:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _note_result(request, response, service_id, row)


@router.get("", response_model=SuccessResponse[Page[SavedWelfareItem]])
def list_saved_welfare(
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
    query: Annotated[PageQuery, Query()],
):
    stmt = (
        select(WelfareService.source_id, WelfareRevision.title)
        .select_from(SavedWelfareService)
        .join(WelfareService, WelfareService.id == SavedWelfareService.service_id)
        .outerjoin(
            WelfareRevision,
            (WelfareRevision.id == WelfareService.active_revision_id)
            & (WelfareRevision.service_id == WelfareService.id)
            & (WelfareService.publication_status == "published")
            & (WelfareRevision.quality_status != "hold")
            & (WelfareRevision.detail_state == "ready"),
        )
        .where(SavedWelfareService.user_id == auth.user.id, welfare_sources())
    )
    if query.q:
        stmt = stmt.where(WelfareRevision.title.icontains(query.q, autoescape=True))
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.execute(
            stmt.order_by(SavedWelfareService.saved_at.desc(), WelfareService.source_id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
    except SQLAlchemyError:
        raise _unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=Page(
            items=[
                SavedWelfareItem(service_id=service_id, title=title)
                for service_id, title in rows
            ],
            total=total,
            limit=query.limit,
            offset=query.offset,
        ),
        meta=build_meta(request),
    )


@router.get("/{service_id}", response_model=SuccessResponse[SavedWelfareState])
def get_saved_welfare(
    service_id: ServiceId,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        saved = (
            db.scalar(
                select(SavedWelfareService.service_id)
                .join(
                    WelfareService, WelfareService.id == SavedWelfareService.service_id
                )
                .where(SavedWelfareService.user_id == auth.user.id, *_key(service_id))
            )
            is not None
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return _state(request, response, saved)


@router.put(
    "/{service_id}",
    response_model=SuccessResponse[SavedWelfareState],
    responses={404: {"model": ErrorResponse}},
)
def save_welfare(
    service_id: ServiceId,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        service = db.execute(
            active_welfare()
            .where(WelfareService.source_id == service_id)
            .with_for_update(read=True, of=WelfareService)
        ).one_or_none()
        if service is None:
            raise AppError(
                404, "WELFARE_NOT_FOUND", "저장할 복지 서비스를 찾을 수 없어요."
            )
        db.execute(
            insert(SavedWelfareService)
            .values(user_id=auth.user.id, service_id=service[0].id)
            .on_conflict_do_nothing()
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _state(request, response, True)


@router.delete("/{service_id}", status_code=204)
def remove_welfare(service_id: ServiceId, auth: CurrentAuth, db: DbSession) -> Response:
    service_keys = select(WelfareService.id).where(*_key(service_id))
    try:
        db.execute(
            delete(SavedWelfareService).where(
                SavedWelfareService.user_id == auth.user.id,
                SavedWelfareService.service_id.in_(service_keys),
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
