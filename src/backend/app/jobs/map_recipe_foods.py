"""Map active recipe ingredients to active food revisions and store computed recipe nutrition.

Run after the recipe and nutrition imports (app.jobs.import_public_data). Everything is read from
the database: active recipe revisions with their parsed ingredients, active food revisions and the
reviewed ingredient map (agetech_data resources/ingredient_food_map.json). The mapping, gram
conversion and nutrient contributions are agetech_data.nutrition.recipe_map, the same calculation
as the data report (data/processed/recipe_ingredient_nutrition.json).

Default is a read-only dry run that computes everything and prints counts. Rows of recipe
revisions that are no longer active are kept (meal plans may still point at them).
"""

import argparse
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from agetech_data.nutrition.foods import FoodRecord
from agetech_data.nutrition.match import USABLE, load_ingredient_map
from agetech_data.nutrition.recipe_map import (
    MAPPER_VERSION,
    food_records,
    map_sha256,
    recipe_map_rows,
)
from agetech_data.textutil import sha256_json
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.jobs.import_public_data import FOOD_PROVIDER, RECIPE_PROVIDER
from app.models import (
    DataImportRun,
    Food,
    FoodRevision,
    Recipe,
    RecipeComputedNutrition,
    RecipeIngredient,
    RecipeIngredientFood,
    RecipeRevision,
)

# Shared with the public-data imports, so a mapping never sees a half-imported recipe or food set.
IMPORT_LOCK = 6711061156
BACKLOG = 20  # most frequent unresolved ingredient names reported for review


