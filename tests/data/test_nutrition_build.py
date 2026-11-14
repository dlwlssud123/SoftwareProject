import hashlib
import json

import pytest

from agetech_data import paths
from agetech_data.nutrition import build
from agetech_data.nutrition.build import build_recipe_nutrition
from agetech_data.nutrition.estimates import Estimates
from agetech_data.nutrition.match import INGREDIENT_MAP_FILE, load_ingredient_map, norm


def _recipe(seq, parts):
    row = {"RCP_SEQ": seq, "RCP_NM": f"시험{seq}", "RCP_PARTS_DTLS": parts,
           "INFO_ENG": "100", "INFO_PRO": "1", "INFO_FAT": "1", "INFO_CAR": "1", "INFO_NA": "1"}
    row.update({f"MANUAL{i:02d}": "" for i in range(1, 21)})
    row.update({f"MANUAL_IMG{i:02d}": "" for i in range(1, 21)})
    row["MANUAL01"] = "1. 만든다"
    return row


NO_EST = Estimates({}, {}, {}, None, None)   # 출처 있는 환산만 (추정 없음)


def _by_name(recipe):
    return {i["name"]: i for i in recipe["ingredients"]}


def test_contribution_only_for_usable_and_converted(sample_foods):
    onion = next(f for f in sample_foods if f.name == "양파, 생것")
    rows = [_recipe("1", "양파 50g, 물 300ml, 감자 100g, 레몬(1/4개), 참깨 약간")]
    [r] = build_recipe_nutrition(rows, sample_foods, entries=(), estimates=NO_EST)
    by = _by_name(r)
    assert by["양파"]["contribution"]["energy_kcal"] == pytest.approx(onion.nutrients["energy_kcal"] / 2)
    assert by["물"]["match"]["status"] == "water" and by["물"]["contribution"] is None
    assert by["감자"]["match"]["status"] == "candidate" and by["감자"]["contribution"] is None
    assert by["레몬"]["grams"]["status"] == "count_unit" and by["레몬"]["contribution"] is None  # 환산표에 없음
    assert r["computed"]["energy_kcal"] == pytest.approx(onion.nutrients["energy_kcal"] / 2, abs=0.01)
    assert r["coverage"]["complete"] is False
    assert r["coverage"]["grams_used_pct"] == pytest.approx(100 * 50 / 150, abs=0.1)
    assert by["양파"]["raw_item"] == "양파 50g" and by["양파"]["amount_text"] == "50g"  # 원문 보존


def test_complete_recipe_and_ml_basis_flag(sample_foods):
    entries = ({"ingredient": "저염간장", "food_code": "P112-005000400-F002-001", "rationale": "저염 간장"},)
    [r] = build_recipe_nutrition([_recipe("2", "양파 50g, 저염간장 10g, 물 100ml")], sample_foods, entries)
    assert r["coverage"]["complete"] is True
    assert _by_name(r)["저염간장"]["basis_ml_approx"] is True  # 100mL 기준 식품을 g 분량으로 계산


def test_build_main_end_to_end(tmp_path, nutrition_sample):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(nutrition_sample, ensure_ascii=False), encoding="utf-8")
    recipes = tmp_path / "recipes.json"
    recipes.write_text(json.dumps([_recipe("1", "양파 50g, 다진 마늘 5g, 물 100ml")], ensure_ascii=False),
                       encoding="utf-8")
    args = ["--nutrition-raw", str(raw), "--recipes", str(recipes), "--foods-out", str(tmp_path / "f.json"),
            "--recipes-out", str(tmp_path / "r.json"), "--report", str(tmp_path / "rep.md")]
    assert build.main(args) == 0
    first = (tmp_path / "rep.md").read_text(encoding="utf-8")
    assert build.main(args) == 0
    assert (tmp_path / "rep.md").read_text(encoding="utf-8") == first  # 같은 입력 → 같은 보고서
    out = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert out["summary"]["complete_recipes"] == 1
    assert len(json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))["foods"]) == len(nutrition_sample["items"])


def test_build_main_without_raw(tmp_path, capsys):
    assert build.main(["--nutrition-raw", str(tmp_path / "none.json"), "--no-report"]) == 1
    assert "client" in capsys.readouterr().err


