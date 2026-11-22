import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AdminAuth, DbSession
from app.core.errors import AppError
from app.jobs.import_meal_facilities import IMPORT_LOCK
from app.models import CatalogAuditEvent, MealFacility, SeasonalFood
from app.schemas.catalog import Page, PageQuery
from app.schemas.catalog_management import (
    CatalogAdminDetail,
    CatalogAdminQuery,
    CatalogAdminSummary,
    CatalogAuditRecord,
    CatalogKind,
    CatalogReviewCommand,
)
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.services.catalog_review import review_allows
from app.services.content_catalog import facility_candidates

router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)
MODELS = {"meal-facilities": MealFacility, "seasonal-foods": SeasonalFood}
FACILITY_FIELDS = (
    "sido",
    "sigungu",
    "address",
    "latitude",
    "longitude",
    "eligibility_text",
    "hours_text",
    "contact_text",
    "reference_date",
    "quality_flags",
    "normalized",
)
SEASONAL_FIELDS = (
    "month",
    "terms",
    "image_url",
    "detail",
    "detail_status",
    "official_related_recipes",
    "shopping_search_url",
    "links_sha256",
)


def _unavailable():
    return AppError(
        503,
        "CATALOG_ADMIN_UNAVAILABLE",
        "자료 검수 작업을 처리할 수 없어요. 다시 시도해 주세요.",
        retryable=True,
    )


def _row(db, kind, target_id, *, lock=False):
    model = MODELS[kind]
    stmt = select(model).where(model.id == target_id)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None:
        raise AppError(404, "CATALOG_NOT_FOUND", "검수할 자료를 찾을 수 없어요.")
    return row


def _content(row, kind):
    # Only public source fields, never credentials or unrelated importer inputs.
    fields = FACILITY_FIELDS if kind == "meal-facilities" else SEASONAL_FIELDS
    return json.loads(
        json.dumps({key: getattr(row, key) for key in fields}, default=str)
    )


def _revision(row, kind):
    source = {
        "name": row.name,
        "source_url": row.source_url,
        "provider": row.provider,
        "source_id": row.source_id,
        "checked_on": row.checked_on,
        "content_sha256": row.content_sha256,
        "is_published": row.is_published,
        "content": _content(row, kind),
    }
    return hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _source_available(row, kind):
    if not row.is_published:
        return False
    if kind == "seasonal-foods":
        return row.detail_status == "ok"
    return bool(
        facility_candidates([row], (datetime.now(UTC) + timedelta(hours=9)).date())
    )


def _record(row, kind, *, detail=False):
    fields = dict(
        id=row.id,
        kind=kind,
        name=row.name,
        provider=row.provider,
        source_id=row.source_id,
        source_url=row.source_url,
        checked_on=row.checked_on,
        content_sha256=row.content_sha256,
        source_run_id=row.last_seen_run_id,
        month=row.month if kind == "seasonal-foods" else None,
        sido=row.sido if kind == "meal-facilities" else None,
        sigungu=row.sigungu if kind == "meal-facilities" else None,
        source_revision=_revision(row, kind),
        source_is_published=row.is_published,
        is_published=_source_available(row, kind) and review_allows(row),
        review_version=row.review_version,
        review_status=row.review_status,
        review_required=row.review_status != "approved"
        or row.reviewed_content_sha256 != row.content_sha256,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        review_updated_at=row.review_updated_at,
    )
    if detail:
        return CatalogAdminDetail(
            **fields, review_note=row.review_note, content=_content(row, kind)
        )
    return CatalogAdminSummary(**fields)


def _state(row):
    return {
        "version": row.review_version,
        "status": row.review_status,
        "review_is_published": row.review_is_published,
        "source_is_published": row.is_published,
        "source_hash": row.content_sha256,
        "reviewed_hash": row.reviewed_content_sha256,
        "source_run_id": str(row.last_seen_run_id) if row.last_seen_run_id else None,
    }


def _https(value):
    try:
        url = urlsplit(value)
        return bool(
            url.scheme == "https"
            and url.hostname
            and url.username is None
            and url.password is None
            and url.port in (None, 443)
        )
    except (TypeError, ValueError):
        return False


def _can_approve(row, kind):
    today = (datetime.now(UTC) + timedelta(hours=9)).date()
    valid = (
        _source_available(row, kind)
        and bool(row.name.strip())
        and row.checked_on <= today
        and _https(row.source_url)
        and row.content_sha256 is not None
        and re.fullmatch(r"[0-9a-f]{64}", row.content_sha256) is not None
    )
    if kind == "seasonal-foods":
        try:
            url = urlsplit(row.shopping_search_url)
            valid = (
                valid
                and _https(row.shopping_search_url)
                and url.hostname == "www.coupang.com"
                and url.path == "/np/search"
                and not url.fragment
                and parse_qs(url.query, keep_blank_values=True, errors="strict")
                == {"q": [row.name]}
            )
        except (TypeError, ValueError, UnicodeError):
            valid = False
    if not valid:
        raise AppError(
            409,
            "CATALOG_SOURCE_UNAVAILABLE",
            "현재 원천 판본·운영 상태·출처·확인일을 점검한 뒤 다시 검수해 주세요.",
        )


