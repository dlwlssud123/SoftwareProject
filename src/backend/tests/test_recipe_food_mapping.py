from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot

from app.jobs import import_public_data, map_recipe_foods
from app.models import (
    Food,
    Recipe,
    RecipeComputedNutrition,
    RecipeIngredient,
    RecipeIngredientFood,
)

DAY1, DAY2, DAY3 = (
    "2026-11-07T00:00:00+00:00",
    "2026-11-08T00:00:00+00:00",
    "2026-11-09T00:00:00+00:00",
)
RECIPES = [
    {
        "RCP_SEQ": "1",
        "RCP_NM": "시금치나물",
        "RCP_PARTS_DTLS": "시금치 200g, 참기름 5g, 물 100ml, 비밀양념 1큰술",
        "MANUAL01": "1. 데친다.",
    },
    {
        "RCP_SEQ": "2",
        "RCP_NM": "양파볶음",
        "RCP_PARTS_DTLS": "양파 1개, 참기름 10g",
        "MANUAL01": "1. 볶는다.",
    },
]


def food(code, name, kcal, sodium="1", basis="100g", group="원재료성"):
    return {
        "FOOD_CD": code,
        "FOOD_NM_KR": name,
        "DB_GRP_NM": group,
        "DB_CLASS_NM": "품목대표",
        "SERVING_SIZE": basis,
        "AMT_NUM1": kcal,
        "AMT_NUM3": "2.0",
        "AMT_NUM13": sodium,
    }


FOODS = [
    food("R1", "시금치, 생것", "30", "50"),
    food("R2", "참기름", "880"),
    food("R3", "양파, 생것", "40"),
]
MAP = (
    {
        "ingredient": "비밀양념",
        "food_code": "R2",
        "food_name": "참기름",
        "rationale": "시험용 수동 매핑",
        "reviewed_by": "최재영",
        "reviewed_at": "2026-11-09",
    },
)


def load(db, tmp_path, recipes=RECIPES, foods=FOODS, fetched_at=DAY1):
    for dataset, rows in (("recipes", recipes), ("nutrition", foods)):
        path = snapshot(
            tmp_path, dataset, rows=[dict(row) for row in rows], fetched_at=fetched_at
        )
        plan = import_public_data.prepare_import(
            dataset,
            recipes_path=path,
            nutrition_path=path,
            corrections_path=corrections(tmp_path),
        )
        import_public_data.apply_import(db, plan)


