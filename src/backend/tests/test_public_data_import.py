import hashlib
import json
from decimal import Decimal

import pytest
from agetech_data.nutrition.client import SERVICE
from agetech_data.textutil import sha256_json
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.jobs.import_public_data import (
    apply_import,
    decimal_value,
    prepare_import,
    read_snapshot,
    verify_import,
)
from app.models import (
    DataImportRun,
    Food,
    FoodRevision,
    Recipe,
    RecipeRevision,
    RecipeStep,
)


def snapshot(tmp_path, dataset="recipes", rows=None, fetched_at=None):
    if rows is None:
        rows = [
            {
                "RCP_SEQ": "1",
                "RCP_NM": "검증 레시피",
                "RCP_PARTS_DTLS": "소금 1g, 물 적당량",
                "MANUAL01": "1. 끓인다.",
                "INFO_ENG": "0",
                "INFO_NA": "0.123456789123456789",
            }
        ]
    checksum = (
        sha256_json(rows)
        if dataset == "recipes"
        else hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    )
    data = {
        "meta": {
            "complete": True,
            "total_count": len(rows),
            "item_count": len(rows),
            "service": "COOKRCP01" if dataset == "recipes" else SERVICE,
            "api_version": "03",
            "items_sha256": checksum,
        },
        "items": rows,
    }
    if fetched_at is not None:
        data["meta"]["fetched_at"] = fetched_at
    path = tmp_path / f"{dataset}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def corrections(tmp_path):
    path = tmp_path / "corrections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "verified_at": "2026-11-05",
                "verified_by": "test",
                "corrections": [],
            }
        )
    )
    return path


