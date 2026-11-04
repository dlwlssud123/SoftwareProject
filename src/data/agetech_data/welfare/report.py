"""복지 지역별 보고서. 같은 입력이면 같은 출력(생성 시각을 넣지 않음)."""

from __future__ import annotations

from agetech_data.recipes.report import _pct, _table
from agetech_data.welfare.regions import CTPV, CTPV_ALIASES, MERGED

SCOPE_LABEL = {"national": "전국 사업(중앙부처)", "province": "시도 전체 사업", "district": "시군구 사업"}
DETAIL_LABEL = {"fresh": "이번 갱신에서 받음", "cached": "캐시 재사용", "stale": "목록이 바뀌어 다시 받을 예정(이전 상세 유지)",
                "pending": "상세 미수집(목록 정보만)"}
FLAG_LABEL = {"detail_pending": "상세 미수집", "detail_stale": "상세 갱신 대기", "period_ended": "시행 기간 종료",
              "no_official_link": "복지로 공식 링크 없음", "unknown_ctpv": "시도명 미인식",
              "homepage_not_url": "관련 누리집 값이 주소가 아님(기관명 등)"}
FIELD_LABEL = {"summary": "서비스 요약", "target_detail": "지원 대상", "selection_criteria": "선정 기준",
               "benefits": "지원 내용", "apply_detail": "신청 방법 설명", "apply_methods": "신청 방법(구분)",
               "target_groups": "대상 특성", "themes": "관심 주제", "contacts": "문의처 목록",
               "main_contact": "대표 문의처", "detail_url": "복지로 링크", "last_modified": "최종 수정일",
               "period_end": "시행 종료일"}


