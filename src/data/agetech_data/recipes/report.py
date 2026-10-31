"""검증 결과(dict) → Markdown 보고서. 같은 입력이면 같은 출력(생성 시각을 넣지 않음)."""

from __future__ import annotations

from agetech_data.recipes.issues import ISSUE_RULES

STATUS_LABEL = {"ok": "정상", "flagged": "표시 후 사용", "hold": "노출 보류 후보"}
SEVERITY_LABEL = {"error": "오류(hold)", "warning": "경고(flagged)", "info": "참고"}
SEVERITY_ACTION = {
    "error": "원문 보완 전까지 앱 노출 보류, 보완 요청",
    "warning": "노출하되 이상 표시, 보완 요청 목록",
    "info": "집계만 (원문 보존)",
}
FORMAT_LABEL = {
    "name_amount": "이름 뒤 분량 `연두부 75g(3/4모)`",
    "paren_amount": "괄호 안 분량 `돼지고기(50g)`",
    "qualitative": "정성 분량 `참깨 약간`",
    "none": "분량 없음",
}
SECTION_LABEL = {
    "colon": "콜론 `●양념장 : …`",
    "inline_word": "콜론 없는 머리말 `재료 닭가슴살(60g)…`",
    "title_line": "제목만 있는 줄 `고명`",
}
INGREDIENT_WARNINGS = [c for c, (s, _) in ISSUE_RULES.items() if c.startswith("ingredient") and s != "info"]
INGREDIENT_INFOS = [c for c, (s, _) in ISSUE_RULES.items() if c.startswith("ingredient") and s == "info"]


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ⏎ ").strip()


def _table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "-"


