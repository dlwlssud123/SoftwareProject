"""영양 매핑 결과 → Markdown 보고서. 같은 입력이면 같은 출력(생성 시각을 넣지 않음)."""

from __future__ import annotations

from agetech_data.nutrition.foods import FOOD_FLAGS
from agetech_data.nutrition.fields import NUTRIENT_FIELDS
from agetech_data.recipes.report import _pct, _table

MATCH_LABEL = {
    "reviewed": ("사람 확인 수동 매핑", "사용"),
    "curated": ("근거를 적은 수동 매핑, 사람 확인 전", "사용 (검토 대기)"),
    "exact": ("규칙 일치, 후보 1개", "사용"),
    "water": ("물", "0으로 취급"),
    "candidate": ("유사 후보만 있음", "사용 안 함"),
    "unmapped": ("후보 없음", "사용 안 함"),
}
GRAM_LABEL = {
    "direct": "원문 g 그대로", "direct_paren": "원문 괄호의 g", "approx_ml": "mL → 1mL≈1g 근사",
    "count_unit": "개수 단위(환산 안 함)", "qualitative": "약간·적당량(환산 안 함)",
    "missing": "분량 없음", "unparsed": "단위 읽기 실패",
}
NUTRIENT_LABEL = {k: label for k, (_f, label) in NUTRIENT_FIELDS.items()}


def _fmt(v, nd=1) -> str:
    return "-" if v is None else f"{v:,.{nd}f}"


def _ratio(calc, src) -> str:
    try:
        s = float(src)
    except (TypeError, ValueError):
        return "-"
    return f"{calc / s:.2f}" if s else "-"