def mapping(db, source_id):
    recipe = db.scalar(select(Recipe).where(Recipe.source_id == source_id))
    items = db.scalars(
        select(RecipeIngredientFood)
        .where(RecipeIngredientFood.recipe_revision_id == recipe.active_revision_id)
        .order_by(RecipeIngredientFood.order_no)
    ).all()
    summary = db.scalar(
        select(RecipeComputedNutrition).where(
            RecipeComputedNutrition.recipe_revision_id == recipe.active_revision_id
        )
    )
    return recipe, items, summary


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_postgres_mapping_stores_matches_grams_and_computed_nutrition(
    tmp_path, pg_connection
):
    with Session(pg_connection) as db, db.begin():
        with pytest.raises(ValueError), db.begin_nested():  # 레시피·식품 적재 전
            map_recipe_foods.apply_mapping(db, MAP)
        load(db, tmp_path)
        result = map_recipe_foods.apply_mapping(db, MAP)
        assert (
            result["recipes"],
            result["ingredients"],
            result["remapped_recipes"],
        ) == (2, 6, 2)
        assert result["match_status"] == {"exact": 4, "water": 1, "reviewed": 1}
        assert map_recipe_foods.apply_mapping(db, MAP)["already_mapped"]
        assert map_recipe_foods.verify_mapping(db, MAP)["verified"]

        recipe, items, summary = mapping(db, "1")
        spinach, oil, water, secret = items
        r1 = db.scalar(select(Food).where(Food.food_code == "R1"))
        assert (spinach.match_status, spinach.match_rule) == ("exact", "raw")
        assert (spinach.food_id, spinach.food_revision_id) == (
            r1.id,
            r1.active_revision_id,
        )
        assert (spinach.grams, spinach.gram_status) == (Decimal("200.0"), "direct")
        assert (
            spinach.contribution["energy_kcal"] == 60.0
            and spinach.contribution["sodium_mg"] == 100.0
        )
        assert (
            water.match_status == "water"
            and water.food_id is None
            and water.contribution is None
        )
        assert (secret.match_status, secret.reviewed_by, secret.reviewed_on) == (
            "reviewed",
            "최재영",
            date(2026, 11, 9),
        )
        # 1큰술 = 15 mL → 1mL≈1g 근사(계량 단위, unit_weights.json)로 계산에 들어간다
        assert (secret.gram_status, secret.grams) == ("approx_ml", Decimal("15.0"))
        assert "1큰술=15mL" in secret.gram_basis
        assert secret.contribution["energy_kcal"] == 132.0
        assert summary.recipe_id == recipe.id and summary.complete
        assert (
            summary.computed["energy_kcal"] == 60.0 + 44.0 + 132.0
            and summary.items_used == 3
        )
        onion = mapping(db, "2")[1][0]
        # 1개 → 개수 단위라 환산하지 않음
        assert onion.match_status == "exact" and onion.grams is None

        # 식품 판본이 바뀌면 그 식품을 쓰는 레시피만 다시 계산하고 새 판본을 가리킨다
        changed = [food("R1", "시금치, 생것", "35", "50"), *FOODS[1:]]
        load(db, tmp_path, foods=changed, fetched_at=DAY2)
        result = map_recipe_foods.apply_mapping(db, MAP)
        assert result["remapped_recipes"] == 1
        recipe, items, summary = mapping(db, "1")
        db.refresh(r1)
        assert items[0].food_revision_id == r1.active_revision_id
        assert items[0].contribution["energy_kcal"] == 70.0
        assert summary.computed["energy_kcal"] == 70.0 + 44.0 + 132.0
        assert map_recipe_foods.verify_mapping(db, MAP)["verified"]

        # 매핑표가 바뀌면(확인 취소 → 근거만 있는 매핑) 그 재료 상태가 바뀌고 확인자가 빠진다
        unreviewed = ({**MAP[0], "reviewed_by": None, "reviewed_at": None},)
        result = map_recipe_foods.apply_mapping(db, unreviewed)
        # 매핑표가 바뀌면 모든 레시피를 그 매핑표로 다시 계산한다(어느 매핑표로 계산했는지 남김)
        assert (
            result["match_status"]["curated"] == 1 and result["remapped_recipes"] == 2
        )
        secret = mapping(db, "1")[1][3]
        assert (secret.match_status, secret.reviewed_by) == ("curated", None)
        assert map_recipe_foods.verify_mapping(db, unreviewed)["verified"]
        # 되돌리면(A → B → A) 입력 지문이 예전 실행과 같아도 저장된 행을 다시 맞춘다
        result = map_recipe_foods.apply_mapping(db, MAP)
        assert not result["already_mapped"] and result["remapped_recipes"] == 2
        assert mapping(db, "1")[1][3].match_status == "reviewed"
        assert map_recipe_foods.verify_mapping(db, MAP)["verified"]

        # 레시피가 새 판본이 되면 새 판본 행을 만들고, 옛 판본 행은 남긴다(식단표가 가리킬 수 있음)
        old_revision = recipe.active_revision_id
        edited = [dict(RECIPES[0], RCP_PARTS_DTLS="시금치 300g, 물 100ml"), RECIPES[1]]
        load(db, tmp_path, recipes=edited, foods=changed, fetched_at=DAY3)
        assert map_recipe_foods.apply_mapping(db, MAP)["remapped_recipes"] == 1
        recipe, items, summary = mapping(db, "1")
        assert recipe.active_revision_id != old_revision and len(items) == 2
        assert summary.complete and summary.computed["energy_kcal"] == 105.0
        kept = db.scalar(
            select(func.count())
            .select_from(RecipeIngredientFood)
            .where(RecipeIngredientFood.recipe_revision_id == old_revision)
        )
        assert kept == 4 and count(db, RecipeComputedNutrition) == 3
        assert map_recipe_foods.verify_mapping(db, MAP)["verified"]


