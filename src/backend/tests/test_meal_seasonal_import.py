import copy
import json
from datetime import date
from decimal import Decimal

import pytest
from agetech_data.collect.meal_facilities import SERVICE as FACILITY_SERVICE
from agetech_data.collect.meal_facilities import add_row_ids
from agetech_data.collect.seasonal import SERVICE as SEASONAL_SERVICE
from agetech_data.textutil import sha256_json
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_public_data_import import corrections
from test_public_data_import import snapshot as recipe_snapshot

from app.jobs import import_meal_facilities, import_public_data, import_seasonal
from app.models import (
    MealFacility,
    Recipe,
    SeasonalFood,
    SeasonalIngredient,
    SeasonalRecipeLink,
)

NAMGU = {
    "fcltyNm": "남구종합사회복지관",
    "rdnmadr": "대구광역시 남구 중앙대로38길 17",
    "lnmadr": "대구광역시 남구 대명동 19-1",
    "operInstitutionNm": "남구종합사회복지관",
    "phoneNumber": "053-476-7700",
    "mlsvPlace": "남구종합사회복지관",
    "mlsvTrget": "결식노인+저소득층+장애인(회원제)",
    "mlsvTime": "중식(11:20-12:20)",
    "mlsvDate": "수+목",
    "operOpenDate": "2008-01-01",
    "operCloseDate": "9999-12-31",
    "latitude": "35.84912345",
    "longitude": "128.59233335",
    "referenceDate": "2026-07-13",
    "insttCode": "3470000",
    "insttNm": "대구광역시 남구",
}
CLOSED = {
    **NAMGU,
    "fcltyNm": "문 닫은 급식소",
    "rdnmadr": "대구광역시 중구 국채보상로 1",
    "operCloseDate": "2025-12-31",
}
NOWHERE = {
    **NAMGU,
    "fcltyNm": "주소 없는 곳",
    "rdnmadr": "",
    "lnmadr": "",
    "insttNm": "모름",
}
DAY1, DAY2, DAY3 = (
    "2026-11-07T07:51:47+00:00",
    "2026-11-08T07:51:47+00:00",
    "2026-11-09T07:51:47+00:00",
)


def facility_snapshot(tmp_path, rows=(NAMGU, CLOSED, NOWHERE), fetched_at=DAY1):
    items = add_row_ids([dict(row) for row in rows])
    data = {
        "meta": {
            "service": FACILITY_SERVICE,
            "fetched_at": fetched_at,
            "total_count": len(items),
            "item_count": len(items),
            "complete": True,
            "items_sha256": sha256_json(items),
        },
        "items": items,
    }
    path = tmp_path / f"free_meal_{fetched_at[:10]}_{len(items)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def seasonal_items(intake="■ 데쳐서 나물로 먹는다."):
    items = []
    for month in range(1, 13):
        name = {12: "시금치", 9: "고구마"}.get(month, f"재료{month}")
        items.append(
            {
                "row_id": f"m{month}-{100 + month}",
                "month": month,
                "fdmtSn": str(100 + month),
                "fdmtNm": name,
                "fdmtImgUrl": f"https://www.nics.go.kr/food/{month}.jpg",
                "detail": {
                    "stdInfo": {"prchCheatDtl": "■ 잎이 싱싱한 것"},
                    "ntkInfo": {"ntkMthDtl": intake},
                    "connRecipeList": {"recipeInfo": [{"recipeNm": f"{name} 요리"}]},
                },
                "detail_status": "ok",
            }
        )
    return items


def seasonal_snapshot(tmp_path, items=None, fetched_at=DAY1, complete=True, tag=""):
    items = seasonal_items() if items is None else items
    data = {
        "meta": {
            "service": SEASONAL_SERVICE,
            "fetched_at": fetched_at,
            "item_count": len(items),
            "months": 12,
            "complete": complete,
            "items_sha256": sha256_json(items),
        },
        "items": items,
    }
    path = tmp_path / f"food_month_{fetched_at[:10]}{tag}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


RECIPES = [
    {
        "RCP_SEQ": "1",
        "RCP_NM": "시금치나물",
        "RCP_PAT2": "반찬",
        "RCP_PARTS_DTLS": "시금치 200g, 다진 마늘 5g",
        "MANUAL01": "1. 데친다.",
    },
    {
        "RCP_SEQ": "2",
        "RCP_NM": "고구마 밥",
        "RCP_PAT2": "밥",
        "RCP_PARTS_DTLS": "밤고구마 1개, 쌀 150g",
        "MANUAL01": "1. 짓는다.",
    },
]


