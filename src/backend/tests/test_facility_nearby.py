from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from agetech_data.facilities.query import distance_km
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_content_api import catalog_db as catalog_db
from test_content_api import facility, sql

from app.core.database import get_db
from app.models import MealFacility
from app.schemas.content import FacilityNearbyQuery
from app.services.content_catalog import nearby_facilities

PATH = "/api/v1/meal-facilities/nearby"
POSITION = {"latitude": 35.87, "longitude": 128.60}


@pytest.mark.parametrize(
    "changes",
    [
        {"latitude": 91},
        {"latitude": -91},
        {"longitude": 181},
        {"longitude": -181},
        {"latitude": True},
        {"longitude": False},
        {"latitude": "35.87"},
        {"radius_km": "5"},
        {"radius_km": 0.49},
        {"radius_km": 50.01},
        {"latitude": float("nan")},
        {"longitude": float("inf")},
        {"radius_km": float("nan")},
        {"district": "남구"},
        {"user_id": "other"},
    ],
)
def test_nearby_contract_rejects_invalid_coordinates_or_authority(changes):
    with pytest.raises(ValidationError):
        FacilityNearbyQuery.model_validate({**POSITION, **changes})


@pytest.mark.parametrize("field", ["latitude", "longitude"])
def test_nearby_requires_both_coordinates(field):
    with pytest.raises(ValidationError):
        FacilityNearbyQuery.model_validate(
            {key: value for key, value in POSITION.items() if key != field}
        )


def test_nearby_reuses_radius_matching_and_keeps_missing_coordinates_after_known():
    here = facility(
        name="현재 위치", latitude=Decimal("35.87"), longitude=Decimal("128.60")
    )
    across = facility(
        name="경계 너머",
        sido="경상북도",
        sigungu="어느군",
        latitude=Decimal("35.871"),
        longitude=Decimal("128.60"),
    )
    far = facility(name="먼 곳", latitude=Decimal("37.5"), longitude=Decimal("127.0"))
    unknown = facility(name="좌표 미확인")
    other_unknown = facility(name="다른 구 좌표 미확인", sigungu="중구")
    ended = facility(
        name="운영 종료",
        latitude=Decimal("35.87"),
        longitude=Decimal("128.60"),
        normalized={"close_date": "2000-01-01"},
    )
    notes, rows = nearby_facilities(
        [far, unknown, other_unknown, across, ended, here],
        FacilityNearbyQuery(**POSITION, region="대구", district="남구"),
        date(2026, 11, 21),
    )
    assert [row.id for row in rows] == [here.id, across.id, unknown.id]
    assert rows[0].distance_km == 0 and rows[0].match == "district"
    assert rows[1].match == "nearby" and 0.10 <= rows[1].distance_km <= 0.12
    assert rows[2].distance_km is None and rows[2].match == "district_no_coords"
    assert any("좌표가 없는" in note for note in notes)
    assert all(row.cautions for row in rows) and any(
        "직선거리" in note for note in notes
    )
    assert unknown.quality_flags == []


def test_nearby_without_region_uses_distance_and_stable_uuid_ties():
    first = facility(id=UUID(int=1), name="같은 이름", latitude=35.87, longitude=128.6)
    second = facility(id=UUID(int=2), name="같은 이름", latitude=35.87, longitude=128.6)
    _, rows = nearby_facilities(
        [second, facility(), first], FacilityNearbyQuery(**POSITION), date(2026, 11, 21)
    )
    assert [row.id for row in rows] == [first.id, second.id]


def test_distance_handles_antipodes_roundoff_and_zero():
    assert distance_km(35.87, 128.6, 35.87, 128.6) == 0
    assert 20000 < distance_km(-35.87, -51.4, 35.87, 128.6) < 20020
    assert 20000 < distance_km(-89.92, 0, 89.92, 180) < 20020