def test_build_applies_verified_recipe_corrections(tmp_path, nutrition_sample):
    raw = tmp_path / "nutrition.json"
    raw.write_text(json.dumps(nutrition_sample), encoding="utf-8")
    output = tmp_path / "recipes.json"
    args = ["--nutrition-raw", str(raw), "--foods-out", str(tmp_path / "foods.json"),
            "--recipes-out", str(output), "--no-report"]
    assert build.main(args) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    recipes = {row["source_id"]: row for row in result["recipes"]}
    assert recipes["33"]["quality_status"] == recipes["36"]["quality_status"] == "ok"
    assert result["input"]["recipes"]["correction_count"] == 6
    assert result["input"]["recipes"]["corrections_sha256"] == hashlib.sha256(paths.RECIPE_CORRECTIONS.read_bytes()).hexdigest()


def test_ingredient_map_file_structure():
    data = json.loads(INGREDIENT_MAP_FILE.read_text(encoding="utf-8"))
    keys, codes = set(), {}
    for e in data["entries"]:
        assert e["ingredient"] and e["rationale"]
        assert e["food_code"] is None or (e["food_code"] and e["food_name"])
        assert e.get("reviewed_by") is None or e.get("reviewed_at")
        key = (e["ingredient"], e.get("when_paren"))
        assert key not in keys, key
        keys.add(key)
        # 매칭은 공백을 지운 이름으로 찾고 첫 항목을 쓴다 → 공백만 다른 두 항목('닭가슴살'·'닭 가슴살')은 같은 식품이어야 한다
        same = codes.setdefault((norm(e["ingredient"]), e.get("when_paren")), e["food_code"])
        assert same == e["food_code"], (e["ingredient"], same, e["food_code"])


@pytest.mark.skipif(not paths.NUTRITION_RAW.is_file(), reason="수집 원본 없음 (client 실행 필요)")
def test_ingredient_map_codes_exist_in_collected_db():
    from agetech_data.nutrition.foods import clean_foods

    foods = {f.food_code: f for f in clean_foods(json.loads(paths.NUTRITION_RAW.read_text(encoding="utf-8"))["items"])}
    for e in load_ingredient_map():
        if e["food_code"]:
            assert e["food_code"] in foods, e
            assert foods[e["food_code"]].name == e["food_name"], e


@pytest.mark.skipif(not paths.NUTRITION_RAW.is_file() or not paths.RECIPES_RAW.is_file(), reason="원본 없음")
def test_real_recipes_regression():
    from agetech_data.nutrition.foods import clean_foods
    from agetech_data.recipes.validate import load_rows

    before = hashlib.sha256(paths.RECIPES_RAW.read_bytes()).hexdigest()
    foods = clean_foods(json.loads(paths.NUTRITION_RAW.read_text(encoding="utf-8"))["items"])
    recipes = {r["source_id"]: r for r in build_recipe_nutrition(load_rows(paths.RECIPES_RAW), foods,
                                                                  load_ingredient_map())}
    assert hashlib.sha256(paths.RECIPES_RAW.read_bytes()).hexdigest() == before
    items = [i for r in recipes.values() for i in r["ingredients"]]
    assert len(items) == 534
    by = {(r, i["name"]): i for r, rec in recipes.items() for i in rec["ingredients"]}
    assert by[("28", "연두부")]["match"]["food_name"] == "두부, 연두부"
    assert by[("644", "검은콩")]["match"]["food_name"] == "대두, 검은색, 서리태, 말린것"  # 두유 음료 아님
    # 부위 미기재(괄호 없음)는 수동 매핑표의 기본 부위(앞다리)
    assert by[("277", "다진 돼지고기")]["match"]["food_name"] == "돼지고기, 앞다리, 생것"
    assert not [i for i in items if i["match"]["status"] == "candidate"]   # 모든 재료에 매핑 결정이 있음
    # 같은 레시피의 구획으로 이미 계산되는 소스는 0으로 침(excluded) — 완전 판정을 막지 않음
    sauce = by[("89", "시금치우유 소스")]["match"]
    assert (sauce["status"], sauce["rule"]) == ("excluded", "manual:counted_elsewhere")
    assert recipes["89"]["coverage"]["excluded_items"][0]["name"] == "시금치우유 소스"
    # 성분 합이 맞지 않는 가공식품 수집 행 대신 원재료성 분석 행
    assert by[("277", "통조림 햄")]["match"]["food_name"] == "햄, 통조림, 돼지고기와 닭고기 함유"
    assert by[("272", "다진 돼지고기")]["match"]["food_name"] == "돼지고기, 등심, 생것"  # 괄호 '등심'
    for i in items:
        if i["contribution"] is not None:
            assert i["match"]["status"] in ("exact", "curated", "reviewed")
            assert i["grams"]["status"] in ("direct", "direct_paren", "approx_ml", "unit_weight", "estimated")
