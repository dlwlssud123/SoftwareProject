"""레시피 원본 품질 판정과 CLI.

    uv run python -m agetech_data.recipes.validate               # 기본 경로(paths.py)
    uv run python -m agetech_data.recipes.validate --fail-on hold  # 보류 레시피가 있으면 종료 코드 1

판정
- hold    : error 항목이 하나라도 있음 → 노출 보류 후보, 원문 보완 요청
- flagged : warning 항목이 있음 → 노출하되 이상 표시, 원문 보완 요청
- ok      : info 이하만 있음

입력 파일은 읽기만 하고, 내용을 임의로 채우거나 고치지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agetech_data import paths
from agetech_data.recipes.allergens import AllergenResult, app_detect, app_terms_found, detect, load_rules
from agetech_data.recipes.fields import (
    SOURCE_FIELDS,
    NutritionCheck,
    check_nutrition,
    energy_bucket,
    field_issues,
    missing_fields,
)
from agetech_data.recipes.ingredients import IngredientResult, parse_ingredients
from agetech_data.recipes.issues import ISSUE_RULES, Issue
from agetech_data.recipes.steps import StepResult, extract_steps
from agetech_data.textutil import clean_text, is_blank, sha256_json

SCHEMA_VERSION = 2  # 2: missing_fields·nutrition·allergens 추가, summary.nutrition_blank → field_blank·nutrition
Status = Literal["ok", "flagged", "hold"]
STATUS_ORDER: dict[Status, int] = {"ok": 0, "flagged": 1, "hold": 2}


@dataclass
class RecipeCheck:
    source_id: str
    name: str
    raw_sha256: str
    steps: StepResult
    ingredients: IngredientResult
    nutrition: NutritionCheck
    allergens: AllergenResult
    missing_fields: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def all_issues(self) -> list[Issue]:
        return self.issues + self.nutrition.issues + self.steps.issues + self.ingredients.issues

    @property
    def status(self) -> Status:
        sev = {i.severity for i in self.all_issues}
        return "hold" if "error" in sev else ("flagged" if "warning" in sev else "ok")

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "status": self.status,
            "raw_sha256": self.raw_sha256,
            "issues": [i.to_dict() for i in self.all_issues],
            "missing_fields": self.missing_fields,
            "nutrition": self.nutrition.to_dict(),
            "allergens": self.allergens.to_dict(),
            **self.steps.to_dict(),
            **self.ingredients.to_dict(),
        }


def check_recipe(row: dict) -> RecipeCheck:
    name = clean_text(row.get("RCP_NM"))
    base = ([] if name else [Issue("name_missing")]) + field_issues(row)
    ingredients = parse_ingredients(row.get("RCP_PARTS_DTLS"))
    return RecipeCheck(
        source_id=str(row.get("RCP_SEQ", "")).strip(),
        name=name,
        raw_sha256=sha256_json(row),
        steps=extract_steps(row),
        ingredients=ingredients,
        nutrition=check_nutrition(row),
        allergens=detect(ingredients),
        missing_fields=missing_fields(row),
        issues=base,
    )


def summarize(checks: list[RecipeCheck], rows: list[dict]) -> dict:
    by_code_recipes: Counter = Counter()
    by_code_items: Counter = Counter()
    for c in checks:
        codes = [i.code for i in c.all_issues]
        by_code_items.update(codes)
        by_code_recipes.update(set(codes))
    ings = [i for c in checks for i in c.ingredients.ingredients]
    return {
        "recipes": len(checks),
        "status": {s: sum(c.status == s for c in checks) for s in STATUS_ORDER},
        "issues": {
            code: {"severity": ISSUE_RULES[code][0], "label": ISSUE_RULES[code][1],
                   "recipes": by_code_recipes[code], "occurrences": by_code_items[code]}
            for code in ISSUE_RULES if by_code_items[code]
        },
        "steps": {
            "total": sum(len(c.steps.steps) for c in checks),
            "recipes_with_gap": sum(bool(c.steps.missing_nos) for c in checks),
            "missing_total": sum(len(c.steps.missing_nos) for c in checks),
        },
        "ingredients": {
            "items": len(ings),
            "amount_kind": dict(Counter(i.amount_kind for i in ings)),
            "amount_format": dict(Counter(i.amount_format for i in ings)),
            "with_paren": sum(bool(i.paren_texts) for i in ings),
            "section_style": dict(Counter(s.style for c in checks for s in c.ingredients.sections)),
        },
        "field_blank": {f: sum(is_blank(r.get(f)) for r in rows) for f in SOURCE_FIELDS},
        "nutrition": {
            "serving_weight_present": sum(c.nutrition.serving_weight_g is not None for c in checks),
            "ingredient_servings": dict(sorted(Counter(
                "·".join(f"{v:g}" for v in i.detail["servings"])
                for c in checks for i in c.nutrition.issues if i.code == "ingredient_servings_stated").items())),
            "energy_ratio": dict(Counter(energy_bucket(c.nutrition) for c in checks)),
            "energy_mismatch": sum(c.nutrition.suspect for c in checks),
        },
        "allergens": summarize_allergens(checks, rows),
    }


def summarize_allergens(checks: list[RecipeCheck], rows: list[dict]) -> dict:
    rules = load_rules()
    by = {}
    for r in rules.allergens:
        if not r.determinable:
            continue
        hits = [d for c in checks for d in c.allergens.detected if d["allergen"] == r.name]
        by[r.name] = {"label": r.label, "recipes": len(hits), "direct": sum(d["kind"] == "direct" for d in hits)}
    # 앱 현재 규칙과 비교 (앱 선택지 6종)
    compare = {}
    for a in ("알류", "우유", "대두", "새우", "밀", "땅콩"):
        app_only, ours_only, both = [], [], 0
        for c, row in zip(checks, rows, strict=True):
            in_app, in_ours = a in app_detect(row.get("RCP_PARTS_DTLS")), a in c.allergens.names
            both += in_app and in_ours
            if in_app != in_ours:
                (app_only if in_app else ours_only).append((c, row))
        compare[a] = {"both": both, "app_only": len(app_only), "ours_only": len(ours_only),
                      # 앱만: 앱이 맞춘 단어 / 이번 규칙만: 근거 재료
                      "app_only_examples": [{"source_id": c.source_id, "name": c.name,
                                             "evidence": app_terms_found(row.get("RCP_PARTS_DTLS"), a)}
                                            for c, row in app_only[:5]],
                      "ours_only_examples": [_example(c, a) for c, _ in ours_only[:5]]}
    return {
        "standard": rules.standard,
        "recipes_with_any": sum(bool(c.allergens.detected) for c in checks),
        "by_allergen": by,
        "needs_check": {"recipes": sum(bool(c.allergens.needs_check) for c in checks),
                        "terms": dict(Counter(n["term"] for c in checks for n in c.allergens.needs_check).most_common())},
        "incomplete": sum(not c.allergens.complete for c in checks),
        "not_determinable": [r.name for r in rules.allergens if not r.determinable],
        "app_compare": compare,
    }


def _example(c: RecipeCheck, allergen: str) -> dict:
    ev = next((d["evidence"] for d in c.allergens.detected if d["allergen"] == allergen), [])
    return {"source_id": c.source_id, "name": c.name, "evidence": [e["ingredient"] for e in ev]}


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def load_payload(path: Path) -> tuple[list[dict], dict | None]:
    """(레시피 행, 파일 안 수집 메타). 행 목록 / API 원 응답 / 갱신 수집본({"meta", "items"}) 형태를 받는다."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    meta = None
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            meta, data = data.get("meta"), data["items"]
        else:
            data = data.get("COOKRCP01", data).get("row", [])
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError(f"레시피 행 목록이 아닙니다: {path}")
    return data, meta


