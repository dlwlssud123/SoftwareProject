import json

import pytest

from agetech_data import paths
from agetech_data.recipes.contract import build, https_image, main, sample_payload, select_samples, to_api_record
from agetech_data.recipes.validate import check_recipe

IMG = "http://www.foodsafetykorea.go.kr/uploadimg/cook/10_00028_2.png"


def _row(seq="28", **kw):
    row = {"RCP_SEQ": seq, "RCP_NM": "새우두부조림", "RCP_PAT2": "반찬", "RCP_WAY2": "끓이기", "HASH_TAG": "",
           "RCP_PARTS_DTLS": "[1인분] 새우 50g, 두부 100g, 저염간장 5g", "RCP_NA_TIP": "간장은 마지막에 넣으세요.",
           "INFO_ENG": "100", "INFO_CAR": "10", "INFO_PRO": "5", "INFO_FAT": "4.4", "INFO_NA": "200", "INFO_WGT": "",
           "ATT_FILE_NO_MAIN": IMG, "ATT_FILE_NO_MK": IMG.replace("_2.png", "_1.png"),
           "MANUAL01": "1. 두부를 썬다.a", "MANUAL_IMG01": IMG.replace("10_", "20_"), "MANUAL02": "2. 끓인다."}
    row.update(kw)
    return row


META = {"provider": "식품안전나라", "service": "COOKRCP01", "fetchedAt": "2026-10-26T07:46:53+00:00"}


def test_https_image_only_for_verified_host():
    assert https_image(IMG) == IMG.replace("http://", "https://")
    assert https_image("http://example.com/a.png") == "http://example.com/a.png"
    assert https_image(" ") is None and https_image(None) is None


def test_api_record_shape():
    r = to_api_record(check_recipe(_row()), _row(), META)
    assert (r["recipe_id"], r["category"], r["cooking_method"], r["hashtag"]) == ("28", "반찬", "끓이기", None)
    assert r["images"]["small"].startswith("https://") and r["steps"][0]["image"].startswith("https://")
    assert r["steps"][0] == {"no": 1, "text": "두부를 썬다.", "image": IMG.replace("http://", "https://").replace("10_", "20_"),
                             "source_field": "MANUAL01"}
    assert [i["name"] for i in r["ingredients"]] == ["새우", "두부", "저염간장"]
    assert r["nutrition"]["ingredient_servings"] == 1.0 and r["nutrition"]["basis"] == "per_serving_unverified"
    assert [d["allergen"] for d in r["allergens"]["detected"]] == ["대두", "밀", "새우"]
    q = r["quality"]
    assert q["status"] == "ok" and q["issues"] == []          # info 는 코드만
    assert "serving_weight_missing" in q["info_codes"] and "HASH_TAG" in q["missing_fields"]
    assert r["source"] == {"provider": "식품안전나라", "service": "COOKRCP01", "source_id": "28",
                           "fetched_at": "2026-10-26T07:46:53+00:00", "raw_sha256": check_recipe(_row()).raw_sha256}


def test_quality_issues_keep_warnings_with_detail():
    row = _row(MANUAL01="", MANUAL_IMG01="", INFO_ENG="500")   # 1단계 누락(hold) + 열량 불일치(flagged)
    q = to_api_record(check_recipe(row), row, META)["quality"]
    assert q["status"] == "hold"
    codes = [i["code"] for i in q["issues"]]
    assert {"step_first_missing", "nutrition_energy_mismatch"} <= set(codes)
    assert all(i["severity"] in ("error", "warning") for i in q["issues"])


def test_select_samples_attaches_extra_cases_and_reports_missing():
    recs = [to_api_record(check_recipe(r), r, META) for r in (_row("29"), _row("33", MANUAL01=""))]
    samples, missing = select_samples(recs)
    by_id = {s["recipe"]["recipe_id"]: s["cases"] for s in samples}
    assert "재료 원문에 [N인분] 표기" in by_id["29"]             # 이미 고른 표본에 사례만 덧붙임
    assert by_id["33"] == ["조리 단계 누락 → hold"]
    assert "원문 영양값 이상 의심 → flagged" in missing


def test_main_writes_outputs_deterministically(tmp_path):
    inp = tmp_path / "recipes.json"
    inp.write_text(json.dumps([_row(), _row("33", MANUAL01="")], ensure_ascii=False), encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META), encoding="utf-8")
    before = inp.read_bytes()
    args = ["--input", str(inp), "--source-meta", str(meta), "--output-json", str(tmp_path / "api.json"),
            "--sample", str(tmp_path / "s" / "sample.json")]
    assert main(args) == 0 and inp.read_bytes() == before
    first = (tmp_path / "s" / "sample.json").read_text(encoding="utf-8")
    assert main(args) == 0 and (tmp_path / "s" / "sample.json").read_text(encoding="utf-8") == first
    assert len(json.loads((tmp_path / "api.json").read_text(encoding="utf-8"))["records"]) == 2
    assert main(["--input", str(tmp_path / "none.json")]) == 1


@pytest.mark.skipif(not paths.RECIPES_RAW.is_file(), reason="recipes.json 없음")
def test_real_sample_cases():
    payload = sample_payload(build(paths.RECIPES_RAW, paths.RECIPES_SOURCE_META))
    assert payload["cases_not_found"] == []
    ids = [s["recipe"]["recipe_id"] for s in payload["samples"]]
    assert ids == ["108", "29", "33", "271", "276", "636"]