def render_report(result: dict) -> str:
    s, inp, recipes = result["summary"], result["input"], result["recipes"]
    meta = inp.get("source_meta") or {}
    n = s["recipes"]
    L: list[str] = []
    L += ["# 레시피 원본 품질 검증 보고서 (식품안전나라 COOKRCP01)", ""]
    L += ["> 이 파일은 `uv run python -m agetech_data.recipes.validate`로 생성됩니다. 직접 고치지 마세요.", ""]
    L += _table(["항목", "값"], [
        ["입력 파일", f"`{inp['path']}`"],
        ["입력 sha256", f"`{inp['sha256'][:16]}…`"],
        ["제공처·서비스", f"{meta.get('provider', '-')} · {meta.get('service', '-')}"],
        ["수집 시각(fetchedAt)", meta.get("fetchedAt", "-")],
        ["수집 모드", meta.get("mode", "-")],
        ["레시피 수 (원본 전체)", f"{n} (전체 {meta.get('totalCount', '-')}건 중)"],
        ["가공 결과", "`data/processed/recipes_validated.json` (gitignore, 명령으로 재생성)"],
    ])

    L += ["", "## 1. 요약", ""]
    L += _table(["판정", "의미", "건수", "비율"], [
        [f"`{k}`", STATUS_LABEL[k], v, _pct(v, n)] for k, v in s["status"].items()
    ])
    st, ing = s["steps"], s["ingredients"]
    L += ["",
          f"- 조리 단계: 총 {st['total']}개. **중간 누락이 있는 레시피 {st['recipes_with_gap']}건, 누락 단계 {st['missing_total']}개**",
          f"- 재료 항목: 총 {ing['items']}개. 괄호 설명이 있는 항목 {ing['with_paren']}개(원문 그대로 보존)"]

    L += ["", "## 2. 판정 기준", ""]
    L += _table(["코드", "수준", "설명", "처리"], [
        [f"`{c}`", SEVERITY_LABEL[sev], label, SEVERITY_ACTION[sev]] for c, (sev, label) in ISSUE_RULES.items()
    ])

    L += ["", "## 3. 조리 단계 누락", ""]
    gap = [r for r in recipes if r["missing_step_nos"]]
    if gap:
        L += _table(["ID", "메뉴명", "원문에 있는 단계(칸)", "누락 번호", "판정"], [
            [r["source_id"], r["name"], ", ".join(st_["source_field"] for st_ in r["steps"]),
             ", ".join(map(str, r["missing_step_nos"])), f"`{r['status']}`"] for r in gap
        ])
    else:
        L.append("누락 없음.")
    none = [r for r in recipes if any(i["code"] == "steps_none" for i in r["issues"])]
    if none:
        L += ["", "조리 단계가 하나도 없는 레시피: " + ", ".join(f"{r['source_id']} {r['name']}" for r in none)]

    L += ["", "## 4. 재료·분량 형식 이상 (경고)", ""]
    rows = []
    for r in recipes:
        for i in r["issues"]:
            if i["code"] in INGREDIENT_WARNINGS:
                d = i["detail"]
                rows.append([r["source_id"], r["name"], f"`{i['code']}`", d.get("line_no", ""),
                             f"`{d.get('raw_item', '')}`"])
    L += _table(["ID", "메뉴명", "코드", "원문 줄", "원문 항목"], rows) if rows else ["경고 없음."]

    L += ["", "## 5. 점검 항목별 집계", ""]
    L += _table(["코드", "수준", "설명", "레시피 수", "발생 수"], [
        [f"`{c}`", SEVERITY_LABEL[v["severity"]], v["label"], v["recipes"], v["occurrences"]]
        for c, v in s["issues"].items()
    ])

    L += ["", "## 6. 재료 표기 형식 분포", ""]
    L += _table(["분량 표기 형식", "항목 수", "비율"], [
        [FORMAT_LABEL.get(k, k), v, _pct(v, ing["items"])]
        for k, v in sorted(ing["amount_format"].items(), key=lambda kv: -kv[1])
    ])
    L += [""]
    L += _table(["섹션 표기 방식", "섹션 수"], [
        [SECTION_LABEL.get(k, k), v] for k, v in sorted(ing["section_style"].items(), key=lambda kv: -kv[1])
    ])
    infos = []
    for r in recipes:
        for i in r["issues"]:
            if i["code"] in ("ingredient_no_space_after_comma", "ingredient_trailing_period"):
                d = i["detail"]
                infos.append([r["source_id"], r["name"], f"`{i['code']}`",
                              f"`{d.get('context') or d.get('raw_item', '')}`"])
    if infos:
        L += ["", "표기 참고 항목(내용 문제는 아님):", ""]
        L += _table(["ID", "메뉴명", "코드", "원문 발췌"], infos)

    L += ["", "## 7. 원본 추적과 보완 원칙", "",
          "- 가공 결과의 레시피마다 원본 행 sha256(`raw_sha256`)을, 단계마다 원본 칸(`source_field`)·칸 번호(`source_no`)·"
          "문장 앞 번호(`stated_no`)·원문(`text_raw`)을 보존합니다. 단계 번호를 다시 매기지 않습니다.",
          "- 재료는 원문 조각(`raw_item`)과 원문 줄 번호(`line_no`)를 보존하고, 이를 `name_raw`와 `amount_text`로 "
          "나누기만 합니다. 수식어(다진 등)와 괄호 설명은 지우지 않습니다.",
          "- 비어 있는 단계와 분량은 **임의로 채우지 않습니다.** 원문 보완은 재수집했을 때 원본에 값이 생긴 경우에만 반영합니다.",
          "- `hold` 레시피는 원문 보완 전까지 앱 노출 보류를 권고합니다. `flagged` 레시피는 노출하되 앱에서 누락·이상을 표시합니다.",
          "- 수작업 보완이 필요해지면 출처 URL·확인자·확인일을 함께 남기는 별도 파일로 관리합니다(후속 작업)."]

    L += ["", "## 8. 참고 (이번 범위 밖)", "",
          "영양 필드의 빈 값 건수입니다. 영양값 검증은 공공 영양 DB 매핑 작업에서 다룹니다.", ""]
    L += _table(["필드", "빈 값", "비율"], [[f"`{k}`", v, _pct(v, n)] for k, v in s["nutrition_blank"].items()])
    return "\n".join(L) + "\n"
