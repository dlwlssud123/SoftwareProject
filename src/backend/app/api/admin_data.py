from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AdminAuth, DbSession
from app.core.errors import AppError
from app.jobs.daily_refresh import KIND
from app.models import JobRun
from app.schemas.catalog import Page
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.content import DataJobQuery, DataJobRecord

router = APIRouter(
    prefix="/admin/data-jobs",
    tags=["admin"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 422, 503)},
)


@router.get("", response_model=SuccessResponse[Page[DataJobRecord]])
def list_data_jobs(
    request: Request,
    response: Response,
    auth: AdminAuth,
    db: DbSession,
    query: Annotated[DataJobQuery, Query()],
):
    # User-owned jobs (including any future photo/AI tasks) are not collection jobs.
    stmt = select(JobRun).where(JobRun.kind == KIND, JobRun.user_id.is_(None))
    if query.status:
        stmt = stmt.where(JobRun.status == query.status)
    if query.q:
        stmt = stmt.where(JobRun.error_code.icontains(query.q, autoescape=True))
    try:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        jobs = db.scalars(
            stmt.order_by(JobRun.created_at.desc(), JobRun.id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
    except SQLAlchemyError:
        raise AppError(
            503,
            "DATA_JOBS_UNAVAILABLE",
            "수집 현황을 잠시 불러올 수 없어요.",
            retryable=True,
            headers={"Cache-Control": "no-store"},
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=Page(
            items=[
                DataJobRecord.model_validate(job, from_attributes=True) for job in jobs
            ],
            total=total,
            offset=query.offset,
            limit=query.limit,
        ),
        meta=build_meta(request),
    )
