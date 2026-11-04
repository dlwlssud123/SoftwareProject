"""레시피 원천 필드 누락과 영양 기준량 점검.

COOKRCP01 명세(식품안전나라 Open API 출력값, 2026-11-05 확인)
- `INFO_WGT`만 '중량(1인분)'으로 기준량이 적혀 있다.
- `INFO_ENG`·`INFO_CAR`·`INFO_PRO`·`INFO_FAT`·`INFO_NA`는 '열량·탄수화물·단백질·지방·나트륨'으로만 적혀 있고
  기준량·단위 표기가 없다. 값 범위로 보아 kcal·g·g·g·mg로 읽고, 기준량은 '1인분(명세 미표기)'으로 둔다.

값을 고치거나 채우지 않는다. 숫자로 읽은 값과 점검 결과만 덧붙인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agetech_data.recipes.issues import Issue
from agetech_data.textutil import is_blank

# 명세 순서. 조리 단계(MANUALnn·MANUAL_IMGnn)는 steps.py 에서 본다.
SOURCE_FIELDS: dict[str, str] = {
    "RCP_SEQ": "일련번호", "RCP_NM": "메뉴명", "RCP_WAY2": "조리방법", "RCP_PAT2": "요리종류",
    "INFO_WGT": "중량(1인분)", "INFO_ENG": "열량", "INFO_CAR": "탄수화물", "INFO_PRO": "단백질",
    "INFO_FAT": "지방", "INFO_NA": "나트륨", "HASH_TAG": "해쉬태그", "ATT_FILE_NO_MAIN": "이미지경로(소)",
    "ATT_FILE_NO_MK": "이미지경로(대)", "RCP_PARTS_DTLS": "재료정보", "RCP_NA_TIP": "저감 조리법 TIP",
}
# 원천 필드 → 가공 키 (단위는 키 이름에)
NUTRIENTS: dict[str, str] = {
    "INFO_ENG": "energy_kcal", "INFO_CAR": "carbohydrate_g", "INFO_PRO": "protein_g",
    "INFO_FAT": "fat_g", "INFO_NA": "sodium_mg",
}
NUTRITION_BASIS = "per_serving_unverified"  # 1인분으로 보이나 명세에 기준량 표기 없음
# 탄수화물·단백질 4kcal/g, 지방 9kcal/g 로 계산한 열량 ÷ 원문 열량이 이 범위 밖이면 원문 영양값 이상 의심
ENERGY_RATIO_RANGE = (0.5, 2.0)
IMAGE_FIELDS = ("ATT_FILE_NO_MAIN", "ATT_FILE_NO_MK")

_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_SERVINGS = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*인분\s*\]")


def missing_fields(row: dict) -> list[str]:
    """비어 있는 원천 필드 (명세 순서)."""
    return [f for f in SOURCE_FIELDS if is_blank(row.get(f))]


def read_number(v) -> float | None:
    """'1,670.5' → 1670.5. 비었거나 숫자가 아니면 None."""
    s = str(v if v is not None else "").replace(",", "").strip()
    return float(s) if _NUMBER.match(s) else None


@dataclass
class NutritionCheck:
    serving_weight_g: float | None          # INFO_WGT (1인분 중량)
    ingredient_servings: float | None       # 재료 원문 '[N인분]' 표기 (재료 분량 기준), 없거나 여러 값이면 None
    values: dict[str, float | None]         # energy_kcal … sodium_mg
    energy_from_macros_kcal: float | None
    energy_ratio: float | None              # 계산 열량 ÷ 원문 열량
    issues: list[Issue] = field(default_factory=list)

    @property
    def suspect(self) -> bool:
        return any(i.code == "nutrition_energy_mismatch" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "basis": NUTRITION_BASIS,
            "serving_weight_g": self.serving_weight_g,
            "ingredient_servings": self.ingredient_servings,
            **self.values,
            "energy_from_macros_kcal": self.energy_from_macros_kcal,
            "energy_ratio": self.energy_ratio,
            "suspect": self.suspect,
        }


def check_nutrition(row: dict) -> NutritionCheck:
    issues: list[Issue] = []
    values: dict[str, float | None] = {}
    for src, key in NUTRIENTS.items():
        values[key] = read_number(row.get(src))
        if values[key] is None:
            issues.append(Issue("nutrition_value_invalid", {"field": src, "value": row.get(src)}))

    weight = read_number(row.get("INFO_WGT"))
    if weight is None:
        issues.append(Issue("serving_weight_missing"))

    stated = sorted({float(m) for m in _SERVINGS.findall(row.get("RCP_PARTS_DTLS") or "")})
    if stated:
        issues.append(Issue("ingredient_servings_stated", {"servings": stated}))
    servings = stated[0] if len(stated) == 1 else None

    from_macros = ratio = None
    c, p, f, e = (values[k] for k in ("carbohydrate_g", "protein_g", "fat_g", "energy_kcal"))
    if None not in (c, p, f, e):
        from_macros = round(4 * c + 4 * p + 9 * f, 1)
        if e > 0:
            ratio = round(from_macros / e, 2)
        lo, hi = ENERGY_RATIO_RANGE
        if (ratio is not None and not lo <= ratio <= hi) or (e == 0 and from_macros > 0):
            issues.append(Issue("nutrition_energy_mismatch",
                                {"energy_kcal": e, "energy_from_macros_kcal": from_macros, "ratio": ratio}))
    return NutritionCheck(weight, servings, values, from_macros, ratio, issues)


ENERGY_BUCKETS = ("0.8~1.25", "0.5~0.8", "1.25~2", "0.5 미만", "2 초과", "원문 열량 0", "계산 불가")


def energy_bucket(n: NutritionCheck) -> str:
    """계산 열량 ÷ 원문 열량 구간 (보고서 집계용)."""
    r = n.energy_ratio
    if r is None:
        return "원문 열량 0" if n.values.get("energy_kcal") == 0 else "계산 불가"
    if r < 0.5:
        return "0.5 미만"
    if r < 0.8:
        return "0.5~0.8"
    if r <= 1.25:
        return "0.8~1.25"
    return "1.25~2" if r <= 2 else "2 초과"


def field_issues(row: dict) -> list[Issue]:
    """영양 외 원천 필드 점검 (화면 표시에 영향이 있는 것만)."""
    return [Issue("image_missing")] if all(is_blank(row.get(f)) for f in IMAGE_FIELDS) else []
