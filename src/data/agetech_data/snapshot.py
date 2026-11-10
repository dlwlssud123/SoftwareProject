"""갱신 수집본(meta.fetched_at) 시각 처리 — DB 적재 행 변환(facilities·seasonal revision)이 같이 쓴다."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def aware_time(value: str) -> datetime:
    """ISO 시각 → UTC. 시간대가 없는 값은 받지 않는다(수집 시각을 잘못 읽어 판단 기준일이 하루 밀리는 것 방지)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Collection timestamps require a timezone")
    return parsed.astimezone(UTC)


def collected_on(meta: dict) -> date:
    """수집 시각(meta.fetched_at) → 수집 날짜(KST). 실행 날짜 대신 판단 기준일·확인일로 쓴다."""
    return aware_time(meta["fetched_at"]).astimezone(KST).date()
