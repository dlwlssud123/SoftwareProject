# 복지 데이터 필드 정의서 (데이터 → 서버·앱 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 복지 API(이진녕), 복지 화면·지역 선택(김찬형), 관리자 검수(김민찬) |
| 원천 | 한국사회보장정보원 중앙부처 복지서비스·지자체 복지서비스 (공공데이터포털), 노년층 `lifeArray=006` |
| 생성 명령 | `uv run python -m agetech_data.refresh --source welfare_central welfare_local` → `uv run python -m agetech_data.welfare.build` |
| 기준 | 기획서 CORE-05 "전국·지역 사업을 구분하고 관련 제도·지원 기준·공식 경로 안내", 11.3 "출처·확인일·미확인 필드 표시" |

## 1. 꼭 지킬 규칙

1. **수급 자격을 판정하지 않는다.** 지역이 맞는 사업을 "확인해 볼 만한 사업"으로 안내하고, 대상·기준 문장은 원문 그대로 보여 준다.
2. **식별자는 `serv_id`(복지로 `servId`, 예: `WLF00003191`)다.**
3. **지역은 (시도, 시군구) 쌍이다.** `중구`·`남구`처럼 같은 시군구 이름이 여러 시도에 있다.
4. **2026-07-01 광주광역시·전라남도 → `전남광주통합특별시`.** 원천 데이터에는 옛 이름이 없다. 옛 이름 입력은 `normalize_ctpv()`가 통합특별시로 바꾼다. 앱 지역 선택 목록에는 아직 `광주광역시`·`전라남도`가 따로 있어, 그대로 보내도 동작하지만 화면 표기는 앱 쪽에서 정해야 한다.
5. **상세가 없을 수 있다.** 개발계정 상세 호출 한도 때문에 상세는 나눠 받는다(`detail_status`). 빠진 필드는 `unverified_fields`에 있으니 "미확인"으로 표시하고 공식 링크·문의처로 안내한다.
6. **확인 시각을 함께 보여 준다.** 목록 확인 시각 `source_fetched_at`, 상세 확인 시각 `detail_fetched_at`, 원천 최종 수정일 `last_modified`.

## 2. 통합 레코드 — `data/processed/welfare_elderly.json`

최상위: `schema_version`, `input`(원문 경로·sha256·수집 메타), `summary`, `records[]`

| 필드 | 형식 | 원천 태그 (중앙 / 지자체) | 설명 |
|---|---|---|---|
| `serv_id` | 문자열 | `servId` | 식별자 |
| `source` | `central`/`local` | | 원천 |
| `scope` | `national`/`province`/`district` | | 전국(중앙부처) / 시도 전체(시군구 없음) / 시군구 |
| `ctpv`, `sgg` | 문자열·null | `ctpvNm`, `sggNm` | 정규화한 시도·시군구 (중앙은 null). 원천 시군구가 `-`처럼 글자 없는 자리 표시면 null(시도 전체) |
| `ctpv_raw`, `sgg_raw` | 문자열·null | | 원천 표기 그대로 |
| `name`, `summary` | 문자열 | `servNm`, `servDgst` | 서비스명, 요약 |
| `target_detail` | 문자열·null | `tgtrDtlCn` / `sprtTrgtCn` | 지원 대상 (상세) |
| `selection_criteria` | 문자열·null | `slctCritCn` | 선정 기준 (상세) |
| `benefits` | 문자열·null | `alwServCn` | 지원 내용 (상세) |
| `apply_detail` | 문자열·null | `aplyMtdCn` | 신청 방법 설명 (지자체 상세) |
| `apply_methods` | 문자열 배열 | `aplyMtdNm` | 신청 방법 구분 (예: 방문, 전화) |
| `online_apply` | true/false/null | `onapPsbltYn` | 온라인 신청 가능 (중앙) |
| `support_cycle` | 문자열·null | `sprtCycNm` | 지원 주기 (월, 1회성 …) |
| `provision_types` | 문자열 배열 | `srvPvsnNm` | 제공 유형 (현금지급, 현물지급 …) |
| `life_stages`, `target_groups`, `themes` | 문자열 배열 | `lifeArray`·`trgterIndvdlArray`·`intrsThemaArray` / `…NmArray` | 생애주기, 대상 특성(저소득·장애인 …), 관심 주제 |
| `department` | 문자열·null | — / `bizChrDeptNm` | 담당 부서 (지자체) |
| `ministry`, `ministry_office`, `main_contact` | 문자열·null | `jurMnofNm`, `jurOrgNm`, `rprsCtadr` | 소관 부처·부서, 대표 문의처 (중앙) |
| `detail_url` | 문자열 | `servDtlLink` | 복지로 공식 안내 링크 |
| `criteria_year` | 문자열·null | `crtrYr` | 기준 연도 (중앙 상세) |
| `last_modified`, `first_registered` | `YYYY-MM-DD`·null | `lastModYmd`, `svcfrstRegTs` | 원천 최종 수정일, 최초 등록일 |
| `period_start`, `period_end` | `YYYY-MM-DD`·null | `enfcBgngYmd`, `enfcEndYmd` | 시행 기간 (지자체 상세) |
| `contacts`, `homepages`, `apply_guides`, `laws`, `forms` | 객체 배열 | 상세 XML `inqplCtadrList`·`inqplHmpgReldList`·`applmetList`·`baslawList`·`basfrmList` | 문의처·관련 누리집·신청 안내(중앙만)·근거 법령·서식. 항목 형식은 아래 2.1 |
| `detail_status` | `fresh`/`cached`/`stale`/`pending` | | 상세 상태 (갱신 안내 참고) |
| `detail_fetched_at`, `source_fetched_at` | ISO 시각·null | | 상세·목록 확인 시각 (UTC) |
| `raw_sha256` | 문자열 | | 원문 항목 해시 |
| `unverified_fields` | 문자열 배열 | | 안내에 필요한데 아직 확인 못 한 필드 |
| `quality_flags` | 문자열 배열 | | `detail_pending`, `detail_stale`, `period_ended`, `no_official_link`, `unknown_ctpv`, `homepage_not_url`, `invalid_date:<필드>` |