def import_recipes(db, tmp_path, rows=RECIPES, fetched_at=DAY1):
    path = recipe_snapshot(
        tmp_path, rows=[dict(row) for row in rows], fetched_at=fetched_at
    )
    plan = import_public_data.prepare_import(
        "recipes", path, corrections_path=corrections(tmp_path)
    )
    return import_public_data.apply_import(db, plan)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


# ── 파일만 보는 단계 ───────────────────────────────────────────────────


def test_facility_plan_counts_published_hidden_and_skipped(tmp_path):
    plan = import_meal_facilities.prepare_import(facility_snapshot(tmp_path))
    assert plan.counts["facilities"] == 2 and plan.counts["published"] == 1
    assert plan.counts["skipped"] == {"region_unknown": 1}
    nam = next(row for row in plan.rows if row["name"] == "남구종합사회복지관")
    assert nam["checked_on"] == date(2026, 11, 7) and nam["reference_date"] == date(
        2026, 7, 13
    )
    values = import_meal_facilities.column_values(nam)
    assert (values["latitude"], values["longitude"]) == (
        Decimal("35.84912"),
        Decimal("128.59233"),
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda meta, items: meta.update(complete=False),
        lambda meta, items: meta.update(service="other"),
        lambda meta, items: meta.update(total_count=99),
        lambda meta, items: items[0].update(fcltyNm="바뀐 이름"),
        lambda meta, items: items[1].update(row_id=items[0]["row_id"]),
        lambda meta, items: meta.update(fetched_at="2999-01-01T00:00:00+00:00"),
    ],
)
def test_facility_snapshot_must_be_complete_and_untouched(tmp_path, change):
    path = facility_snapshot(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data["meta"], data["items"])
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        import_meal_facilities.prepare_import(path)


def test_facility_snapshot_rejects_all_rows_skipped(tmp_path):
    path = facility_snapshot(tmp_path, rows=(NOWHERE,))
    with pytest.raises(ValueError, match="no usable rows"):
        import_meal_facilities.prepare_import(path)


def test_seasonal_snapshot_requires_all_months_and_opt_in_for_failed_details(tmp_path):
    items = seasonal_items()
    with pytest.raises(ValueError):
        import_seasonal.prepare_import(seasonal_snapshot(tmp_path, items[:-1]))
    failed = copy.deepcopy(items)
    failed[11].update(detail=None, detail_status="failed")
    # complete 라고 하면서 상세가 빠짐
    with pytest.raises(ValueError):
        import_seasonal.prepare_import(seasonal_snapshot(tmp_path, failed))
    partial = seasonal_snapshot(tmp_path, failed, complete=False, tag="p")
    with pytest.raises(ValueError):
        import_seasonal.prepare_import(partial)
    plan = import_seasonal.prepare_import(partial, allow_partial_details=True)
    assert plan.partial and plan.counts["details_failed"] == 1


# ── PostgreSQL ────────────────────────────────────────────────────────


def test_postgres_facility_import_idempotent_unpublishes_missing_and_keeps_manual(
    tmp_path, pg_connection
):
    first = import_meal_facilities.prepare_import(facility_snapshot(tmp_path))
    with Session(pg_connection) as db, db.begin():
        manual = MealFacility(
            name="남구청 확인 경로식당",
            sido="대구광역시",
            sigungu="남구",
            source_url="https://www.namgu.daegu.kr",
            checked_on=date(2026, 11, 10),
            is_published=True,
        )
        db.add(manual)
        result = import_meal_facilities.apply_import(db, first)
        assert (result["new_facilities"], result["published"]) == (2, 1)
        assert import_meal_facilities.apply_import(db, first)["already_imported"]
        assert import_meal_facilities.verify_import(db, first)["verified"]
        nam = db.scalar(
            select(MealFacility).where(MealFacility.name == "남구종합사회복지관")
        )
        assert nam.provider == "data.go.kr:15013107" and nam.source_id.startswith("FM")
        assert (nam.latitude, nam.longitude) == (
            Decimal("35.84912"),
            Decimal("128.59233"),
        )
        assert nam.hours_text == "수+목 / 중식(11:20-12:20)" and nam.is_published
        assert nam.reference_date == date(2026, 7, 13) and nam.normalized["days"] == [
            "수",
            "목",
        ]
        closed = db.scalar(
            select(MealFacility).where(MealFacility.name == "문 닫은 급식소")
        )
        assert not closed.is_published and "operation_ended" in closed.quality_flags

        # 다음 날: 전화번호가 바뀌고, 문 닫은 곳은 원천에서 빠짐
        moved = {**NAMGU, "phoneNumber": "053-000-0000"}
        second = import_meal_facilities.prepare_import(
            facility_snapshot(tmp_path, (moved,), DAY2)
        )
        result = import_meal_facilities.apply_import(db, second)
        assert (result["new_facilities"], result["changed_facilities"]) == (0, 1)
        db.refresh(nam)
        assert nam.contact_text == "053-000-0000" and nam.checked_on == date(
            2026, 11, 8
        )
        assert import_meal_facilities.verify_import(db, second)["verified"]

        # 남구 시설이 빠진 완전한 수집본 → 게시 내림, 행은 남김
        third = import_meal_facilities.prepare_import(
            facility_snapshot(tmp_path, (CLOSED,), DAY3)
        )
        assert import_meal_facilities.apply_import(db, third)["newly_unpublished"] == 1
        db.refresh(nam)
        assert not nam.is_published and count(db, MealFacility) == 3
        older = import_meal_facilities.prepare_import(
            facility_snapshot(tmp_path, (moved,), DAY1)
        )
        with pytest.raises(ValueError):  # 더 오래된 수집본으로 덮지 않음
            import_meal_facilities.apply_import(db, older)
        db.refresh(manual)
        assert manual.is_published and manual.provider is None

        # 원천 행은 출처 칸이 다 있어야 함
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                MealFacility(
                    name="반쪽 출처",
                    sido="대구광역시",
                    sigungu="중구",
                    source_url="x",
                    checked_on=date(2026, 11, 10),
                    provider="data.go.kr:15013107",
                    source_id="FMhalf",
                )
            )
            db.flush()


