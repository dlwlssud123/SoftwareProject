"""갱신 수집본(collect.seasonal) + 레시피 → DB 제철 행 (backend app.jobs.import_seasonal 의 입력).

    from agetech_data.seasonal.revision import seasonal_rows
    rows = seasonal_rows(payload, recipes)      # payload = data/raw/seasonal/food_month.json

- 정제·연결은 seasonal.normalize.build_records 그대로다(docs/data/seasonal_contract.md 3·4절).
- recipes 는 레시피 계약 형식(recipe_id·name·category·quality.status·ingredients[name·amount_kind·unit·amount]).
  DB 적재 때는 백엔드가 **DB 활성 레시피 판본**으로 이 형식을 만들어 넘긴다 — 앱이 보여 주는 레시피와 연결이 같게.
- 행 하나 = (월, 식재료) 하나. 내용(normalized)과 연결(ingredients·recipes)을 나눠 해시한다:
  content_sha256 = 식재료 내용(상세 글 포함) 해시 — 제철 상세 글 RAG 청크를 붙일 때 이 값을 쓴다.
  links_sha256 = 레시피 재료명 연결·레시피 연결 해시 — 레시피나 연결 규칙만 바뀐 날을 구분한다.
- (월, 레시피 재료명)은 #18 seasonal_ingredients 의 유일 조건이다. 같은 달 두 식재료가 같은 재료명에 걸리면
  화면이 '이 재료가 이달 제철인가'에 답을 하나로 못 하므로 적재를 멈추고 규칙(resources/seasonal_terms.json)을 고친다.
"""

from __future__ import annotations

from agetech_data.collect.seasonal import DOCUMENTATION
from agetech_data.seasonal.normalize import build_records, load_rules
from agetech_data.snapshot import collected_on
from agetech_data.textutil import sha256_json

NORMALIZER_VERSION = "refresh-seasonal-v2"          # v2: 관련 레시피를 레시피 번호 순으로 고정
PROVIDER = "data.go.kr:15168024"                # 농식품 이달의 식재료
SOURCE_URL = DOCUMENTATION
LINK_FIELDS = ("matched_ingredients", "recipe_count", "recipes")


def food_content(record: dict) -> dict:
    """정제 레코드 → 식재료 내용(연결 빼고)."""
    return {k: v for k, v in record.items() if k not in LINK_FIELDS}


def content_sha256(record: dict) -> str:
    return sha256_json(food_content(record))


def seasonal_rows(payload: dict, recipes: list[dict], rules: dict | None = None) -> list[dict]:
    """수집본 + 레시피 → 식재료 행 목록 (월, 이름 순).

    행: source_id(m{월}-{순번}), 구조화 칸, normalized, content_sha256,
    ingredients [{name, term, kind}] (레시피 재료명 연결), recipes [{recipe_id, ingredients, weight_g, share}], links_sha256.
    """
    checked_on = collected_on(payload["meta"])
    records, _ = build_records(payload, recipes, rules or load_rules())
    rows, owner = [], {}
    for rec in records:
        ingredients = [{"name": i["name"], "term": i["term"], "kind": i["kind"]} for i in rec["matched_ingredients"]]
        links = [{"recipe_id": r["recipe_id"], "ingredients": r["ingredients"], "weight_g": r["weight_g"],
                  "share": r["share"]} for r in rec["recipes"]]
        for i in ingredients:
            key = (rec["month"], i["name"])
            if key in owner:
                raise ValueError(f"Seasonal rules map one recipe ingredient to two items in month {rec['month']}: "
                                 f"{owner[key]} and {rec['id']}")
            owner[key] = rec["id"]
        normalized = food_content(rec)
        rows.append({
            "source_id": rec["id"],
            "month": rec["month"],
            "fdmt_sn": rec["fdmt_sn"],
            "name": rec["name"],
            "terms": rec["terms"],
            "image_url": rec["image_url"],
            "detail": rec["detail"],
            "detail_status": rec["detail_status"],
            "official_related_recipes": rec["official_related_recipes"],
            "shopping_search_url": rec["shopping_search_url"],
            "source_url": SOURCE_URL,
            "checked_on": checked_on,
            "is_published": bool(rec["name"]),
            "normalized": normalized,
            "content_sha256": sha256_json(normalized),
            "ingredients": ingredients,
            "recipes": links,
            "links_sha256": sha256_json({"ingredients": ingredients, "recipes": links}),
        })
    ids = [r["source_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate seasonal item IDs")
    return rows
