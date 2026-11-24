"""Authenticated text community with private reporting and mutual visibility blocks."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AdminAuth, CurrentAuth, DbSession, unauthenticated
from app.core.errors import AppError
from app.models import AuthSession, CommunityBlock, CommunityPost, CommunityReport, User
from app.schemas.catalog import Page, PageQuery
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.community import (
    AdminReport,
    BlockRecord,
    PostCreate,
    PostCreated,
    PostEdit,
    PostQuery,
    PostRecord,
    PostVersion,
    ReportCreate,
    ReportQuery,
    ReportReceipt,
    ReportResolve,
)

_errors = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 503)
}
router = APIRouter(prefix="/community", tags=["community"], responses=_errors)
admin_router = APIRouter(prefix="/admin/community", tags=["admin"], responses=_errors)


def _unavailable():
    return AppError(
        503,
        "COMMUNITY_UNAVAILABLE",
        "게시판을 잠시 이용할 수 없어요. 다시 시도해 주세요.",
        retryable=True,
    )


def _missing():
    return AppError(404, "COMMUNITY_NOT_FOUND", "글을 찾을 수 없어요.")


def _conflict():
    return AppError(
        409, "COMMUNITY_VERSION_CONFLICT", "글이 변경됐어요. 최신 내용을 확인해 주세요."
    )


@contextmanager
def _write(db):
    try:
        yield
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    except AppError:
        db.rollback()
        raise


def _lock_user(db, auth, *, admin=False):
    # Same identity-first ordering as account reset/disable and session refresh.
    user = db.scalar(
        select(User)
        .where(User.id == auth.user.id)
        # Serialize writes/disable while allowing other authors' FK KEY SHARE reads.
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    session = db.get(
        AuthSession, auth.session.id, populate_existing=True, with_for_update=True
    )
    now = datetime.now(UTC)
    if (
        user is None
        or user.disabled_at is not None
        or session is None
        or session.revoked_at is not None
        or session.expires_at <= now
    ):
        raise unauthenticated()
    if admin and user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "관리자 권한이 필요합니다.")


def _label(author_id):
    return f"이웃 {author_id.hex[:6]}"


def _post(row, viewer):
    return PostRecord(
        id=row.id,
        category=row.category,
        title=row.title,
        body=row.body,
        author_label=_label(row.author_id),
        is_mine=row.author_id == viewer,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _blocked(viewer):
    return exists(
        select(CommunityBlock.id).where(
            or_(
                (CommunityBlock.viewer_id == viewer)
                & (CommunityBlock.blocked_id == CommunityPost.author_id),
                (CommunityBlock.blocked_id == viewer)
                & (CommunityBlock.viewer_id == CommunityPost.author_id),
            )
        )
    )


def _visible(viewer, *, own=False):
    stmt = (
        select(CommunityPost)
        .join(User, User.id == CommunityPost.author_id)
        .where(User.disabled_at.is_(None))
    )
    if own:
        return stmt.where(
            CommunityPost.author_id == viewer, CommunityPost.status != "deleted"
        )
    return stmt.where(CommunityPost.status == "published", ~_blocked(viewer))


def _read_post(db, identifier, viewer, *, lock=False):
    stmt = (
        select(CommunityPost)
        .join(User, User.id == CommunityPost.author_id)
        .where(
            CommunityPost.id == identifier,
            User.disabled_at.is_(None),
            CommunityPost.status != "deleted",
            or_(
                CommunityPost.author_id == viewer,
                (CommunityPost.status == "published") & ~_blocked(viewer),
            ),
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=CommunityPost)
    row = db.scalar(stmt.execution_options(populate_existing=True))
    if row is None:
        raise _missing()
    return row


def _page(db, stmt, query, record):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
        .offset(query.offset)
        .limit(query.limit)
    )
    return Page(
        items=[record(row) for row in rows],
        total=total,
        offset=query.offset,
        limit=query.limit,
    )


@router.get("/posts", response_model=SuccessResponse[Page[PostRecord]])
def posts(
    request: Request,
    query: Annotated[PostQuery, Query()],
    db: DbSession,
    auth: CurrentAuth,
):
    try:
        stmt = _visible(auth.user.id)
        if query.category:
            stmt = stmt.where(CommunityPost.category == query.category)
        if query.q:
            stmt = stmt.where(
                or_(
                    CommunityPost.title.icontains(query.q, autoescape=True),
                    CommunityPost.body.icontains(query.q, autoescape=True),
                )
            )
        result = _page(db, stmt, query, lambda row: _post(row, auth.user.id))
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=result, meta=build_meta(request))


@router.get("/posts/mine", response_model=SuccessResponse[Page[PostRecord]])
def mine(
    request: Request,
    query: Annotated[PageQuery, Query()],
    db: DbSession,
    auth: CurrentAuth,
):
    try:
        result = _page(
            db,
            _visible(auth.user.id, own=True),
            query,
            lambda row: _post(row, auth.user.id),
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=result, meta=build_meta(request))


@router.post("/posts", status_code=201, response_model=SuccessResponse[PostCreated])
def create_post(
    request: Request,
    response: Response,
    payload: PostCreate,
    db: DbSession,
    auth: CurrentAuth,
):
    values = payload.model_dump(include={"category", "title", "body"})
    fingerprint = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    with _write(db):
        _lock_user(db, auth)
        row = db.scalar(
            select(CommunityPost).where(
                CommunityPost.author_id == auth.user.id,
                CommunityPost.submission_id == payload.submission_id,
            )
        )
        replayed = row is not None
        if replayed:
            if row.fingerprint != fingerprint:
                raise AppError(
                    409,
                    "COMMUNITY_SUBMISSION_CONFLICT",
                    "다른 내용으로 사용한 전송 번호예요. 새 글로 작성해 주세요.",
                )
            # A retry must not recreate a deleted post or reveal hidden text to others.
            if row.status == "deleted":
                raise _missing()
            response.status_code = 200
        else:
            count = db.scalar(
                select(func.count())
                .select_from(CommunityPost)
                .where(
                    CommunityPost.author_id == auth.user.id,
                    CommunityPost.created_at >= datetime.now(UTC) - timedelta(hours=24),
                )
            )
            if count >= 10:
                raise AppError(
                    429, "COMMUNITY_POST_LIMIT", "글은 하루에 10개까지 올릴 수 있어요."
                )
            row = CommunityPost(
                author_id=auth.user.id,
                submission_id=payload.submission_id,
                fingerprint=fingerprint,
                **values,
            )
            db.add(row)
            db.flush()
        result = PostCreated(post=_post(row, auth.user.id), replayed=replayed)
    return SuccessResponse(data=result, meta=build_meta(request))


@router.get("/posts/{post_id}", response_model=SuccessResponse[PostRecord])
def detail(request: Request, post_id: UUID, db: DbSession, auth: CurrentAuth):
    try:
        result = _post(_read_post(db, post_id, auth.user.id), auth.user.id)
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=result, meta=build_meta(request))


def _owned(db, auth, post_id, version):
    _lock_user(db, auth)
    row = _read_post(db, post_id, auth.user.id, lock=True)
    if row.author_id != auth.user.id:
        raise AppError(
            403, "COMMUNITY_OWNER_REQUIRED", "내가 쓴 글만 변경할 수 있어요."
        )
    if row.version != version:
        raise _conflict()
    return row


@router.patch("/posts/{post_id}", response_model=SuccessResponse[PostRecord])
def edit(
    request: Request, post_id: UUID, payload: PostEdit, db: DbSession, auth: CurrentAuth
):
    with _write(db):
        row = _owned(db, auth, post_id, payload.expected_version)
        for name in ("category", "title", "body"):
            setattr(row, name, getattr(payload, name))
        # Author edits cannot undo moderator hiding.
        row.version += 1
        row.updated_at = datetime.now(UTC)
        result = _post(row, auth.user.id)
    return SuccessResponse(data=result, meta=build_meta(request))


@router.delete("/posts/{post_id}", status_code=204)
def remove(post_id: UUID, payload: PostVersion, db: DbSession, auth: CurrentAuth):
    with _write(db):
        row = _owned(db, auth, post_id, payload.expected_version)
        row.title = row.body = ""
        row.status = "deleted"
        row.version += 1
        row.updated_at = datetime.now(UTC)
    return Response(status_code=204)


@router.post("/posts/{post_id}/reports", response_model=SuccessResponse[ReportReceipt])
def report(
    request: Request,
    post_id: UUID,
    payload: ReportCreate,
    db: DbSession,
    auth: CurrentAuth,
):
    with _write(db):
        _lock_user(db, auth)
        post = _read_post(db, post_id, auth.user.id, lock=True)
        if post.author_id == auth.user.id:
            raise AppError(
                422, "COMMUNITY_SELF_REPORT", "다른 사람의 글만 신고할 수 있어요."
            )
        row = db.scalar(
            select(CommunityReport).where(
                CommunityReport.post_id == post_id,
                CommunityReport.reporter_id == auth.user.id,
            )
        )
        if row is None:
            row = CommunityReport(
                post_id=post_id, reporter_id=auth.user.id, **payload.model_dump()
            )
            db.add(row)
            db.flush()
        result = ReportReceipt(id=row.id, status=row.status)
    return SuccessResponse(data=result, meta=build_meta(request))


@router.post(
    "/posts/{post_id}/block-author", response_model=SuccessResponse[BlockRecord]
)
def block(request: Request, post_id: UUID, db: DbSession, auth: CurrentAuth):
    with _write(db):
        _lock_user(db, auth)
        # Resolve only the author of a visible post; clients cannot submit arbitrary user IDs.
        post = db.scalar(
            select(CommunityPost).where(
                CommunityPost.id == post_id, CommunityPost.status == "published"
            )
        )
        if post is None:
            raise _missing()
        if post.author_id == auth.user.id:
            raise AppError(422, "COMMUNITY_SELF_BLOCK", "내 계정은 차단할 수 없어요.")
        row = db.scalar(
            select(CommunityBlock).where(
                CommunityBlock.viewer_id == auth.user.id,
                CommunityBlock.blocked_id == post.author_id,
            )
        )
        if row is None:
            _read_post(db, post_id, auth.user.id)
            row = CommunityBlock(viewer_id=auth.user.id, blocked_id=post.author_id)
            db.add(row)
            db.flush()
        result = BlockRecord(
            id=row.id, author_label=_label(row.blocked_id), created_at=row.created_at
        )
    return SuccessResponse(data=result, meta=build_meta(request))


@router.get("/blocks", response_model=SuccessResponse[Page[BlockRecord]])
def blocks(
    request: Request,
    query: Annotated[PageQuery, Query()],
    db: DbSession,
    auth: CurrentAuth,
):
    try:
        stmt = select(CommunityBlock).where(CommunityBlock.viewer_id == auth.user.id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(
            stmt.order_by(CommunityBlock.created_at.desc(), CommunityBlock.id.desc())
            .offset(query.offset)
            .limit(query.limit)
        )
        result = Page(
            items=[
                BlockRecord(
                    id=row.id,
                    author_label=_label(row.blocked_id),
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=total,
            offset=query.offset,
            limit=query.limit,
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=result, meta=build_meta(request))


@router.delete("/blocks/{block_id}", status_code=204)
def unblock(block_id: UUID, db: DbSession, auth: CurrentAuth):
    with _write(db):
        _lock_user(db, auth)
        row = db.scalar(
            select(CommunityBlock)
            .where(
                CommunityBlock.id == block_id, CommunityBlock.viewer_id == auth.user.id
            )
            .with_for_update()
        )
        if row is None:
            raise AppError(
                404, "COMMUNITY_BLOCK_NOT_FOUND", "차단 내역을 찾을 수 없어요."
            )
        db.delete(row)
    return Response(status_code=204)


def _admin_report(row, post, viewer):
    return AdminReport(
        id=row.id,
        status=row.status,
        reason=row.reason,
        note=row.note,
        post=_post(post, viewer),
        resolution=row.resolution,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


@admin_router.get("/reports", response_model=SuccessResponse[Page[AdminReport]])
def reports(
    request: Request,
    query: Annotated[ReportQuery, Query()],
    db: DbSession,
    auth: AdminAuth,
):
    try:
        stmt = select(CommunityReport, CommunityPost).join(
            CommunityPost, CommunityPost.id == CommunityReport.post_id
        )
        if query.status:
            stmt = stmt.where(CommunityReport.status == query.status)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.execute(
            stmt.order_by(CommunityReport.created_at, CommunityReport.id)
            .offset(query.offset)
            .limit(query.limit)
        )
        result = Page(
            items=[_admin_report(row, post, auth.user.id) for row, post in rows],
            total=total,
            offset=query.offset,
            limit=query.limit,
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    return SuccessResponse(data=result, meta=build_meta(request))


@admin_router.patch("/reports/{report_id}", response_model=SuccessResponse[AdminReport])
def resolve(
    request: Request,
    report_id: UUID,
    payload: ReportResolve,
    db: DbSession,
    auth: AdminAuth,
):
    with _write(db):
        _lock_user(db, auth, admin=True)
        report_row = db.scalar(
            select(CommunityReport)
            .where(CommunityReport.id == report_id)
            .with_for_update()
        )
        if report_row is None:
            raise AppError(
                404, "COMMUNITY_REPORT_NOT_FOUND", "신고 내역을 찾을 수 없어요."
            )
        post = db.get(
            CommunityPost,
            report_row.post_id,
            with_for_update=True,
            populate_existing=True,
        )
        if (
            report_row.status != "received"
            or post.version != payload.expected_post_version
        ):
            raise _conflict()
        if payload.decision == "hide":
            if post.status == "deleted":
                raise _conflict()
            post.status = "hidden"
            post.version += 1
            post.updated_at = datetime.now(UTC)
        report_row.status = "actioned" if payload.decision == "hide" else "dismissed"
        report_row.resolution = payload.resolution
        report_row.reviewer_id = auth.user.id
        report_row.reviewed_at = datetime.now(UTC)
        result = _admin_report(report_row, post, auth.user.id)
    return SuccessResponse(data=result, meta=build_meta(request))
