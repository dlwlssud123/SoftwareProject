"""Apply source-verified recipe corrections to a copy and retain an audit trail."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from agetech_data import paths
from agetech_data.recipes.validate import check_recipe, load_rows, summarize, write_json
from agetech_data.textutil import sha256_json

ALLOWED_FIELD = re.compile(r"MANUAL(?:0[1-9]|1[0-9]|20)|RCP_PARTS_DTLS")


_BRACKETS = "()[]"


def _single_edit(expected: str, value: str) -> tuple[int, str, str] | None:
    """(position, removed, inserted) when the texts differ by one inserted, deleted or replaced character."""
    if expected == value:
        return None
    shorter = min(len(expected), len(value))
    at = next(
        (i for i in range(shorter) if expected[i] != value[i]), shorter
    )
    tail = 0
    while tail < shorter - at and expected[-1 - tail] == value[-1 - tail]:
        tail += 1
    removed, inserted = expected[at : len(expected) - tail], value[at : len(value) - tail]
    if len(removed) > 1 or len(inserted) > 1:
        return None
    return at, removed, inserted


def _line_at(text: str, at: int) -> str:
    end = text.find("\n", at)
    return text[text.rfind("\n", 0, at) + 1 : len(text) if end < 0 else end]


def _well_formed(line: str) -> bool:
    """Every '(' / '[' on the line is closed by its own kind, in order."""
    stack = []
    for ch in line:
        if ch in "([":
            stack.append(ch)
        elif ch in ")]":
            if not stack or "([".index(stack.pop()) != ")]".index(ch):
                return False
    return not stack


def _fixes_one_mark(expected: str, value: str) -> bool:
    """Allow one punctuation character to change; Hangul, digits and units stay exactly as they were.

    - a bracket edit (add a closing mark, drop an extra opening mark, or turn an opening mark into a
      closing one) that makes its own line's ( ) [ ] well formed when it was not, or
    - a stray Latin letter typed for the comma between two items ('마늘(20g)m 적양배추' → '마늘(20g), 적양배추').
    """
    edit = _single_edit(expected, value)
    if edit is None:
        return False
    at, removed, inserted = edit
    if set(removed + inserted) <= set(_BRACKETS):
        return not _well_formed(_line_at(expected, at)) and _well_formed(
            _line_at(value, at)
        )
    return (
        removed.isascii()
        and removed.isalpha()
        and inserted == ","
        and expected[at - 1 : at] == ")"
        and expected[at + 1 : at + 2].isspace()
    )


# '… 미나리 3g 주먹밥' — a section name (Hangul only) right after an item's amount, at the end of the text so far
_SECTION_AFTER_AMOUNT = re.compile(r"(?:\d\s*[A-Za-z가-힣]*|\))\s+[가-힣]{2,20}$")


def _adds_section_colons(expected: str, value: str) -> bool:
    """Only ':' marks inserted, each after a section name typed between two items without its colon.

    '미나리 3g 주먹밥 데친꼬막살 12g' → '미나리 3g 주먹밥: 데친꼬막살 12g': the name follows an item's amount and
    a name (not an amount) follows the colon, so the colon starts a section and cannot turn a name into an amount.
    """
    if len(value) <= len(expected):
        return False
    i, spots = 0, []
    for j, ch in enumerate(value):
        if i < len(expected) and expected[i] == ch:
            i += 1
        elif ch == ":":
            spots.append(j)
        else:
            return False
    return i == len(expected) and all(
        _SECTION_AFTER_AMOUNT.search(value[:k])
        and value[k + 1 : k + 2].isspace()
        and value[k + 1 :].lstrip()[:1].isalpha()
        for k in spots
    )


def _attribution(entry: dict, manifest: dict) -> tuple[str, str]:
    """An entry may name its own verifier; otherwise the manifest-level one applies."""
    verified_at = entry.get("verified_at", manifest["verified_at"])
    verified_by = entry.get("verified_by", manifest["verified_by"])
    if not (
        isinstance(verified_at, str)
        and verified_at
        and isinstance(verified_by, str)
        and verified_by
    ):
        raise ValueError("Recipe corrections require verification attribution")
    return verified_at, verified_by


def apply_corrections(
    rows: list[dict], manifest: dict
) -> tuple[list[dict], list[dict]]:
    """Never change the input or silently overwrite upstream changes."""
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("corrections"), list
    ):
        raise ValueError("Unsupported recipe correction manifest")
    if not manifest.get("verified_at") or not manifest.get("verified_by"):
        raise ValueError("Recipe corrections require verification attribution")

    corrected = [dict(row) for row in rows]
    by_id = {str(row.get("RCP_SEQ", "")): row for row in corrected}
    if len(by_id) != len(rows):
        raise ValueError("Duplicate recipe IDs in correction input")

    seen = set()
    audit = []
    for entry in manifest["corrections"]:
        required = (
            "source_id",
            "recipe_name",
            "field",
            "expected_value",
            "value",
            "kind",
            "source_url",
        )
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(key), str) for key in required
        ):
            raise ValueError("Invalid recipe correction entry")
        field = entry["field"]
        source = urlsplit(entry["source_url"])
        key = (entry["source_id"], field)
        if (
            not ALLOWED_FIELD.fullmatch(field)
            or key in seen
            or not entry["value"].strip()
        ):
            raise ValueError("Unsupported or duplicate recipe correction field")
        if source.scheme != "https" or source.hostname not in (
            "www.foodsafetykorea.go.kr",
            "foodsafetykorea.go.kr",
        ):
            raise ValueError(
                "Recipe corrections require an official Food Safety Korea source"
            )
        if entry["kind"] not in ("official_source", "format_only"):
            raise ValueError("Unsupported recipe correction kind")
        if entry["kind"] == "official_source" and entry["expected_value"].strip():
            raise ValueError("Official source recovery may only fill missing fields")
        if entry["kind"] == "format_only" and not (
            field == "RCP_PARTS_DTLS"
            and (
                _fixes_one_mark(entry["expected_value"], entry["value"])
                or _adds_section_colons(entry["expected_value"], entry["value"])
            )
        ):
            raise ValueError(
                "Format correction may only fix a single parenthesis or bracket mark"
                " (or one stray letter typed for a comma, or add the colon after a section name)"
            )
        verified_at, verified_by = _attribution(entry, manifest)
        seen.add(key)

        row = by_id.get(entry["source_id"])
        if row is None:
            continue
        if row.get("RCP_NM") != entry["recipe_name"]:
            raise ValueError(
                f"Recipe name changed for correction {entry['source_id']}; reverify the source"
            )
        previous = row.get(field, "")
        if previous not in (entry["expected_value"], entry["value"]):
            raise ValueError(
                f"Recipe {entry['source_id']} field {field} changed upstream; reverify the source"
            )
        row[field] = entry["value"]
        audit.append(
            {
                **entry,
                "verified_at": verified_at,
                "verified_by": verified_by,
                "state": "already_present" if previous == entry["value"] else "applied",
            }
        )
    return corrected, audit


def build_result(input_path: Path, corrections_path: Path) -> tuple[list[dict], dict]:
    rows = load_rows(input_path)
    manifest = json.loads(corrections_path.read_text(encoding="utf-8"))
    corrected, audit = apply_corrections(rows, manifest)
    before = summarize([check_recipe(row) for row in rows], rows)
    after = summarize([check_recipe(row) for row in corrected], corrected)
    return corrected, {
        "schema_version": 1,
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "corrections_sha256": hashlib.sha256(corrections_path.read_bytes()).hexdigest(),
        "effective_rows_sha256": sha256_json(corrected),
        "nutrition_source_available": paths.NUTRITION_RAW.is_file(),
        "changes": audit,
        "before": before,
        "after": after,
        "recipes": [
            {
                "source_id": str(raw["RCP_SEQ"]),
                "source_raw_sha256": sha256_json(raw),
                "effective_sha256": sha256_json(effective),
            }
            for raw, effective in zip(rows, corrected, strict=True)
        ],
    }


def render_report(audit: dict) -> str:
    before, after = audit["before"], audit["after"]
    lines = [
        "# 레시피 외부 원문 대조·보완 결과",
        "",
        "> `python -m agetech_data.recipes.correct`로 생성합니다. 수집 원본은 변경하지 않습니다.",
        "",
        f"- 수집 원본 SHA-256: `{audit['input_sha256']}`",
        f"- 보완 목록 SHA-256: `{audit['corrections_sha256']}`",
        f"- 원본/보완본 단계 수: {before['steps']['total']} → {after['steps']['total']}",
        f"- 누락 단계: {before['steps']['missing_total']} → {after['steps']['missing_total']}",
        f"- 품질 상태: `{before['status']}` → `{after['status']}`",
        "",
        "| 레시피 ID | 항목 | 구분 | 확인일 | 근거 |",
        "|---|---|---|---|---|",
    ]
    for change in audit["changes"]:
        lines.append(
            f"| {change['source_id']} | `{change['field']}` | {change['kind']} | "
            f"{change['verified_at']} | [공식 원문]({change['source_url']}) |"
        )
    lines += [
        "",
        "## 남은 확인 항목",
        "",
        "- ID 38의 표고버섯 기둥 분량은 공식 상세·배포 자료에도 수치가 없어 미확정으로 유지합니다.",
        f"- `INFO_WGT` {after['nutrition_blank']['INFO_WGT']}건 누락은 조리 후 중량 근거 없이 재료 합계로 대체하지 않습니다.",
        "- 표기 보완(format_only)은 재료 이름·수치·단위는 그대로 두고 괄호·대괄호 한 글자(닫는 괄호 넣기·여분 여는 괄호 빼기·"
        "여는 괄호를 닫는 괄호로), 쉼표 자리에 잘못 친 영문 한 글자, 또는 재료 사이에 쌍점 없이 적힌 구획 이름 뒤 쌍점만 "
        "고치는 수정입니다. 공식 원문에도 같은 표기 오류가 있습니다.",
        "- 보완본은 `data/processed/recipes_corrected.json`, 상세 감사 기록은 `recipe_correction_audit.json`입니다.",
        "- 백엔드 적재와 데이터 처리는 같은 보완 목록을 적용합니다. upstream 값이 바뀌면 재검증 오류를 냅니다. Flutter 앱의 보완 목록 연결은 후속 작업입니다.",
    ]
    if not audit["nutrition_source_available"]:
        lines.append(
            "- 식품 영양 원본은 현재 체크아웃에 없어 8,807건 전체 매핑 재생성은 별도 수집 후 확인합니다."
        )
    lines += [
        "",
        "## 외부 자료의 불일치",
        "",
        "ID 38의 나트륨은 식품안전나라 원문에서 2441mg이지만 교육부 배포 가이드에서는 244mg입니다. "
        "누락 보완 범위를 넘어서는 수치 불일치이므로 현재 값을 임의로 변경하지 않고 검토 대상으로 남깁니다.",
        "- [식품안전나라 상세](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=38)",
        "- [교육부 학교급식 나트륨 줄이기 가이드, 인쇄 50쪽](https://clik.nanet.go.kr/clikr-collection/policyinfo/202/1010/2014/CLIKC6983894526481553_attach_1.pdf)",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=paths.RECIPES_RAW)
    parser.add_argument("--corrections", type=Path, default=paths.RECIPE_CORRECTIONS)
    parser.add_argument("--output", type=Path, default=paths.RECIPES_CORRECTED)
    parser.add_argument("--audit", type=Path, default=paths.RECIPE_CORRECTION_AUDIT)
    parser.add_argument("--report", type=Path, default=paths.RECIPE_CORRECTION_REPORT)
    args = parser.parse_args(argv)
    corrected, audit = build_result(args.input, args.corrections)
    write_json(args.output, corrected)
    write_json(args.audit, audit)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(audit), encoding="utf-8", newline="\n")
    print(
        f"Recipes: {len(corrected)}, verified corrections: {len(audit['changes'])}, missing steps: {audit['after']['steps']['missing_total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
