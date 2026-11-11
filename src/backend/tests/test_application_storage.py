from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot
from test_welfare_import import snapshot as welfare_snapshot

from alembic import command
from app.jobs import import_public_data, import_welfare
from app.models import (
    AuthSession,
    Food,
    FoodRevision,
    JobRun,
    LifeGuide,
    MealFacility,
    MealLog,
    MealLogItem,
    MealPlanEntry,
    Profile,
    Recipe,
    SavedRecipe,
    SavedWelfareService,
    SeasonalIngredient,
    User,
    WelfareService,
)


def test_storage_upgrade_preserves_source_data_and_cascades_only_owned_rows(
    pg_connection, tmp_path
):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = pg_connection
    command.downgrade(config, "20261109_01")
    pg_connection.commit()
    assert not inspect(pg_connection).has_table("meal_logs")
    pg_connection.rollback()

    recipe_plan = import_public_data.prepare_import(
        "recipes", snapshot(tmp_path), corrections_path=corrections(tmp_path)
    )
    food_snapshot = snapshot(
        tmp_path,
        "nutrition",
        rows=[
            {
                "FOOD_CD": "M1",
                "FOOD_NM_KR": "검증 음료",
                "SERVING_SIZE": "100mL",
                "AMT_NUM1": "70",
            }
        ],
    )
    food_plan = import_public_data.prepare_import(
        "nutrition", nutrition_path=food_snapshot
    )
    welfare_plan = import_welfare.prepare_import(welfare_snapshot(tmp_path))
    now = datetime.now(UTC)
    with Session(pg_connection) as db, db.begin():
        import_public_data.apply_import(db, recipe_plan)
        import_public_data.apply_import(db, food_plan)
        import_welfare.apply_import(db, welfare_plan)
        first, second = User(), User()
        db.add_all([first, second])
        db.flush()
        owners = first.id, second.id
        for index, user_id in enumerate(owners):
            db.add(
                Profile(
                    user_id=user_id, preferences={}, consented_at=now, updated_at=now
                )
            )
            db.add(
                AuthSession(
                    user_id=user_id,
                    token_hash=str(index) * 64,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
        recipe = db.scalar(select(Recipe))
        recipe_id, recipe_revision_id = recipe.id, recipe.active_revision_id
        food_revision_id = db.scalar(select(Food.active_revision_id))
        service_id = db.scalar(select(WelfareService.id).order_by(WelfareService.id))

    command.upgrade(config, "head")
    pg_connection.commit()
    command.check(config)
    pg_connection.rollback()

    with Session(pg_connection) as db, db.begin():
        assert import_public_data.apply_import(db, recipe_plan)["already_imported"]
        assert import_public_data.apply_import(db, food_plan)["already_imported"]
        assert import_welfare.apply_import(db, welfare_plan)["already_imported"]
        assert db.get(Recipe, recipe_id).active_revision_id == recipe_revision_id
        assert db.get(FoodRevision, food_revision_id).basis_unit == "mL"
        assert db.get(WelfareService, service_id).active_revision_id is not None
        for user_id in owners:
            assert db.get(Profile, user_id).preferences == {}
            meal = MealLog(user_id=user_id, eaten_at=now)
            db.add(meal)
            db.flush()
            db.add_all(
                [
                    MealLogItem(
                        meal_log_id=meal.id,
                        food_revision_id=food_revision_id,
                        amount=Decimal("123.456"),
                        amount_unit="mL",
                        nutrients={"energy_kcal": "86.4192"},
                        calculation_version="test-v1",
                    ),
                    SavedRecipe(user_id=user_id, recipe_id=recipe_id),
                    SavedWelfareService(user_id=user_id, service_id=service_id),
                    MealPlanEntry(
                        user_id=user_id,
                        plan_date=now.date(),
                        meal_slot="lunch",
                        recipe_revision_id=recipe_revision_id,
                    ),
                    JobRun(user_id=user_id, kind="nutrition"),
                ]
            )
        db.add(JobRun(kind="public_data"))
        db.flush()

        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                MealPlanEntry(
                    user_id=owners[1],
                    plan_date=now.date(),
                    meal_slot="lunch",
                    recipe_revision_id=recipe_revision_id,
                )
            )
            db.flush()
        db.execute(delete(User).where(User.id == owners[0]))

        for model in (
            Profile,
            AuthSession,
            MealLog,
            MealPlanEntry,
            SavedRecipe,
            SavedWelfareService,
        ):
            assert db.scalars(select(model.user_id)).all() == [owners[1]]
        item = db.scalar(select(MealLogItem))
        assert db.scalar(select(func.count()).select_from(MealLogItem)) == 1
        assert (item.amount, item.amount_unit) == (Decimal("123.456"), "mL")
        assert db.get(FoodRevision, item.food_revision_id) is not None
        assert db.get(Recipe, recipe_id) is not None
        assert db.get(WelfareService, service_id) is not None
        assert {job.user_id for job in db.scalars(select(JobRun))} == {None, owners[1]}


def test_content_provenance_and_constraints(pg_connection):
    source_url = "https://example.org/public-data"
    checked_on = date(2026, 11, 10)
    with Session(pg_connection) as db, db.begin():
        guide = LifeGuide(
            slug="getting-started",
            title="Getting started",
            steps=[{"text": "Open the app"}],
            source_reference="ValueFlow app manual",
            checked_on=checked_on,
        )
        facility = MealFacility(
            name="Test facility",
            sido="대구",
            sigungu="중구",
            source_url=source_url,
            checked_on=checked_on,
        )
        seasonal = SeasonalIngredient(
            month=11,
            ingredient_name="배추",
            recipe_ingredient_name="알배추",
            source_url=source_url,
            checked_on=checked_on,
        )
        db.add_all([guide, facility, seasonal])
        db.flush()
        assert all(
            row.checked_on == checked_on and row.is_published is False
            for row in (guide, facility, seasonal)
        )
        with pytest.raises(IntegrityError), db.begin_nested():
            facility.latitude = Decimal("35.87")
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            seasonal.month = 13
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(JobRun(kind="nutrition", status="invalid"))
            db.flush()
