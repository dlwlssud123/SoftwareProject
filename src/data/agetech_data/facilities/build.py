"""무료급식소 정제 실행: 수집 원본 → 시설 레코드·보고서·시범 지역 조회 표본.

    uv run python -m agetech_data.refresh --source meal_facilities    # 수집(판본·실패 시 이전 판본 유지)
    uv run python -m agetech_data.facilities.build                    # 정제·보고서·표본

출력
- data/processed/meal_facilities.json     시설 레코드 (gitignore)
- docs/data/meal_facility_report.md       보고서 (커밋, 생성물)
- docs/data/samples/meal_facility_sample.json  대구 남구 조회 표본 (커밋, 생성물)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from agetech_data import paths
from agetech_data.facilities.normalize import STALE_DAYS, MealFacility, normalize_payload
from agetech_data.facilities.query import CLOSED_FLAGS, facilities_for

SCHEMA_VERSION = 1
PILOT = ("대구광역시", "남구")
FLAG_LABELS = {
    "reference_stale": f"자료 기준일이 {STALE_DAYS}일 넘음",
    "operation_ended": "운영 종료일 지남 (조회에서 기본 제외)",
    "not_operating": "원천에 '미운영' (조회에서 기본 제외)",
    "not_started": "운영 시작일 전",
    "coords_missing": "좌표 없음",
    "coords_invalid": "좌표가 국내 범위 밖",
    "phone_missing": "전화번호 없음",
    "days_unparsed": "급식 요일을 읽지 못함 (원문 보존)",
    "time_unparsed": "급식 시간을 읽지 못함 (원문 보존)",
    "includes_delivery": "반찬·도시락 배달 포함",
    "duplicate_merged": "다른 지자체·기준일 중복 등록을 합침",
    "address_missing": "주소 없음",
    "region_from_provider": "주소 없어 제공 지자체로 지역 결정",
    "region_unknown": "시도를 알 수 없음",
    "sgg_from_provider": "주소에서 시군구를 못 읽어 같은 시도의 제공 지자체로 정함",
}


def _rel(p: Path) -> str:
    p = p.resolve()
    return p.relative_to(paths.REPO_ROOT).as_posix() if p.is_relative_to(paths.REPO_ROOT) else p.as_posix()


def summarize(rows: int, records: list[MealFacility]) -> dict:
    def has(r, f):
        return f in r.quality_flags
    open_ = [r for r in records if not CLOSED_FLAGS.intersection(r.quality_flags)]
    by_ctpv = {}
    for c in sorted({r.ctpv or "알 수 없음" for r in records}):
        rs = [r for r in records if (r.ctpv or "알 수 없음") == c]
        by_ctpv[c] = {"facilities": len(rs), "closed": sum(1 for r in rs if CLOSED_FLAGS.intersection(r.quality_flags)),
                      "coords_missing": sum(1 for r in rs if r.latitude is None),
                      "stale": sum(1 for r in rs if has(r, "reference_stale")),
                      "latest_reference": max((r.reference_date or "" for r in rs), default="")}
    return {
        "rows": rows, "facilities": len(records), "merged_rows": rows - len(records),
        "open_facilities": len(open_),
        "flags": dict(Counter(f for r in records for f in r.quality_flags).most_common()),
        "reference_years": dict(sorted(Counter((r.reference_date or "")[:4] for r in records).items())),
        "days_parsed_pct": round(100 * sum(1 for r in records if r.days) / max(1, len(records)), 1),
        "time_parsed_pct": round(100 * sum(1 for r in records if r.meals) / max(1, len(records)), 1),
        "by_ctpv": by_ctpv,
    }


def _days(r: MealFacility) -> str:
    return "·".join(r.days) if r.days else f"({r.days_raw or '—'})"


def _meals(r: MealFacility) -> str:
    if not r.meals:
        return f"({r.time_raw or '—'})"
    return ", ".join(f"{m['meal'] or ''} {m['start']}" + (f"~{m['end']}" if m["end"] else "~") for m in r.meals).strip()


def render_report(meta: dict, raw_info: dict, summary: dict, records: list[MealFacility], as_of: date) -> str:
    pilot = [r for r in records if (r.ctpv, r.sgg) == PILOT]
    daegu = [r for r in records if r.ctpv == PILOT[0]]
    L = [
        "# 무료급식소·경로식당 자료 보고서 (전국무료급식소표준데이터)",
        "",
        "> 이 파일은 `uv run python -m agetech_data.facilities.build`로 생성됩니다. 직접 고치지 마세요.",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 원천 | {meta.get('service')} — [공공데이터포털]({meta.get('documentation')}) |",
        f"| 원문 파일 (gitignore) | `{raw_info['path']}` (sha256 `{raw_info['sha256'][:12]}…`) |",
        f"| 수집 시각(UTC) | {meta.get('fetched_at')} |",
        f"| 판단 기준일 | {as_of.isoformat()} (기준일 {STALE_DAYS}일 넘으면 '오래됨', 운영 종료일이 지나면 '종료') |",
        "",
        "## 1. 요약",
        "",
        f"- 원천 {summary['rows']:,}행 → 시설 **{summary['facilities']:,}곳** (중복 등록 {summary['merged_rows']}행 합침). "
        f"운영 종료·미운영을 뺀 조회 대상 {summary['open_facilities']:,}곳",
        f"- 급식 요일을 읽은 시설 {summary['days_parsed_pct']}%, 급식 시간을 읽은 시설 {summary['time_parsed_pct']}%. "
        "못 읽은 것은 원문을 그대로 보여 준다",
        "- 지자체가 올린 시설만 있다. 노인복지관 경로식당 등 빠진 시설이 있을 수 있어 **시범 지역은 남구청 확인이 필요**하다.",
        "- 가깝거나 지역이 같다고 이용 자격·당일 운영을 확정하지 않는다. 화면은 '이용 전 전화로 확인'을 함께 안내한다.",
        "",
        "| 표시 | 의미 | 시설 수 |",
        "|---|---|---:|",
    ]
    for f, n in summary["flags"].items():
        L.append(f"| `{f}` | {FLAG_LABELS.get(f, f)} | {n} |")
    L += ["", "자료 기준일 분포: " + ", ".join(f"{y or '없음'}년 {n}곳" for y, n in summary["reference_years"].items()), "",
          "## 2. 시도별", "",
          "| 시도 | 시설 | 종료·미운영 | 좌표 없음 | 기준일 1년 넘음 | 최신 기준일 |", "|---|---:|---:|---:|---:|---|"]
    for c, s in summary["by_ctpv"].items():
        L.append(f"| {c} | {s['facilities']} | {s['closed']} | {s['coords_missing']} | {s['stale']} | {s['latest_reference']} |")
    L += ["", "- 원천 주소의 시도 표기가 섞여 있다(옛 `전라남도`·`광주광역시`·`강원도`, 어순 바뀐 `광주전남통합특별시`, "
          "띄어쓰기 빠진 `충청남도홍성군`). 모두 현재 시도명으로 맞췄다(`welfare.regions`).",
          "", f"## 3. 시범 지역 시도 — {PILOT[0]}", "", "| 시군구 | 시설 |", "|---|---:|"]
    for sgg, n in sorted(Counter(r.sgg or "—" for r in daegu).items()):
        L.append(f"| {sgg} | {n} |")
    L += ["", f"## 4. 시범 지역 — {PILOT[0]} {PILOT[1]} ({len(pilot)}곳)", "",
          "| 시설 | 주소 | 대상 | 요일 | 시간 | 전화 | 기준일 | 표시 |", "|---|---|---|---|---|---|---|---|"]
    for r in pilot:
        L.append(f"| {r.name} | {r.address_road or r.address_lot or '—'} | {', '.join(r.targets) or '—'} | {_days(r)} | "
                 f"{_meals(r)} | {r.phone or '—'} | {r.reference_date or '—'} | {', '.join(r.quality_flags) or '—'} |")
    L += ["", "- 남구 자료는 2곳뿐이다. 남구청 노인복지 담당에 경로식당·추가 무료급식 시설이 있는지 시연 전 확인한다.", "",
          "## 5. 요일·시간을 읽지 못한 원문 (상위 10)", "", "| 원문 | 시설 수 |", "|---|---:|"]
    unparsed = Counter(r.days_raw for r in records if "days_unparsed" in r.quality_flags)
    unparsed.update(r.time_raw for r in records if "time_unparsed" in r.quality_flags)
    for raw, n in unparsed.most_common(10):
        L.append(f"| {raw} | {n} |")
    merged = [r for r in records if r.merged_from]
    L += ["", "## 6. 중복 등록 합치기", "",
          "- 같은 (시설명, 주소)를 여러 지자체·기준일로 올린 행은 기준일이 가장 최신인 행 하나만 남긴다"
          "(같으면 현재 시도명 지자체). 합친 행은 레코드의 `merged_from`에 남는다.",
          "- 같은 지자체가 한 장소의 다른 급식 요일·시간을 올린 행은 서로 다른 레코드로 둔다(`facility_id` 끝 `-2`).",
          f"- 합친 시설 {len(merged)}곳. 대부분 통합 전 `광주광역시`와 통합 후 `전남광주통합특별시`가 같은 시설을 각각 올린 경우.",
          ""]
    return "\n".join(L)


def _sample_item(x: dict) -> dict:
    r: MealFacility = x["facility"]
    keep = ("facility_id", "name", "operator", "ctpv", "sgg", "address_road", "address_lot", "phone", "place", "targets",
            "days", "days_raw", "meals", "time_raw", "latitude", "longitude", "reference_date", "provider",
            "quality_flags")
    return {"match": x["match"], "distance_km": x["distance_km"], "cautions": x["cautions"],
            **{k: getattr(r, k) for k in keep}}


def build_sample(records: list[MealFacility]) -> dict:
    region, by_region = facilities_for(records, "대구", "남구")
    anchor = next((r for r in records if (r.ctpv, r.sgg) == PILOT and r.latitude is not None), None)
    cases = [{"id": "region_daegu_namgu", "description": "위치 거부 — 앱 프로필 '대구 남구'로 지역 조회 (남구 → 대구시 다른 구)",
              "input": {"ctpv": "대구", "sgg": "남구"},
              "resolved": {"ctpv": region.ctpv, "sgg": region.sgg, "notes": region.notes},
              "count": len(by_region), "results": [_sample_item(x) for x in by_region[:10]]}]
    if anchor:
        _, near = facilities_for(records, "대구", "남구", lat=anchor.latitude, lon=anchor.longitude, radius_km=3.0)
        cases.append({"id": "nearby_3km", "description": f"위치 허용 — 예시 위치 = {anchor.name} 좌표, 반경 3km 가까운 순 "
                                                          "(지역 경계와 무관)",
                      "input": {"ctpv": "대구", "sgg": "남구", "lat": anchor.latitude, "lon": anchor.longitude,
                                "radius_km": 3.0},
                      "count": len(near), "results": [_sample_item(x) for x in near[:10]]})
    return {"schema_version": 1, "description": "무료급식소·경로식당 조회 표본(시범 지역 대구 남구). "
            "`python -m agetech_data.facilities.build`로 생성 — 직접 고치지 마세요.", "cases": cases}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="무료급식소 정제·보고서·조회 표본")
    ap.add_argument("--input", type=Path, default=paths.FREE_MEAL_RAW)
    ap.add_argument("--output", type=Path, default=paths.MEAL_FACILITIES_PROCESSED)
    ap.add_argument("--report", type=Path, default=paths.MEAL_FACILITY_REPORT)
    ap.add_argument("--sample", type=Path, default=paths.MEAL_FACILITY_SAMPLE)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="오래됨·종료 판단 기준일 (기본: 오늘)")
    args = ap.parse_args(argv)
    if not args.input.exists():
        print(f"{args.input} 없음 — 먼저 `python -m agetech_data.refresh --source meal_facilities`")
        return 1
    raw_bytes = args.input.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    as_of = args.as_of or date.today()
    records = normalize_payload(payload, as_of)
    meta = payload.get("meta") or {}
    raw_info = {"path": _rel(args.input), "sha256": hashlib.sha256(raw_bytes).hexdigest(), "meta": meta}
    summary = summarize(len(payload.get("items") or []), records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "as_of": as_of.isoformat(), "input": raw_info,
                                       "summary": summary, "records": [r.to_dict() for r in records]},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    args.report.write_text(render_report(meta, raw_info, summary, records, as_of), encoding="utf-8", newline="\n")
    args.sample.parent.mkdir(parents=True, exist_ok=True)
    args.sample.write_text(json.dumps(build_sample(records), ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"시설 {summary['facilities']}곳 (원천 {summary['rows']}행), 조회 대상 {summary['open_facilities']}곳")
    print(f"→ {args.output}\n→ {args.report}\n→ {args.sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
