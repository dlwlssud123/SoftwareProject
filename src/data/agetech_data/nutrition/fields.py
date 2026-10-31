"""식품영양성분DB 03 판본 응답 필드 → 정제 레코드 키.

근거: resources/foodntr_v03_fields.json (공공데이터포털 Open API 명세에서 2026-10-31 추출).
AMT_NUM 번호는 판본마다 바뀐 적이 있으므로, 아래 표의 공식 항목명이 명세와 같은지 테스트로 확인한다.
(예: 03 판본에서 AMT_NUM22=비타민 D, 23=콜레스테롤, 24=포화지방산)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
SPEC_FILE = RESOURCES / "foodntr_v03_fields.json"

# 정제 레코드 키: (원본 필드, 명세의 공식 항목명). 앱·추천·식사 기록에서 쓰는 성분만 정제한다.
NUTRIENT_FIELDS: dict[str, tuple[str, str]] = {
    "energy_kcal": ("AMT_NUM1", "에너지(kcal)"),
    "water_g": ("AMT_NUM2", "수분(g)"),
    "protein_g": ("AMT_NUM3", "단백질(g)"),
    "fat_g": ("AMT_NUM4", "지방(g)"),
    "ash_g": ("AMT_NUM5", "회분(g)"),
    "carbohydrate_g": ("AMT_NUM6", "탄수화물(g)"),
    "sugars_g": ("AMT_NUM7", "당류(g)"),
    "fiber_g": ("AMT_NUM8", "식이섬유(g)"),
    "calcium_mg": ("AMT_NUM9", "칼슘(mg)"),
    "iron_mg": ("AMT_NUM10", "철(mg)"),
    "phosphorus_mg": ("AMT_NUM11", "인(mg)"),
    "potassium_mg": ("AMT_NUM12", "칼륨(mg)"),
    "sodium_mg": ("AMT_NUM13", "나트륨(mg)"),
    "vitamin_a_ug_rae": ("AMT_NUM14", "비타민 A(μg RAE)"),
    "vitamin_b1_mg": ("AMT_NUM18", "비타민 B1(mg)"),
    "vitamin_b2_mg": ("AMT_NUM19", "비타민 B2(mg)"),
    "niacin_mg": ("AMT_NUM20", "니아신(mg)"),
    "vitamin_c_mg": ("AMT_NUM21", "비타민 C(mg)"),
    "vitamin_d_ug": ("AMT_NUM22", "비타민 D(μg)"),
    "cholesterol_mg": ("AMT_NUM23", "콜레스테롤(mg)"),
    "sat_fat_g": ("AMT_NUM24", "포화지방산(g)"),
    "trans_fat_g": ("AMT_NUM25", "트랜스지방산(g)"),
    "salt_equiv_g": ("AMT_NUM156", "식염상당량(g)"),
    "refuse_pct": ("AMT_NUM157", "폐기율(%)"),
}

# 정제 레코드 키: 원본 필드 (텍스트)
TEXT_FIELDS: dict[str, str] = {
    "food_code": "FOOD_CD",
    "name": "FOOD_NM_KR",
    "db_group": "DB_GRP_NM",          # 음식 / 원재료성 / 가공식품
    "db_class": "DB_CLASS_NM",        # 품목대표 / 상용제품
    "category1": "FOOD_CAT1_NM",      # 식품대분류명
    "ref_name": "FOOD_REF_NM",        # 대표식품명
    "basis_text": "SERVING_SIZE",     # 영양성분함량기준량 (예: 100g, 100mL)
    "food_weight_text": "Z10500",     # 식품중량
    "serving_ref_text": "NUTRI_AMOUNT_SERVING",  # 1회 섭취참고량
    "source_name": "SUB_REF_NAME",    # 출처명
    "create_method": "CRT_MTH_NM",    # 데이터생성방법명 (분석/산출/수집)
    "research_date": "RESEARCH_YMD",  # 데이터생성일자
    "update_date": "UPDATE_DATE",     # 데이터수정일자
}


@lru_cache
def official_labels() -> dict[str, str]:
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))["fields"]
