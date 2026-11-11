"""Import a refresh 'food of the month' snapshot and link it to active recipes; default is a dry run.

Input is the data refresh output (agetech_data.collect.seasonal via agetech_data.refresh):
data/raw/seasonal/food_month.json. Rows come from agetech_data.seasonal.revision. Recipe links are
computed against the *active recipe revisions in this database* (import recipes first), so the
links always describe recipes the app can serve.

Tables: seasonal_foods (one row per month/item with detail text), seasonal_ingredients (recipe
ingredient name -> seasonal item, with match evidence), seasonal_recipe_links (recipe -> item with
weight share). Items missing from a newer complete snapshot are unpublished and lose their links.
Manually entered seasonal_ingredients rows (seasonal_food_id NULL) are never touched.
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from agetech_data import paths
from agetech_data.collect.seasonal import SERVICE
from agetech_data.seasonal.normalize import load_rules
from agetech_data.seasonal.revision import NORMALIZER_VERSION, PROVIDER, seasonal_rows
from agetech_data.snapshot import aware_time
from agetech_data.textutil import sha256_json
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    DataImportRun,
    Recipe,
    RecipeIngredient,
    RecipeRevision,
    SeasonalFood,
    SeasonalIngredient,
    SeasonalRecipeLink,
)

# Shared with the recipe import, so links are computed against a settled recipe set.
IMPORT_LOCK = 6711061156
FOOD_COLUMNS = (
    "month",
    "fdmt_sn",
    "name",
    "terms",
    "image_url",
    "detail",
    "detail_status",
    "official_related_recipes",
    "shopping_search_url",
    "source_url",
    "checked_on",
    "normalized",
    "content_sha256",
)
CONTENT_COLUMNS = (
    "detail",
    "detail_status",
    "official_related_recipes",
    "normalized",
    "content_sha256",
)


def number(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(repr(value))


@dataclass
class ActiveRecipes:
    """Active recipe revisions in the contract shape agetech_data.seasonal expects."""

    records: list[dict]
    # source_id -> (recipe id, active revision id)
    revisions: dict[str, tuple[uuid.UUID, uuid.UUID]]
    sha256: str


@dataclass
class SeasonalPlan:
    inputs: dict
    collected_at: datetime
    snapshot: dict
    partial: bool
    counts: dict
    rows: list[dict] = field(default_factory=list)
    fingerprint: str = ""


def read_snapshot(
    path: Path, allow_partial_details: bool = False
) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    snapshot = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("meta"), dict):
        raise ValueError("Complete seasonal collector metadata is required")
    meta, items = snapshot["meta"], snapshot.get("items")
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(item, dict) for item in items)
        or (meta.get("complete") is not True and not allow_partial_details)
        or meta.get("item_count") != len(items)
        or meta.get("service") != SERVICE
        or meta.get("items_sha256") != sha256_json(items)
    ):
        raise ValueError(
            "Seasonal snapshot is incomplete or its source/checksum/count is invalid"
        )
    failed = sum(item.get("detail_status") != "ok" for item in items)
    if meta.get("complete") is True and failed:
        raise ValueError("A complete seasonal snapshot cannot have missing details")
    if {item.get("month") for item in items} != set(range(1, 13)):
        raise ValueError("Seasonal snapshot must cover all twelve months")
    row_ids = [item.get("row_id") for item in items]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("Duplicate seasonal item IDs")
    return snapshot, raw


def prepare_import(
    path: Path = paths.SEASONAL_RAW, allow_partial_details: bool = False
) -> SeasonalPlan:
    """File-only part. Recipe links are added by link_plan() inside the database lock."""
    snapshot, raw = read_snapshot(path, allow_partial_details)
    collected_at = aware_time(snapshot["meta"]["fetched_at"])
    if collected_at > datetime.now(UTC):
        raise ValueError("Seasonal collection time cannot be in the future")
    items = snapshot["items"]
    inputs = {
        "dataset": "seasonal_foods",
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "meta": snapshot["meta"],
        "rules_sha256": sha256_json(load_rules()),
    }
    counts = {
        "items": len(items),
        "details_ok": sum(item.get("detail_status") == "ok" for item in items),
        "details_failed": sum(item.get("detail_status") != "ok" for item in items),
    }
    return SeasonalPlan(
        inputs,
        collected_at,
        snapshot,
        snapshot["meta"].get("complete") is not True,
        counts,
    )


def load_active_recipes(session: Session) -> ActiveRecipes:
    revisions = session.execute(
        select(
            Recipe.source_id,
            Recipe.id,
            RecipeRevision.id,
            RecipeRevision.fingerprint,
            RecipeRevision.name,
            RecipeRevision.category,
            RecipeRevision.quality_status,
        ).join(RecipeRevision, RecipeRevision.id == Recipe.active_revision_id)
    ).all()
    ingredients: dict[uuid.UUID, list[dict]] = {}
    for revision_id, parsed in session.execute(
        select(RecipeIngredient.recipe_revision_id, RecipeIngredient.parsed)
        .where(RecipeIngredient.recipe_revision_id.in_([row[2] for row in revisions]))
        .order_by(RecipeIngredient.recipe_revision_id, RecipeIngredient.order_no)
    ):
        ingredients.setdefault(revision_id, []).append(parsed)
    records, by_source, identity = [], {}, []
    for (
        source_id,
        recipe_id,
        revision_id,
        fingerprint,
        name,
        category,
        status,
    ) in sorted(revisions, key=lambda row: (len(row[0]), row[0])):
        records.append(
            {
                "recipe_id": source_id,
                "name": name,
                "category": category,
                "quality": {"status": status},
                "ingredients": ingredients.get(revision_id, []),
            }
        )
        by_source[source_id] = (recipe_id, revision_id)
        identity.append([source_id, fingerprint])
    return ActiveRecipes(records, by_source, sha256_json(identity))


def link_plan(plan: SeasonalPlan, recipes: ActiveRecipes) -> SeasonalPlan:
    if not recipes.records:
        raise ValueError("Import active recipes before linking seasonal items")
    rows = seasonal_rows(plan.snapshot, recipes.records)
    inputs = {**plan.inputs, "recipes_sha256": recipes.sha256}
    links = [link for row in rows for link in row["recipes"]]
    counts = {
        **plan.counts,
        "published": sum(row["is_published"] for row in rows),
        "linked_items": sum(bool(row["recipes"]) for row in rows),
        "ingredient_names": sum(len(row["ingredients"]) for row in rows),
        "ingredient_matches": dict(
            Counter(i["kind"] for row in rows for i in row["ingredients"])
        ),
        "recipe_links": len(links),
        "recipes_with_seasonal": len({link["recipe_id"] for link in links}),
        "active_recipes": len(recipes.records),
    }
    return SeasonalPlan(
        inputs,
        plan.collected_at,
        plan.snapshot,
        plan.partial,
        counts,
        rows,
        sha256_json({"input": inputs, "normalizer": NORMALIZER_VERSION}),
    )


def manual_names(session: Session) -> set[tuple[int, str]]:
    """(month, recipe ingredient name) already curated by hand; those win over rule-based matches."""
    return set(
        session.execute(
            select(
                SeasonalIngredient.month, SeasonalIngredient.recipe_ingredient_name
            ).where(SeasonalIngredient.seasonal_food_id.is_(None))
        ).all()
    )


def ingredient_rows(
    food: SeasonalFood, row: dict, manual: set[tuple[int, str]]
) -> list[SeasonalIngredient]:
    return [
        SeasonalIngredient(
            month=food.month,
            ingredient_name=food.name,
            recipe_ingredient_name=item["name"],
            source_url=food.source_url,
            checked_on=row["checked_on"],
            is_published=food.is_published,
            seasonal_food_id=food.id,
            match_term=item["term"],
            match_kind=item["kind"],
        )
        for item in row["ingredients"]
        if (food.month, item["name"]) not in manual
    ]


def link_rows(
    food: SeasonalFood, row: dict, recipes: ActiveRecipes
) -> list[SeasonalRecipeLink]:
    out = []
    for link in row["recipes"]:
        recipe_id, revision_id = recipes.revisions[link["recipe_id"]]
        out.append(
            SeasonalRecipeLink(
                seasonal_food_id=food.id,
                recipe_id=recipe_id,
                recipe_revision_id=revision_id,
                ingredient_names=link["ingredients"],
                weight_g=number(link["weight_g"]),
                share=number(link["share"]),
            )
        )
    return out


def stored_links(session: Session) -> dict[uuid.UUID, set]:
    out: dict[uuid.UUID, set] = {}
    for food_id, recipe_id, revision_id in session.execute(
        select(
            SeasonalRecipeLink.seasonal_food_id,
            SeasonalRecipeLink.recipe_id,
            SeasonalRecipeLink.recipe_revision_id,
        )
    ):
        out.setdefault(food_id, set()).add((recipe_id, revision_id))
    return out


def planned_links(row: dict, recipes: ActiveRecipes) -> set:
    return {recipes.revisions[link["recipe_id"]] for link in row["recipes"]}


def needs_relink(
    food: SeasonalFood | None, row: dict, current: dict, recipes: ActiveRecipes
) -> bool:
    return (
        food is None
        or food.links_sha256 != row["links_sha256"]
        or current.get(food.id, set()) != planned_links(row, recipes)
    )


def apply_import(session: Session, plan: SeasonalPlan) -> dict:
    """Caller owns the transaction; never commit a partially applied snapshot."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
    recipes = load_active_recipes(session)
    plan = link_plan(plan, recipes)
    existing = session.scalars(
        select(SeasonalFood).where(SeasonalFood.provider == PROVIDER)
    ).all()
    by_source = {food.source_id: food for food in existing}
    current_links = stored_links(session)
    previous = session.scalar(
        select(DataImportRun).where(DataImportRun.fingerprint == plan.fingerprint)
    )
    # Same fingerprint is not enough: active recipes can go A -> B -> A (a source edit reverted),
    # leaving links on B's revisions. Skip only when every stored link already matches.
    if previous and not any(
        needs_relink(by_source.get(row["source_id"]), row, current_links, recipes)
        for row in plan.rows
    ):
        return {
            "run_id": str(previous.id),
            "already_imported": True,
            **previous.counts,
            "new_items": 0,
            "changed_items": 0,
            "relinked_items": 0,
            "newly_unpublished": 0,
        }
    if any(food.last_seen_at > plan.collected_at for food in existing):
        raise ValueError(
            "An older seasonal snapshot cannot replace the latest successful scan"
        )
    run = previous or DataImportRun(
        id=uuid.uuid4(),
        fingerprint=plan.fingerprint,
        parser_version=NORMALIZER_VERSION,
        inputs=plan.inputs,
        counts=plan.counts,
    )
    session.add(run)
    session.flush()
    new = changed = kept_details = newly_unpublished = 0
    relink: list[tuple[SeasonalFood, dict]] = []
    for row in plan.rows:
        food = by_source.get(row["source_id"])
        values = {column: row[column] for column in FOOD_COLUMNS}
        if food is None:
            food = SeasonalFood(
                id=uuid.uuid4(), provider=PROVIDER, source_id=row["source_id"]
            )
            session.add(food)
            new += 1
        else:
            if row["detail_status"] != "ok" and food.detail_status == "ok":
                # Partial snapshot: keep the last good detail text instead of blanking it.
                for column in CONTENT_COLUMNS:
                    values[column] = getattr(food, column)
                kept_details += 1
            if any(getattr(food, column) != value for column, value in values.items()):
                changed += 1
        for column, value in values.items():
            setattr(food, column, value)
        food.is_published = row["is_published"]
        food.last_seen_at, food.last_seen_run_id = plan.collected_at, run.id
        if needs_relink(food, row, current_links, recipes):
            relink.append((food, row))
        food.links_sha256 = row["links_sha256"]
    session.flush()
    seen = {row["source_id"] for row in plan.rows}
    gone = [food for source_id, food in by_source.items() if source_id not in seen]
    for food in gone:
        if food.is_published:
            newly_unpublished += 1
        food.is_published = False
    # Delete every outdated mapping first so a name moving between items never hits the unique key.
    stale = [food.id for food, _ in relink] + [food.id for food in gone]
    if stale:
        session.execute(
            delete(SeasonalIngredient).where(
                SeasonalIngredient.seasonal_food_id.in_(stale)
            )
        )
        session.execute(
            delete(SeasonalRecipeLink).where(
                SeasonalRecipeLink.seasonal_food_id.in_(stale)
            )
        )
        session.flush()
    relinked = {food.id for food, _ in relink}
    manual = manual_names(session)
    for food, row in relink:
        session.add_all(ingredient_rows(food, row, manual))
        session.add_all(link_rows(food, row, recipes))
    for row in plan.rows:
        food = by_source.get(row["source_id"])
        if food is not None and food.id not in relinked:
            session.execute(
                update(SeasonalIngredient)
                .where(SeasonalIngredient.seasonal_food_id == food.id)
                .values(checked_on=row["checked_on"], is_published=food.is_published)
            )
    result = {
        **plan.counts,
        "new_items": new,
        "changed_items": changed,
        "relinked_items": len(relink),
        "kept_previous_details": kept_details,
        "newly_unpublished": newly_unpublished,
        "manual_overrides": sum(
            (row["month"], item["name"]) in manual
            for row in plan.rows
            for item in row["ingredients"]
        ),
    }
    run.counts, run.completed_at = result, datetime.now(UTC)
    session.flush()
    return {"run_id": str(run.id), "already_imported": False, **result}


