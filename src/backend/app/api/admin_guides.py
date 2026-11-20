from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.auth import AdminAuth, DbSession
from app.core.errors import AppError
from app.models import GuideAuditEvent, LifeGuide
from app.schemas.catalog import Page, PageQuery
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.guide_management import (
    GuideAdminDetail,
    GuideAdminQuery,
    GuideAdminSummary,
    GuideAuditRecord,
    GuideCommand,
    GuideContent,
    GuideCreate,
    GuideEdit,
)

router = APIRouter(
    prefix="/admin/life-guides",
    tags=["admin"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


def _unavailable():
    return AppError(
        503,
        "GUIDE_ADMIN_UNAVAILABLE",
        "가이드 작업을 처리할 수 없어요. 다시 시도해 주세요.",
        retryable=True,
    )


def _guide(db, guide_id, *, lock=False):
    stmt = select(LifeGuide).where(LifeGuide.id == guide_id)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None:
        raise AppError(404, "GUIDE_NOT_FOUND", "가이드를 찾을 수 없어요.")
    return row


def _expect(row, version):
    if row.version != version:
        raise AppError(
            409,
            "GUIDE_VERSION_CHANGED",
            "다른 관리자가 수정했어요. 최신 내용을 확인해 주세요.",
        )


def _state(row):
    return {
        "version": row.version,
        "review_status": row.review_status,
        "is_published": row.is_published,
    }


def _audit(db, request, auth, row, action, before):
    # Record who changed state, never tokens, draft bodies, or free-form review notes.
    db.add(
        GuideAuditEvent(
            guide_id=row.id,
            actor_id=auth.user.id,
            action=action,
            before_state=before,
            after_state=_state(row),
            request_id=UUID(request.state.request_id),
        )
    )


def _result(request, row):
    return SuccessResponse(
        data=GuideAdminDetail.model_validate(row, from_attributes=True),
        meta=build_meta(request),
    )


def _page(db, stmt, query, model, ordering):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(*ordering).offset(query.offset).limit(query.limit)
    ).all()
    return Page(
        items=[model.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        offset=query.offset,
        limit=query.limit,
    )


@router.get("", response_model=SuccessResponse[Page[GuideAdminSummary]])
def list_guides(
    request: Request,
    query: Annotated[GuideAdminQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    stmt = select(LifeGuide)
    if query.review_status is not None:
        stmt = stmt.where(LifeGuide.review_status == query.review_status)
    if query.is_published is not None:
        stmt = stmt.where(LifeGuide.is_published == query.is_published)
    if query.q:
        stmt = stmt.where(LifeGuide.title.icontains(query.q, autoescape=True))
    try:
        data = _page(
            db,
            stmt,
            query,
            GuideAdminSummary,
            (LifeGuide.updated_at.desc(), LifeGuide.id),
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))


@router.post("", status_code=201, response_model=SuccessResponse[GuideAdminDetail])
def create_guide(request: Request, body: GuideCreate, auth: AdminAuth, db: DbSession):
    row = LifeGuide(
        **body.model_dump(exclude={"steps"}),
        steps=[step.model_dump(exclude_none=True) for step in body.steps],
        version=1,
        review_status="draft",
        is_published=False,
    )
    try:
        db.add(row)
        db.flush()
        _audit(db, request, auth, row, "create", None)
        result = _result(request, row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise AppError(
                409,
                "GUIDE_SLUG_EXISTS",
                "이미 사용 중인 가이드 주소예요. 다른 주소를 정해 주세요.",
            ) from None
        raise _unavailable() from None
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return result


@router.get("/{guide_id}", response_model=SuccessResponse[GuideAdminDetail])
def get_guide(guide_id: UUID, request: Request, auth: AdminAuth, db: DbSession):
    try:
        return _result(request, _guide(db, guide_id))
    except SQLAlchemyError:
        raise _unavailable() from None


@router.put("/{guide_id}", response_model=SuccessResponse[GuideAdminDetail])
def edit_guide(
    guide_id: UUID, body: GuideEdit, request: Request, auth: AdminAuth, db: DbSession
):
    try:
        row = _guide(db, guide_id, lock=True)
        _expect(row, body.expected_version)
        before = _state(row)
        for name, value in body.model_dump(
            exclude={"expected_version", "steps"}
        ).items():
            setattr(row, name, value)
        row.steps = [step.model_dump(exclude_none=True) for step in body.steps]
        row.is_published = False
        row.review_status = "draft"
        row.review_note = row.reviewed_by = row.reviewed_at = None
        row.updated_at = datetime.now(UTC)
        row.version += 1
        _audit(db, request, auth, row, "edit", before)
        result = _result(request, row)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return result


def _command(row, body, actor, now):
    action = body.action
    valid = {
        "submit": row.review_status in ("draft", "rejected") and not row.is_published,
        "approve": row.review_status == "review" and not row.is_published,
        "reject": row.review_status == "review" and not row.is_published,
        "publish": row.review_status == "approved" and not row.is_published,
        "unpublish": row.is_published,
    }
    if not valid[action]:
        raise AppError(
            409,
            "GUIDE_STATE_CHANGED",
            "현재 상태에서는 처리할 수 없어요. 최신 가이드 상태를 확인해 주세요.",
        )
    if action in ("submit", "approve", "publish"):
        try:
            GuideContent.model_validate(
                {key: getattr(row, key) for key in GuideContent.model_fields}
            )
        except ValidationError:
            raise AppError(
                409,
                "GUIDE_CONTENT_INVALID",
                "제목·단계·출처·확인일을 수정한 뒤 다시 검수해 주세요.",
            ) from None
    if action == "submit":
        row.review_status = "review"
        row.review_note = row.reviewed_by = row.reviewed_at = None
    elif action in ("approve", "reject"):
        row.review_status = "approved" if action == "approve" else "rejected"
        row.review_note = body.note
        row.reviewed_by = actor
        row.reviewed_at = now
    elif action == "publish":
        row.is_published = True
    else:
        row.is_published = False
    row.version += 1
    row.updated_at = now


@router.post("/{guide_id}/actions", response_model=SuccessResponse[GuideAdminDetail])
def guide_action(
    guide_id: UUID, body: GuideCommand, request: Request, auth: AdminAuth, db: DbSession
):
    try:
        row = _guide(db, guide_id, lock=True)
        _expect(row, body.expected_version)
        before = _state(row)
        _command(row, body, auth.user.id, datetime.now(UTC))
        _audit(db, request, auth, row, body.action, before)
        result = _result(request, row)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return result


@router.get("/{guide_id}/audit", response_model=SuccessResponse[Page[GuideAuditRecord]])
def guide_audit(
    guide_id: UUID,
    request: Request,
    query: Annotated[PageQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    stmt = select(GuideAuditEvent).where(GuideAuditEvent.guide_id == guide_id)
    if query.q:
        stmt = stmt.where(GuideAuditEvent.action.icontains(query.q, autoescape=True))
    try:
        data = _page(
            db,
            stmt,
            query,
            GuideAuditRecord,
            (GuideAuditEvent.created_at.desc(), GuideAuditEvent.id.desc()),
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))