def test_prepare_keeps_raw_and_missing_distinct_from_zero(tmp_path):
    plan = prepare_import(
        "recipes", snapshot(tmp_path), corrections_path=corrections(tmp_path)
    )
    assert plan.counts["recipes"] == 1
    assert plan.recipes[0]["raw"]["INFO_ENG"] == "0"
    assert decimal_value("0") == Decimal(0)
    assert decimal_value("") is None
    assert decimal_value("NaN") is None
    assert decimal_value("Infinity") is None
    assert decimal_value("1,670.00001") == Decimal("1670.00001")


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"total_count": 2},
        {"items_sha256": "invalid"},
        {"service": "other"},
        {"fetched_at": "invalid"},
        {"fetched_at": "2026-11-05T00:00:00"},
        {"fetched_at": 123},
    ],
)
def test_reject_partial_or_altered_snapshot(tmp_path, change):
    path = snapshot(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"].update(change)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_snapshot(path, "recipes")


def test_reject_duplicate_ids(tmp_path):
    path = snapshot(tmp_path, rows=[{"RCP_SEQ": "1"}, {"RCP_SEQ": "1"}])
    with pytest.raises(ValueError, match="duplicate"):
        read_snapshot(path, "recipes")


def test_all_requires_real_nutrition_input_before_writing(tmp_path):
    with pytest.raises(FileNotFoundError):
        prepare_import(
            "all", snapshot(tmp_path), tmp_path / "missing.json", corrections(tmp_path)
        )


def total(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_postgres_idempotency_revision_history_and_rollback(tmp_path, pg_connection):
    path = snapshot(tmp_path)
    correction_path = corrections(tmp_path)
    plan = prepare_import("recipes", path, corrections_path=correction_path)
    with Session(pg_connection) as session:
        with session.begin():
            first = apply_import(session, plan)
        with session.begin():
            repeated = apply_import(session, plan)
            assert repeated["already_imported"] is True
            assert repeated["new_recipes"] == repeated["new_recipe_revisions"] == 0
            assert verify_import(session, plan)["recipe_revisions"] == 1
            assert total(session, Recipe) == total(session, RecipeRevision) == 1
            revision = session.scalar(select(RecipeRevision))
            assert revision.source_energy_kcal == Decimal(0)
            assert revision.source_protein_g is None
            assert revision.source_sodium_mg == Decimal("0.123456789123456789")
        rows = [dict(plan.recipes[0]["raw"], RCP_NM="새 판본")]
        snapshot(tmp_path, rows=rows)
        second_plan = prepare_import("recipes", path, corrections_path=correction_path)
        with pytest.raises(RuntimeError), session.begin():
            apply_import(session, second_plan)
            raise RuntimeError("failure before commit")
        with session.begin():
            assert total(session, DataImportRun) == 1
            assert total(session, RecipeRevision) == 1
            assert (
                session.get(
                    RecipeRevision, session.scalar(select(Recipe.active_revision_id))
                ).name
                == "검증 레시피"
            )
        with session.begin():
            second = apply_import(session, second_plan)
            assert second["new_recipes"] == 0
            assert second["new_recipe_revisions"] == 1
        with session.begin():
            assert total(session, RecipeRevision) == total(session, RecipeStep) == 2
            assert first["run_id"] != second["run_id"]
        with pytest.raises(ValueError, match="source"), session.begin():
            original = session.scalar(
                select(RecipeRevision).where(
                    RecipeRevision.fingerprint == plan.recipes[0]["fingerprint"]
                )
            )
            original.raw = {**original.raw, "RCP_NM": "tampered"}
            session.flush()
            verify_import(session, plan)


def test_postgres_owned_active_revision_constraint_and_hold(tmp_path, pg_connection):
    path = snapshot(
        tmp_path,
        rows=[
            {
                "RCP_SEQ": "1",
                "RCP_NM": "정상",
                "RCP_PARTS_DTLS": "소금 1g",
                "MANUAL01": "1. 끓인다.",
            },
            {"RCP_SEQ": "2", "RCP_NM": "보류"},
        ],
    )
    plan = prepare_import("recipes", path, corrections_path=corrections(tmp_path))
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, plan)
        with session.begin():
            recipes = session.scalars(select(Recipe).order_by(Recipe.source_id)).all()
            first_revision = recipes[0].active_revision_id
            assert first_revision is not None
            second_id = recipes[1].id
            assert recipes[1].active_revision_id is None
        with pytest.raises(IntegrityError), session.begin():
            session.get(Recipe, second_id).active_revision_id = first_revision
            session.flush()


def test_postgres_food_units_precision_and_missing(tmp_path, pg_connection):
    path = snapshot(
        tmp_path,
        "nutrition",
        rows=[
            {
                "FOOD_CD": "G1",
                "FOOD_NM_KR": "같은 이름",
                "SERVING_SIZE": "100g",
                "AMT_NUM1": "0",
                "AMT_NUM13": "0.123456789123456789",
            },
            {
                "FOOD_CD": "M1",
                "FOOD_NM_KR": "같은 이름",
                "SERVING_SIZE": "100mL",
                "AMT_NUM1": "",
            },
        ],
    )
    plan = prepare_import("nutrition", nutrition_path=path)
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, plan)
        with session.begin():
            assert apply_import(session, plan)["already_imported"] is True
            foods = session.scalars(
                select(FoodRevision).order_by(FoodRevision.basis_unit)
            ).all()
            assert total(session, Food) == 2
            assert [food.basis_unit for food in foods] == ["g", "mL"]
            assert foods[0].energy_kcal == Decimal(0)
            assert foods[1].energy_kcal is None
            assert foods[0].sodium_mg == Decimal("0.123456789123456789")
            assert foods[0].nutrients["sodium_mg"] == "0.123456789123456789"
            assert verify_import(session, plan)["food_revisions"] == 2