def verify_import(session: Session, plan: SeasonalPlan) -> dict:
    """Read-only: items, ingredient mappings and recipe links all match a fresh plan."""
    recipes = load_active_recipes(session)
    plan = link_plan(plan, recipes)
    manual = manual_names(session)
    stored = {
        food.source_id: food
        for food in session.scalars(
            select(SeasonalFood).where(SeasonalFood.provider == PROVIDER)
        )
    }
    for row in plan.rows:
        food = stored.get(row["source_id"])
        if food is None:
            raise ValueError("Seasonal items are missing")
        columns = FOOD_COLUMNS if row["detail_status"] == "ok" else ("month", "name")
        if any(getattr(food, column) != row[column] for column in columns) or (
            food.is_published != row["is_published"]
            or food.links_sha256 != row["links_sha256"]
        ):
            raise ValueError("Seasonal item fields differ from the snapshot")
        mapped = {
            (item.recipe_ingredient_name, item.match_term, item.match_kind, item.month)
            for item in session.scalars(
                select(SeasonalIngredient).where(
                    SeasonalIngredient.seasonal_food_id == food.id
                )
            )
        }
        if mapped != {
            (item["name"], item["term"], item["kind"], row["month"])
            for item in row["ingredients"]
            if (row["month"], item["name"]) not in manual
        }:
            raise ValueError("Seasonal ingredient mappings differ")
        links = {
            (
                link.recipe_id,
                link.recipe_revision_id,
                tuple(link.ingredient_names),
                link.weight_g,
                link.share,
            )
            for link in session.scalars(
                select(SeasonalRecipeLink).where(
                    SeasonalRecipeLink.seasonal_food_id == food.id
                )
            )
        }
        if links != {
            (
                *recipes.revisions[link["recipe_id"]],
                tuple(link["ingredients"]),
                number(link["weight_g"]),
                number(link["share"]),
            )
            for link in row["recipes"]
        }:
            raise ValueError("Seasonal recipe links differ from the active recipes")
    planned = {row["source_id"] for row in plan.rows}
    if any(food.is_published and key not in planned for key, food in stored.items()):
        raise ValueError("A seasonal item missing from the snapshot is still published")
    return {
        "verified": True,
        "items": len(plan.rows),
        "recipe_links": plan.counts["recipe_links"],
        "fingerprint": plan.fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=paths.SEASONAL_RAW)
    parser.add_argument(
        "--allow-partial-details",
        action="store_true",
        help="import a snapshot with failed details, keeping previously stored detail text",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = prepare_import(args.input, args.allow_partial_details)
        if args.apply or args.verify:
            from app.core.database import SessionLocal

            with SessionLocal.begin() as session:
                result = (
                    apply_import(session, plan)
                    if args.apply
                    else verify_import(session, plan)
                )
        else:
            result = {
                "dry_run": True,
                "note": "recipe links are computed against the database on --apply",
                **plan.counts,
            }
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        # Driver messages can include connection details; never print exception strings.
        print(
            "Seasonal import failed. Check the complete refresh snapshot, imported recipes, seasonal rules and database schema. Transaction was not committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
