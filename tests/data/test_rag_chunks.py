"""RAG 청크 규칙 (표준 라이브러리만)."""

import json

import pytest
from rag_samples import recipe_rec, welfare_rec

from agetech_data import paths
from agetech_data.rag.chunks import MAX_CHARS, build_chunks, recipe_chunks, region_label, welfare_chunks
from agetech_data.welfare.revision import content_sha256


def test_region_label():
    assert region_label("national", None, None) == "전국"
    assert region_label("province", "대구광역시", None) == "대구광역시 전체"
    assert region_label("district", "대구광역시", "남구") == "대구광역시 남구"


def test_welfare_short_record_is_one_chunk_with_header_and_original_text():
    [c] = welfare_chunks(welfare_rec(), "welfare_local:abc")
    assert c.chunk_id == "welfare_local:WLF00004828:all:1"
    assert c.content.startswith("[복지] 경로우대사업 (대구광역시 남구)\n")
    assert "지원 대상: 65세 이상 노인" in c.content
    assert "문의처: 남구청 복지지원과: 053-664-2538" in c.content
    assert (c.region_scope, c.ctpv, c.sgg, c.period_end) == ("district", "대구광역시", "남구", "9999-12-31")
    assert c.source_checked_at == "2026-11-05T00:00:00+00:00"       # 상세 확인 시각 우선
    # 원본 표와 대조할 해시 = 정제 레코드 내용 해시(DB welfare_revisions.content_sha256 과 같은 함수)
    assert c.source_record_sha256 == content_sha256(welfare_rec()) != welfare_rec()["raw_sha256"]
    changed_views = {**welfare_rec(), "raw_sha256": "f" * 64, "source_fetched_at": "2026-11-09T00:00:00+00:00"}
    assert welfare_chunks(changed_views, "welfare_local:abc")[0].source_record_sha256 == c.source_record_sha256
    assert welfare_chunks(welfare_rec(), "welfare_local:abc")[0].content_sha256 == c.content_sha256


def test_welfare_central_has_no_region_and_uses_main_contact_and_guides():
    rec = welfare_rec("WLF00001164", "central", "national", None, None, contacts=[], main_contact="129",
                      apply_guides=[{"name": "신청기관연락처목록", "value": "주민센터", "raw": {}}],
                      department=None, ministry="보건복지부 기초연금과")
    [c] = welfare_chunks(rec, "welfare_central:abc")
    assert c.source_type == "welfare_central" and c.region_scope == "national"
    assert c.ctpv is None and c.sgg is None
    assert "(전국)" in c.content and "신청기관: 주민센터" in c.content and "문의처: 129" in c.content
    assert "담당: 보건복지부 기초연금과" in c.content


def test_welfare_province_record_drops_sgg():
    [c] = welfare_chunks(welfare_rec(scope="province", sgg=None), "v")
    assert (c.region_scope, c.ctpv, c.sgg) == ("province", "대구광역시", None)
    assert "(대구광역시 전체)" in c.content


def test_welfare_long_record_splits_on_sections_and_keeps_header():
    long = "지원 내용 문장입니다. " * 120
    cs = welfare_chunks(welfare_rec(benefits=long), "v", max_chars=600)
    assert len(cs) > 2
    assert all(len(c.content) <= 600 for c in cs)
    assert all(c.content.startswith("[복지] 경로우대사업 (대구광역시 남구)\n") for c in cs)
    assert [c.chunk_no for c in cs] == list(range(1, len(cs) + 1))
    assert {c.section for c in cs} >= {"overview", "benefits", "apply"}
    assert len({c.chunk_id for c in cs}) == len(cs)


def test_welfare_unverified_fields_become_flags():
    [c] = welfare_chunks(welfare_rec(unverified_fields=["apply_detail"], apply_detail=None,
                                     quality_flags=["homepage_not_url"]), "v")
    assert c.quality_flags == ["homepage_not_url", "unverified:apply_detail"]


def test_recipe_chunk_hold_flagged_allergens_and_suspect_nutrition():
    assert recipe_chunks(recipe_rec(status="hold"), "v") == []
    [c] = recipe_chunks(recipe_rec(status="flagged"), "recipes:abc")
    assert c.chunk_id == "recipe:28:all:1" and c.region_scope == "none"
    assert c.quality_status == "flagged"
    assert c.quality_flags == ["allergen_analysis_complete", "ingredient_amount_missing"]
    assert c.allergens == ["대두", "알류"]
    assert c.source_record_sha256 == recipe_rec()["source"]["raw_sha256"]
    assert "재료: 연두부 75g(3/4모), 달걀 30g(1/2개) / 고명 / 시금치 10g" in c.content
    assert "1. 새우를 데친다." in c.content and "열량 220kcal" in c.content
    [s] = recipe_chunks(recipe_rec(suspect=True), "v")
    assert "열량" not in s.content and "nutrition_suspect" in s.quality_flags


def test_build_chunks_versions_order_and_duplicates():
    welfare = {"input": {"local": {"sha256": "3f761c00cacb90e7"}, "central": {"sha256": "630c2a9468dd15c5"}},
               "records": [welfare_rec("WLF2"), welfare_rec("WLF1", "central", "national", None, None)]}
    recipes = {"input": {"sha256": "6d0635b4aa4c0fd0"}, "records": [recipe_rec("100"), recipe_rec("28")]}
    cs = build_chunks(welfare, recipes)
    assert [c.source_id for c in cs] == ["WLF1", "WLF2", "28", "100"]
    assert cs[0].data_version == "welfare_central:630c2a9468dd" and cs[2].data_version == "recipes:6d0635b4aa4c"
    with pytest.raises(ValueError):
        build_chunks({"input": {}, "records": [welfare_rec(), welfare_rec()]}, None)