def render_report(inputs: dict, s: dict, recipes: list[dict], dishes: dict) -> str:
    """dishes = dish_eval.evaluate() 결과 (음식명 검색 정답 표본 평가)."""
    meta = (inputs["nutrition_raw"].get("meta") or {})
    L: list[str] = ["# 레시피 재료 → 식품영양성분DB 매핑 보고서", "",
                    "> 이 파일은 `uv run python -m agetech_data.nutrition.build`로 생성됩니다. 직접 고치지 마세요.", ""]
    L += _table(["항목", "값"], [
        ["영양DB", f"{meta.get('service', '-')} ({meta.get('api_version', '-')} 판본)"],
        ["수집 조건", f"`DB_CLASS_NM={(meta.get('params') or {}).get('DB_CLASS_NM', '-')}`"],
        ["수집 시각(UTC)", meta.get("fetched_at", "-")],
        ["수집 건수", f"{meta.get('item_count', '-')} / totalCount {meta.get('total_count', '-')}"],
        ["원본 파일", f"`{inputs['nutrition_raw']['path']}` (gitignore) sha256 `{inputs['nutrition_raw']['sha256'][:16]}…`"],
        ["레시피 입력", f"`{inputs['recipes']['path']}` sha256 `{inputs['recipes']['sha256'][:16]}…`"],
        ["가공 결과", "`data/processed/foods_v03.json`, `data/processed/recipe_ingredient_nutrition.json` (gitignore)"],
    ])

    if inputs["recipes"].get("corrections_path"):
        L += ["", f"레시피 보완: `{inputs['recipes']['corrections_path']}` "
              f"sha256 `{inputs['recipes']['corrections_sha256'][:16]}…`, "
              f"적용 항목 {inputs['recipes']['correction_count']}건. 원본 해시와 보완 목록 해시를 함께 보존합니다."]

    n_items = s["items"]
    mi, mg = s["match_items"], s["match_grams"]
    used_items = sum(mi.get(k, 0) for k in ("reviewed", "curated", "exact"))
    g_all = sum(v for k, v in mg.items() if k != "water")
    g_used = sum(mg.get(k, 0) for k in ("reviewed", "curated", "exact"))
    L += ["", "## 1. 요약", "",
          f"- 레시피 {s['recipes']}건, 재료 {n_items}개. 식품코드가 정해진 재료 **{used_items}개({_pct(used_items, n_items)})**, "
          f"g 환산된 재료 무게(물 제외) 기준 **{_pct(round(g_used), round(g_all))}**",
          f"- 모든 재료(물 제외)가 영양 계산에 들어간 레시피 **{s['complete_recipes']}건**. "
          "나머지는 개수 단위·정성 분량·미매핑 재료가 있어 합계가 부분값입니다.",
          f"- 수동 매핑표 {s['manual_map']['entries']}건 중 사람 확인 {s['manual_map']['reviewed']}건"
          + ("" if s["manual_map"]["reviewed"] == s["manual_map"]["entries"]
             else " (나머지는 근거만 적은 `curated`, PR 리뷰에서 확인 요청)"), ""]
    L += _table(["매핑 상태", "의미", "영양 계산", "항목 수", "비율", "g (환산분)", "무게 비율(물 제외)"], [
        [f"`{k}`", MATCH_LABEL[k][0], MATCH_LABEL[k][1], mi.get(k, 0), _pct(mi.get(k, 0), n_items),
         _fmt(mg.get(k), 0), "-" if k == "water" else _pct(round(mg.get(k, 0)), round(g_all))]
        for k in MATCH_LABEL
    ])
    L += [""]
    L += _table(["분량 → g 환산", "항목 수"], [
        [f"`{k}` {GRAM_LABEL.get(k, k)}", v] for k, v in sorted(s["gram_status"].items(), key=lambda kv: -kv[1])
    ])
    if s["ml_approx_items"]:
        L += ["", f"- 식품 기준량이 100mL 인 식품을 g 분량으로 계산한 항목 {s['ml_approx_items']}개는 1mL≈1g 으로 근사했습니다."]

    L += ["", "## 2. 매핑 기준", "",
          "- 수동 매핑표(`src/data/agetech_data/resources/ingredient_food_map.json`)가 규칙보다 우선합니다.",
          "- `exact` 규칙: 식품명 전체 일치(`참기름`), `재료명, 생것`(`양파, 생것`), "
          "`상위, 재료명[, 생것]`이고 상위 이름이 재료명에 포함(`파, 대파, 생것`), 괄호 별칭(`큰느타리버섯(새송이버섯), 생것`), "
          "`다진 ○○` → `○○, 다진것` 우선.",
          "- 같은 규칙에서 후보가 둘 이상이면 원재료성을 우선하고, 그래도 여럿이면 자동으로 정하지 않습니다.",
          "- 가공식품으로만 맞았는데 같은 이름의 원재료 계열이 있으면 자동으로 정하지 않습니다 "
          "(예: `땅콩`이 과자류 `땅콩`에, `검은콩`이 두유 음료 `검은콩`에 붙지 않도록).",
          "- `candidate`는 유사도 상위 후보만 제시하며 영양 계산에 쓰지 않습니다."]

    cur = [d for d in s["review"] if d["status"] == "curated"]
    mm = s["manual_map"]
    L += ["", f"## 3. 검토 대기: 수동 매핑(`curated`) {len(cur)}종", "",
          "근거만 적고 사람이 확인하지 않은 매핑입니다. 확인 후 매핑표의 `reviewed_by`·`reviewed_at`을 채우면 `reviewed`가 됩니다. "
          f"(매핑표 {mm['entries']}건 중 확인 완료 {mm['reviewed']}건)", ""]
    L += _table(["재료명", "식품명", "근거", "사용 횟수", "g"], [
        [d["name"], d["food_name"], d["rationale"], d["count"], _fmt(d["grams"], 0)] for d in cur
    ]) if cur else ["없음."]

    rest = [d for d in s["review"] if d["status"] in ("candidate", "unmapped")]
    L += ["", f"## 4. 식품코드가 정해지지 않은 재료 {len(rest)}종", "",
          "부위·품종·가공 형태를 원문만으로 정할 수 없거나 DB에 대응 식품이 없는 재료입니다. 영양 계산에서 빠집니다. "
          "`unmapped` 중 근거가 있는 것은 매핑표에서 '매핑하지 않음'으로 정한 것입니다(먹지 않는 약재·이중 계산되는 소스 등).", ""]
    L += _table(["재료명", "상태", "사용 횟수", "g", "결정 근거 / 상위 후보 (식품명·점수)"], [
        [d["name"], f"`{d['status']}`", d["count"], _fmt(d["grams"], 0),
         d["rationale"] or "; ".join(f"{c['name']} ({c['score']:.2f})" for c in d["candidates"]) or "-"] for d in rest
    ]) if rest else ["없음."]

    L += ["", "## 5. 레시피 원문 영양값과 비교 (참고)", "",
          "레시피 원문 `INFO_*`는 1인분 표기지만 1인분 중량(`INFO_WGT`)이 대부분 비어 있고, 재료 분량이 몇 인분 기준인지도 "
          "원문마다 다릅니다. 아래 비율(계산값 ÷ 원문값)은 매핑이 크게 어긋났는지 보는 점검용이며 정답 비교가 아닙니다.",
          "계산 범위가 '전체'면 물을 뺀 모든 재료가 계산에 들어간 것이고, 백분율이면 g 환산된 재료 무게 중 계산에 들어간 "
          "비율입니다(개수 단위·정성 분량 재료는 이 비율에 포함되지 않음). 모든 재료 계산 또는 90% 이상인 레시피만 싣습니다.", ""]
    rows = []
    for r in recipes:
        cov = r["coverage"]
        if not (cov["complete"] or (cov["grams_used_pct"] or 0) >= 90):
            continue
        c, src = r["computed"], r["source_values"]
        rows.append([r["source_id"], r["name"], "전체" if cov["complete"] else f"{cov['grams_used_pct']}%",
                     _fmt(c["energy_kcal"], 0), src["energy_kcal"], _ratio(c["energy_kcal"], src["energy_kcal"]),
                     _fmt(c["sodium_mg"], 0), src["sodium_mg"], _ratio(c["sodium_mg"], src["sodium_mg"]),
                     _fmt(c["protein_g"], 1), src["protein_g"], _ratio(c["protein_g"], src["protein_g"])])
    L += _table(["ID", "메뉴명", "계산 범위", "열량 계산", "원문", "비율", "나트륨 계산", "원문", "비율",
                 "단백질 계산", "원문", "비율"], rows) if rows else ["대상 없음."]

    f = s["foods"]
    L += ["", "## 6. 식품영양성분DB 정제 결과", "",
          f"- 정제 식품 {f['count']}건. 값은 기준량(100g 또는 100mL)당 함량 그대로이며 g↔mL 환산은 하지 않습니다.",
          "- 이상값은 `quality_flags`로 표시합니다. 근거가 있는 원천 오류만 보정표"
          "(`src/data/agetech_data/resources/food_corrections.json`)로 고치며, 수집 원본은 바꾸지 않고 원래 값을 `corrections`에 남깁니다.", ""]
    cs = f.get("corrections", [])
    L += [f"### 원천 오류 보정 {len(cs)}건", ""]
    L += _table(["식품코드", "식품명", "필드", "원래 값", "바꾼 값", "이유", "확인"], [
        [f"`{c['food_code']}`", c["name"], f"`{c['field']}`", c["from"], c["to"], c["reason"], f"{c['by']} {c['at']}"]
        for c in cs
    ]) if cs else ["없음."]
    stale, gone = f.get("corrections_stale", []), f.get("corrections_missing", [])
    if stale or gone:
        L += ["", "**다시 확인 필요**: 원천이 바뀌어 적용하지 않은 보정 "
              + ", ".join(f"`{x['food_code']}` {x['name']}" for x in stale)
              + (" / 수집본에 없는 식품코드 " + ", ".join(f"`{c}`" for c in gone) if gone else "")]
    L += [""]
    L += _table(["DB군", "기준량 단위", "식품 수"], [
        [k.split("|")[0], k.split("|")[1] if k.split("|")[1] != "None" else "(형식 오류)", v]
        for k, v in f["by_group_basis"].items()
    ])
    L += [""]
    L += _table(["품질 표시", "설명", "식품 수"], [[f"`{k}`", FOOD_FLAGS.get(k, k), v] for k, v in f["flags"].items()])
    L += [""]
    L += _table(["성분", "결측률"], [[NUTRIENT_LABEL.get(k, k), f"{v}%"] for k, v in f["missing_pct"].items()])

    d = dishes
    L += ["", "## 7. 음식명 검색 정답 표본 (사진 분석 연계)", "",
          "사진 분석이 돌려줄 음식명으로 `search_dishes()`(음식 DB군 + 원재료성 보조 후보)를 돌린 결과입니다. "
          "정답은 `src/data/agetech_data/resources/dish_search_gold.json`"
          + (f"({d['checked_by']}, {d['checked_at']} 확인)" if d["checked_by"] else "(**사람 확인 전 초안**)")
          + "이며, 기준량 단위를 적은 항목은 1순위 후보의 단위까지 맞아야 일치로 셉니다. "
          "같은 음식명이 식품코드 계열별로 여러 행(100g 분석 / 100mL 산출)이라 점수가 같으면 100g 기준 행을 앞에 둡니다. "
          "최종 선택은 사용자 확인을 거칩니다.", "",
          f"- 정답 표본 {d['total']}건: **1순위 일치 {d['top1']}건**, 3순위 안 {d['top3']}건"
          + (f" (알려진 미해결 {d['known_miss']}건 포함 — 이유는 표 아래 목록)" if d["known_miss"] else "")
          + (f", **예상 밖 불일치: {', '.join(d['unexpected'])}**" if d["unexpected"] else ""),
          "- 정답이 '(후보 없음)'인 항목은 DB에 없는 음식·인식 실패 문구로, 후보를 내지 않아야 맞습니다(화면에서 음식명 직접 수정).",
          "- 찾은 방식: `name` 음식명 일치 · `family` 대표 음식명만 일치(세부 종류 확인) · `partial` 일부 일치 · "
          "`alias_code` 별칭표가 식품 지정 · `ingredient` 원재료성 보조 후보", ""]

    def _c(c):
        return f"{c['name']} ({c['basis_unit']}, {c['match']}, {c['score']:.2f})"

    L += _table(["입력", "1순위", "일치", "후보 2", "후보 3"], [
        [r["query"], _c(r["candidates"][0]) if r["candidates"] else "(후보 없음)",
         "O" if r["top1"] else ("3위 안" if r["top3"] else "X")]
        + [_c(c) for c in r["candidates"][1:3]] + ["-"] * (2 - len(r["candidates"][1:3]))
        for r in d["rows"]
    ])
    misses = [r for r in d["rows"] if r["known_miss"]]
    if misses:
        L += ["", "알려진 미해결 (사용자에게 음식명을 다시 묻거나 데이터를 더 찾아야 하는 항목):", ""]
        L += [f"- **{r['query']}** — {r['known_miss']}" for r in misses]

    L += ["", "## 8. 원칙과 제한", "",
          "- 원문 분량(`amount_text`)과 재료명은 바꾸지 않습니다. g 환산·매핑 결과는 근거와 함께 별도 필드로 둡니다.",
          "- 개수 단위(개·장·알 등)는 출처 있는 개당 중량표가 없어 환산하지 않습니다. 근거 자료가 생기면 추가합니다.",
          "- 부위·품종이 적히지 않은 재료(돼지고기·소고기 → 앞다리, 새우 → 대하 등)는 매핑표의 기본값으로 계산하며, 고른 이유는 매핑표 근거에 있습니다.",
          "- 저염 제품 항목이 없는 재료(저염된장·저염소금)는 일반 제품으로 근사해 **나트륨이 실제보다 많게** 잡힙니다.",
          "- 원천 식품과 보정 내역의 DB 적재는 구현되어 있습니다. 재료 매핑·계산 결과의 DB 연결은 후속 작업이며, 필드 정의는 `docs/data/food_nutrition_contract.md`를 따릅니다."]
    return "\n".join(L) + "\n"
