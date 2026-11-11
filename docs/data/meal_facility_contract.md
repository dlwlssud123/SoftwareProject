# 무료급식소·경로식당 필드 정의서 (데이터 → 서버·앱 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 시설 API(이진녕), 식단추천 홈 '오늘 밥하기 힘들어요' → 시설 목록·지도(김찬형), 관리자 자료 상태(김민찬) |
| 원천 | 공공데이터포털 [전국무료급식소표준데이터](https://www.data.go.kr/data/15013107/standard.do) (지자체 제공, 무료, 활용신청 필요) |
| 생성 명령 | `uv run python -m agetech_data.refresh --source meal_facilities` → `uv run python -m agetech_data.facilities.build` |
| 기준 | 기획서 ADD-06 "공식 자료의 시범 지역 시설명·주소·대상·시간/요일·문의처·기준일 안내. 위치 허용 시 가까운 순, 거부 시 지역 선택. 자료 누락/휴무 가능성과 문의 경로 표시. 가깝다는 이유로 이용 자격·당일 운영을 확정하지 않음" |
| 산출물 | `data/processed/meal_facilities.json`(gitignore), `docs/data/meal_facility_report.md`, `docs/data/samples/meal_facility_sample.json`(대구 남구 조회 표본) |

## 1. 꼭 지킬 규칙

1. **이용 자격·당일 운영을 확정하지 않는다.** 결과마다 `cautions`(확인할 점)와 자료 기준일을 보여 주고, "이용 전 전화로 확인"을 함께 안내한다.
2. **원문을 바꾸지 않는다.** 요일·시간·대상은 읽을 수 있는 만큼만 따로 풀고(`days`·`meals`·`targets`), 원문(`days_raw`·`time_raw`·`target_raw`)을 같이 준다. 못 읽은 것은 원문을 그대로 보여 준다.
3. **식별자는 `facility_id`**(`FM` + 해시 10자리). 같은 시설을 여러 지자체·기준일로 올린 중복은 합친 뒤의 ID다. 원천에는 ID가 없다.
4. **지역은 (시도, 시군구) 쌍.** 주소에서 정하고 복지와 같은 시도명(`welfare.regions`, 2026-07-01 전남광주통합특별시)으로 맞춘다.
5. **기본 조회에서 운영 종료(`operation_ended`)·미운영(`not_operating`)은 뺀다.**

## 2. 시설 레코드 — `data/processed/meal_facilities.json`

최상위: `schema_version`, `as_of`(판단 기준일), `input`(원문 경로·sha256·수집 메타), `summary`, `records[]`

| 필드 | 형식 | 원천 태그 | 설명 |
|---|---|---|---|
| `facility_id` | 문자열 | — | 시설 ID. 같은 장소의 다른 급식 일정은 끝에 `-2`, `-3` |
| `name`, `operator` | 문자열 | `fcltyNm`, `operInstitutionNm` | 시설명, 운영 기관 |
| `ctpv`, `sgg` | 문자열·null | 주소에서 | 정규화 시도·시군구. 주소가 없으면 제공 지자체로(`region_from_provider`), 주소에서 시군구만 못 읽으면 같은 시도의 제공 지자체 시군구로(`sgg_from_provider`) |
| `address_road`, `address_lot` | 문자열·null | `rdnmadr`, `lnmadr` | 도로명·지번 주소 원문 |
| `phone` | 문자열·null | `phoneNumber` | 전화번호 |
| `place` | 문자열·null | `mlsvPlace` | 급식 장소 |
| `targets`, `target_raw` | 배열, 문자열 | `mlsvTrget` | 대상(`+`·`,`로 나눔), 원문 |
| `days`, `days_raw` | 배열·null, 문자열 | `mlsvDate` | 급식 요일 `["수","목"]`(월~일 순). `월~금`, `주 2회(화, 목)`, `매주 월~금요일`도 읽음. 못 읽으면 null |
| `meals`, `time_raw` | 배열, 문자열 | `mlsvTime` | `[{"meal": "중식", "start": "11:20", "end": "12:20"}]`. 시작만 있으면 `end` null(`중식(12:00)`), 끼니 이름이 없으면 `meal` null |
| `open_date`, `close_date` | `YYYY-MM-DD`·null | `operOpenDate`, `operCloseDate` | 운영 기간 |
| `latitude`, `longitude` | 실수·null | `latitude`, `longitude` | 국내 범위(위도 33~39, 경도 124~132) 밖이면 null + `coords_invalid` |
| `reference_date` | `YYYY-MM-DD`·null | `referenceDate` | **원천 자료 기준일** — 화면에 "자료 기준일"로 표시 |
| `provider`, `provider_code` | 문자열 | `insttNm`, `insttCode` | 자료를 올린 지자체 |
| `source_fetched_at` | ISO 시각 | — | 수집 시각(UTC) |
| `raw_sha256`, `row_ids` | 문자열, 배열 | — | 원문 해시, 수집 행 ID(`row_id`, 합친 행 포함) |
| `merged_from` | 객체 배열 | — | 합친 중복 행 `{provider, provider_code, reference_date, row_ids}` |
| `quality_flags` | 문자열 배열 | — | 아래 |

| `quality_flags` | 의미 | 화면 안내(`query.CAUTIONS`) |
|---|---|---|
| `reference_stale` | 기준일이 365일 넘음 | 지금도 운영하는지 전화로 확인 |
| `operation_ended` | 운영 종료일이 지남 | 기본 조회에서 뺌 |
| `not_operating` | 원천 요일 칸이 '미운영' | 기본 조회에서 뺌 |
| `not_started` | 운영 시작일 전 | 운영 시작일 전 |
| `coords_missing`, `coords_invalid` | 좌표 없음·이상 | 지도·거리 계산에서 빠짐 |
| `phone_missing` | 전화번호 없음 | 운영 기관·제공 지자체로 문의 |
| `days_unparsed`, `time_unparsed` | 요일·시간을 읽지 못함 | 원문 확인 |
| `includes_delivery` | 반찬·도시락 배달 포함 | 찾아가는 식당이 아닐 수 있음 |
| `duplicate_merged` | 다른 지자체·기준일 중복 등록을 합침 | — |
| `address_missing`, `region_from_provider`, `sgg_from_provider`, `region_unknown`, `invalid_date:<필드>` | 주소·지역·날짜 문제 | — |

### 2.1 중복 등록 합치기

- 같은 (시설명, 주소)를 **다른 지자체가 올렸거나 기준일만 다르면** 같은 시설로 보고, 기준일이 가장 최신인 행 하나만 남긴다(같으면 현재 시도명을 쓰는 지자체). 나머지는 `merged_from`에 남는다. 대부분 통합 전 `광주광역시`와 통합 후 `전남광주통합특별시`가 같은 시설을 각각 올린 경우다.
- **같은 지자체가 한 장소의 다른 급식 요일·시간을 올렸으면** 다른 급식 일정으로 보고 모두 남긴다(예: 조식·석식을 따로 올린 시설).

## 3. 조회 (서버 연동용)

```python
from agetech_data.facilities.normalize import normalize_payload
from agetech_data.facilities.query import facilities_for

records = normalize_payload(payload)                  # payload = data/raw/facilities/free_meal.json
region, out = facilities_for(records, "대구", "남구")  # 위치 거부: 앱 프로필 시도·시군구 그대로
region, out = facilities_for(records, "대구", "남구", lat=35.849, lon=128.592, radius_km=3)  # 위치 허용
# out = [{"facility": MealFacility, "match": "district"|"province"|"nearby"|"district_no_coords",
#         "distance_km": 1.1 | None, "cautions": ["…", "급식 대상·요일·시간은 바뀔 수 있으니 이용 전 시설에 전화로 확인"]}]
```

- **위치 거부**: 내 시군구(`district`) → 같은 시도의 다른 시군구(`province`) 순, 각각 이름순.
- **위치 허용**: 반경 `radius_km`(기본 5km) 안의 좌표 있는 시설을 가까운 순으로 — 시도·시군구 경계와 무관(`nearby`). 좌표가 없는 내 시군구 시설은 맨 뒤(`district_no_coords`).
- `cautions` 마지막 줄은 항상 "급식 대상·요일·시간은 바뀔 수 있으니 이용 전 시설에 전화로 확인"이다.

## 4. 시범 지역 (대구광역시 남구, 11/07 잠정)

- 원천에 남구 시설은 **2곳**: 남구종합사회복지관(수·목 중식 11:20~12:20, 결식노인·저소득층·장애인 회원제), 희망의집(화·금·토 중식 11:00~12:30, 결식노인·저소득층·장애인·노숙자). 기준일 2026-07-13, 좌표·전화 있음.
- 위치 허용 시 남구 2곳 외에 반경 3km 안 중구·달서구·북구 시설도 나온다(표본 `nearby_3km`).
- 지자체가 올리지 않은 노인복지관 경로식당 등은 빠져 있을 수 있다 → **시연 전 남구청 노인복지 담당에 확인**한다.

## 5. 알려진 제한

- 원천이 지자체별로 연 1회 안팎 갱신된다(기준일 2022~2026 섞임). 갱신은 다른 공공데이터와 같은 `refresh`로 돌고, 실패하면 이전 판본을 유지한다.
- 요일·시간 원문 표기가 제각각이라 약 6%·3%는 읽지 못한다(보고서 5절). 원문을 그대로 보여 준다.
- 표준데이터에 시설 ID가 없어 시설명·주소가 바뀌면 `facility_id`도 바뀐다.

## 6. DB 적재

- 표는 #18 `meal_facilities`에 원천 칸(Alembic `20261111_01`)을 더해 쓴다. 칸 대응·게시 규칙·명령은 [`facility_seasonal_db_import.md`](facility_seasonal_db_import.md).
- 요약: `source_id` = `facility_id`, `checked_on` = 수집 날짜(KST), `reference_date` = 원천 기준일, `hours_text` = 요일 원문 + 시간 원문, `quality_flags` 그대로, 정제 레코드 전체는 `normalized`. 운영 종료·미운영은 비게시.
