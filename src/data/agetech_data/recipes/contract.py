"""레시피 API 계약 형식(데이터 → 서버·앱)과 표본 생성.

    uv run python -m agetech_data.recipes.contract                 # 앱 50건 → 가공 결과 + 표본
    uv run python -m agetech_data.recipes.contract --input data/raw/recipes/cookrcp01_all.json --no-sample
    # RAG·DB 게시 내용과 맞추려면 보완표(원문 보완, DB import_public_data 와 같은 파일)를 적용한다
    uv run python -m agetech_data.recipes.contract --input data/raw/recipes/cookrcp01_all.json --no-sample         --corrections src/frontend/assets/data/recipe_corrections.json --output-json data/processed/recipes_api_all.json

출력
- data/processed/recipes_api.json           계약 형식 전체 (gitignore)
- docs/data/samples/recipe_api_sample.json  대표 사례 표본 (커밋, 같은 입력이면 같은 출력)

필드 정의는 docs/data/recipe_contract.md. 원문 값을 고치거나 채우지 않는다(이미지 주소의 https 전환만 예외, 아래 참고).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

from agetech_data import paths
from agetech_data.recipes.correct import apply_corrections
from agetech_data.recipes.validate import RecipeCheck, _rel, check_recipe, load_payload, write_json
from agetech_data.textutil import clean_text, sha256_json

SCHEMA_VERSION = 1
# 식품안전나라 이미지는 http 주소로 오지만 같은 경로가 https로 제공된다(http는 https로 302 이동, 2026-11-05 확인).
# Android 9+ 는 기본 설정에서 http 요청을 막으므로 이 호스트만 https로 바꾼다.
HTTPS_HOSTS = ("www.foodsafetykorea.go.kr",)


def https_image(url: str | None) -> str | None:
    u = (url or "").strip()
    if not u:
        return None
    for host in HTTPS_HOSTS:
        if u.startswith(f"http://{host}/"):
            return "https://" + u[len("http://"):]
    return u


def _text(v) -> str | None:
    return clean_text(v) or None


def to_api_record(check: RecipeCheck, row: dict, meta: dict | None) -> dict:
    meta = meta or {}
    issues = check.all_issues
    return {
        "recipe_id": check.source_id,
        "name": check.name,
        "category": _text(row.get("RCP_PAT2")),            # 요리종류 (반찬·일품·후식·밥·국&찌개·기타)
        "cooking_method": _text(row.get("RCP_WAY2")),      # 조리방법 (끓이기·굽기 …)
        "hashtag": _text(row.get("HASH_TAG")),             # 원천은 대표 재료 한 단어
        "images": {"small": https_image(row.get("ATT_FILE_NO_MAIN")), "large": https_image(row.get("ATT_FILE_NO_MK"))},
        "ingredients_text": _text(row.get("RCP_PARTS_DTLS")),
        "ingredients": [
            {"order_no": i.order_no, "section": i.section or None, "name": i.name, "name_raw": i.name_raw,
             "amount_text": i.amount_text or None, "amount": i.amount, "unit": i.unit, "amount_kind": i.amount_kind}
            for i in check.ingredients.ingredients
        ],
        "steps": [{"no": s.number, "text": s.text_clean, "image": https_image(s.image_url), "source_field": s.source_field}
                  for s in check.steps.steps],
        "missing_step_nos": check.steps.missing_nos,
        "nutrition": check.nutrition.to_dict(),
        "sodium_tip": _text(row.get("RCP_NA_TIP")),
        "allergens": check.allergens.to_dict(),
        "quality": {
            "status": check.status,
            "issues": [{"code": i.code, "severity": i.severity, "label": i.label, "detail": i.detail}
                       for i in issues if i.severity != "info"],
            "info_codes": sorted({i.code for i in issues if i.severity == "info"}),
            "missing_fields": check.missing_fields,
        },
        "source": {
            "provider": meta.get("provider"), "service": meta.get("service") or "COOKRCP01",
            "source_id": check.source_id,
            "fetched_at": meta.get("fetchedAt") or meta.get("fetched_at"),
            "raw_sha256": check.raw_sha256,
        },
    }


def _id_key(r: dict):
    rid = r["recipe_id"]
    return (0, int(rid), "") if rid.isdigit() else (1, 0, rid)


# 표본으로 보여 줄 사례 (순서대로, 레시피 ID가 작은 것부터 아직 고르지 않은 것 하나씩)
SAMPLE_CASES: list[tuple[str, Callable[[dict], bool]]] = [
    ("정상 · 1인분 중량 있음", lambda r: r["quality"]["status"] == "ok" and r["nutrition"]["serving_weight_g"] is not None),
    ("정상 · 알레르기 근거가 가공식품(usually)", lambda r: r["quality"]["status"] == "ok"
        and any(d["kind"] == "usually" for d in r["allergens"]["detected"])),
    ("조리 단계 누락 → hold", lambda r: bool(r["missing_step_nos"])),
    ("원문 영양값 이상 의심 → flagged", lambda r: r["nutrition"]["suspect"]),
    ("재료 괄호 미닫힘 → flagged, 알레르기 추정 불완전", lambda r: not r["allergens"]["complete"]),
    ("정할 수 없는 재료(needs_check)", lambda r: bool(r["allergens"]["needs_check"])),
    ("재료 원문에 N인분 표기", lambda r: r["nutrition"]["ingredient_servings"] is not None),
]


def select_samples(records: list[dict]) -> tuple[list[dict], list[str]]:
    """사례마다 하나. 이미 고른 표본이 그 사례에도 해당하면 새로 고르지 않고 사례만 덧붙인다."""
    chosen, missing = [], []
    ordered = sorted(records, key=_id_key)
    for label, pred in SAMPLE_CASES:
        already = next((s for s in chosen if pred(s["recipe"])), None)
        if already:
            already["cases"].append(label)
            continue
        rec = next((r for r in ordered if pred(r)), None)
        if rec is None:
            missing.append(label)
        else:
            chosen.append({"cases": [label], "recipe": rec})
    return chosen, missing


def build(input_path: Path, source_meta_path: Path | None, corrections_path: Path | None = None) -> dict:
    """corrections_path 를 주면 보완표를 적용한 행(DB recipe_revisions.effective 와 같은 행)으로 레코드를 만들고,
    source 에 원문 해시(raw_sha256)·보완 후 해시(effective_sha256)·이 레시피에 적용한 보완(corrections)을 남긴다."""
    rows, meta = load_payload(input_path)
    if meta is None and source_meta_path and source_meta_path.is_file():
        meta = json.loads(source_meta_path.read_text(encoding="utf-8-sig"))
    inputs = {"path": _rel(input_path), "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}
    if corrections_path is None:
        records = [to_api_record(check_recipe(r), r, meta) for r in rows]
    else:
        manifest_bytes = corrections_path.read_bytes()
        effective, audit = apply_corrections(rows, json.loads(manifest_bytes))
        inputs["corrections"] = {"path": _rel(corrections_path),
                                 "sha256": hashlib.sha256(manifest_bytes).hexdigest()}
        records = []
        for raw, row in zip(rows, effective, strict=True):
            rec = to_api_record(check_recipe(row), row, meta)
            rec["source"].update(
                raw_sha256=sha256_json(raw), effective_sha256=sha256_json(row),
                corrections=[{"field": a["field"], "kind": a["kind"], "state": a["state"]} for a in audit
                             if str(a["source_id"]) == rec["recipe_id"]])
            records.append(rec)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "docs/data/recipe_contract.md",
        "input": inputs,
        "records": records,
    }


def sample_payload(result: dict) -> dict:
    samples, missing = select_samples(result["records"])
    return {
        "schema_version": result["schema_version"],
        "description": "레시피 API 계약 표본 (데이터 → 서버·앱). 대표 사례만 골랐다. 필드 정의는 contract 문서.",
        "contract": result["contract"],
        "input": result["input"],
        "samples": samples,
        "cases_not_found": missing,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="레시피 API 계약 형식 가공 결과와 표본 생성")
    ap.add_argument("--input", type=Path, default=paths.RECIPES_RAW, help="레시피 원본 JSON (읽기 전용)")
    ap.add_argument("--source-meta", type=Path, default=paths.RECIPES_SOURCE_META, help="수집 메타 JSON")
    ap.add_argument("--output-json", type=Path, default=paths.RECIPES_API, help="계약 형식 전체 (gitignore)")
    ap.add_argument("--sample", type=Path, default=paths.RECIPE_API_SAMPLE, help="표본 JSON (커밋)")
    ap.add_argument("--no-sample", action="store_true", help="표본을 쓰지 않음")
    ap.add_argument("--corrections", type=Path, default=None,
                    help="보완표를 적용해 DB 게시 내용(effective)과 같은 행으로 만든다 (예: RAG 입력)")
    args = ap.parse_args(argv)
    if not args.input.is_file():
        print(f"입력 파일 없음: {args.input}", file=sys.stderr)
        return 1

    result = build(args.input, args.source_meta, args.corrections)
    write_json(args.output_json, result)
    print(f"레시피 {len(result['records'])}건 → {_rel(args.output_json)}")
    if not args.no_sample:
        payload = sample_payload(result)
        write_json(args.sample, payload)
        print(f"표본 {len(payload['samples'])}건 → {_rel(args.sample)}"
              + (f" (없는 사례: {', '.join(payload['cases_not_found'])})" if payload["cases_not_found"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