def _command(row, kind, body, actor, now):
    if (
        row.review_version != body.expected_version
        or _revision(row, kind) != body.expected_revision
    ):
        raise AppError(
            409,
            "CATALOG_VERSION_CHANGED",
            "자료나 검수 상태가 바뀌었어요. 최신 내용을 확인해 주세요.",
        )
    status, visible = row.review_status, row.review_is_published
    current = row.reviewed_content_sha256 == row.content_sha256
    valid = {
        "submit": status in ("legacy", "rejected")
        or (status == "approved" and (not visible or not current)),
        "approve": status == "review",
        "reject": status == "review",
        "publish": status == "approved" and not visible and current,
        "unpublish": visible,
    }
    if not valid[body.action]:
        raise AppError(
            409,
            "CATALOG_STATE_CHANGED",
            "현재 상태에서는 처리할 수 없어요. 최신 검수 상태를 확인해 주세요.",
        )
    if body.action in ("approve", "publish"):
        _can_approve(row, kind)
    if body.action == "submit":
        row.review_status, row.review_is_published = "review", False
        row.review_note = row.reviewed_by = row.reviewed_at = (
            row.reviewed_content_sha256
        ) = None
    elif body.action in ("approve", "reject"):
        row.review_status = "approved" if body.action == "approve" else "rejected"
        row.review_is_published = False
        row.review_note, row.reviewed_by, row.reviewed_at = body.note, actor, now
        row.reviewed_content_sha256 = row.content_sha256
    else:
        row.review_is_published = body.action == "publish"
    row.review_version += 1
    row.review_updated_at = now


@router.get("/{kind}", response_model=SuccessResponse[Page[CatalogAdminSummary]])
def list_catalog(
    kind: CatalogKind,
    request: Request,
    query: Annotated[CatalogAdminQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    model = MODELS[kind]
    stmt = select(model)
    if query.q:
        stmt = stmt.where(model.name.icontains(query.q, autoescape=True))
    if query.review_status:
        stmt = stmt.where(model.review_status == query.review_status)
    if query.month is not None:
        if kind != "seasonal-foods":
            raise AppError(
                422,
                "CATALOG_MONTH_NOT_APPLICABLE",
                "월 검색은 제철 자료에서만 사용할 수 있어요.",
            )
        stmt = stmt.where(model.month == query.month)
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(
            stmt.order_by(model.review_updated_at.desc(), model.id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        data = Page(
            items=[_record(row, kind) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))


@router.get("/{kind}/{target_id}", response_model=SuccessResponse[CatalogAdminDetail])
def get_catalog(
    kind: CatalogKind, target_id: UUID, request: Request, auth: AdminAuth, db: DbSession
):
    try:
        data = _record(_row(db, kind, target_id), kind, detail=True)
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))


@router.post(
    "/{kind}/{target_id}/actions", response_model=SuccessResponse[CatalogAdminDetail]
)
def catalog_action(
    kind: CatalogKind,
    target_id: UUID,
    body: CatalogReviewCommand,
    request: Request,
    auth: AdminAuth,
    db: DbSession,
):
    try:
        # Same order as collectors: shared import lock, then source row lock.
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
        row = _row(db, kind, target_id, lock=True)
        before = _state(row)
        _command(row, kind, body, auth.user.id, datetime.now(UTC))
        db.add(
            CatalogAuditEvent(
                kind=kind,
                target_id=row.id,
                actor_id=auth.user.id,
                action=body.action,
                before_state=before,
                after_state=_state(row),
                request_id=UUID(request.state.request_id),
            )
        )
        data = _record(row, kind, detail=True)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))


@router.get(
    "/{kind}/{target_id}/audit",
    response_model=SuccessResponse[Page[CatalogAuditRecord]],
)
def catalog_audit(
    kind: CatalogKind,
    target_id: UUID,
    request: Request,
    query: Annotated[PageQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    stmt = select(CatalogAuditEvent).where(
        CatalogAuditEvent.kind == kind, CatalogAuditEvent.target_id == target_id
    )
    if query.q:
        stmt = stmt.where(CatalogAuditEvent.action.icontains(query.q, autoescape=True))
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(
            stmt.order_by(
                CatalogAuditEvent.created_at.desc(), CatalogAuditEvent.id.desc()
            )
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        data = Page(
            items=[
                CatalogAuditRecord.model_validate(row, from_attributes=True)
                for row in rows
            ],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=data, meta=build_meta(request))