def test_nearby_http_paginates_after_distance_filter_and_never_writes(
    catalog_db, caplog
):
    client, db = catalog_db
    # Both points are inside the radius; input coordinates are not facility output fields.
    db.scalars.return_value.all.return_value = [
        facility(id=UUID(int=1), name="첫째", latitude=35.87, longitude=128.6),
        facility(id=UUID(int=2), name="둘째", latitude=35.88, longitude=128.6),
    ]
    body = {
        "latitude": 35.871234,
        "longitude": 128.601234,
        "limit": 1,
        "offset": 1,
        "q": "%",
    }
    response = client.post(PATH, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()["data"]
    assert payload["total"] == 2 and len(payload["items"]) == 1
    assert payload["items"][0]["id"] == str(UUID(int=2))
    assert "meal_facilities.is_published IS true" in sql(db.scalars.call_args.args[0])
    assert "/%" in db.scalars.call_args.args[0].compile().params.values()
    for key in ("latitude", "longitude"):
        assert str(body[key]) not in response.text and str(body[key]) not in caplog.text
    assert not any(
        method in ("add", "commit", "flush", "execute")
        for method, _, _ in db.mock_calls
    )
    # Existing GET DTOs do not acquire location-derived fields.
    standard = client.get("/api/v1/meal-facilities").json()["data"]["items"][0]
    assert "distance_km" not in standard and "match" not in standard


def test_nearby_validation_and_database_errors_are_private(catalog_db):
    client, db = catalog_db
    response = client.post(PATH, json={"latitude": 9123456.78, "longitude": 128.601234})
    assert (
        response.status_code == 422 and response.headers["Cache-Control"] == "no-store"
    )
    assert "9123456.78" not in response.text and "128.601234" not in response.text
    db.scalars.side_effect = OperationalError(
        "private query detail", {}, Exception("private database")
    )
    response = client.post(PATH, json=POSITION)
    assert (
        response.status_code == 503 and response.headers["Cache-Control"] == "no-store"
    )
    assert response.json()["error"]["code"] == "CONTENT_UNAVAILABLE"
    assert "private" not in response.text


def test_nearby_empty_and_unknown_region_keep_explicit_warnings(catalog_db):
    client, db = catalog_db
    db.scalars.return_value.all.return_value = [facility()]
    response = client.post(PATH, json={**POSITION, "region": "모르는 지역"})
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert response.json()["data"]["warnings"]


def test_postgres_nearby_uses_published_current_rows_and_does_not_store_position(
    pg_connection, client
):
    with Session(pg_connection, expire_on_commit=False) as db:
        client.app.dependency_overrides[get_db] = lambda: db
        known = facility(
            id=UUID(int=10),
            name="가까운 곳",
            latitude=Decimal("35.87"),
            longitude=Decimal("128.60"),
        )
        hidden = facility(
            name="비공개",
            is_published=False,
            latitude=Decimal("35.87"),
            longitude=Decimal("128.60"),
        )
        unknown = facility(name="같은 구 좌표 없음")
        ended = facility(
            name="종료된 곳",
            latitude=Decimal("35.87"),
            longitude=Decimal("128.60"),
            normalized={"close_date": "2000-01-01"},
        )
        db.add_all([known, hidden, unknown, ended])
        db.commit()
        before = [
            row.normalized
            for row in db.scalars(select(MealFacility).order_by(MealFacility.id))
        ]
        response = client.post(
            PATH, json={**POSITION, "region": "대구", "district": "남구"}
        )
        assert response.status_code == 200, response.text
        rows = response.json()["data"]["items"]
        assert [row["id"] for row in rows] == [str(known.id), str(unknown.id)]
        assert rows[0]["distance_km"] == 0 and rows[1]["distance_km"] is None
        after = [
            row.normalized
            for row in db.scalars(select(MealFacility).order_by(MealFacility.id))
        ]
        assert before == after and not db.new and not db.dirty
        known.is_published = False
        db.commit()
        assert client.post(PATH, json=POSITION).json()["data"]["items"] == []
