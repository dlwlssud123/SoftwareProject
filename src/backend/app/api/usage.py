"""Best-effort app telemetry is not a source of truth for user activity or audit."""

import hashlib
from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AdminAuth, CurrentAuth, DbSession
from app.core.errors import AppError
from app.models.usage import UsageEvent
from app.schemas.common import SuccessResponse, build_meta
from app.schemas.usage import (
    UsageAccepted,
    UsageBatch,
    UsagePage,
    UsagePruned,
    UsageQuery,
)

router = APIRouter(tags=["usage"])
RETENTION_DAYS = 30
DAILY_LIMIT = 4000


def prune(db, now=None):
    result = db.execute(
        delete(UsageEvent).where(
            UsageEvent.created_at
            < (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
        )
    )
    return result.rowcount


def unavailable():
    return AppError(
        503,
        "USAGE_UNAVAILABLE",
        "이용 현황을 잠시 처리할 수 없습니다.",
        retryable=True,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/usage-events", response_model=SuccessResponse[UsageAccepted])
def collect(
    request: Request,
    response: Response,
    payload: UsageBatch,
    auth: CurrentAuth,
    db: DbSession,
):
    # This domain-separated digest is not a login token. No user ID or raw auth session is stored.
    key = hashlib.sha256(b"usage-v1:" + auth.session.id.bytes).hexdigest()
    now = datetime.now(UTC)
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(key[:15], 16)}
        )
        existing = db.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(
                UsageEvent.collector_key == key,
                UsageEvent.created_at >= now - timedelta(days=1),
            )
        )
        known = set(
            db.scalars(
                select(UsageEvent.event_id).where(
                    UsageEvent.collector_key == key,
                    UsageEvent.event_id.in_([item.event_id for item in payload.events]),
                )
            )
        )
        new_ids = {item.event_id for item in payload.events} - known
        if existing + len(new_ids) > DAILY_LIMIT:
            raise AppError(
                429,
                "USAGE_RATE_LIMIT",
                "이용 기록 전송이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": "3600", "Cache-Control": "no-store"},
            )
        rows = [
            {**item.model_dump(), "collector_key": key, "created_at": now}
            for item in payload.events
        ]
        ids = db.scalars(
            insert(UsageEvent)
            .values(rows)
            .on_conflict_do_nothing()
            .returning(UsageEvent.event_id)
        ).all()
        prune(db, now)
        db.commit()
    except AppError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(data={"accepted": len(ids)}, meta=build_meta(request))


def scoped(query, now):
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    since = datetime.combine(
        today - timedelta(days=query.days - 1), time(), ZoneInfo("Asia/Seoul")
    )
    conditions = [UsageEvent.created_at >= since, UsageEvent.created_at <= now]
    if query.feature:
        conditions.append(UsageEvent.feature == query.feature)
    if query.outcome:
        conditions.append(UsageEvent.outcome == query.outcome)
    return conditions


@router.get("/admin/usage-events", response_model=SuccessResponse[UsagePage])
def dashboard(
    request: Request,
    response: Response,
    auth: AdminAuth,
    db: DbSession,
    query: Annotated[UsageQuery, Query()],
):
    now = datetime.now(UTC)
    conditions = scoped(query, now)
    try:
        # One repeatable snapshot keeps aggregate totals and the visible event page consistent.
        db.commit()
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        groups = (
            db.execute(
                select(
                    UsageEvent.feature,
                    UsageEvent.event,
                    UsageEvent.outcome,
                    func.count().label("count"),
                    func.avg(UsageEvent.duration_ms).label("avg_ms"),
                    func.sum(UsageEvent.duration_ms).label("total_ms"),
                )
                .where(*conditions)
                .group_by(UsageEvent.feature, UsageEvent.event, UsageEvent.outcome)
            )
            .mappings()
            .all()
        )
        daily = (
            db.execute(
                select(
                    func.date(func.timezone("Asia/Seoul", UsageEvent.created_at)).label(
                        "day"
                    ),
                    func.count().label("count"),
                )
                .where(*conditions)
                .group_by("day")
                .order_by("day")
            )
            .mappings()
            .all()
        )
        total = sum(row["count"] for row in groups)
        recent = db.scalars(
            select(UsageEvent)
            .where(*conditions)
            .order_by(UsageEvent.created_at.desc(), UsageEvent.event_id)
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        by_feature = {}
        for row in groups:
            item = by_feature.setdefault(
                row["feature"],
                {
                    "feature": row["feature"],
                    "events": 0,
                    "requests": 0,
                    "success": 0,
                    "failure": 0,
                    "cancelled": 0,
                    "duration_total": 0,
                },
            )
            item["events"] += row["count"]
            if row["event"] == "request_finished":
                item["requests"] += row["count"]
                item[row["outcome"]] += row["count"]
                item["duration_total"] += row["total_ms"] or 0
        features = []
        for item in by_feature.values():
            duration = item.pop("duration_total")
            features.append(
                {
                    **item,
                    "avg_ms": round(duration / item["requests"])
                    if item["requests"]
                    else None,
                }
            )
        events = [
            {
                field: getattr(event, field)
                for field in [
                    "event_id",
                    "created_at",
                    "event",
                    "feature",
                    "action",
                    "outcome",
                    "app_version",
                    "platform",
                    "duration_ms",
                    "error_kind",
                    "request_id",
                    "result_count",
                    "result_kind",
                    "setting_kind",
                    "setting_value",
                ]
            }
            for event in recent
        ]
        data = {
            "checked_at": now,
            "retention_days": RETENTION_DAYS,
            "total": total,
            "offset": query.offset,
            "limit": query.limit,
            "app_opens": sum(
                row["count"] for row in groups if row["event"] == "app_open"
            ),
            "features": sorted(features, key=lambda row: -row["events"]),
            "daily": [dict(row) for row in daily],
            "items": events,
        }
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(data=data, meta=build_meta(request))


@router.post("/admin/usage-events/prune", response_model=SuccessResponse[UsagePruned])
def cleanup(request: Request, response: Response, auth: AdminAuth, db: DbSession):
    try:
        removed = prune(db)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(data={"removed": removed}, meta=build_meta(request))
