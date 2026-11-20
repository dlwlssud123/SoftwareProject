from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import guest
from test_meal_seasonal_import import (
    NAMGU,
    facility_snapshot,
    seasonal_snapshot,
)
from test_public_data_import import corrections, snapshot

from app.core.auth import AuthContext, current_auth
from app.core.database import get_db
from app.jobs import import_meal_facilities, import_public_data, import_seasonal
from app.jobs.daily_refresh import KIND
from app.models import JobRun, LifeGuide, MealFacility, SeasonalFood
from app.schemas.content import FacilityQuery
from app.services.content_catalog import matching_facilities


def facility(**changes):
    values = dict(
        id=uuid4(),
        name="확인된 급식소",
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


@pytest.fixture
def catalog_db(client):
    db = Mock()
    client.app.dependency_overrides[get_db] = lambda: db
    db.scalar.return_value = 0
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = []
    db.get.return_value = None
    return client, db


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


def test_facility_regions_runtime_expiry_and_cautions():
    south = facility()
    central = facility(sigungu="중구")
    other = facility(sido="부산광역시")
    closed = facility(normalized={"close_date": "2026-11-17"})
    inactive = facility(quality_flags=["not_operating"])
    future = facility(
        normalized={"open_date": "2027-01-01"}, reference_date=date(2020, 1, 1)
    )
    rows = [central, other, closed, inactive, future, south]
    _, results = matching_facilities(
        rows, FacilityQuery(region="대구", district="남구"), date(2026, 11, 18)
    )
    assert results[0].sigungu == "남구"
    assert {record.id for record in results} == {south.id, central.id, future.id}
    caution = next(record for record in results if record.id == future.id)
    assert {"not_started", "reference_stale"} <= set(caution.quality_flags)
    assert any("전화" in text for text in caution.cautions)
    notes, results = matching_facilities(
        rows, FacilityQuery(region="모름"), date(2026, 11, 18)
    )
    assert results == [] and notes
    _, all_regions = matching_facilities(rows, FacilityQuery(), date(2026, 11, 18))
    assert {record.id for record in all_regions} == {
        south.id,
        central.id,
        other.id,
        future.id,
    }
    assert south.quality_flags == []


def test_facility_api_metadata_filtering_and_expired_detail(catalog_db):
    client, db = catalog_db
    item = facility()
    db.scalars.return_value.all.return_value = [item]
    response = client.get(
        "/api/v1/meal-facilities", params={"region": "대구", "limit": 1, "q": "%"}
    )
    assert response.status_code == 200, response.text
    record = response.json()["data"]["items"][0]
    assert record["id"] == str(item.id)
    assert (
        record["checked_on"] == "2026-11-18"
        and record["reference_date"] == "2026-07-01"
    )
    statement = db.scalars.call_args.args[0]
    assert "meal_facilities.is_published IS true" in sql(statement)
    assert "/%" in statement.compile().params.values()
    db.get.return_value = item
    assert client.get(f"/api/v1/meal-facilities/{item.id}").status_code == 200
    item.normalized = {"close_date": "2000-01-01"}
    assert client.get(f"/api/v1/meal-facilities/{item.id}").status_code == 404


def test_seasonal_detail_and_current_recipe_link_sql(catalog_db):
    client, db = catalog_db
    food = SeasonalFood(
        id=uuid4(),
        provider="test:seasonal",
        source_id="m11-1",
        month=11,
        name="무",
        terms=["무"],
        detail={"storage_prep": "서늘한 곳"},
        detail_status="ok",
        official_related_recipes=["무 요리"],
        shopping_search_url="https://www.coupang.com/np/search?q=무",
        source_url="https://example.org/public",
        checked_on=date(2026, 11, 18),
        content_sha256="0" * 64,
        is_published=True,
    )
    db.get.return_value = food
    detail = client.get(f"/api/v1/seasonal-foods/{food.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["detail"]["storage_prep"] == "서늘한 곳"
    db.scalars.return_value.all.return_value = [food]
    db.scalar.return_value = 1
    listing = client.get("/api/v1/seasonal-foods", params={"month": 11})
    assert listing.status_code == 200, listing.text
    assert "detail" not in listing.json()["data"]["items"][0]
    query = db.scalars.call_args.args[0]
    assert "seasonal_foods.is_published IS true" in sql(query)
    assert "seasonal_foods.detail_status" in sql(query)
    assert 11 in query.compile().params.values()
    db.scalar.return_value = 0
    linked = client.get(f"/api/v1/seasonal-foods/{food.id}/recipes")
    assert linked.status_code == 200 and linked.json()["data"]["items"] == []
    statement = sql(db.execute.call_args.args[0])
    assert "seasonal_recipe_links.recipe_revision_id = recipe_revisions.id" in statement
    assert "recipes.active_revision_id = recipe_revisions.id" in statement
    food.is_published = False
    assert client.get(f"/api/v1/seasonal-foods/{food.id}").status_code == 404
    assert client.get(f"/api/v1/seasonal-foods/{food.id}/recipes").status_code == 404


def test_published_guide_summary_and_ordered_steps(catalog_db):
    client, db = catalog_db
    guide = LifeGuide(
        id=uuid4(),
        slug="app-start",
        title="앱 시작",
        steps=[{"text": "첫째"}, {"text": "둘째"}],
        source_reference="서비스 사용 안내",
        checked_on=date(2026, 11, 18),
        is_published=True,
    )
    db.scalar.return_value = guide
    response = client.get("/api/v1/life-guides/app-start")
    assert response.status_code == 200
    assert [step["text"] for step in response.json()["data"]["steps"]] == [
        "첫째",
        "둘째",
    ]
    assert "life_guides.is_published IS true" in sql(db.scalar.call_args.args[0])
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [guide]
    listing = client.get("/api/v1/life-guides")
    assert listing.json()["data"]["total"] == 1
    assert "steps" not in listing.json()["data"]["items"][0]


@pytest.mark.parametrize(
    "path",
    [
        "/meal-facilities?district=남구",
        "/meal-facilities?limit=0",
        "/meal-facilities/not-a-uuid",
        "/seasonal-foods?month=0",
        "/seasonal-foods?month=13",
        "/seasonal-foods/not-a-uuid",
        "/life-guides?offset=-1",
    ],
)
def test_catalog_query_boundaries(catalog_db, path):
    client, _ = catalog_db
    assert client.get(f"/api/v1{path}").status_code == 422


@pytest.mark.parametrize(
    "path", ["/meal-facilities", "/seasonal-foods", "/life-guides"]
)
def test_catalog_db_errors_do_not_expose_connection_details(catalog_db, path):
    client, db = catalog_db
    error = OperationalError(None, None, RuntimeError("private-connection"))
    db.scalar.side_effect = db.scalars.side_effect = error
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True
    assert "private-connection" not in response.text


def test_admin_data_jobs_role_filter_and_private_jobs(catalog_db):
    client, db = catalog_db
    path = "/api/v1/admin/data-jobs"
    assert client.get(path).status_code == 401
    auth = AuthContext(user=SimpleNamespace(role="user"), session=SimpleNamespace())
    client.app.dependency_overrides[current_auth] = lambda: auth
    assert client.get(path).status_code == 403
    auth.user.role = "admin"
    now = datetime.now(UTC)
    job = JobRun(
        id=uuid4(),
        kind=KIND,
        status="failed",
        attempts=1,
        next_run_at=now,
        created_at=now,
        started_at=now,
        finished_at=now,
        error_code="import_welfare",
    )
    db.scalar.return_value = 1
    db.scalars.return_value.all.return_value = [job]
    response = client.get(path, params={"status": "failed"})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]["items"][0]
    assert data["error_code"] == "import_welfare" and "user_id" not in data
    statement = sql(db.scalars.call_args.args[0])
    assert "job_runs.user_id IS NULL" in statement and "job_runs.kind =" in statement
    assert client.get(path, params={"status": "invalid"}).status_code == 422


def test_catalog_real_postgres_publication_and_stale_recipe_links(
    pg_connection, client, tmp_path
):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        facility_plan = import_meal_facilities.prepare_import(
            facility_snapshot(tmp_path)
        )
        import_meal_facilities.apply_import(db, facility_plan)
        recipes = [
            {
                "RCP_SEQ": "1",
                "RCP_NM": "시금치 무침",
                "RCP_PARTS_DTLS": "시금치 100g",
                "MANUAL01": "1. 익힌다.",
            }
        ]
        recipe_path = snapshot(tmp_path, rows=recipes)
        import_public_data.apply_import(
            db,
            import_public_data.prepare_import(
                "recipes", recipe_path, corrections_path=corrections(tmp_path)
            ),
        )
        import_seasonal.apply_import(
            db, import_seasonal.prepare_import(seasonal_snapshot(tmp_path))
        )
        guide = LifeGuide(
            slug="first",
            title="시작",
            steps=[{"text": "시작하기"}],
            source_reference="팀 사용 안내",
            checked_on=date(2026, 11, 18),
        )
        db.add(guide)
        db.commit()
        assert client.get("/api/v1/meal-facilities").json()["data"]["total"] == 1
        facility_row = db.scalar(
            select(MealFacility).where(MealFacility.name == NAMGU["fcltyNm"])
        )
        assert (
            client.get(f"/api/v1/meal-facilities/{facility_row.id}").status_code == 200
        )
        assert client.get("/api/v1/life-guides").json()["data"]["total"] == 0
        assert client.get("/api/v1/life-guides/first").status_code == 404
        guide.is_published = True
        guide.review_status = "approved"
        db.commit()
        assert client.get("/api/v1/life-guides/first").status_code == 200
        seasonal = client.get("/api/v1/seasonal-foods", params={"month": 12}).json()[
            "data"
        ]["items"][0]
        linked = f"/api/v1/seasonal-foods/{seasonal['id']}/recipes"
        assert client.get(linked).json()["data"]["total"] == 1
        recipes[0]["RCP_NM"] = "새 시금치 무침"
        recipe_path = snapshot(tmp_path, rows=recipes)
        import_public_data.apply_import(
            db,
            import_public_data.prepare_import(
                "recipes", recipe_path, corrections_path=corrections(tmp_path)
            ),
        )
        db.commit()
        assert client.get(linked).json()["data"]["total"] == 0
        db.get(SeasonalFood, UUID(seasonal["id"])).is_published = False
        facility_row.is_published = False
        db.commit()
        assert client.get("/api/v1/meal-facilities").json()["data"]["total"] == 0
        assert (
            client.get("/api/v1/seasonal-foods", params={"month": 12}).json()["data"][
                "total"
            ]
            == 0
        )
        assert client.get(linked).status_code == 404
        _, regular = guest(client)
        assert client.get("/api/v1/admin/data-jobs", headers=regular).status_code == 403
