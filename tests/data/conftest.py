import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def nutrition_sample() -> dict:
    """식약처 식품영양성분DB(03) 실제 응답에서 발췌한 행 (공개 데이터)."""
    return json.loads((FIXTURES / "foodntr_v03_sample.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample_foods(nutrition_sample):
    from agetech_data.nutrition.foods import clean_foods

    return clean_foods(nutrition_sample["items"])
