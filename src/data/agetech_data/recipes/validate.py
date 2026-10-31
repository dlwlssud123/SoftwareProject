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
from agetech_data.recipes.ingredients import IngredientResult, parse_ingredients
from agetech_data.recipes.issues import ISSUE_RULES, Issue
from agetech_data.recipes.steps import StepResult, extract_steps
from agetech_data.textutil import clean_text, is_blank, sha256_json

SCHEMA_VERSION = 1
Status = Literal["ok", "flagged", "hold"]
STATUS_ORDER: dict[Status, int] = {"ok": 0, "flagged": 1, "hold": 2}
NUTRITION_FIELDS = ["INFO_WGT", "INFO_ENG", "INFO_CAR", "INFO_PRO", "INFO_FAT", "INFO_NA"]


@dataclass
class RecipeCheck:
    source_id: str
    name: str
    raw_sha256: str
    steps: StepResult
    ingredients: IngredientResult
    issues: list[Issue] = field(default_factory=list)

    @property
    def all_issues(self) -> list[Issue]:
        return self.issues + self.steps.issues + self.ingredients.issues

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
            **self.steps.to_dict(),
            **self.ingredients.to_dict(),
        }


def check_recipe(row: dict) -> RecipeCheck:
    name = clean_text(row.get("RCP_NM"))
    base = [] if name else [Issue("name_missing")]
    return RecipeCheck(
        source_id=str(row.get("RCP_SEQ", "")).strip(),
        name=name,
        raw_sha256=sha256_json(row),
        steps=extract_steps(row),
        ingredients=parse_ingredients(row.get("RCP_PARTS_DTLS")),
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
        # 참고(범위 외): 영양 필드 결측 건수. 영양 검증은 식품 매핑 작업에서 다룬다.
        "nutrition_blank": {f: sum(is_blank(r.get(f)) for r in rows) for f in NUTRITION_FIELDS},
    }


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):  # API 원 응답 형태도 허용
        data = data.get("COOKRCP01", data).get("row", [])
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError(f"레시피 행 목록이 아닙니다: {path}")
    return data


def build_result(input_path: Path, source_meta_path: Path | None) -> dict:
    raw_bytes = input_path.read_bytes()
    rows = load_rows(input_path)
    meta = None
    if source_meta_path and source_meta_path.is_file():
        meta = json.loads(source_meta_path.read_text(encoding="utf-8-sig"))
    checks = [check_recipe(r) for r in rows]
    return {
        "schema_version": SCHEMA_VERSION,
        "input": {
            "path": _rel(input_path),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_meta_path": _rel(source_meta_path) if meta is not None else None,
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
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(result), encoding="utf-8", newline="\n")

    s = result["summary"]
    st = s["status"]
    print(f"레시피 {s['recipes']}건: ok {st['ok']} / flagged {st['flagged']} / hold {st['hold']}")
    print(f"조리 단계 누락 레시피 {s['steps']['recipes_with_gap']}건 (누락 단계 {s['steps']['missing_total']}개)")
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
