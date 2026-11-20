"""Private topic proposals and human moderation; never auto-publish user text."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AdminAuth, CurrentAuth, DbSession, unauthenticated
from app.core.errors import AppError
from app.models import ContentTopicRequest, LifeGuide, TopicRequestAudit, User
from app.schemas.catalog import Page, PageQuery
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.content import GuideSummary
from app.schemas.topic_requests import (
    AdminTopicRecord,
    TopicAuditRecord,
    TopicCreate,
    TopicCreated,
    TopicQuery,
    TopicRecord,
    TopicReview,
)

_errors = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 503)
}
router = APIRouter(
    prefix="/content-topic-requests", tags=["topic-requests"], responses=_errors
)
admin_router = APIRouter(
    prefix="/admin/content-topic-requests", tags=["admin"], responses=_errors
)


def _unavailable():
    return AppError(
        503,
        "TOPIC_REQUEST_UNAVAILABLE",
        "주제 요청을 잠시 처리할 수 없어요. 다시 시도해 주세요.",
        retryable=True,
    )


def _missing():
    return AppError(404, "TOPIC_REQUEST_NOT_FOUND", "요청을 찾을 수 없어요.")


def _state(row):
    return {
        "version": row.version,
        "status": row.status,
        "guide_id": str(row.guide_id) if row.guide_id else None,
    }


def _audit(db, request, auth, row, action, before):
    # No proposal text, reply, profile or authentication value is copied here.
    db.add(
        TopicRequestAudit(
            topic_request_id=row.id,
            actor_id=auth.user.id,
            action=action,
            before_state=before,
            after_state=_state(row),
            request_id=UUID(request.state.request_id),
        )
    )


def _public_guide(db, row):
    if row.guide_id is None:
        return None
    return db.scalar(
        select(LifeGuide).where(
            LifeGuide.id == row.guide_id,
            LifeGuide.is_published.is_(True),
            LifeGuide.review_status == "approved",
        )
    )


def _record(row, guide, *, admin=False):
    values = {
        name: getattr(row, name)
        for name in (
            "id",
            "kind",
            "topic",
            "status",
            "version",
            "reply",
            "created_at",
            "updated_at",
        )
    }
    values["guide"] = (
        None
        if guide is None
        else GuideSummary.model_validate(guide, from_attributes=True)
    )
    return (
        AdminTopicRecord(**values, guide_id=row.guide_id)
        if admin
        else TopicRecord(**values)
    )


def _result(request, db, row, *, admin=False):
    return SuccessResponse(
        data=_record(row, _public_guide(db, row), admin=admin), meta=build_meta(request)
    )


def _row(db, request_id, *, owner=None, lock=False, admin=False):
    stmt = select(ContentTopicRequest).where(ContentTopicRequest.id == request_id)
    if owner is not None:
        stmt = stmt.where(ContentTopicRequest.user_id == owner)
    row = db.scalar(
        stmt.with_for_update().execution_options(populate_existing=True)
        if lock
        else stmt
    )
    if row is None or (admin and row.status == "withdrawn"):
        raise _missing()
    return row


def _fingerprint(body):
    raw = json.dumps(
        body.model_dump(exclude={"submission_id"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post("", status_code=201, response_model=SuccessResponse[TopicCreated])
def create_topic(
    body: TopicCreate,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        # Serialize duplicate submissions and the rolling quota per owner. Never trust a client user ID.
        owner = db.scalar(
            select(User.id)
            .where(User.id == auth.user.id, User.disabled_at.is_(None))
            .with_for_update()
        )
        if owner is None:
            raise unauthenticated()
        fingerprint = _fingerprint(body)
        existing = db.scalar(
            select(ContentTopicRequest).where(
                ContentTopicRequest.user_id == owner,
                ContentTopicRequest.submission_id == body.submission_id,
            )
        )
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise AppError(
                    409,
                    "TOPIC_SUBMISSION_CHANGED",
                    "같은 전송 번호로 내용을 바꿀 수 없어요. 새 요청으로 작성해 주세요.",
                )
            response.status_code = 200
            result = SuccessResponse(
                data=TopicCreated(
                    request=_record(existing, _public_guide(db, existing)),
                    replayed=True,
                ),
                meta=build_meta(request),
            )
            db.commit()
            return result
        now = datetime.now(UTC)
        count, oldest = db.execute(
            select(func.count(), func.min(ContentTopicRequest.created_at)).where(
                ContentTopicRequest.user_id == owner,
                ContentTopicRequest.created_at > now - timedelta(days=1),
            )
        ).one()
        if count >= 5:
            remaining = max(
                1, math.ceil((oldest + timedelta(days=1) - now).total_seconds())
            )
            raise AppError(
                429,
                "TOPIC_REQUEST_LIMIT",
                "주제 요청은 24시간 동안 다섯 번까지 보낼 수 있어요. 잠시 후 다시 시도해 주세요.",
                retryable=True,
                headers={"Retry-After": str(remaining)},
            )
        row = ContentTopicRequest(
            user_id=owner,
            submission_id=body.submission_id,
            fingerprint=fingerprint,
            kind=body.kind,
            topic=body.topic,
            status="received",
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        _audit(db, request, auth, row, "create", None)
        result = SuccessResponse(
            data=TopicCreated(request=_record(row, None), replayed=False),
            meta=build_meta(request),
        )
        db.commit()
        return result
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None


def _list(db, query, *, owner=None, admin=False):
    table = ContentTopicRequest
    stmt = select(table, LifeGuide).outerjoin(
        LifeGuide,
        and_(
            table.guide_id == LifeGuide.id,
            LifeGuide.is_published.is_(True),
            LifeGuide.review_status == "approved",
        ),
    )
    if owner is not None:
        stmt = stmt.where(table.user_id == owner)
    if admin:
        stmt = stmt.where(table.status != "withdrawn")
    if query.kind:
        stmt = stmt.where(table.kind == query.kind)
    if query.status:
        stmt = stmt.where(table.status == query.status)
    if query.submission_id is not None:
        stmt = stmt.where(table.submission_id == query.submission_id)
    if query.q:
        stmt = stmt.where(table.topic.icontains(query.q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(table.created_at.desc(), table.id)
        .offset(query.offset)
        .limit(query.limit)
    ).all()
    return Page(
        items=[_record(row, guide, admin=admin) for row, guide in rows],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


@router.get("", response_model=SuccessResponse[Page[TopicRecord]])
def own_topics(
    request: Request,
    query: Annotated[TopicQuery, Query()],
    auth: CurrentAuth,
    db: DbSession,
):
    try:
        return SuccessResponse(
            data=_list(db, query, owner=auth.user.id), meta=build_meta(request)
        )
    except SQLAlchemyError:
        raise _unavailable() from None


@router.get("/{request_id}", response_model=SuccessResponse[TopicRecord])
def own_topic(request_id: UUID, request: Request, auth: CurrentAuth, db: DbSession):
    try:
        return _result(request, db, _row(db, request_id, owner=auth.user.id))
    except SQLAlchemyError:
        raise _unavailable() from None


@router.delete("/{request_id}", response_model=SuccessResponse[TopicRecord])
def withdraw_topic(
    request_id: UUID, request: Request, auth: CurrentAuth, db: DbSession
):
    try:
        row = _row(db, request_id, owner=auth.user.id, lock=True)
        if row.status != "withdrawn":
            before = _state(row)
            row.status, row.topic, row.reply, row.guide_id, row.reviewed_by = (
                "withdrawn",
                None,
                None,
                None,
                None,
            )
            row.version += 1
            row.updated_at = datetime.now(UTC)
            _audit(db, request, auth, row, "withdraw", before)
        result = _result(request, db, row)
        db.commit()
        return result
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None


@admin_router.get("", response_model=SuccessResponse[Page[AdminTopicRecord]])
def admin_topics(
    request: Request,
    query: Annotated[TopicQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    try:
        return SuccessResponse(
            data=_list(db, query, admin=True), meta=build_meta(request)
        )
    except SQLAlchemyError:
        raise _unavailable() from None


@admin_router.get("/{request_id}", response_model=SuccessResponse[AdminTopicRecord])
def admin_topic(request_id: UUID, request: Request, auth: AdminAuth, db: DbSession):
    try:
        return _result(request, db, _row(db, request_id, admin=True), admin=True)
    except SQLAlchemyError:
        raise _unavailable() from None


@admin_router.put("/{request_id}", response_model=SuccessResponse[AdminTopicRecord])
def review_topic(
    request_id: UUID,
    body: TopicReview,
    request: Request,
    auth: AdminAuth,
    db: DbSession,
):
    try:
        row = _row(db, request_id, lock=True, admin=True)
        if row.version != body.expected_version:
            raise AppError(
                409,
                "TOPIC_VERSION_CHANGED",
                "다른 관리자가 처리했어요. 최신 내용을 확인해 주세요.",
            )
        transitions = {
            "received": {"reviewing", "completed", "declined"},
            "reviewing": {"reviewing", "completed", "declined"},
            "completed": {"reviewing", "completed"},
            "declined": {"reviewing", "declined"},
        }
        if body.status not in transitions[row.status]:
            raise AppError(
                409, "TOPIC_STATUS_CHANGED", "먼저 검토 중으로 되돌린 뒤 처리해 주세요."
            )
        if (
            row.kind == "life_guide"
            and body.status == "completed"
            and body.guide_id is None
        ):
            raise AppError(
                422,
                "TOPIC_GUIDE_REQUIRED",
                "생활 가이드 요청을 완료하려면 검수 후 게시한 가이드를 연결해 주세요.",
            )
        if body.guide_id is not None:
            if row.kind != "life_guide":
                raise AppError(
                    422,
                    "TOPIC_GUIDE_KIND",
                    "생활 가이드 요청에만 가이드를 연결할 수 있어요.",
                )
            guide = db.scalar(
                select(LifeGuide.id)
                .where(
                    LifeGuide.id == body.guide_id,
                    LifeGuide.is_published.is_(True),
                    LifeGuide.review_status == "approved",
                )
                .with_for_update(read=True)
            )
            if guide is None:
                raise AppError(
                    409,
                    "TOPIC_GUIDE_UNAVAILABLE",
                    "검수 후 게시된 생활 가이드를 선택해 주세요.",
                )
        before = _state(row)
        row.status, row.reply, row.guide_id = body.status, body.reply, body.guide_id
        row.reviewed_by = auth.user.id
        row.updated_at = datetime.now(UTC)
        row.version += 1
        _audit(db, request, auth, row, "review", before)
        result = _result(request, db, row, admin=True)
        db.commit()
        return result
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None


@admin_router.get(
    "/{request_id}/audit", response_model=SuccessResponse[Page[TopicAuditRecord]]
)
def topic_audit(
    request_id: UUID,
    request: Request,
    query: Annotated[PageQuery, Query()],
    auth: AdminAuth,
    db: DbSession,
):
    try:
        _row(db, request_id, admin=True)
        stmt = select(TopicRequestAudit).where(
            TopicRequestAudit.topic_request_id == request_id
        )
        if query.q:
            stmt = stmt.where(
                TopicRequestAudit.action.icontains(query.q, autoescape=True)
            )
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(
            stmt.order_by(TopicRequestAudit.created_at.desc(), TopicRequestAudit.id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        return SuccessResponse(
            data=Page(
                items=[
                    TopicAuditRecord.model_validate(row, from_attributes=True)
                    for row in rows
                ],
                total=total,
                offset=query.offset,
                limit=query.limit,
            ),
            meta=build_meta(request),
        )
    except SQLAlchemyError:
        raise _unavailable() from None
