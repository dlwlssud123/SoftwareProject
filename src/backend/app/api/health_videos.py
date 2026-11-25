from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.core.errors import AppError
from app.schemas.catalog import Page
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.health_video import HealthVideo, HealthVideoQuery
from app.services.health_videos import published_videos

router = APIRouter(
    prefix="/health-videos",
    tags=["content"],
    responses={code: {"model": ErrorResponse} for code in (404, 422, 503)},
)


def _catalog():
    try:
        return published_videos()
    except (OSError, ValueError, TypeError):
        raise AppError(
            503,
            "VIDEO_CATALOG_UNAVAILABLE",
            "건강 영상을 불러오지 못했어요. 잠시 후 다시 확인해 주세요.",
            retryable=True,
        ) from None


@router.get("", response_model=SuccessResponse[Page[HealthVideo]])
def list_videos(request: Request, query: Annotated[HealthVideoQuery, Query()]):
    rows = [
        row for row in _catalog() if query.topic is None or row.topic == query.topic
    ]
    return SuccessResponse(
        data=Page(
            items=rows[query.offset : query.offset + query.limit],
            total=len(rows),
            limit=query.limit,
            offset=query.offset,
        ),
        meta=build_meta(request),
    )


@router.get("/{video_id}", response_model=SuccessResponse[HealthVideo])
def video_detail(
    request: Request,
    video_id: Annotated[
        str, Path(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)
    ],
):
    row = next((row for row in _catalog() if row.id == video_id), None)
    if row is None:
        raise AppError(404, "VIDEO_NOT_FOUND", "지금은 제공하지 않는 영상이에요.")
    return SuccessResponse(data=row, meta=build_meta(request))
