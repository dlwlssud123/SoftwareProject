"""시도·시군구 이름 정규화.

기준(2026-11-01): 원천 복지 데이터의 시도명 16개. 2026-07-01 광주광역시와 전라남도가 통합해
'전남광주통합특별시'가 출범했고, 원천 데이터에는 '광주광역시'·'전라남도'가 더 이상 나오지 않는다.
앱·사용자가 옛 이름이나 줄임말을 넣어도 현재 시도명으로 바꿔 찾는다.

시군구는 시도 안에서만 의미가 있다('중구'·'남구' 등은 여러 시도에 있음). 항상 (시도, 시군구) 쌍으로 다룬다.
"""

from __future__ import annotations

import re

from agetech_data.textutil import nfc

CTPV = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전남광주통합특별시",
    "경상북도", "경상남도", "제주특별자치도",
)
MERGED = "전남광주통합특별시"
# 옛 이름·줄임말 → 현재 시도명
CTPV_ALIASES = {
    "서울": "서울특별시", "서울시": "서울특별시",
    "부산": "부산광역시", "부산시": "부산광역시",
    "대구": "대구광역시", "대구시": "대구광역시",
    "인천": "인천광역시", "인천시": "인천광역시",
    "대전": "대전광역시", "대전시": "대전광역시",
    "울산": "울산광역시", "울산시": "울산광역시",
    "세종": "세종특별자치시", "세종시": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    # 2026-07-01 통합
    "광주": MERGED, "광주시": MERGED, "광주광역시": MERGED,
    "전남": MERGED, "전라남도": MERGED, "전남광주특별시": MERGED, "전남광주": MERGED,
    "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도",
}
# 통합 전 광주광역시 자치구 (통합특별시 안에서 옛 광주 지역 구분용)
FORMER_GWANGJU_DISTRICTS = ("동구", "서구", "남구", "북구", "광산구")
_SGG_SUFFIX = ("시", "군", "구")


def _key(s: str | None) -> str:
    return re.sub(r"\s+", "", nfc(s or ""))


def normalize_ctpv(name: str | None) -> str | None:
    """시도명 → 현재 시도명. 알 수 없으면 None."""
    k = _key(name)
    if not k:
        return None
    if k in CTPV:
        return k
    return CTPV_ALIASES.get(k)


def normalize_sgg(name: str | None) -> str | None:
    k = _key(name)
    return k or None


def match_sgg(user_input: str | None, known: set[str] | list[str]) -> str | None:
    """사용자가 적은 시군구('경산', '경산시', '수성 구') → 같은 시도 안의 알려진 시군구 이름.
    정확히 같으면 그대로, 아니면 시·군·구 접미사를 붙여 하나만 맞을 때만 돌려준다."""
    k = _key(user_input)
    if not k:
        return None
    known = set(known)
    if k in known:
        return k
    cands = [k + s for s in _SGG_SUFFIX if k + s in known]
    return cands[0] if len(cands) == 1 else None