def test_postgres_seasonal_links_follow_active_recipe_revisions(
    tmp_path, pg_connection
):
    plan = import_seasonal.prepare_import(seasonal_snapshot(tmp_path))
    with Session(pg_connection) as db, db.begin():
        # 레시피를 먼저 적재해야 연결할 수 있음
        with pytest.raises(ValueError):
            with db.begin_nested():
                import_seasonal.apply_import(db, plan)
        import_recipes(db, tmp_path)
        result = import_seasonal.apply_import(db, plan)
        assert (result["items"], result["new_items"], result["recipe_links"]) == (
            12,
            12,
            2,
        )
        assert result["ingredient_matches"] == {"official": 2}
        assert import_seasonal.apply_import(db, plan)["already_imported"]
        assert import_seasonal.verify_import(db, plan)["verified"]

        spinach = db.scalar(select(SeasonalFood).where(SeasonalFood.name == "시금치"))
        assert spinach.month == 12 and spinach.detail["intake"].startswith("■ 데쳐서")
        assert (
            spinach.official_related_recipes == ["시금치 요리"] and spinach.is_published
        )
        [mapping] = db.scalars(
            select(SeasonalIngredient).where(
                SeasonalIngredient.seasonal_food_id == spinach.id
            )
        ).all()
        assert (
            mapping.month,
            mapping.ingredient_name,
            mapping.recipe_ingredient_name,
        ) == (
            12,
            "시금치",
            "시금치",
        )
        assert (mapping.match_term, mapping.match_kind, mapping.is_published) == (
            "시금치",
            "official",
            True,
        )
        link = db.scalar(
            select(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id == spinach.id
            )
        )
        recipe = db.get(Recipe, link.recipe_id)
        assert (
            recipe.source_id == "1"
            and link.recipe_revision_id == recipe.active_revision_id
        )
        assert (link.weight_g, link.share, link.ingredient_names) == (
            Decimal("200.0"),
            Decimal(repr(round(200 / 205, 3))),
            ["시금치"],
        )
        sweet = db.scalar(select(SeasonalFood).where(SeasonalFood.name == "고구마"))
        sweet_link = db.scalar(
            select(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id == sweet.id
            )
        )
        # 분량이 g 가 아니면 비중을 계산하지 않음
        assert sweet_link.share is None and sweet_link.weight_g is None

        # 레시피 1 이 바뀌면(새 판본) 같은 제철 수집본이라도 연결을 새 판본으로 다시 만든다
        changed = [
            dict(RECIPES[0], RCP_PARTS_DTLS="시금치 100g, 다진 마늘 5g"),
            RECIPES[1],
        ]
        import_recipes(db, tmp_path, changed, DAY2)
        result = import_seasonal.apply_import(db, plan)
        assert not result["already_imported"] and result["relinked_items"] == 1
        link = db.scalar(
            select(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id == spinach.id
            )
        )
        assert (
            link.recipe_revision_id == db.get(Recipe, link.recipe_id).active_revision_id
        )
        assert link.share == Decimal(repr(round(100 / 105, 3)))
        assert import_seasonal.verify_import(db, plan)["verified"]

        # 레시피가 예전 내용으로 돌아가면(A → B → A) 입력 지문이 첫 적재와 같아도 연결을 다시 맞춘다
        import_recipes(db, tmp_path, RECIPES, DAY3)
        result = import_seasonal.apply_import(db, plan)
        assert not result["already_imported"] and result["relinked_items"] == 1
        link = db.scalar(
            select(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id == spinach.id
            )
        )
        assert (
            link.recipe_revision_id == db.get(Recipe, link.recipe_id).active_revision_id
        )
        assert link.share == Decimal(repr(round(200 / 205, 3)))
        assert import_seasonal.apply_import(db, plan)["already_imported"]
        assert import_seasonal.verify_import(db, plan)["verified"]


