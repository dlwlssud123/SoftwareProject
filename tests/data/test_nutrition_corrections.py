import json
from collections import Counter

import pytest
from agetech_data import paths
from agetech_data.nutrition.corrections import (
    apply_corrections,
    check_field,
    load_corrections,
)
from agetech_data.nutrition.foods import clean_foods

BAD_BASIS = "D117-707000000-0001"   # 픽스처: 기준량 '4㎍ RAE' → invalid_basis
G_ROW = "D101-006000000-0001"       # 픽스처: 기장밥 100g


@pytest.fixture()
def foods(nutrition_sample):
    return {f.food_code: f for f in clean_foods(nutrition_sample["items"], corrections=())}


def _c(rec, field, frm, to, **kw):
    return {"food_code": rec.food_code, "food_name": rec.name, "field": field, "from": frm, "to": to,
            "reason": "시험", "evidence": "시험", "raw_sha256": rec.raw_sha256, "by": "시험", "at": "2026-11-09", **kw}


def test_basis_correction_applies_and_recomputes_flags(foods):
    r = foods[BAD_BASIS]
    assert r.basis_unit is None and "invalid_basis" in r.quality_flags
    res = apply_corrections([r], [_c(r, "basis_text", "4㎍ RAE", "100g")])
    assert res == [{"food_code": BAD_BASIS, "field": "basis_text", "status": "applied"}]
    assert (r.basis_text, r.basis_amount, r.basis_unit) == ("100g", 100.0, "g")
    assert "invalid_basis" not in r.quality_flags and r.quality_flags[-1] == "corrected"
    assert r.corrections == [{"field": "basis_text", "from": "4㎍ RAE", "to": "100g", "reason": "시험",
                              "evidence": "시험", "by": "시험", "at": "2026-11-09"}]


def test_nutrient_correction(foods):
    r = foods[G_ROW]
    before = r.nutrients["sodium_mg"]
    apply_corrections([r], [_c(r, "nutrients.sodium_mg", before, 123.0)])
    assert r.nutrients["sodium_mg"] == 123.0 and r.corrections[0]["from"] == before


@pytest.mark.parametrize("change", ["sha", "from"])
def test_stale_when_source_changed(foods, change):
    r = foods[G_ROW]
    c = _c(r, "basis_text", "100g", "100mL")
    if change == "sha":
        c["raw_sha256"] = "0" * 64        # 식약처가 행을 고쳐 원본 해시가 바뀐 경우
    else:
        c["from"] = "100mL"               # 원래 값이 이미 달라진 경우
    res = apply_corrections([r], [c])
    assert res[0]["status"] == "stale"
    assert r.basis_text == "100g" and r.corrections == [] and "correction_stale" in r.quality_flags


def test_missing_code(foods):
    r = foods[G_ROW]
    res = apply_corrections([r], [{**_c(r, "basis_text", "100g", "100mL"), "food_code": "NOPE"}])
    assert res[0]["status"] == "missing" and r.basis_text == "100g"


@pytest.mark.parametrize("field", ["name", "nutrients.없는성분", "basis_amount"])
def test_unknown_field_rejected(field):
    with pytest.raises(ValueError):
        check_field(field)


def test_empty_corrections_disable(nutrition_sample):
    recs = clean_foods(nutrition_sample["items"], corrections=())
    assert not any(r.corrections for r in recs)


def test_corrections_file_shape():
    entries = load_corrections()
    assert entries
    keys = Counter((c["food_code"], c["field"]) for c in entries)
    assert max(keys.values()) == 1                     # 같은 식품·필드에 보정이 둘이면 안 됨
    assert all(c["from"] != c["to"] for c in entries)


def test_source_identity_ignores_only_response_sequence(nutrition_sample):
    raw = dict(nutrition_sample["items"][0], NUM="100")
    original = clean_foods([raw], corrections=())[0]
    correction = _c(original, "basis_text", original.basis_text, "200g",
                    source_sha256=original.source_sha256)
    reordered = clean_foods([{**raw, "NUM": "101"}], corrections=())[0]
    assert reordered.raw_sha256 != original.raw_sha256
    assert reordered.source_sha256 == original.source_sha256
    assert apply_corrections([reordered], [correction])[0]["status"] == "applied"
    assert reordered.basis_text == "200g" and reordered.corrections[0]["source_sha256"] == original.source_sha256


@pytest.mark.parametrize("change", [{"AMT_NUM1": "999"}, {"FOOD_NM_KR": "changed name"}, {"NEW_FIELD": "value"}])
def test_source_identity_still_rejects_content_or_schema_change(nutrition_sample, change):
    raw = nutrition_sample["items"][0]
    original = clean_foods([raw], corrections=())[0]
    correction = _c(original, "basis_text", original.basis_text, "200g",
                    source_sha256=original.source_sha256)
    changed = clean_foods([{**raw, "NUM": "101", **change}], corrections=())[0]
    assert apply_corrections([changed], [correction])[0]["status"] == "stale"
    assert changed.corrections == [] and changed.basis_text == original.basis_text


@pytest.mark.skipif(not paths.NUTRITION_RAW.is_file(), reason="수집 원본 없음 (client 실행 필요)")
def test_real_corrections_all_apply():
    raw = json.loads(paths.NUTRITION_RAW.read_text(encoding="utf-8"))["items"]
    recs = clean_foods(raw, corrections=())
    res = apply_corrections(recs, load_corrections())
    assert {r["status"] for r in res} == {"applied"}
    by = {r.food_code: r for r in recs}
    for c in load_corrections():
        r = by[c["food_code"]]
        assert r.name == c["food_name"] and "corrected" in r.quality_flags
        if c["field"] == "basis_text":
            # 분말 기준량 보정: 고친 뒤 성분 합이 기준량(100g)과 맞아야 한다
            n = r.nutrients
            total = sum(n[k] or 0 for k in ("water_g", "protein_g", "fat_g", "ash_g", "carbohydrate_g"))
            assert r.basis_unit == "g" and abs(total - r.basis_amount) <= 1.0