텍스트는 HTML 엔티티·`<br>`(줄바꿈)·태그만 정리하고 내용은 바꾸지 않는다. 원문은 `data/raw/welfare/`에 그대로 있다.

### 2.1 목록형 항목 (`contacts` 등)

원천은 같은 목록이라도 하위 태그가 다르다(중앙 `servSeDetailNm`·`servSeDetailLink`, 지자체 `wlfareInfoReldNm`·`wlfareInfoReldCn`). 서버·RAG는 공통 키만 쓰면 된다.

```json
{"name": "경산시 노인장애인과", "value": "053-810-5000", "raw": {"wlfareInfoDtlCd": "010", "wlfareInfoReldNm": "…", "wlfareInfoReldCn": "…"}}
{"name": "치매안심센터", "value": "gbgs.nid.or.kr/", "url": "https://gbgs.nid.or.kr/", "link_status": "scheme_added", "raw": {…}}
```

| 키 | 설명 |
|---|---|
| `name` | 기관·부서명, 법령명, 서식 파일명, 신청 안내 구분(중앙 `apply_guides`: 신청기관·조사기관·결정기관·지급기관·사후관리기관) |
| `value` | 원문 값 그대로. 문의처는 대부분 전화번호지만 약 1.5%는 "주소지 읍·면·동 주민센터" 같은 안내 문구이고, 이름만 있고 값이 없는 것도 있다. 법령은 `null` |
| `url`, `link_status` | `homepages`·`forms`에만 있음. `ok` 원문이 http(s) 주소 / `scheme_added` 도메인만 있어 `https://`를 붙임 / `not_url` 주소가 아님(예: "목포시청", "-") → `url`은 `null`, 레코드에 `homepage_not_url` 표시 |
| `raw` | 원천 하위 태그 그대로 (추적용) |

- 이름·값 없이 구분 코드만 있는 항목은 뺀다.
- 중앙은 신청 방법 설명(`apply_detail`)이 없고 `apply_guides`에 단계별 기관 안내가 있다. 지자체는 `apply_guides`가 없다.
- 원문 오타는 고치지 않는다. 예: `https;//www.ulleung.go.kr`, `강원특별자치도청(www.provin.gangwon.kr)`은 `not_url`로 남는다.
- 전체 1,468건 상세 확인(11/06) 기준: 서식 링크 1,644개는 모두 `ok`, 누리집은 `ok` 208 / `scheme_added` 79 / `not_url` 20. 지자체 신청 방법 설명(`apply_detail`)이 원천에 없는 사업은 1,338건 중 258건.

## 3. 지역별 조회 (서버 연동용)

```python
from agetech_data.welfare.normalize import normalize_payload
from agetech_data.welfare.query import services_for

records = normalize_payload(central_payload, "central") + normalize_payload(local_payload, "local")
query, matches = services_for(records, "광주광역시", "광산")   # 앱 프로필의 시도·시군구 문자열 그대로
# query.ctpv="전남광주통합특별시", query.sgg="광산구", query.notes=["'광주광역시' → … (2026-07-01 통합)"]
# matches = [{"record": WelfareRecord, "match": "district"|"province"|"national", "reason": "…"}]
```

- 순서: 내 시군구 → 내 시도 전체 → 전국. 같은 범위 안에서는 상세가 있는 것을 먼저 둔다.
- 기본으로 시행 기간이 끝난 사업(`period_ended`)은 뺀다(`include_ended=True`로 포함).
- 시군구 입력은 공백·`시/군/구` 접미사 생략을 허용하고, 같은 시도 안에서 하나로 정해질 때만 맞춘다. 못 맞추면 `notes`에 이유를 남기고 시도 전체·전국 사업만 준다.
- `reason`은 지역이 맞는 이유일 뿐 자격 판단이 아니다. 화면에는 "지원 대상·기준은 원문과 문의처로 확인" 안내를 함께 둔다.

## 4. 알려진 제한

- 상세는 첫 갱신 후 이틀 동안 일부 `pending`이다(중앙 100/일, 지자체 1,000/일, 매일 00시 KST 초기화). 이번 수집은 11/05·11/06 두 번에 나눠 전부 받았다. 한도를 늘리려면 공공데이터포털 운영계정 전환이 필요하다.
- 중앙부처 사업은 지역 구분이 없어 모두 `national`이다.
- 통합특별시의 시도 전체 사업(`sgg` 없음) 중에는 통합 전 광주·전남 단위 사업이 섞여 있을 수 있다. 원천이 구분하지 않으므로 담당 부서(`department`)로 확인한다.
- 생애주기에 노년이 포함된 사업만 받았으므로, 다른 생애주기와 함께 쓰는 사업(예: 장애인 가정 지원)도 포함된다.
