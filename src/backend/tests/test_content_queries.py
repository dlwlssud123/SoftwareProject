"""Exercise catalog queries synchronously without a DB or ASGI worker threads."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from starlette.responses import Response

from app.api import admin_data, content
from app.core.auth import AuthContext, require_admin
from app.core.errors import AppError
from app.models import JobRun, LifeGuide, MealFacility, SeasonalFood
from app.schemas.catalog import PageQuery
from app.schemas.content import DataJobQuery, FacilityQuery, SeasonalQuery
from app.services.content_catalog import matching_facilities


@pytest.fixture
def context():
    request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
    db = Mock()
    db.scalar.return_value = 0
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = []
    db.get.return_value = None
    return request, db


def facility(**changes):
    values = dict(
        id=uuid4(),
        name="급식소",
        sido="대구광역시",
        sigungu="남구",
        source_url="https://example.org/public",
        checked_on=date(2026, 11, 18),
        reference_date=date(2026, 7, 1),
        is_published=True,
        quality_flags=[],
    )
    values.update(changes)
    return MealFacility(**values)


def test_facility_query_filter_page_and_metadata(context):
    request, db = context
    row = facility()
    db.scalars.return_value.all.return_value = [row]
    result = content.list_facilities(request, FacilityQuery(region="대구", q="%"), db)
    assert result.meta.request_id == "test-request"
    assert result.data.total == 1
    assert result.data.items[0].id == row.id
    assert result.data.items[0].reference_date == date(2026, 7, 1)
    stmt = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "meal_facilities.is_published IS true" in str(stmt)
    assert "/%" in stmt.params.values()
    result = content.list_facilities(request, FacilityQuery(offset=1), db)
    assert result.data.total == 1 and result.data.items == []
    db.get.return_value = row
    assert content.get_facility(row.id, request, db).data.id == row.id
    row.normalized = {"close_date": "2000-01-01"}
    with pytest.raises(AppError) as error:
        content.get_facility(row.id, request, db)
    assert error.value.status_code == 404


def test_facility_fallback_district_priority_and_current_dates():
    local = facility()
    province = facility(sigungu="중구")
    closed = facility(normalized={"close_date": "2026-11-17"})
    future = facility(
        normalized={"open_date": "2027-01-01"}, reference_date=date(2020, 1, 1)
    )
    rows = [province, closed, local, future]
    _, items = matching_facilities(
        rows, FacilityQuery(region="대구", district="남구"), date(2026, 11, 18)
    )
    assert items[-1].id == province.id
    assert {item.id for item in items} == {local.id, province.id, future.id}
    future_item = next(item for item in items if item.id == future.id)
    assert {"reference_stale", "not_started"} <= set(future_item.quality_flags)
    assert any("전화" in caution for caution in future_item.cautions)
    assert future.quality_flags == []
    notes, items = matching_facilities(
        rows, FacilityQuery(region="없는지역"), date(2026, 11, 18)
    )
    assert notes and items == []


def test_seasonal_queries_and_active_revision_join(context):
    request, db = context
    food = SeasonalFood(
        id=uuid4(),
        provider="source",
        source_id="m11-1",
        month=11,
        name="무",
        terms=["무"],
        detail={"storage_prep": "보관 안내"},
        detail_status="ok",
        official_related_recipes=["무 요리"],
        shopping_search_url="https://www.coupang.com/np/search?q=무",
        source_url="https://example.org/public",
        checked_on=date(2026, 11, 18),
        content_sha256="0" * 64,
        is_published=True,
    )
    db.scalars.return_value.all.return_value = [food]
    db.scalar.return_value = 1
    result = content.list_seasonal(request, SeasonalQuery(month=11), db)
    assert result.data.items[0].month == 11
    assert "detail" not in result.data.items[0].model_dump()
    stmt = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "seasonal_foods.is_published IS true" in str(stmt)
    assert "seasonal_foods.detail_status =" in str(stmt)
    assert 11 in stmt.params.values()
    db.get.return_value = food
    assert (
        content.get_seasonal(food.id, request, db).data.detail["storage_prep"]
        == "보관 안내"
    )
    db.scalar.return_value = 0
    linked = content.list_seasonal_recipes(food.id, request, PageQuery(), db)
    assert linked.data.items == []
    compiled = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "seasonal_recipe_links.recipe_revision_id = recipe_revisions.id" in compiled
    assert "recipes.active_revision_id = recipe_revisions.id" in compiled
    food.detail_status = "failed"
    with pytest.raises(AppError) as error:
        content.get_seasonal(food.id, request, db)
    assert error.value.status_code == 404


def test_guide_publication_and_detail(context):
    request, db = context
    guide = LifeGuide(
        id=uuid4(),
        slug="start",
        title="시작",
        steps=[{"text": "첫째"}, {"text": "둘째"}],
        source_reference="팀 사용 안내",
        checked_on=date(2026, 11, 18),
        is_published=True,
    )
    db.scalar.return_value = guide
    result = content.get_guide("start", request, db)
    assert [step["text"] for step in result.data.steps] == ["첫째", "둘째"]
    stmt = str(db.scalar.call_args.args[0].compile())
    assert "life_guides.is_published IS true" in stmt
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [guide]
    assert (
        "steps"
        not in content.list_guides(request, PageQuery(), db).data.items[0].model_dump()
    )


@pytest.mark.parametrize(
    "query_type,values",
    [
        (FacilityQuery, {"district": "남구"}),
        (FacilityQuery, {"limit": 0}),
        (SeasonalQuery, {"month": 0}),
        (SeasonalQuery, {"month": 13}),
        (PageQuery, {"offset": -1}),
        (DataJobQuery, {"status": "invalid"}),
    ],
)
def test_query_models_reject_invalid_inputs(query_type, values):
    with pytest.raises(ValidationError):
        query_type(**values)


@pytest.mark.parametrize(
    "endpoint,query",
    [
        (content.list_facilities, FacilityQuery()),
        (content.list_seasonal, SeasonalQuery()),
        (content.list_guides, PageQuery()),
    ],
)
def test_query_errors_are_retryable(context, endpoint, query):
    request, db = context
    db.scalar.side_effect = db.scalars.side_effect = OperationalError(
        None, None, RuntimeError("private")
    )
    with pytest.raises(AppError) as error:
        endpoint(request, query, db)
    assert error.value.status_code == 503 and error.value.retryable
    assert "private" not in error.value.message


def test_admin_jobs_exclude_private_jobs_and_check_role(context):
    request, db = context
    auth = AuthContext(user=SimpleNamespace(role="user"), session=SimpleNamespace())
    with pytest.raises(AppError) as error:
        require_admin(auth)
    assert error.value.status_code == 403
    auth.user.role = "admin"
    assert require_admin(auth) is auth
    now = datetime.now(UTC)
    job = JobRun(
        id=uuid4(),
        kind="public_data_daily",
        status="failed",
        attempts=1,
        next_run_at=now,
        created_at=now,
        started_at=now,
        finished_at=now,
        error_code="import_welfare",
    )
    db.scalars.return_value.all.return_value = [job]
    db.scalar.return_value = 1
    response = Response()
    result = admin_data.list_data_jobs(
        request, response, auth, db, DataJobQuery(status="failed")
    )
    assert result.data.items[0].error_code == "import_welfare"
    assert response.headers["Cache-Control"] == "no-store"
    compiled = str(db.scalars.call_args.args[0].compile())
    assert "job_runs.user_id IS NULL" in compiled
    assert "job_runs.kind =" in compiled and "job_runs.status =" in compiled
    assert "user_id" not in result.data.items[0].model_dump()
