"""복지 정제·지역 정규화 + 지역별 보고서.

    uv run python -m agetech_data.refresh --source welfare_central welfare_local   # 1) 원문 갱신 (키 필요)
    uv run python -m agetech_data.welfare.build                                     # 2) 정제·보고서 (네트워크 불필요)

출력
- data/processed/welfare_elderly.json      통합 레코드 (gitignore)
- docs/data/welfare_regional_report.md     지역별 보고서 (커밋)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from agetech_data import paths
from agetech_data.welfare.normalize import WelfareRecord, normalize_payload
from agetech_data.welfare.query import services_for

SCHEMA_VERSION = 1
# 보고서 조회 예시 (팀 소재지 경산, 대도시 구, 통합특별시 옛 이름 입력, 이름 접미사 생략)
EXAMPLES = [("경상북도", "경산시"), ("대구광역시", "수성구"), ("서울특별시", "중구"),
            ("광주광역시", "광산구"), ("전라남도", "순천"), ("강원도", None)]
FILL_FIELDS = ["summary", "target_detail", "selection_criteria", "benefits", "apply_detail", "apply_methods",
               "target_groups", "themes", "contacts", "main_contact", "detail_url", "last_modified", "period_end"]


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def summarize(records: list[WelfareRecord]) -> dict:
    local = [r for r in records if r.source == "local"]
    by_ctpv = {}
    for c in sorted({r.ctpv for r in local if r.ctpv}):
        rs = [r for r in local if r.ctpv == c]
        by_ctpv[c] = {"total": len(rs), "province": sum(r.scope == "province" for r in rs),
                      "district": sum(r.scope == "district" for r in rs),
                      "districts_covered": len({r.sgg for r in rs if r.sgg}),
                      "with_detail": sum(r.detail_status != "pending" for r in rs),
                      "raw_names": sorted({r.ctpv_raw for r in rs if r.ctpv_raw})}
    n = len(records) or 1

    def filled(r, f):
        v = getattr(r, f)
        return bool(v) if not isinstance(v, list) else len(v) > 0

    return {
        "records": len(records),
        "by_source": dict(Counter(r.source for r in records)),
        "by_scope": dict(Counter(r.scope for r in records)),
        "detail_status": dict(Counter(r.detail_status for r in records)),
        "flags": dict(Counter(f for r in records for f in r.quality_flags).most_common()),
        "unverified": dict(Counter(f for r in records for f in r.unverified_fields).most_common()),
        "fill_pct": {f: {s: round(100 * sum(filled(r, f) for r in records if r.source == s)
                                  / max(sum(r.source == s for r in records), 1), 1) for s in ("central", "local")}
                     for f in FILL_FIELDS},
        "by_ctpv": by_ctpv,
        "last_modified_year": dict(sorted(Counter((r.last_modified or "없음")[:4] for r in local).items(),
                                          reverse=True)),
        "unknown_ctpv": sorted({r.ctpv_raw or "" for r in records if "unknown_ctpv" in r.quality_flags}),
        "_n": n,
    }


def examples(records: list[WelfareRecord]) -> list[dict]:
    out = []
    for c, s in EXAMPLES:
        q, matches = services_for(records, c, s)
        cnt = Counter(m["match"] for m in matches)
        local_names = [m["record"].name for m in matches if m["match"] != "national"][:3]
        out.append({"input": f"{c} {s or ''}".strip(), "ctpv": q.ctpv, "sgg": q.sgg, "notes": q.notes,
                    "district": cnt.get("district", 0), "province": cnt.get("province", 0),
                    "national": cnt.get("national", 0), "local_examples": local_names})
    return out


def main(argv: list[str] | None = None) -> int:
    from agetech_data.welfare.report import render_report

    ap = argparse.ArgumentParser(description="복지 정제·지역 정규화·지역별 보고서")
    ap.add_argument("--central", type=Path, default=paths.WELFARE_CENTRAL_RAW)
    ap.add_argument("--local", type=Path, default=paths.WELFARE_LOCAL_RAW)
    ap.add_argument("--output", type=Path, default=paths.WELFARE_PROCESSED)
    ap.add_argument("--report", type=Path, default=paths.WELFARE_REGIONAL_REPORT)
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args(argv)

    inputs, records = {}, []
    for source, path in (("central", args.central), ("local", args.local)):
        if not path.is_file():
            print(f"원문이 없습니다: {_rel(path)} — 먼저 `python -m agetech_data.refresh --source welfare_{source}` 실행",
                  file=sys.stderr)
            return 1
        raw = path.read_bytes()
        payload = json.loads(raw)
        inputs[source] = {"path": _rel(path), "sha256": hashlib.sha256(raw).hexdigest(), "meta": payload.get("meta")}
        records += normalize_payload(payload, source)
    summary = summarize(records)
    ex = examples(records)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "input": inputs,
                               "summary": {k: v for k, v in summary.items() if not k.startswith("_")},
                               "records": [r.to_dict() for r in records]}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(args.output)
    if not args.no_report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(inputs, summary, ex), encoding="utf-8", newline="\n")

    ds = summary["detail_status"]
    print(f"복지 {summary['records']}건 정제 (전국 {summary['by_scope'].get('national', 0)}, "
          f"시도 전체 {summary['by_scope'].get('province', 0)}, 시군구 {summary['by_scope'].get('district', 0)})"
          f" → {_rel(args.output)}")
    print(f"상세 상태: {ds}")
    if not args.no_report:
        print(f"보고서 → {_rel(args.report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
