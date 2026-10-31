import json

from agetech_data.recipes.report import render_report
from agetech_data.recipes.validate import build_result, check_recipe, main


def _row(seq, name="테스트", parts="두부 20g(2×2×2cm)", **manual):
    row = {"RCP_SEQ": seq, "RCP_NM": name, "RCP_PARTS_DTLS": parts}
    row.update({f"MANUAL{i:02d}": "" for i in range(1, 21)})
    row.update({f"MANUAL_IMG{i:02d}": "" for i in range(1, 21)})
    row.update(manual)
    return row


GOOD = _row("1", MANUAL01="1. 씻는다", MANUAL02="2. 끓인다")
GAP = _row("2", MANUAL01="1. 씻는다", MANUAL03="3. 끓인다")
FIRST_MISSING = _row("3", MANUAL02="2. 썬다", MANUAL03="3. 끓인다")
NO_PARTS = _row("4", parts="", MANUAL01="1. 씻는다")


def test_status_rules():
    assert check_recipe(GOOD).status == "ok"
    assert check_recipe(GAP).status == "flagged"
    assert check_recipe(FIRST_MISSING).status == "hold"
    assert check_recipe(NO_PARTS).status == "hold"
    assert check_recipe(_row("5", name="", MANUAL01="1. a")).status == "hold"


def test_raw_hash_tracks_source_row():
    a, b = check_recipe(GOOD), check_recipe(dict(reversed(list(GOOD.items()))))
    assert a.raw_sha256 == b.raw_sha256                       # 키 순서와 무관
    assert a.raw_sha256 != check_recipe(GAP).raw_sha256


def _write(tmp_path, rows, meta=None):
    inp = tmp_path / "recipes.json"
    inp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    m = tmp_path / "recipe_source.json"
    m.write_text(json.dumps(meta or {"provider": "식품안전나라", "service": "COOKRCP01"}), encoding="utf-8")
    return inp, m


def test_cli_writes_outputs_and_does_not_touch_input(tmp_path):
    inp, meta = _write(tmp_path, [GOOD, GAP, FIRST_MISSING])
    before = inp.read_bytes()
    out, rep = tmp_path / "out" / "v.json", tmp_path / "rep" / "r.md"
    code = main(["--input", str(inp), "--source-meta", str(meta), "--output-json", str(out), "--report", str(rep)])
    assert code == 0 and inp.read_bytes() == before
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["status"] == {"ok": 1, "flagged": 1, "hold": 1}
    assert data["recipes"][2]["missing_step_nos"] == [1]
    assert "| 3 | 테스트 |" in rep.read_text(encoding="utf-8")


def test_cli_fail_on(tmp_path):
    inp, meta = _write(tmp_path, [GOOD, GAP])
    common = ["--input", str(inp), "--source-meta", str(meta), "--output-json", str(tmp_path / "v.json"), "--no-report"]
    assert main(common + ["--fail-on", "hold"]) == 0
    assert main(common + ["--fail-on", "flagged"]) == 1


def test_accepts_raw_api_response_shape(tmp_path):
    inp, meta = _write(tmp_path, {"COOKRCP01": {"row": [GOOD]}})
    assert build_result(inp, meta)["summary"]["recipes"] == 1


def test_report_is_deterministic(tmp_path):
    inp, meta = _write(tmp_path, [GOOD, GAP])
    assert render_report(build_result(inp, meta)) == render_report(build_result(inp, meta))
