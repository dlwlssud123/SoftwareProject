from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import DbSession
from app.core.errors import AppError
from app.models import WelfareRevision, WelfareService
from app.schemas.catalog import (
    Page,
    Recommendation,
    RecommendationResult,
    WelfareDetailResponse,
    WelfareListQuery,
    WelfareListResponse,
    WelfareRecommendationRequest,
    WelfareRecommendationResponse,
)
from app.schemas.common import ErrorResponse, build_meta
from app.services.welfare_catalog import (
    RULES_VERSION,
    active_welfare,
    matching_services,
    recommend_services,
    welfare_record,
)

router = APIRouter(
    prefix="/welfare",
    tags=["welfare"],
    responses={code: {"model": ErrorResponse} for code in (422, 503)},
)
ServiceId = Annotated[str, Path(pattern=r"^WLF[0-9]+$", max_length=64)]
KST = timezone(timedelta(hours=9))


def unavailable() -> AppError:
    return AppError(
        503, "WELFARE_UNAVAILABLE", "복지 정보를 잠시 불러올 수 없어요.", retryable=True
    )


@router.get("", response_model=WelfareListResponse)
def list_welfare(
    request: Request,
    query: Annotated[WelfareListQuery, Query()],
    db: DbSession,
):
    stmt = active_welfare()
    if query.scope:
        stmt = stmt.where(WelfareService.scope == query.scope)
    if query.q:
        stmt = stmt.where(
            or_(
                *(
                    column.icontains(query.q, autoescape=True)
                    for column in (
                        WelfareRevision.title,
                        WelfareRevision.summary,
                        WelfareRevision.target_text,
                    )
                )
            )
        )
    try:
        _, matches = matching_services(
            db.execute(stmt).all(),
            query.region,
            query.district,
            datetime.now(KST).date(),
        )
    except SQLAlchemyError:
        raise unavailable() from None
    return WelfareListResponse(
        data=Page(
            items=[
                welfare_record(*row)
                for row, _, _ in matches[query.offset : query.offset + query.limit]
            ],
            limit=query.limit,
            offset=query.offset,
            total=len(matches),
        ),
        meta=build_meta(request),
    )


@router.post("/recommendations", response_model=WelfareRecommendationResponse)
def recommend_welfare(
    request: Request,
    response: Response,
    body: WelfareRecommendationRequest,
    db: DbSession,
):
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(UTC)
    try:
        notes, matches = matching_services(
            db.execute(active_welfare()).all(),
            body.region,
            body.district,
            now.astimezone(KST).date(),
        )
    except SQLAlchemyError:
        raise unavailable() from None
    ranked = recommend_services(matches, body.age, body.lives_alone)
    warnings = [
        "확인해 볼 만한 복지 사업 안내예요. 수급 자격이나 현재 신청 가능 여부를 확정하지 않아요.",
        "연령·가구 관련 원문은 정렬에만 사용해요. 소득 등 세부 요건은 공식 안내나 문의처에서 확인해 주세요.",
        *notes,
    ]
    if body.age < 65:
        warnings.append(
            "현재 자료는 노년층 관련 사업 중심으로 수집되어 다른 연령의 사업은 빠질 수 있어요."
        )
    return WelfareRecommendationResponse(
        data=RecommendationResult(
            items=[
                Recommendation(item=welfare_record(*row), reasons=reasons)
                for row, reasons in ranked[: body.limit]
            ],
            evaluated_at=now,
            rules_version=RULES_VERSION,
            warnings=warnings,
        ),
        meta=build_meta(request),
    )


@router.get(
    "/{service_id}",
    response_model=WelfareDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_welfare(service_id: ServiceId, request: Request, db: DbSession):
    try:
        row = db.execute(
            active_welfare().where(WelfareService.source_id == service_id)
        ).one_or_none()
    except SQLAlchemyError:
        raise unavailable() from None
    if row is None:
        raise AppError(404, "WELFARE_NOT_FOUND", "복지 서비스를 찾을 수 없어요.")
    return WelfareDetailResponse(data=welfare_record(*row), meta=build_meta(request))