def test_postgres_unit_weight_is_stored_with_its_source(tmp_path, pg_connection):
    # 출처 있는 개당 중량(달걀 1개 60 g)은 새 상태 unit_weight 로 DB CHECK(20261113_01)를 통과한다
    recipes = [
        {
            "RCP_SEQ": "3",
            "RCP_NM": "달걀찜",
            "RCP_PARTS_DTLS": "달걀 2개, 양파 1개, 소금 약간",
            "MANUAL01": "1. 찐다.",
        }
    ]
    foods = [food("R4", "달걀, 생것", "140", "137"), food("R3", "양파, 생것", "40")]
    with Session(pg_connection) as db, db.begin():
        load(db, tmp_path, recipes=recipes, foods=foods)
        result = map_recipe_foods.apply_mapping(db, ())
        _, items, summary = mapping(db, "3")
        egg, onion, salt = items
        # '약간'은 g이 없어 계산에 안 들어가고, coverage 에 따로 남는다(양파 '1개'가 있어 그것만 빠진 건 아님)
        assert salt.gram_status == "qualitative" and salt.contribution is None
        assert summary.coverage["qualitative_items"] == [
            {"name": "소금", "amount_text": "약간", "food_code": None}
        ]
        assert summary.coverage["complete_except_qualitative"] is False
        assert result["complete_except_qualitative_recipes"] == 0
        assert (egg.gram_status, egg.grams) == ("unit_weight", Decimal("120.0"))
        assert "1개=60g" in egg.gram_basis and "식품의약품안전처" in egg.gram_basis
        assert egg.contribution["energy_kcal"] == 168.0
        assert (onion.gram_status, onion.grams) == ("count_unit", None)  # 표에 없음
        assert not summary.complete and summary.computed["energy_kcal"] == 168.0
        assert map_recipe_foods.verify_mapping(db, ())["verified"]


def test_postgres_mapping_constraints(tmp_path, pg_connection):
    with Session(pg_connection) as db, db.begin():
        load(db, tmp_path)
        map_recipe_foods.apply_mapping(db, MAP)
        recipe, items, _ = mapping(db, "1")
        other = db.scalar(
            select(RecipeIngredient)
            .join(
                Recipe, Recipe.active_revision_id == RecipeIngredient.recipe_revision_id
            )
            .where(Recipe.source_id == "2")
        )
        # 이 재료의 매핑을 지워 두고, 제약만으로 막히는지 본다(유일 조건과 섞이지 않게)
        db.execute(
            delete(RecipeIngredientFood).where(
                RecipeIngredientFood.recipe_ingredient_id == other.id
            )
        )
        base = {
            "order_no": 9,
            "gram_status": "missing",
            "gram_basis": "분량 표기 없음",
        }
        # 쓸 수 있는 매핑인데 식품이 없음
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                RecipeIngredientFood(
                    recipe_revision_id=other.recipe_revision_id,
                    recipe_ingredient_id=other.id,
                    match_status="exact",
                    **base,
                )
            )
            db.flush()
        # 식품 판본 없이 식품 ID만 남길 수 없음
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                RecipeIngredientFood(
                    recipe_revision_id=other.recipe_revision_id,
                    recipe_ingredient_id=other.id,
                    match_status="unmapped",
                    food_id=db.scalar(select(Food.id).limit(1)),
                    **base,
                )
            )
            db.flush()
        # 다른 판본의 재료 행을 가리킴
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                RecipeIngredientFood(
                    recipe_revision_id=recipe.active_revision_id,
                    recipe_ingredient_id=other.id,
                    match_status="unmapped",
                    **base,
                )
            )
            db.flush()
        # 확인자는 reviewed 매핑에만
        with pytest.raises(IntegrityError), db.begin_nested():
            items[0].reviewed_by = "누군가"
            db.flush()


def test_postgres_mapping_only_uses_cookrcp01_recipes(tmp_path, pg_connection):
    with Session(pg_connection) as db, db.begin():
        load(db, tmp_path)
        recipe = db.scalar(select(Recipe).where(Recipe.source_id == "2"))
        recipe.provider = "another-provider"
        db.flush()

        result = map_recipe_foods.apply_mapping(db, MAP)

        assert result["recipes"] == 1
        assert db.scalar(select(RecipeComputedNutrition.recipe_revision_id)) != (
            recipe.active_revision_id
        )