def render_report(inputs: dict, s: dict, examples: list[dict]) -> str:
    L = ["# 복지 데이터 지역별 보고서 (노년층, 중앙부처 + 지자체)", "",
         "> 이 파일은 `uv run python -m agetech_data.welfare.build`로 생성됩니다. 직접 고치지 마세요.", ""]
    rows = []
    for src, label in (("central", "중앙부처 복지"), ("local", "지자체 복지")):
        m = inputs[src].get("meta") or {}
        d = (m.get("details") or {})
        rows.append([label, f"`{inputs[src]['path']}`", m.get("fetched_at", "-"), m.get("item_count", "-"),
                     ", ".join(f"{k} {v}" for k, v in sorted((d.get("counts") or {}).items())) or "-",
                     f"`{inputs[src]['sha256'][:12]}…`"])
    L += _table(["원천", "원문 파일 (gitignore)", "목록 확인 시각(UTC)", "건수", "상세 상태", "sha256"], rows)

    n, scope, ds = s["records"], s["by_scope"], s["detail_status"]
    with_detail = n - ds.get("pending", 0)
    L += ["", "## 1. 요약", "",
          f"- 노년층(`lifeArray=006`) 복지 **{n}건**: " + ", ".join(
              f"{SCOPE_LABEL[k]} {scope.get(k, 0)}" for k in ("national", "province", "district")),
          f"- 상세(지원 대상·선정 기준·지원 내용·신청 방법·문의처) 확보 **{with_detail}건({_pct(with_detail, n)})**. "
          "공공데이터포털 개발계정 상세 호출 한도(중앙 100/일, 지자체 1,000/일) 때문에 매일 갱신하며 나눠 받습니다.",
          "- 상세를 받지 못한 항목도 목록 정보(이름·요약·지역·대상 특성·신청 방법 구분·담당 부서·복지로 링크)로 안내할 수 있고, "
          "빠진 필드는 레코드의 `unverified_fields`로 '미확인' 표시합니다.",
          "- 지역이 맞는 사업을 안내할 뿐 **수급 자격을 판정하지 않습니다.**", ""]
    L += _table(["상세 상태", "의미", "건수"], [[f"`{k}`", DETAIL_LABEL.get(k, k), v] for k, v in sorted(ds.items())])

    L += ["", "## 2. 시도명 정규화", "",
          f"- 원천 시도명 {len(s['by_ctpv'])}개를 현재 시도명 목록({len(CTPV)}개)으로 모두 인식했습니다"
          + (f". 미인식: {', '.join(s['unknown_ctpv'])}" if s["unknown_ctpv"] else "."),
          f"- **2026-07-01 광주광역시·전라남도 통합 → `{MERGED}`**. 원천 데이터에는 옛 이름이 없습니다. "
          "사용자·앱이 옛 이름을 보내도 통합특별시로 찾습니다. 앱 지역 선택 목록에는 아직 옛 이름이 따로 있어 앱 쪽 확인이 필요합니다.",
          "- 옛 이름·줄임말 처리: " + ", ".join(f"`{a}`→{b}" for a, b in CTPV_ALIASES.items()
                                              if a in ("광주광역시", "전라남도", "강원도", "전라북도", "제주도", "서울", "경북")) + " 등",
          "- 시군구는 시도 안에서만 맞춥니다(`중구`·`남구` 등 같은 이름이 여러 시도에 있음). '경산'처럼 시·군·구를 빼고 적어도 하나로 정해지면 찾습니다."]

    L += ["", "## 3. 시도별 지자체 사업", ""]
    L += _table(["시도", "지자체 사업", "시도 전체", "시군구 사업", "사업이 있는 시군구 수", "상세 확보"], [
        [c, v["total"], v["province"], v["district"], v["districts_covered"], f"{v['with_detail']} ({_pct(v['with_detail'], v['total'])})"]
        for c, v in sorted(s["by_ctpv"].items(), key=lambda kv: -kv[1]["total"])
    ])

    L += ["", "## 4. 필드 채움률", "", "상세가 아직 없는 항목은 상세 전용 필드(지원 대상 등)가 비어 있습니다. 상세 수집이 끝나면 다시 생성합니다.", ""]
    L += _table(["필드", "중앙부처", "지자체"], [[FIELD_LABEL.get(f, f), f"{v['central']}%", f"{v['local']}%"]
                                         for f, v in s["fill_pct"].items()])

    L += ["", "## 5. 최신성과 품질 표시", ""]
    L += _table(["지자체 최종 수정 연도", "건수"], [[k, v] for k, v in s["last_modified_year"].items()])
    L += [""]
    L += _table(["품질 표시", "설명", "건수"], [[f"`{k}`", FLAG_LABEL.get(k, k), v] for k, v in s["flags"].items()]) \
        if s["flags"] else ["품질 표시 없음."]

    L += ["", "## 6. 지역별 조회 예시", "",
          "`services_for(records, 시도, 시군구)` 결과입니다. 순서는 내 시군구 → 내 시도 전체 → 전국이며, 시행 기간이 끝난 사업은 뺍니다.", ""]
    L += _table(["입력", "해석", "시군구", "시도 전체", "전국", "지역 사업 예시", "메모"], [
        [e["input"], f"{e['ctpv'] or '-'} {e['sgg'] or ''}".strip(), e["district"], e["province"], e["national"],
         "; ".join(e["local_examples"]) or "-", " / ".join(e["notes"]) or "-"] for e in examples
    ])

    L += ["", "## 7. 원칙과 제한", "",
          "- 원문(목록 필드·상세 XML)은 `data/raw/welfare/`에 그대로 있고, 정제는 HTML 엔티티·`<br>`·태그 정리와 쉼표 목록 분리만 합니다.",
          "- 문의처·누리집·서식·법령 목록은 중앙·지자체의 서로 다른 하위 태그를 `name`·`value`로 맞추고 원래 태그는 `raw`에 둡니다. "
          "누리집 주소에 `https://`가 없으면 붙이고 `link_status`로 표시합니다.",
          "- 중앙부처 사업은 지역 구분이 없어 '전국'으로 둡니다. 실제 신청 창구·지역 조건은 원문의 대상·기준 문장을 따릅니다.",
          "- 상세가 `stale`이면 목록이 바뀌었는데 상세는 이전 것이라, 다음 갱신 전까지 내용이 다를 수 있습니다.",
          "- 필드 정의는 `docs/data/welfare_contract.md`를 따릅니다."]
    return "\n".join(L) + "\n"
