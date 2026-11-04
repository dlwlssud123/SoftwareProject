import pytest

from agetech_data.welfare.regions import MERGED, match_sgg, normalize_ctpv


# --- 지역 정규화 ----------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("서울특별시", "서울특별시"), ("서울", "서울특별시"), ("강원도", "강원특별자치도"), ("전라북도", "전북특별자치도"),
    ("광주광역시", MERGED), ("전라남도", MERGED), ("전남광주통합특별시", MERGED), (" 경 북 ", "경상북도"),
    ("제주도", "제주특별자치도"), ("없는도", None), ("", None), (None, None),
])
def test_normalize_ctpv(raw, expected):
    assert normalize_ctpv(raw) == expected


def test_match_sgg():
    known = {"경산시", "구미시", "중구", "수성구"}
    assert match_sgg("경산", known) == "경산시" and match_sgg("경산 시", known) == "경산시"
    assert match_sgg("수성", known) == "수성구" and match_sgg("중구", known) == "중구"
    assert match_sgg("포항", known) is None and match_sgg("", known) is None
