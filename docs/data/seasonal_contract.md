# 이달의 식재료 필드 정의서 (데이터 → 서버·앱·AI 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 제철 추천·식단 API(이진녕), 제철 재료 화면·쿠팡 외부 링크(김찬형), AI 도우미 제철 설명 근거 |
| 원천 | 공공데이터포털 [농식품 이달의 식재료 목록정보](https://www.data.go.kr/data/15168024/openapi.do) (농촌진흥청 국립식량과학원, 이용허락범위 제한 없음, 무료) |
| 생성 명령 | `uv run python -m agetech_data.refresh --source seasonal_foods` → `uv run python -m agetech_data.seasonal.build` (레시피 계약 형식 전체 `data/processed/recipes_api_all.json` 필요) |
| 기준 | 기획서 "적용 월·공식 출처가 있는 제철 재료와 실제 레시피 재료를 매핑. 쿠팡은 재료명 기반 외부 검색/검토 링크용 필드만, 가격·재고·최저가를 수집/보장하지 않음" |
| 산출물 | `data/processed/seasonal_foods.json`(gitignore), `docs/data/seasonal_report.md`(월별 표·연결 규칙), `docs/data/samples/seasonal_sample.json`(11·12월 표본) |

## 1. 꼭 지킬 규칙

1. **월은 원천이 정한 '그달에 먹기 좋은 대표 식재료'다.** 지역·작황별 실제 출하 시기를 보장하지 않는다.
2. **상세 글(효능·섭취 방법 등)은 원문 그대로** 쓴다. 효능 문장은 건강 효과를 단정하는 말투가 있어, 화면·AI는 "~로 알려져 있다"처럼 옮기고 질병 치료처럼 말하지 않는다.
3. **쇼핑은 `shopping_search_url`(재료명 검색 링크)만.** 가격·재고·최저가는 수집하지 않는다.
4. **레시피 연결은 재료명 규칙으로 만든 추정**이다. 연결 근거(`matched_ingredients`의 `term`·`kind`)를 함께 넘긴다.

## 2. API (수집기가 쓰는 것)

| 기능 | 경로 | 요청 | 응답 주요 칸 |
|---|---|---|---|
| 이달의 식재료 목록 | `/foodList` | `srchMonth`(1~12), `format=json` | `fdmtSn`, `fdmtNm`, `fdmtImgUrl` |
| 이달의 식재료 상세 | `/foodCont` | `srchFdmtSn` | `stdInfo`(유래·구입 요령·손질법·기타), `ntkInfo`(섭취 방법·영양 성분 효능·관련 연구·소비량), `connRecipeList`(농진청 레시피) |

- 기본 주소 `https://apis.data.go.kr/1390803/allbaroFoodMonth`. 기능 경로는 포털 페이지에 묻힌 Swagger 명세에서 확인했다(2026-11-07, 페이지 글에는 없음).
- 정상 결과코드는 `"200"`(다른 포털 API의 `"00"`과 다름). 레시피·상차림 기능(`/recipeList`·`/recipeCont`·`/mealList`)은 쓰지 않는다.
- **한도: 하루 10,000회, 초당 10회.** 초당 한도를 넘으면 HTTP 429·코드 23(잠시 막힘) → 수집기는 호출 사이 0.5초, 23이면 15·30·45…초 쉬고 다시. 한 번 수집 = 목록 12 + 상세 약 123 = 약 135회(2~3분).

## 3. 레코드 — `data/processed/seasonal_foods.json`

최상위: `schema_version`, `input`(원문·레시피 파일 sha256), `summary`, `records[]`, `recipe_months`(`레시피 ID → [제철 월]`)

| 필드 | 형식 | 설명 |
|---|---|---|
| `id` | 문자열 | `m{월}-{fdmtSn}` (예: `m12-59`) |
| `month`, `fdmt_sn`, `name` | 정수, 문자열, 문자열 | 월, 원천 순번, 공식 이름(`돼지고기(수제 소시지)`, `풋콩/껍질콩` 그대로) |
| `terms` | 문자열 배열 | 연결에 쓴 이름(공백 제거, `/` 나눔, 괄호 뺌) |
| `image_url` | 문자열 | 원천 이미지 주소 |
| `detail` | 객체 | `origin`(유래), `purchase_tip`(구입 요령), `storage_prep`(손질·보관), `etc`, `intake`(섭취 방법), `efficacy`(영양 성분 효능), `research`(관련 연구), `consumption`(소비량) — 원문(`■` 글머리 포함) |
| `detail_status` | `ok`/`failed` | 상세 수집 결과 |
| `official_related_recipes` | 문자열 배열 | 농진청이 붙인 관련 레시피 이름(우리 레시피 DB와 별개) |
| `shopping_search_url` | 문자열 | `https://www.coupang.com/np/search?q=<재료명>` — 검색 링크만 |
| `matched_ingredients` | 객체 배열 | 연결된 레시피 재료명 `{name, term, kind: official|alias, recipes}` |
| `recipe_count`, `recipes` | 정수, 객체 배열 | 연결 레시피(hold 제외) `{recipe_id, name, category, quality_status, ingredients, weight_g, share}` — `share` 높은 순 |

- `share` = 레시피 재료 중 g으로 적힌 무게 합에서 이 제철 재료가 차지하는 비율(물·육수는 뺌). 주재료(시금치나물)와 고명(잣 몇 g)을 가른다. g 분량이 없으면 null.
- 레시피 쪽은 `recipe_months`로 "이 레시피는 몇 월 제철 재료가 들어감"을 바로 찾는다.

## 4. 연결 규칙 (`src/data/agetech_data/resources/seasonal_terms.json`)

- 공식 이름의 `/`는 둘로 나누고, 괄호는 설명으로 본다.
- **한 글자 이름**(무·배·감·쌀·잣·팥·조·쑥·밤·귤)은 재료명이 정확히 같거나 별칭일 때만 — 무염버터·배추·감자·조개·쑥갓이 걸리지 않게.
- 두 글자 이상은 재료명에 들어 있으면 맞추되, **제외어**가 있으면 뺀다(고추장·고추냉이·고춧가루, 토마토케첩·소스, 감자전분, 사과식초, 진달래, 2가지색, 미더덕, 아몬드우유 …).
- **겹치는 이름은 긴 쪽이 이긴다**: 단호박 → 8월(10월 호박 아님), 방울토마토 → 3월, 옥수수 → 8월(9월 수수 아님). 긴 쪽이 제외어로 빠져도 그 안의 짧은 이름은 살리지 않는다(옥수수전분 → 수수 아님). 겹치지 않으면 둘 다(깻잎장아찌 → 2월 깻잎·1월 장아찌).
- **별칭**: 계란→달걀, 쇠고기→소고기, 키위→참다래, 수삼→인삼, 닭다리살 등→닭고기, 단감·홍시→감, 견과류·건과일 분류명 → 대표 견과·말린 과일 등. 근거(`reason`)를 같이 적었다.
- 연결 안 된 식재료 14개(한라봉, 머위순, 늙은 호박, 모과 등)는 같은 이름으로 쓰인 레시피가 없다. 보고서 3절에 비슷한 재료명을 참고로 적었고(머위순 ↔ 머위대), 별칭에 넣을지는 사람이 정한다.

## 5. 쓰는 법

```python
import json
data = json.load(open("data/processed/seasonal_foods.json", encoding="utf-8"))
december = [r for r in data["records"] if r["month"] == 12]
top = [(r["name"], [x["name"] for x in r["recipes"][:3]]) for r in december if r["recipe_count"]]
months_of = data["recipe_months"].get("28", [])     # 레시피 28이 제철인 달
```

- 제철 추천: 그달 `records`에서 `share`가 높은(주재료인) 레시피를 고르고, 사용자 알레르기·레시피 품질(`quality_status`)은 기존 추천 규칙대로 거른다.
- AI 도우미: 제철 재료 질문의 근거는 RAG 청크 `source_type = 'seasonal'`(11/13)로 검색한다. 상세 글(유래·영양·고르는 법·보관·먹는 법·농진청 관련 레시피)을 식재료마다 개요 / 고르기·보관 / 먹는 법으로 나눠 넣었다(`rag_index_contract.md` 3절).

## 6. 알려진 제한

- 월별 식재료 9~11개로 많지 않다. 원천 항목(순번)은 달마다 다르지만, 돼지고기는 1월(수제 소시지)·4월 두 번 나와 돼지고기 레시피는 두 달 모두 제철로 잡힌다.
- 레시피 재료명은 원문 표기라 같은 재료가 여러 이름으로 적혀 있다(쇠고기 다진것·다진 쇠고기 …). 규칙은 그 표기를 그대로 맞추고, 새 표기가 생기면 규칙 파일에 더한다.
- 상세 글은 원천 기준이고 우리가 고치지 않는다(오탈자 포함).

## 7. DB 적재

- 식재료는 `seasonal_foods`, 레시피 재료명 매핑은 #18 `seasonal_ingredients`(+ 연결 근거 칸), 레시피 연결(`share` 포함)은 `seasonal_recipe_links`에 둔다(Alembic `20261111_01`). 자세한 것은 [`facility_seasonal_db_import.md`](facility_seasonal_db_import.md).
- DB 적재 때 레시피 연결은 이 정의서 3절과 같은 규칙으로, **DB 활성 레시피 판본**을 대상으로 계산한다(보완표가 반영된 판본이라 파일 기준보다 연결이 조금 많을 수 있다 — 레시피 33·36).