@pytest.mark.parametrize("change", ["validator", "rules"])
def test_validation_revision_refreshes_recipe_but_reuses_food(
    tmp_path, pg_connection, monkeypatch, change
):
    from app.jobs import import_public_data as importer

    recipe_path = snapshot(tmp_path, fetched_at="2026-11-05T00:00:00Z")
    food_path = snapshot(
        tmp_path,
        "nutrition",
        rows=[
            {
                "FOOD_CD": "FOOD1",
                "FOOD_NM_KR": "소금",
                "SERVING_SIZE": "100g",
                "AMT_NUM1": "0",
            }
        ],
    )
    correction_path = corrections(tmp_path)
    initial = prepare_import("all", recipe_path, food_path, correction_path)
    if change == "validator":
        monkeypatch.setattr(
            importer, "RECIPE_VALIDATION_VERSION", "recipe-validation-next"
        )
    else:
        rules = json.loads(importer.RULES_FILE.read_text(encoding="utf-8"))
        rules["test_revision"] = 2
        rule_path = tmp_path / "allergen_rules.json"
        rule_path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(importer, "RULES_FILE", rule_path)
    updated = prepare_import("all", recipe_path, food_path, correction_path)
    assert initial.fingerprint != updated.fingerprint
    assert initial.recipes[0]["fingerprint"] != updated.recipes[0]["fingerprint"]
    assert initial.foods[0]["fingerprint"] == updated.foods[0]["fingerprint"]
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, initial)
        with session.begin():
            result = apply_import(session, updated)
            assert result["new_recipe_revisions"] == 1
            assert result["new_food_revisions"] == 0
            assert total(session, Recipe) == total(session, Food) == 1
            assert total(session, RecipeRevision) == 2
            assert total(session, FoodRevision) == 1
            assert verify_import(session, updated)["verified"] is True
        with session.begin():
            assert apply_import(session, updated)["already_imported"] is True
            assert total(session, RecipeRevision) == 2


@pytest.mark.parametrize("dataset", ["recipes", "nutrition"])
@pytest.mark.parametrize("incoming_time", ["2026-11-05T00:00:00Z", None])
def test_older_or_undated_snapshot_cannot_reactivate_previous_revision(
    tmp_path, pg_connection, dataset, incoming_time
):
    # Value: protects=latest active or held state survives stale cross-mode imports;
    # fails_when=old revisions are reactivated; why_new=idempotency does not cover all-mode fingerprints;
    # seam=none; no_claim=authenticity of a provider's source clock.
    old_time, new_time = "2026-11-05T00:00:00Z", "2026-11-06T00:00:00Z"
    food_rows = [
        {"FOOD_CD": "F1", "FOOD_NM_KR": "소금", "SERVING_SIZE": "100g", "AMT_NUM1": "1"}
    ]
    recipe_path = snapshot(tmp_path, fetched_at=old_time)
    food_path = snapshot(tmp_path, "nutrition", food_rows, fetched_at=old_time)
    correction_path = corrections(tmp_path)
    original = prepare_import(dataset, recipe_path, food_path, correction_path)
    stale_path = recipe_path if dataset == "recipes" else food_path
    raw = json.loads(stale_path.read_text(encoding="utf-8"))
    if incoming_time is None:
        raw["meta"].pop("fetched_at")
    stale_path.write_text(json.dumps(raw), encoding="utf-8")
    stale = prepare_import("all", recipe_path, food_path, correction_path)
    if dataset == "recipes":
        latest_rows = [{**original.recipes[0]["raw"], "MANUAL01": ""}]
        snapshot(tmp_path, rows=latest_rows, fetched_at=new_time)
    else:
        snapshot(
            tmp_path,
            "nutrition",
            [{**food_rows[0], "AMT_NUM1": "2"}],
            fetched_at=new_time,
        )
    latest = prepare_import(dataset, recipe_path, food_path, correction_path)
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, original)
        with session.begin():
            apply_import(session, latest)
        with pytest.raises(ValueError, match="snapshot"), session.begin():
            apply_import(session, stale)
        with session.begin():
            assert total(session, DataImportRun) == 2
            if dataset == "recipes":
                assert session.scalar(select(Recipe.active_revision_id)) is None
                assert total(session, Food) == 0
            else:
                active = session.scalar(
                    select(FoodRevision).join(
                        Food, Food.active_revision_id == FoodRevision.id
                    )
                )
                assert active.energy_kcal == Decimal(2)
                assert total(session, Recipe) == 0