def test_postgres_seasonal_partial_missing_and_manual_rows(tmp_path, pg_connection):
    with Session(pg_connection) as db, db.begin():
        import_recipes(db, tmp_path)
        manual = SeasonalIngredient(
            month=9,
            ingredient_name="고구마",
            recipe_ingredient_name="밤고구마",
            source_url="https://example.org/reviewed",
            checked_on=date(2026, 11, 10),
            is_published=True,
        )
        db.add(manual)
        db.flush()
        result = import_seasonal.apply_import(
            db, import_seasonal.prepare_import(seasonal_snapshot(tmp_path))
        )
        # 손으로 넣은 매핑이 이김
        assert result["manual_overrides"] == 1
        rows = db.scalars(
            select(SeasonalIngredient).where(
                SeasonalIngredient.recipe_ingredient_name == "밤고구마"
            )
        ).all()
        assert [row.id for row in rows] == [manual.id]

        # 상세 하나가 실패한 수집본: 알고 넣을 때만, 예전 상세 글은 유지
        failed = seasonal_items(intake="■ 새 글")
        failed[11].update(detail=None, detail_status="failed")
        partial = import_seasonal.prepare_import(
            seasonal_snapshot(tmp_path, failed, DAY2, complete=False),
            allow_partial_details=True,
        )
        result = import_seasonal.apply_import(db, partial)
        assert result["kept_previous_details"] == 1
        spinach = db.scalar(select(SeasonalFood).where(SeasonalFood.name == "시금치"))
        assert spinach.detail_status == "ok" and spinach.detail["intake"].startswith(
            "■ 데쳐서"
        )
        assert spinach.official_related_recipes == ["시금치 요리"]
        assert spinach.checked_on == date(2026, 11, 8)
        assert import_seasonal.verify_import(db, partial)["verified"]

        # 고구마가 빠진 완전한 수집본 → 게시 내림, 매핑·연결 지움(수동 행은 그대로)
        without = [item for item in seasonal_items() if item["fdmtNm"] != "고구마"]
        without.append(
            {
                **seasonal_items()[0],
                "row_id": "m9-900",
                "month": 9,
                "fdmtSn": "900",
                "fdmtNm": "대추",
            }
        )
        result = import_seasonal.apply_import(
            db,
            import_seasonal.prepare_import(seasonal_snapshot(tmp_path, without, DAY3)),
        )
        assert result["newly_unpublished"] == 1
        sweet = db.scalar(select(SeasonalFood).where(SeasonalFood.name == "고구마"))
        assert not sweet.is_published
        assert not db.scalars(
            select(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id == sweet.id
            )
        ).all()
        db.refresh(manual)
        assert manual.seasonal_food_id is None and manual.is_published
        older = seasonal_snapshot(tmp_path, seasonal_items(intake="■ 옛 글"), tag="old")
        with pytest.raises(ValueError):  # 더 오래된 수집본으로 덮지 않음
            import_seasonal.apply_import(db, import_seasonal.prepare_import(older))

        # 매핑 유형 없이 식재료를 붙이지 않음
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                SeasonalIngredient(
                    month=12,
                    ingredient_name="시금치",
                    recipe_ingredient_name="섬초",
                    source_url="x",
                    checked_on=date(2026, 11, 10),
                    seasonal_food_id=spinach.id,
                    match_term="섬초",
                )
            )
            db.flush()
        # 식재료와 다른 달로 붙이지 않음
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                SeasonalIngredient(
                    month=1,
                    ingredient_name="시금치",
                    recipe_ingredient_name="섬초",
                    source_url="x",
                    checked_on=date(2026, 11, 10),
                    seasonal_food_id=spinach.id,
                    match_term="섬초",
                    match_kind="alias",
                )
            )
            db.flush()
