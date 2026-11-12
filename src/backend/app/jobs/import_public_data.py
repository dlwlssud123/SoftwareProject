"""Validate complete public snapshots, then atomically import immutable revisions.

Default operation is a file-only dry run. Apply requires an upgraded database.
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agetech_data import paths
from agetech_data.nutrition.client import SERVICE as NUTRITION_SERVICE
from agetech_data.nutrition.fields import NUTRIENT_FIELDS
from agetech_data.nutrition.foods import clean_foods
from agetech_data.recipes.allergens import RULES_FILE
from agetech_data.recipes.correct import apply_corrections
from agetech_data.recipes.validate import SCHEMA_VERSION as RECIPE_SCHEMA_VERSION
from agetech_data.recipes.validate import check_recipe
from agetech_data.textutil import sha256_json
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    DataImportRun,
    Food,
    FoodRevision,
    Recipe,
    RecipeIngredient,
    RecipeRevision,
    RecipeStep,
)

PARSER_VERSION = "public-data-v1"
# v3: 재료 원문의 HTML 줄바꿈 태그·대괄호 섹션·"N인분 기준" 줄 처리(agetech_data.recipes.ingredients)
RECIPE_VALIDATION_VERSION = "recipe-validation-v3"
RECIPE_PROVIDER = "foodsafetykorea:COOKRCP01"
FOOD_PROVIDER = "data.go.kr:FoodNtrCpntDbInfo03"
RECIPE_NUTRIENTS = {
    "source_energy_kcal": "INFO_ENG",
    "source_carbohydrate_g": "INFO_CAR",
    "source_protein_g": "INFO_PRO",
    "source_fat_g": "INFO_FAT",
    "source_sodium_mg": "INFO_NA",
}
FOOD_COLUMNS = (
    "energy_kcal",
    "carbohydrate_g",
    "protein_g",
    "fat_g",
    "sugars_g",
    "fiber_g",
    "sodium_mg",
)


def decimal_value(value) -> Decimal | None:
    """Keep source precision; missing/invalid/non-finite numbers are never zero."""
    if value is None or str(value).strip() in ("", "None", "-", "null"):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def food_nutrient_values(entry: dict) -> dict[str, Decimal | None]:
    # Preserve untouched source precision while applying only verified nutrient corrections.
    values = {
        key: decimal_value(entry["raw"].get(source))
        for key, (source, _) in NUTRIENT_FIELDS.items()
    }
    for correction in entry["record"].get("corrections", []):
        if correction["field"].startswith("nutrients."):
            key = correction["field"].split(".", 1)[1]
            values[key] = decimal_value(correction["to"])
    return values


def snapshot_time(meta: dict) -> datetime | None:
    value = meta.get("fetched_at", meta.get("fetchedAt"))
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            "Snapshot fetched_at must be an ISO datetime with timezone"
        ) from None
    if parsed.tzinfo is None:
        raise ValueError("Snapshot fetched_at requires a timezone")
    return parsed.astimezone(UTC)


def read_snapshot(path: Path, dataset: str) -> tuple[list[dict], dict]:
    raw_bytes = path.read_bytes()
    data = json.loads(raw_bytes.decode("utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
        raise ValueError(f"{dataset}: full collector snapshot with metadata required")
    meta, items = data["meta"], data.get("items")
    snapshot_time(meta)
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(row, dict) for row in items)
    ):
        raise ValueError(f"{dataset}: nonempty row list required")
    if (
        meta.get("complete") is not True
        or meta.get("total_count") != len(items)
        or meta.get("item_count") != len(items)
    ):
        raise ValueError(f"{dataset}: incomplete snapshot or count mismatch")
    if dataset == "recipes":
        valid_service = meta.get("service") == "COOKRCP01"
        items_hash = sha256_json(items)
        id_field = "RCP_SEQ"
    else:
        valid_service = (
            meta.get("api_version") == "03" and meta.get("service") == NUTRITION_SERVICE
        )
        items_hash = hashlib.sha256(
            json.dumps(items, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        id_field = "FOOD_CD"
    if not valid_service or meta.get("items_sha256") != items_hash:
        raise ValueError(f"{dataset}: source version or content checksum mismatch")
    ids = [str(row.get(id_field) or "").strip() for row in items]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{dataset}: missing or duplicate source IDs")
    if dataset == "recipes" and any(not value.isdigit() for value in ids):
        raise ValueError("recipes: numeric RCP_SEQ required")
    return items, {"file_sha256": hashlib.sha256(raw_bytes).hexdigest(), "meta": meta}


@dataclass
class ImportPlan:
    inputs: dict
    fingerprint: str
    recipes: list[dict]
    foods: list[dict]
    counts: dict


def prepare_import(
    dataset: str,
    recipes_path: Path = paths.RECIPES_ALL_RAW,
    nutrition_path: Path = paths.NUTRITION_RAW,
    corrections_path: Path = paths.RECIPE_CORRECTIONS,
) -> ImportPlan:
    inputs, recipes, foods = {}, [], []
    if dataset in ("recipes", "all"):
        rows, inputs["recipes"] = read_snapshot(recipes_path, "recipes")
        corrections_bytes = corrections_path.read_bytes()
        manifest = json.loads(corrections_bytes)
        inputs["corrections_sha256"] = hashlib.sha256(corrections_bytes).hexdigest()
        inputs["recipe_validation"] = {
            "version": RECIPE_VALIDATION_VERSION,
            "schema_version": RECIPE_SCHEMA_VERSION,
            "allergen_rules_sha256": sha256_json(
                json.loads(RULES_FILE.read_text(encoding="utf-8"))
            ),
        }
        effective, audit = apply_corrections(rows, manifest)
        for raw, row in zip(rows, effective, strict=True):
            checked = check_recipe(row)
            entry = {
                "source_id": checked.source_id,
                "raw": raw,
                "effective": row,
                "check": checked.to_dict(),
                "corrections": [
                    item for item in audit if item["source_id"] == checked.source_id
                ],
            }
            entry["fingerprint"] = sha256_json(
                {
                    "raw": sha256_json(raw),
                    "effective": sha256_json(row),
                    "corrections": inputs["corrections_sha256"],
                    "validation": inputs["recipe_validation"],
                    "parser": PARSER_VERSION,
                }
            )
            recipes.append(entry)
    if dataset in ("nutrition", "all"):
        rows, inputs["nutrition"] = read_snapshot(nutrition_path, "nutrition")
        for raw, food in zip(rows, clean_foods(rows), strict=True):
            record = food.to_dict()
            if not record["name"]:
                raise ValueError("nutrition: food name is required")
            foods.append(
                {
                    "raw": raw,
                    "record": record,
                    "fingerprint": sha256_json(
                        {
                            "raw": sha256_json(raw),
                            "normalized": record,
                            "parser": PARSER_VERSION,
                        }
                    ),
                }
            )
        inputs["nutrition_normalization_sha256"] = sha256_json(
            [entry["fingerprint"] for entry in foods]
        )
    status = Counter(entry["check"]["status"] for entry in recipes)
    counts = {
        "recipes": len(recipes),
        "recipe_quality": dict(status),
        "foods": len(foods),
        "steps": sum(len(entry["check"]["steps"]) for entry in recipes),
        "ingredients": sum(len(entry["check"]["ingredients"]) for entry in recipes),
        "corrections": sum(len(entry["corrections"]) for entry in recipes),
    }
    return ImportPlan(
        inputs,
        sha256_json({"inputs": inputs, "parser": PARSER_VERSION}),
        recipes,
        foods,
        counts,
    )


def apply_import(session: Session, plan: ImportPlan) -> dict:
    """Caller owns the transaction; never commit a partially applied dataset."""
    session.execute(text("SELECT pg_advisory_xact_lock(6711061156)"))
    previous = session.scalar(
        select(DataImportRun).where(DataImportRun.fingerprint == plan.fingerprint)
    )
    if previous:
        return {
            "run_id": str(previous.id),
            "already_imported": True,
            **previous.counts,
            "new_recipes": 0,
            "new_recipe_revisions": 0,
            "new_foods": 0,
            "new_food_revisions": 0,
        }
    history = list(session.scalars(select(DataImportRun.inputs)))
    for dataset in ("recipes", "nutrition"):
        if dataset not in plan.inputs:
            continue
        incoming = snapshot_time(plan.inputs[dataset]["meta"])
        known_times = [
            timestamp
            for inputs in history
            if dataset in inputs
            if (timestamp := snapshot_time(inputs[dataset]["meta"])) is not None
        ]
        if known_times and (incoming is None or incoming < max(known_times)):
            raise ValueError(
                f"{dataset}: older or undated snapshot cannot replace newer data"
            )
    run = DataImportRun(
        id=uuid.uuid4(),
        fingerprint=plan.fingerprint,
        parser_version=PARSER_VERSION,
        inputs=plan.inputs,
        counts=plan.counts,
    )
    session.add(run)
    session.flush()
    new_recipes = new_recipe_revisions = new_foods = new_food_revisions = 0
    for entry in plan.recipes:
        recipe = session.scalar(
            select(Recipe).where(
                Recipe.provider == RECIPE_PROVIDER,
                Recipe.source_id == entry["source_id"],
            )
        )
        if recipe is None:
            recipe = Recipe(
                id=uuid.uuid4(), provider=RECIPE_PROVIDER, source_id=entry["source_id"]
            )
            session.add(recipe)
            session.flush()
            new_recipes += 1
        revision = session.scalar(
            select(RecipeRevision).where(
                RecipeRevision.recipe_id == recipe.id,
                RecipeRevision.fingerprint == entry["fingerprint"],
            )
        )
        if revision is None:
            row, checked = entry["effective"], entry["check"]
            revision = RecipeRevision(
                id=uuid.uuid4(),
                recipe_id=recipe.id,
                import_run_id=run.id,
                fingerprint=entry["fingerprint"],
                raw_sha256=sha256_json(entry["raw"]),
                effective_sha256=sha256_json(row),
                raw=entry["raw"],
                effective=row,
                corrections=entry["corrections"],
                name=checked["name"],
                method=row.get("RCP_WAY2"),
                category=row.get("RCP_PAT2"),
                quality_status=checked["status"],
                issues=checked["issues"],
                missing_step_nos=checked["missing_step_nos"],
                source_weight_text=row.get("INFO_WGT") or None,
                **{
                    key: decimal_value(row.get(source))
                    for key, source in RECIPE_NUTRIENTS.items()
                },
            )
            session.add(revision)
            session.flush()
            for step in checked["steps"]:
                session.add(
                    RecipeStep(
                        recipe_revision_id=revision.id,
                        **{
                            key: step[key]
                            for key in (
                                "source_no",
                                "stated_no",
                                "source_field",
                                "text_raw",
                                "text_clean",
                                "image_url",
                            )
                        },
                    )
                )
            for ingredient in checked["ingredients"]:
                session.add(
                    RecipeIngredient(
                        recipe_revision_id=revision.id,
                        parsed=ingredient,
                        **{
                            key: ingredient[key]
                            for key in (
                                "order_no",
                                "line_no",
                                "section",
                                "raw_item",
                                "name_raw",
                                "name",
                                "amount_text",
                                "unit",
                            )
                        },
                    )
                )
            new_recipe_revisions += 1
        # Hold records remain traceable but cannot enter the active application dataset.
        recipe.active_revision_id = (
            revision.id if revision.quality_status != "hold" else None
        )
    for entry in plan.foods:
        raw, record = entry["raw"], entry["record"]
        food = session.scalar(
            select(Food).where(
                Food.provider == FOOD_PROVIDER, Food.food_code == record["food_code"]
            )
        )
        if food is None:
            food = Food(
                id=uuid.uuid4(), provider=FOOD_PROVIDER, food_code=record["food_code"]
            )
            session.add(food)
            session.flush()
            new_foods += 1
        revision = session.scalar(
            select(FoodRevision).where(
                FoodRevision.food_id == food.id,
                FoodRevision.fingerprint == entry["fingerprint"],
            )
        )
        if revision is None:
            exact = food_nutrient_values(entry)
            basis = decimal_value(record["basis_amount"])
            if basis is not None and basis <= 0:
                raise ValueError("nutrition: basis amount must be positive")
            revision = FoodRevision(
                id=uuid.uuid4(),
                food_id=food.id,
                import_run_id=run.id,
                fingerprint=entry["fingerprint"],
                raw_sha256=record["raw_sha256"],
                raw=raw,
                normalized=record,
                name=record["name"],
                basis_text=record["basis_text"],
                basis_amount=basis,
                basis_unit=record["basis_unit"],
                quality_flags=record["quality_flags"],
                nutrients={
                    key: str(value) if value is not None else None
                    for key, value in exact.items()
                },
                **{key: exact[key] for key in FOOD_COLUMNS},
            )
            session.add(revision)
            session.flush()
            new_food_revisions += 1
        food.active_revision_id = revision.id
    result = {
        **plan.counts,
        "new_recipes": new_recipes,
        "new_recipe_revisions": new_recipe_revisions,
        "new_foods": new_foods,
        "new_food_revisions": new_food_revisions,
    }
    run.counts = result
    session.flush()
    return {"run_id": str(run.id), "already_imported": False, **result}


def verify_import(session: Session, plan: ImportPlan) -> dict:
    """Read-only comparison of all planned revisions against their source snapshots."""
    recipe_rows = (
        session.scalars(
            select(RecipeRevision).where(
                RecipeRevision.fingerprint.in_(
                    [entry["fingerprint"] for entry in plan.recipes]
                )
            )
        ).all()
        if plan.recipes
        else []
    )
    food_rows = (
        session.scalars(
            select(FoodRevision).where(
                FoodRevision.fingerprint.in_(
                    [entry["fingerprint"] for entry in plan.foods]
                )
            )
        ).all()
        if plan.foods
        else []
    )
    recipes = {revision.fingerprint: revision for revision in recipe_rows}
    foods = {revision.fingerprint: revision for revision in food_rows}
    if len(recipes) != len(plan.recipes) or len(foods) != len(plan.foods):
        raise ValueError("Expected source revisions are missing")
    for entry in plan.recipes:
        revision = recipes[entry["fingerprint"]]
        if (
            revision.raw != entry["raw"]
            or revision.effective != entry["effective"]
            or revision.raw_sha256 != sha256_json(entry["raw"])
            or revision.effective_sha256 != sha256_json(entry["effective"])
            or revision.quality_status != entry["check"]["status"]
        ):
            raise ValueError("Recipe source or quality does not match the snapshot")
        for column, field in RECIPE_NUTRIENTS.items():
            if getattr(revision, column) != decimal_value(
                entry["effective"].get(field)
            ):
                raise ValueError("Recipe nutrition differs from the source value")
    for entry in plan.foods:
        revision = foods[entry["fingerprint"]]
        exact = food_nutrient_values(entry)
        expected_nutrients = {
            key: str(value) if value is not None else None
            for key, value in exact.items()
        }
        if (
            revision.raw != entry["raw"]
            or revision.raw_sha256 != sha256_json(entry["raw"])
            or revision.normalized != entry["record"]
            or revision.nutrients != expected_nutrients
            or revision.basis_unit != entry["record"]["basis_unit"]
        ):
            raise ValueError(
                "Food source, nutrition or units do not match the snapshot"
            )
        for column in FOOD_COLUMNS:
            if getattr(revision, column) != exact[column]:
                raise ValueError("Food nutrition differs from the source value")
    return {
        "verified": True,
        "recipe_revisions": len(recipes),
        "food_revisions": len(foods),
        "fingerprint": plan.fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", choices=("all", "recipes", "nutrition"), default="all"
    )
    parser.add_argument("--recipes", type=Path, default=paths.RECIPES_ALL_RAW)
    parser.add_argument("--nutrition", type=Path, default=paths.NUTRITION_RAW)
    parser.add_argument("--corrections", type=Path, default=paths.RECIPE_CORRECTIONS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = prepare_import(
            args.dataset, args.recipes, args.nutrition, args.corrections
        )
        if args.verify:
            from app.core.database import SessionLocal

            with SessionLocal() as session:
                result = verify_import(session, plan)
        elif args.apply:
            from app.core.database import SessionLocal

            with SessionLocal.begin() as session:
                result = apply_import(session, plan)
        else:
            result = {"dry_run": True, "fingerprint": plan.fingerprint, **plan.counts}
    except (OSError, ValueError, SQLAlchemyError) as error:
        # Driver messages can include connection details; never print exception strings.
        print(
            f"Import failed ({type(error).__name__}). Check complete input snapshots and database schema/connectivity; no partial import was committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
