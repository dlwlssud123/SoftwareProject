import copy
import hashlib
import json

import pytest
from agetech_data import paths
from agetech_data.recipes.correct import apply_corrections, build_result, main
from agetech_data.recipes.validate import check_recipe, load_rows


@pytest.fixture
def manifest():
    return json.loads(paths.RECIPE_CORRECTIONS.read_text(encoding="utf-8"))


def test_official_step_recovery_preserves_raw_and_unrelated_fields(manifest):
    raw = load_rows(paths.RECIPES_RAW)
    before = copy.deepcopy(raw)
    corrected, audit = apply_corrections(raw, manifest)

    assert raw == before
    assert len(audit) == 6
    assert len(corrected) == len(raw) == 50
    for row in corrected:
        if row["RCP_SEQ"] in ("33", "36"):
            check = check_recipe(row)
            assert check.status == "ok"
            assert check.steps.missing_nos == []
            assert [step.source_no for step in check.steps.steps] == [1, 2, 3, 4, 5]
        original = next(item for item in before if item["RCP_SEQ"] == row["RCP_SEQ"])
        changed_fields = {
            item["field"] for item in audit if item["source_id"] == row["RCP_SEQ"]
        }
        assert all(
            value == original.get(key)
            for key, value in row.items()
            if key not in changed_fields
        )


def test_corrections_are_idempotent(manifest):
    first, _ = apply_corrections(load_rows(paths.RECIPES_RAW), manifest)
    second, audit = apply_corrections(first, manifest)
    assert second == first
    assert all(item["state"] == "already_present" for item in audit)


def test_upstream_change_is_not_overwritten(manifest):
    rows = load_rows(paths.RECIPES_RAW)
    next(row for row in rows if row["RCP_SEQ"] == "33")["MANUAL01"] = (
        "1. New upstream content"
    )
    before = copy.deepcopy(rows)
    with pytest.raises(ValueError, match="changed upstream"):
        apply_corrections(rows, manifest)
    assert rows == before


@pytest.mark.parametrize("field", ["INFO_ENG", "INFO_WGT", "MANUAL21"])
def test_corrections_cannot_invent_nutrition_values(manifest, field):
    manifest["corrections"][0]["field"] = field
    with pytest.raises(ValueError, match="field"):
        apply_corrections(load_rows(paths.RECIPES_RAW), manifest)