def load_rows(path: Path) -> list[dict]:
    return load_payload(path)[0]


def build_result(input_path: Path, source_meta_path: Path | None) -> dict:
    raw_bytes = input_path.read_bytes()
    rows, meta = load_payload(input_path)
    meta_path = None
    # 입력 파일 안에 수집 메타가 있으면 그것을 쓴다 (기본 --source-meta 는 앱 50건용이라 섞지 않음)
    if meta is None and source_meta_path and source_meta_path.is_file():
        meta = json.loads(source_meta_path.read_text(encoding="utf-8-sig"))
        meta_path = _rel(source_meta_path)
    checks = [check_recipe(r) for r in rows]
    return {
        "schema_version": SCHEMA_VERSION,
        "input": {
            "path": _rel(input_path),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_meta_path": meta_path,
            "source_meta": meta,
        },
        "rules": {code: {"severity": s, "label": label} for code, (s, label) in ISSUE_RULES.items()},
        "summary": summarize(checks, rows),
        "recipes": [c.to_dict() for c in checks],
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    from agetech_data.recipes.report import render_report

    ap = argparse.ArgumentParser(description="COOKRCP01 레시피 원본의 조리 단계·재료 품질 검증")
    ap.add_argument("--input", type=Path, default=paths.RECIPES_RAW, help="레시피 원본 JSON (읽기 전용)")
    ap.add_argument("--source-meta", type=Path, default=paths.RECIPES_SOURCE_META, help="수집 메타 JSON")
    ap.add_argument("--output-json", type=Path, default=paths.RECIPES_VALIDATED, help="가공 결과 JSON")
    ap.add_argument("--report", type=Path, default=paths.RECIPE_QUALITY_REPORT, help="Markdown 보고서")
    ap.add_argument("--no-report", action="store_true", help="보고서를 쓰지 않음")
    ap.add_argument("--fail-on", choices=["never", "hold", "flagged"], default="never",
                    help="해당 상태 이상 레시피가 있으면 종료 코드 1")
    args = ap.parse_args(argv)

    result = build_result(args.input, args.source_meta)
    write_json(args.output_json, result)
    if not args.no_report:
        command = "uv run python -m agetech_data.recipes.validate"
        if args.input != paths.RECIPES_RAW:  # 기본 입력이 아니면 다시 만들 수 있게 경로를 적는다
            command += (f" --input {_rel(args.input)} --output-json {_rel(args.output_json)}"
                        f" --report {_rel(args.report)}")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(result, _rel(args.output_json), command), encoding="utf-8", newline="\n")

    s = result["summary"]
    st = s["status"]
    print(f"레시피 {s['recipes']}건: ok {st['ok']} / flagged {st['flagged']} / hold {st['hold']}")
    print(f"조리 단계 누락 레시피 {s['steps']['recipes_with_gap']}건 (누락 단계 {s['steps']['missing_total']}개)")
    print(f"원문 영양값 이상 의심 {s['nutrition']['energy_mismatch']}건, "
          f"1인분 중량 있음 {s['nutrition']['serving_weight_present']}건")
    print(f"가공 결과 → {_rel(args.output_json)}")
    if not args.no_report:
        print(f"보고서   → {_rel(args.report)}")

    if args.fail_on != "never":
        limit = STATUS_ORDER[args.fail_on]
        if any(STATUS_ORDER[r["status"]] >= limit for r in result["recipes"]):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
