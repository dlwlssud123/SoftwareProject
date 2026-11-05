"""실제 수집본(src/frontend/assets/data/recipes.json) 회귀 검증. 파일이 없으면 건너뛴다."""

import hashlib
import json
import re

import pytest

from agetech_data import paths
from agetech_data.recipes.validate import build_result

pytestmark = pytest.mark.skipif(not paths.RECIPES_RAW.is_file(), reason="recipes.json 없음")


@pytest.fixture(scope="module")
def raw_rows():
    return json.loads(paths.RECIPES_RAW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result():
    before = hashlib.sha256(paths.RECIPES_RAW.read_bytes()).hexdigest()
    res = build_result(paths.RECIPES_RAW, paths.RECIPES_SOURCE_META)
    assert hashlib.sha256(paths.RECIPES_RAW.read_bytes()).hexdigest() == before  # 읽기 전용
    return res


@pytest.fixture(scope="module")
def by_id(result):
    return {r["source_id"]: r for r in result["recipes"]}


def test_all_recipes_checked(result, raw_rows):
    assert result["summary"]["recipes"] == len(raw_rows)


def test_known_step_gaps(by_id):
    assert by_id["33"]["missing_step_nos"] == [1, 4]       # 사과 새우 북엇국
    assert by_id["36"]["missing_step_nos"] == [1, 2]       # 황태해장국
    assert by_id["33"]["status"] == by_id["36"]["status"] == "hold"
    assert [s["source_field"] for s in by_id["33"]["steps"]] == ["MANUAL02", "MANUAL03", "MANUAL05"]


def test_known_ingredient_anomalies(by_id):
    def codes(rid):
        return {i["code"] for i in by_id[rid]["issues"]}
    assert "ingredient_unclosed_paren" in codes("642")
    assert "ingredient_unclosed_paren" in codes("276")
    assert "ingredient_amount_missing" in codes("38")


def test_step_text_raw_matches_source(by_id, raw_rows):
    for row in raw_rows:
        for s in by_id[row["RCP_SEQ"]]["steps"]:
            assert s["text_raw"] == row[s["source_field"]]
            assert s["text_clean"] and s["text_clean"] in re.sub(r"\s+", " ", row[s["source_field"]])


def test_ingredient_text_fully_preserved(by_id, raw_rows):
    """원문 재료 텍스트에서 섹션 제목·구분자를 빼면 raw_item 을 이어 붙인 것과 같아야 한다."""
    for row in raw_rows:
        rec = by_id[row["RCP_SEQ"]]
        joined = "".join(i["raw_item"] for i in rec["ingredients"])
        lines = row["RCP_PARTS_DTLS"].replace("\r\n", "\n").split("\n")
        for sec in rec["ingredient_sections"]:  # 섹션 제목은 그 제목이 있던 줄에서만 뺀다
            lines[sec["line_no"] - 1] = lines[sec["line_no"] - 1].replace(sec["title"], "", 1)
        src = "".join(lines)
        strip = re.compile(r"[\s,.:：●•·\[\]]|1인분")
        assert strip.sub("", joined) == strip.sub("", src), row["RCP_SEQ"]


def test_name_amount_and_paren_preserved(by_id, raw_rows):
    for row in raw_rows:
        src = row["RCP_PARTS_DTLS"]
        for i in by_id[row["RCP_SEQ"]]["ingredients"]:
            assert i["raw_item"] in src
            assert i["name_raw"] and i["name_raw"] in i["raw_item"]
            assert i["raw_item"].replace(" ", "") == (i["name_raw"] + i["amount_text"]).replace(" ", "")
            for p in i["paren_texts"]:
                assert p in i["raw_item"]
        # 원문의 모든 괄호 내용이 어느 항목엔가 남아 있다
        kept = {p for i in by_id[row["RCP_SEQ"]]["ingredients"] for p in i["paren_texts"]}
        for p in re.findall(r"\(([^()]*)\)", src):
            assert p in kept, (row["RCP_SEQ"], p)


def test_source_nutrition_kept_and_suspects_flagged(by_id, raw_rows):
    for row in raw_rows:  # 원문 영양값을 바꾸지 않는다
        assert by_id[row["RCP_SEQ"]]["nutrition"]["energy_kcal"] == float(row["INFO_ENG"])
    # 271~281 찌개류: 탄수화물·단백질·지방이 원문 열량의 1/5 안팎 → 원문 영양값 이상 의심
    suspects = {rid for rid, r in by_id.items() if r["nutrition"]["suspect"]}
    assert suspects == {"271", "272", "273", "274", "276", "277", "278", "280", "281"}


def test_known_allergens(by_id):
    def names(rid):
        return [d["allergen"] for d in by_id[rid]["allergens"]["detected"]]
    assert "새우" in names("33")                                  # 사과 새우 북엇국
    assert "땅콩" in names("642") and "대두" not in names("642")  # 앱 규칙은 땅콩의 '콩'을 대두로 봄
    assert all(r["allergens"]["not_determinable"] == ["아황산류"] for r in by_id.values())
