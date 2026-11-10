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
