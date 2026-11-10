"""복지 API 표본 — 시범 지역(대구광역시 남구) 조회 결과와 지역 입력 해석 사례 (데이터 → 복지 API·화면·RAG).

    uv run python -m agetech_data.welfare.sample    # 수집 원본 → docs/data/samples/welfare_api_sample.json

같은 원본이면 같은 출력이다(실행 날짜와 무관 — 시행 기간 종료는 수집 날짜 기준으로 판단).
필드 정의는 docs/data/welfare_contract.md (2절 레코드, 3절 조회, 5절 표본·지역 키).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

from agetech_data import paths
from agetech_data.recipes.validate import _rel, write_json
from agetech_data.welfare.normalize import WelfareRecord, normalize_payload
from agetech_data.welfare.query import services_for

SCHEMA_VERSION = 1
SAMPLE_PATH = paths.REPORTS_DIR / "samples" / "welfare_api_sample.json"
PILOT = ("대구광역시", "남구")

# (사례, 앱이 보내는 시도, 시군구) — 지역 입력을 어떻게 해석하는지
REGION_CASES: list[tuple[str, str | None, str | None]] = [
    ("시범 지역 — 정식 이름", "대구광역시", "남구"),
    ("줄임말 시도", "대구", "남구"),
    ("공백·'구' 생략", "대구 광역시", "남"),
    ("같은 이름 시군구가 다른 시도에도 있음(부산 남구)", "부산광역시", "남구"),
    ("데이터에 없는 시군구 → 시도 전체·전국만", "대구광역시", "해운대구"),
    ("2026-07-01 통합 전 옛 이름", "광주광역시", "광산"),
    ("시군구 없이 시도만", "서울특별시", None),
    ("알 수 없는 시도 → 전국만", "아무도", "어디"),
    ("지역 미입력 → 전국만", None, None),
]

# 전국 사업(130건)은 대표 사례만 싣는다
NATIONAL_CASES: list[tuple[str, Callable[[WelfareRecord], bool]]] = [
    ("상세 있음 · 신청 단계별 기관 안내(apply_guides)", lambda r: bool(r.apply_guides) and not r.unverified_fields),
    ("온라인 신청 가능(online_apply=true)", lambda r: r.online_apply is True),
    ("문의처 값이 전화번호가 아닌 안내 문구", lambda r: any(c.get("value") and not re.search(r"\d", c["value"])
                                                   for c in r.contacts)),
]


def _input(path: Path) -> dict:
    b = path.read_bytes()
    meta = json.loads(b).get("meta") or {}
    return {"path": _rel(path), "sha256": hashlib.sha256(b).hexdigest(), "fetched_at": meta.get("fetched_at"),
            "item_count": meta.get("item_count") or meta.get("total_count")}


def _resolved(q) -> dict:
    return {"ctpv": q.ctpv, "sgg": q.sgg, "notes": q.notes}


def _counts(matches) -> dict:
    c = Counter(m["match"] for m in matches)
    return {k: c.get(k, 0) for k in ("district", "province", "national")}


def sample_date(*payloads: dict) -> date | None:
    """표본 기준일 = 수집 원본 목록 확인 날짜 중 늦은 것(정제 `normalize_payload`와 같은 `fetched_at[:10]`)."""
    days = [f[:10] for p in payloads if (f := (p.get("meta") or {}).get("fetched_at"))]
    return date.fromisoformat(max(days)) if days else None


def build(central_path: Path, local_path: Path, as_of: date | None = None) -> dict:
    central = json.loads(central_path.read_text(encoding="utf-8"))
    local = json.loads(local_path.read_text(encoding="utf-8"))
    # services_for 는 기준일을 안 주면 오늘 날짜로 종료 사업을 거른다 → 표본이 실행 날짜에 따라 바뀌지 않게 고정
    as_of = as_of or sample_date(central, local) or date.today()
    records = normalize_payload(central, "central", as_of) + normalize_payload(local, "local", as_of)

    regions = []
    for label, ctpv, sgg in REGION_CASES:
        q, m = services_for(records, ctpv, sgg, as_of=as_of)
        regions.append({"cases": [label], "input": {"ctpv": ctpv, "sgg": sgg}, "resolved": _resolved(q),
                        "counts": _counts(m),
                        # 지역 사업 이름 몇 개 (대구 남구·부산 남구처럼 숫자가 같아도 다른 사업임을 보이려고)
                        "local_examples": [f"{x['record'].ctpv} {x['record'].sgg or '(시도 전체)'} · {x['record'].name}"
                                           for x in m if x["match"] != "national"][:3]})

    q, matches = services_for(records, *PILOT, as_of=as_of)
    local_items = [{"match": m["match"], "reason": m["reason"], "record": m["record"].to_dict()}
                   for m in matches if m["match"] != "national"]
    national = [m for m in matches if m["match"] == "national"]
    examples, missing = [], []
    for label, pred in NATIONAL_CASES:
        hit = next((m for m in national if pred(m["record"])), None)
        if hit is None:
            missing.append(label)
            continue
        already = next((e for e in examples if e["record"]["serv_id"] == hit["record"].serv_id), None)
        if already:
            already["cases"].append(label)
        else:
            examples.append({"cases": [label], "match": hit["match"], "reason": hit["reason"],
                             "record": hit["record"].to_dict()})
    return {
        "schema_version": SCHEMA_VERSION,
        "description": "복지 API 표본 — 시범 지역(대구광역시 남구) 조회 결과와 지역 입력 해석 사례. 필드 정의는 contract 문서.",
        "contract": "docs/data/welfare_contract.md",
        "input": {"central": _input(central_path), "local": _input(local_path)},
        "as_of": as_of.isoformat(),
        "region_key": {
            "fields": ["ctpv", "sgg"],
            "rule": "지역은 정규화한 (시도, 시군구) 이름 쌍으로 맞춘다. 원천(복지로 중앙·지자체)에는 지역 코드가 없다(정의서 5.2절).",
        },
        "regions": regions,
        "pilot": {
            "input": {"ctpv": PILOT[0], "sgg": PILOT[1]},
            "resolved": _resolved(q),
            "counts": _counts(matches),
            "order": "내 시군구(district) → 내 시도 전체(province) → 전국(national). 같은 범위 안에서는 상세가 있는 것 먼저, 이름순",
            "items": local_items,
            "national_examples": examples,
            "national_omitted": len(national) - len(examples),
        },
        "cases_not_found": missing,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="복지 API 표본(시범 지역) 생성")
    ap.add_argument("--central", type=Path, default=paths.WELFARE_CENTRAL_RAW)
    ap.add_argument("--local", type=Path, default=paths.WELFARE_LOCAL_RAW)
    ap.add_argument("--sample", type=Path, default=SAMPLE_PATH, help="표본 JSON (커밋)")
    ap.add_argument("--as-of", type=date.fromisoformat, default=None,
                    help="시행 기간 종료 판단 기준일 (기본: 수집 원본 목록 확인 날짜)")
    args = ap.parse_args(argv)
    for p in (args.central, args.local):
        if not p.is_file():
            print(f"원본이 없습니다: {_rel(p)} — 먼저 `python -m agetech_data.refresh --source welfare_central welfare_local`",
                  file=sys.stderr)
            return 1
    payload = build(args.central, args.local, args.as_of)
    write_json(args.sample, payload)
    c = payload["pilot"]["counts"]
    print(f"시범 지역 {PILOT[0]} {PILOT[1]}: 시군구 {c['district']} · 시도 전체 {c['province']} · 전국 {c['national']}"
          f"(표본 {len(payload['pilot']['national_examples'])}건) / 지역 해석 사례 {len(payload['regions'])}건 → {_rel(args.sample)}"
          + (f" (없는 사례: {', '.join(payload['cases_not_found'])})" if payload["cases_not_found"] else ""))
    return 1 if payload["cases_not_found"] else 0


if __name__ == "__main__":
    sys.exit(main())