def number(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(repr(value))


@dataclass
class ActiveData:
    recipes: list[dict]
    # source_id -> (recipe id, active revision id)
    revisions: dict[str, tuple[uuid.UUID, uuid.UUID]]
    # revision id -> order_no -> recipe_ingredients.id
    ingredient_ids: dict[uuid.UUID, dict[int, uuid.UUID]]
    foods: list[FoodRecord]
    # food_code -> (food id, active revision id)
    food_revisions: dict[str, tuple[uuid.UUID, uuid.UUID]]
    recipes_sha256: str
    foods_sha256: str


@dataclass
class MappingPlan:
    fingerprint: str
    inputs: dict
    rows: list[dict]
    counts: dict


def load_active(session: Session) -> ActiveData:
    recipe_rows = session.execute(
        select(
            Recipe.source_id, Recipe.id, RecipeRevision.id, RecipeRevision.fingerprint
        )
        .join(RecipeRevision, RecipeRevision.id == Recipe.active_revision_id)
        .where(Recipe.provider == RECIPE_PROVIDER)
        .order_by(Recipe.source_id)
    ).all()
    parsed: dict[uuid.UUID, list[dict]] = {}
    ingredient_ids: dict[uuid.UUID, dict[int, uuid.UUID]] = {}
    for ingredient_id, revision_id, order_no, item in session.execute(
        select(
            RecipeIngredient.id,
            RecipeIngredient.recipe_revision_id,
            RecipeIngredient.order_no,
            RecipeIngredient.parsed,
        ).where(
            RecipeIngredient.recipe_revision_id.in_([row[2] for row in recipe_rows])
        )
    ):
        parsed.setdefault(revision_id, []).append(item)
        ingredient_ids.setdefault(revision_id, {})[order_no] = ingredient_id
    food_rows = session.execute(
        select(
            Food.food_code,
            Food.id,
            FoodRevision.id,
            FoodRevision.fingerprint,
            FoodRevision.normalized,
        )
        .join(FoodRevision, FoodRevision.id == Food.active_revision_id)
        .where(Food.provider == FOOD_PROVIDER)
        .order_by(Food.food_code)
    ).all()
    return ActiveData(
        recipes=[
            {"recipe_id": source_id, "ingredients": parsed.get(revision_id, [])}
            for source_id, _, revision_id, _ in recipe_rows
        ],
        revisions={row[0]: (row[1], row[2]) for row in recipe_rows},
        ingredient_ids=ingredient_ids,
        foods=food_records([row[4] for row in food_rows]),
        food_revisions={row[0]: (row[1], row[2]) for row in food_rows},
        recipes_sha256=sha256_json([[row[0], row[3]] for row in recipe_rows]),
        foods_sha256=sha256_json([[row[0], row[3]] for row in food_rows]),
    )


def plan_mapping(active: ActiveData, entries=None) -> MappingPlan:
    if not active.recipes or not active.foods:
        raise ValueError("Import active recipes and foods before mapping")
    entries = load_ingredient_map() if entries is None else entries
    entries_sha256 = map_sha256(entries)
    rows = recipe_map_rows(active.recipes, active.foods, entries)
    for row in rows:
        row["recipe_uuid"], row["revision_id"] = active.revisions[row["recipe_id"]]
        used = []
        for item in row["ingredients"]:
            match = item["match"]
            item["food"] = (
                active.food_revisions[match["food_code"]]
                if match["status"] in USABLE
                else None
            )
            used.append(str(item["food"][1]) if item["food"] else None)
        # A newer food revision with the same values still moves the stored pointers, and every
        # row records which mapper and ingredient map produced it.
        row["mapping_sha256"] = sha256_json(
            {
                "content": row["content_sha256"],
                "food_revisions": used,
                "mapper_version": MAPPER_VERSION,
                "ingredient_map_sha256": entries_sha256,
            }
        )
    items = [item for row in rows for item in row["ingredients"]]
    unresolved = Counter(
        item["name"]
        for item in items
        if item["match"]["status"] in ("candidate", "unmapped")
    )
    inputs = {
        "dataset": "recipe_food_map",
        "mapper_version": MAPPER_VERSION,
        "recipes_sha256": active.recipes_sha256,
        "foods_sha256": active.foods_sha256,
        "ingredient_map_sha256": entries_sha256,
        "mapping_manifest": {row["recipe_id"]: row["mapping_sha256"] for row in rows},
    }
    counts = {
        "recipes": len(rows),
        "ingredients": len(items),
        "match_status": dict(Counter(item["match"]["status"] for item in items)),
        "gram_status": dict(Counter(item["grams"]["status"] for item in items)),
        "used_in_calculation": sum(item["contribution"] is not None for item in items),
        "ml_approx_items": sum(item["basis_ml_approx"] for item in items),
        "complete_recipes": sum(row["coverage"]["complete"] for row in rows),
        "foods": len(active.foods),
        "unresolved_top": unresolved.most_common(BACKLOG),
    }
    return MappingPlan(sha256_json(inputs), inputs, rows, counts)


def ingredient_values(row: dict, item: dict, active: ActiveData) -> dict:
    review = item["review"] or {}
    food = item["food"]
    match, grams = item["match"], item["grams"]
    return {
        "recipe_revision_id": row["revision_id"],
        "recipe_ingredient_id": active.ingredient_ids[row["revision_id"]][
            item["order_no"]
        ],
        "order_no": item["order_no"],
        "match_status": match["status"],
        "match_rule": match["rule"],
        "match_rationale": match["rationale"],
        "candidates": match["candidates"],
        "food_id": food[0] if food else None,
        "food_revision_id": food[1] if food else None,
        "reviewed_by": review.get("by"),
        "reviewed_on": date.fromisoformat(review["on"]) if review.get("on") else None,
        "grams": number(grams["grams"]),
        "gram_status": grams["status"],
        "gram_basis": grams["basis"],
        "contribution": item["contribution"],
        "basis_ml_approx": item["basis_ml_approx"],
    }


def summary_values(row: dict, plan: MappingPlan) -> dict:
    coverage = row["coverage"]
    return {
        "recipe_id": row["recipe_uuid"],
        "recipe_revision_id": row["revision_id"],
        "computed": row["computed"],
        "computed_missing": row["computed_missing"],
        "coverage": coverage,
        "complete": coverage["complete"],
        "items": coverage["items"],
        "items_used": coverage["items_used"],
        "grams_used_pct": number(coverage["grams_used_pct"]),
        "mapper_version": MAPPER_VERSION,
        "ingredient_map_sha256": plan.inputs["ingredient_map_sha256"],
        "mapping_sha256": row["mapping_sha256"],
    }


def apply_mapping(session: Session, entries=None) -> dict:
    """Caller owns the transaction; never commit a partially written mapping."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
    active = load_active(session)
    plan = plan_mapping(active, entries)
    stored = dict(
        session.execute(
            select(
                RecipeComputedNutrition.recipe_revision_id,
                RecipeComputedNutrition.mapping_sha256,
            ).where(
                RecipeComputedNutrition.recipe_revision_id.in_(
                    [row["revision_id"] for row in plan.rows]
                )
            )
        ).all()
    )
    changed = [
        row
        for row in plan.rows
        if stored.get(row["revision_id"]) != row["mapping_sha256"]
    ]
    previous = session.scalar(
        select(DataImportRun).where(DataImportRun.fingerprint == plan.fingerprint)
    )
    # Same inputs as an earlier run is not enough: inputs can go A -> B -> A (e.g. a map edit
    # reverted), so skip only when the stored rows already equal this calculation.
    if previous and not changed:
        return {
            "run_id": str(previous.id),
            "already_mapped": True,
            **previous.counts,
            "remapped_recipes": 0,
        }
    run = previous or DataImportRun(
        id=uuid.uuid4(),
        fingerprint=plan.fingerprint,
        parser_version=MAPPER_VERSION,
        inputs=plan.inputs,
        counts=plan.counts,
    )
    session.add(run)
    session.flush()
    revision_ids = [row["revision_id"] for row in changed]
    if revision_ids:
        session.execute(
            delete(RecipeIngredientFood).where(
                RecipeIngredientFood.recipe_revision_id.in_(revision_ids)
            )
        )
        session.execute(
            delete(RecipeComputedNutrition).where(
                RecipeComputedNutrition.recipe_revision_id.in_(revision_ids)
            )
        )
        ingredient_rows = [
            ingredient_values(row, item, active)
            for row in changed
            for item in row["ingredients"]
        ]
        if ingredient_rows:
            session.execute(insert(RecipeIngredientFood), ingredient_rows)
        session.execute(
            insert(RecipeComputedNutrition),
            [
                {**summary_values(row, plan), "mapping_run_id": run.id}
                for row in changed
            ],
        )
    result = {**plan.counts, "remapped_recipes": len(changed)}
    run.counts, run.completed_at = result, datetime.now(UTC)
    session.flush()
    return {"run_id": str(run.id), "already_mapped": False, **result}


def verify_mapping(session: Session, entries=None) -> dict:
    """Read-only: every active revision's stored mapping equals a fresh calculation."""
    active = load_active(session)
    plan = plan_mapping(active, entries)
    summaries = {
        summary.recipe_revision_id: summary
        for summary in session.scalars(
            select(RecipeComputedNutrition).where(
                RecipeComputedNutrition.recipe_revision_id.in_(
                    [row["revision_id"] for row in plan.rows]
                )
            )
        )
    }
    stored_items: dict[uuid.UUID, dict[uuid.UUID, RecipeIngredientFood]] = {}
    for item in session.scalars(
        select(RecipeIngredientFood).where(
            RecipeIngredientFood.recipe_revision_id.in_(list(summaries))
        )
    ):
        stored_items.setdefault(item.recipe_revision_id, {})[
            item.recipe_ingredient_id
        ] = item
    for row in plan.rows:
        summary = summaries.get(row["revision_id"])
        if summary is None:
            raise ValueError("Computed nutrition is missing for an active recipe")
        expected = summary_values(row, plan)
        if any(getattr(summary, key) != value for key, value in expected.items()):
            raise ValueError("Computed nutrition differs from a fresh calculation")
        items = stored_items.get(row["revision_id"], {})
        if len(items) != len(row["ingredients"]):
            raise ValueError("Ingredient mappings are missing")
        for item in row["ingredients"]:
            values = ingredient_values(row, item, active)
            stored = items.get(values["recipe_ingredient_id"])
            if stored is None or any(
                getattr(stored, key) != value for key, value in values.items()
            ):
                raise ValueError("Ingredient mapping differs from a fresh calculation")
    return {
        "verified": True,
        "recipes": len(plan.rows),
        "ingredients": plan.counts["ingredients"],
        "fingerprint": plan.fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.database import SessionLocal

        if args.apply:
            with SessionLocal.begin() as session:
                result = apply_mapping(session)
        else:
            with SessionLocal() as session:
                if args.verify:
                    result = verify_mapping(session)
                else:
                    plan = plan_mapping(load_active(session))
                    result = {
                        "dry_run": True,
                        "fingerprint": plan.fingerprint,
                        **plan.counts,
                    }
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        # Driver messages can include connection details; never print exception strings.
        print(
            "Recipe food mapping failed. Import recipes and foods first and check the database schema. Transaction was not committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