@pytest.mark.skipif(not (paths.WELFARE_PROCESSED.exists() and paths.RECIPES_API_ALL.exists()),
                    reason="정제 결과 없음 (welfare.build·recipes.contract 실행 필요)")
def test_real_data_chunks():
    welfare = json.loads(paths.WELFARE_PROCESSED.read_text(encoding="utf-8"))
    recipes = json.loads(paths.RECIPES_API_ALL.read_text(encoding="utf-8"))
    cs = build_chunks(welfare, recipes)
    assert any(r["quality"]["status"] == "hold" for r in recipes["records"])
    assert {c.source_id for c in cs if c.source_type == "recipe"} == \
        {str(r["recipe_id"]) for r in recipes["records"] if r["quality"]["status"] != "hold"}
    assert {c.source_id for c in cs if c.source_type != "recipe"} == {r["serv_id"] for r in welfare["records"]}
    assert all(len(c.content) <= MAX_CHARS for c in cs)
    assert all(c.source_record_sha256 and len(c.source_record_sha256) == 64 for c in cs)
    assert all(c.ctpv and c.sgg for c in cs if c.region_scope == "district")
    nam = {c.source_id for c in cs if c.ctpv == "대구광역시" and c.sgg == "남구"}
    assert {"WLF00004828", "WLF00006010"} <= nam


def test_recipe_chunk_matches_the_corrected_row_hash_when_given():
    # recipes.contract --corrections 로 만든 레코드는 DB recipe_revisions.effective_sha256 과 같은 해시를 갖는다
    rec = recipe_rec()
    rec["source"]["effective_sha256"] = "e" * 64
    [c] = recipe_chunks(rec, "v")
    assert c.source_record_sha256 == "e" * 64


def _seasonal_rows():
    from pathlib import Path

    from agetech_data.seasonal.revision import seasonal_rows

    payload = json.loads((Path(__file__).parent / "fixtures" / "seasonal_sample.json").read_text(encoding="utf-8"))
    return {r["name"]: r for r in seasonal_rows(payload, [])}


def test_seasonal_chunk_has_header_sections_and_db_content_hash():
    from agetech_data.rag.chunks import seasonal_chunks

    row = _seasonal_rows()["시금치"]
    cs = seasonal_chunks(row, "seasonal:abc")
    assert cs and all(c.source_type == "seasonal" and c.source_id == row["source_id"] for c in cs)
    assert all(c.content.startswith("[제철 식재료] 12월 · 시금치\n") for c in cs)
    assert all(c.source_record_sha256 == row["content_sha256"] for c in cs)     # DB seasonal_foods.content_sha256
    assert all(c.region_scope == "none" and c.ctpv is None and len(c.content) <= MAX_CHARS for c in cs)
    text = "\n".join(c.content for c in cs)
    assert "먹는 법:" in text and "\n■" in text                                  # 원문 '■' 항목은 줄을 바꿔 둔다
    assert "농촌진흥청 관련 레시피: 시금치그린스무디" in text
    assert cs[0].source_checked_at == "2026-11-07" and cs[0].title == "12월 시금치"
    assert seasonal_chunks({**row, "detail_status": "failed"}, "v") == []        # 상세가 없으면 만들지 않음
    assert seasonal_chunks({**row, "is_published": False}, "v") == []
    assert all(c.allergens == [] and c.quality_flags == ["allergen_analysis_complete"] for c in cs)


@pytest.mark.parametrize("name,allergens,complete", [
    ("시금치", [], True), ("두부", ["대두"], True), ("콩나물", ["대두"], True), ("달걀", ["알류"], True),
    ("요거트", ["우유"], True), ("잣", ["잣"], True), ("닭가슴살/닭안심", ["닭고기"], True),
    ("풋콩/껍질콩", ["대두"], True),           # 모호한 '콩'은 후보(대두)까지 넣는다
    ("녹두", [], True),                        # '콩' 규칙의 제외어
    ("만두", [], False), ("견과류", [], False), ("돼지고기(수제 소시지)", [], False),   # 이름만으로 모름 → 판정 불가
])
def test_seasonal_allergens_from_name(name, allergens, complete):
    from agetech_data.rag.chunks import seasonal_allergens

    assert seasonal_allergens(name) == (allergens, complete)


def test_build_chunks_adds_seasonal_rows_after_recipes_in_month_order():
    rows = list(_seasonal_rows().values())
    cs = build_chunks(None, {"input": {"sha256": "6d0635b4aa4c0fd0"}, "records": [recipe_rec("28")]},
                      seasonal=(rows, "seasonal:a2a04dbc7bb2"))
    kinds = [c.source_type for c in cs]
    assert kinds[0] == "recipe" and set(kinds[1:]) == {"seasonal"}
    months = [int(c.source_id.split("-")[0][1:]) for c in cs[1:]]
    assert months == sorted(months) and {c.data_version for c in cs[1:]} == {"seasonal:a2a04dbc7bb2"}


@pytest.mark.skipif(not paths.SEASONAL_RAW.exists(), reason="이달의 식재료 수집본 없음 (refresh 필요)")
def test_real_seasonal_chunks():
    from agetech_data.rag.chunks import seasonal_chunks
    from agetech_data.seasonal.revision import seasonal_rows

    rows = seasonal_rows(json.loads(paths.SEASONAL_RAW.read_text(encoding="utf-8")), [])
    cs = [c for r in rows for c in seasonal_chunks(r, "v")]
    assert {c.source_id for c in cs} == {r["source_id"] for r in rows if r["detail_status"] == "ok"}
    assert all(len(c.content) <= MAX_CHARS for c in cs)