def test_conflicting_duplicate_correction_is_rejected(manifest):
    manifest["corrections"].append(dict(manifest["corrections"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        apply_corrections(load_rows(paths.RECIPES_RAW), manifest)


def test_unofficial_source_is_rejected(manifest):
    manifest["corrections"][0]["source_url"] = "https://example.com/recipe"
    with pytest.raises(ValueError, match="official"):
        apply_corrections(load_rows(paths.RECIPES_RAW), manifest)


def test_format_correction_cannot_change_quantities(manifest):
    entry = next(
        item for item in manifest["corrections"] if item["kind"] == "format_only"
    )
    entry["value"] = entry["value"].replace("0.5g", "5g")
    with pytest.raises(ValueError, match="parenthesis"):
        apply_corrections(load_rows(paths.RECIPES_RAW), manifest)


def test_partial_recipe_fetch_applies_only_matching_entries(manifest):
    rows = [row for row in load_rows(paths.RECIPES_RAW) if row["RCP_SEQ"] == "33"]
    corrected, audit = apply_corrections(rows, manifest)
    assert len(corrected) == 1
    assert len(audit) == 2


def test_cli_is_reproducible_and_keeps_source_bytes(tmp_path):
    before = paths.RECIPES_RAW.read_bytes()
    output, audit_path, report = (
        tmp_path / "rows.json",
        tmp_path / "audit.json",
        tmp_path / "report.md",
    )
    args = [
        "--output",
        str(output),
        "--audit",
        str(audit_path),
        "--report",
        str(report),
    ]
    assert main(args) == 0
    first = (output.read_bytes(), audit_path.read_bytes(), report.read_bytes())
    assert main(args) == 0
    assert first == (output.read_bytes(), audit_path.read_bytes(), report.read_bytes())
    assert paths.RECIPES_RAW.read_bytes() == before
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["input_sha256"] == hashlib.sha256(before).hexdigest()
    assert audit["before"]["steps"]["missing_total"] == 4
    assert audit["after"]["steps"]["missing_total"] == 0
    # Nine source-nutrition warnings remain after correcting steps and parentheses.
    assert audit["after"]["status"] == {"ok": 40, "flagged": 10, "hold": 0}
    assert audit["after"]["nutrition"]["energy_mismatch"] == 9
    assert audit["after"]["nutrition_blank"]["INFO_WGT"] == 47


def test_corrected_export_contains_traceable_hashes():
    rows, audit = build_result(paths.RECIPES_RAW, paths.RECIPE_CORRECTIONS)
    assert len(rows) == len(audit["recipes"]) == 50
    changed = {
        item["source_id"]
        for item in audit["recipes"]
        if item["source_raw_sha256"] != item["effective_sha256"]
    }
    assert changed == {"33", "36", "642", "276"}


def _bracket_entry(manifest):
    return next(item for item in manifest["corrections"] if item["source_id"] == "981")


def _row_for(entry):
    """981 is not in the app's 50 recipes, so build its upstream row from the entry."""
    return {
        "RCP_SEQ": entry["source_id"],
        "RCP_NM": entry["recipe_name"],
        "RCP_PARTS_DTLS": entry["expected_value"],
    }


def test_format_correction_closes_one_section_bracket(manifest):
    entry = _bracket_entry(manifest)
    corrected, audit = apply_corrections([_row_for(entry)], manifest)

    assert corrected[0]["RCP_PARTS_DTLS"] == entry["value"]
    assert [(item["source_id"], item["state"]) for item in audit] == [
        ("981", "applied")
    ]
    # The entry names its own verifier; the others keep the manifest-level one.
    assert (audit[0]["verified_at"], audit[0]["verified_by"]) == (
        "2026-11-14",
        "최재영",
    )
    ingredients = check_recipe(corrected[0]).to_dict()["ingredients"]
    onion = next(item for item in ingredients if item["name_raw"] == "양파다진것")
    assert (onion["section"], onion["amount"], onion["unit"]) == (
        "양송이 속",
        10.0,
        "g",
    )
    pepper = next(item for item in ingredients if item["name_raw"] == "후추")
    assert (pepper["raw_item"], pepper["amount_kind"]) == ("후추적당량", "qualitative")


def test_manifest_level_verifier_still_applies_without_entry_override(manifest):
    _, audit = apply_corrections(load_rows(paths.RECIPES_RAW), manifest)
    assert {(item["verified_at"], item["verified_by"]) for item in audit} == {
        (manifest["verified_at"], manifest["verified_by"])
    }


@pytest.mark.parametrize(
    "mutate",
    [
        # extra change besides the bracket
        lambda e: e["value"].replace("10g", "100g"),
        # a bracket that closes nothing
        lambda e: e["expected_value"].replace("닭가슴살", "닭가슴살]", 1),
        # two brackets
        lambda e: e["value"].replace("양파다진것", "]양파다진것"),
        # a different mark
        lambda e: e["expected_value"].replace("[양송이 속", "[양송이 속)"),
    ],
)
def test_bracket_correction_cannot_change_anything_else(manifest, mutate):
    entry = _bracket_entry(manifest)
    entry["value"] = mutate(entry)
    with pytest.raises(ValueError, match="parenthesis"):
        apply_corrections([_row_for(entry)], manifest)


def test_entry_verifier_must_be_complete(manifest):
    _bracket_entry(manifest)["verified_by"] = ""
    with pytest.raises(ValueError, match="attribution"):
        apply_corrections(load_rows(paths.RECIPES_RAW), manifest)


def _entry(manifest, source_id):
    return next(item for item in manifest["corrections"] if item["source_id"] == source_id)


@pytest.mark.parametrize(
    "source_id,names",
    [
        # a stray 'm' typed for the comma (the next item was the garlic's amount text)
        ("485", ["마늘", "적양배추"]),
        # one extra opening parenthesis swallowed the next item
        ("523", ["두부", "부추"]),
        # an opening mark written for the closing one swallowed the other eight items
        ("781", ["바지락", "양파", "마늘", "마른 홍고추", "올리브유", "호이트와인", "쳥양고추", "저염치즈", "후추", "바질"]),
    ],
)
def test_format_correction_fixes_one_mark_that_hid_items(manifest, source_id, names):
    entry = _entry(manifest, source_id)
    corrected, audit = apply_corrections([_row_for(entry)], manifest)

    assert [(item["source_id"], item["state"]) for item in audit] == [(source_id, "applied")]
    assert (audit[0]["verified_at"], audit[0]["verified_by"]) == ("2026-11-17", "최재영")
    before = {issue.code for issue in check_recipe(_row_for(entry)).all_issues}
    assert before & {"ingredient_item_in_amount", "ingredient_unclosed_paren"}
    after = check_recipe(corrected[0])
    ingredients = after.to_dict()["ingredients"]
    found = [item["name"] for item in ingredients]
    assert all(name in found for name in names), found
    assert all(item["amount_kind"] != "none" for item in ingredients)
    codes = {issue["code"] for issue in after.to_dict()["issues"]}
    assert not codes & {"ingredient_item_in_amount", "ingredient_unclosed_paren"}


@pytest.mark.parametrize(
    "source_id,mutate",
    [
        # a Hangul character changes too
        ("485", lambda e: e["value"].replace("마늘(20g), 적양배추", "마늘(20g), 적양배")),
        # the comma replaces part of a unit, not a stray letter
        ("485", lambda e: e["expected_value"].replace("마늘(20g)m", "마늘(20,)m")),
        # a comma typed in where nothing was wrong
        ("523", lambda e: e["expected_value"].replace("배추(100g)", "배추(100g,)")),
        # two marks change
        ("523", lambda e: e["value"].replace("두부(30g)", "두부(30g")),
        # the bracket edit leaves the line still unbalanced
        ("781", lambda e: e["value"].replace("바지락(모시조개) 200g", "바지락(모시조개 200g")),
    ],
)
def test_format_correction_rejects_more_than_one_mark(manifest, source_id, mutate):
    entry = _entry(manifest, source_id)
    entry["value"] = mutate(entry)
    assert entry["value"] != entry["expected_value"]
    with pytest.raises(ValueError, match="parenthesis"):
        apply_corrections([_row_for(entry)], manifest)


def test_format_correction_adds_colons_after_section_names(manifest):
    entry = _entry(manifest, "774")
    corrected, audit = apply_corrections([_row_for(entry)], manifest)
    assert [(item["source_id"], item["state"]) for item in audit] == [("774", "applied")]
    by_name = {item["name"]: item["section"] for item in check_recipe(corrected[0]).to_dict()["ingredients"]}
    # before: '주먹밥 데친꼬막살'·'두부강된장 참기름' were read as item names
    assert (by_name["데친꼬막살"], by_name["밥"], by_name["다진양파"]) == ("주먹밥", "주먹밥", "두부강된장")
    assert not any(" " in name for name in by_name)


@pytest.mark.parametrize(
    "mutate",
    [
        # a colon in front of an amount would turn a name into a section
        lambda e: e["value"].replace("참기름 3g 두릎 8g", "참기름 3g 두릎: 8g"),
        # a colon after an item that does not follow an amount
        lambda e: e["value"].replace("봄동 10g, 깻잎 6g", "봄동 10g, 깻잎: 6g"),
        # anything besides colons changes
        lambda e: e["value"].replace("주먹밥: 데친꼬막살", "주먹밥: 꼬막살"),
    ],
)
def test_section_colon_correction_rejects_other_edits(manifest, mutate):
    entry = _entry(manifest, "774")
    entry["value"] = mutate(entry)
    with pytest.raises(ValueError, match="parenthesis"):
        apply_corrections([_row_for(entry)], manifest)


def test_collected_source_hides_no_item_in_an_amount_after_corrections(manifest):
    if not paths.RECIPES_ALL_RAW.is_file():
        pytest.skip("전체 레시피 수집본 없음(gitignore)")
    rows, _ = apply_corrections(load_rows(paths.RECIPES_ALL_RAW), manifest)
    hidden = [
        (str(row["RCP_SEQ"]), issue["detail"].get("raw_item"))
        for row in rows
        for issue in check_recipe(row).to_dict()["issues"]
        if issue["code"] == "ingredient_item_in_amount"
    ]
    assert hidden == []
