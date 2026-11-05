"""갱신 대상 소스 목록. 소스를 추가할 때는 여기에 한 줄을 더한다."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agetech_data import paths
from agetech_data.collect import welfare
from agetech_data.collect.recipes import collect_recipes
from agetech_data.nutrition import client as nutrition_client


@dataclass(frozen=True)
class Source:
    name: str
    label: str
    latest: Path
    key_names: tuple[str, ...]
    id_field: str
    # (key, *, fetch, sleep, log, **options) -> {"meta": ..., "items": [...]}
    collect: Callable[..., dict]
    # 게시 전 품질 요약 (실패 조건 아님, 상태 파일에 기록)
    quality: Callable[[list[dict]], dict] | None = field(default=None)
    # 변경 감지에 쓸 내용 (기본: 항목 전체)
    content_of: Callable[[dict], object] | None = field(default=None)

    def id_of(self, item: dict) -> str:
        return str(item.get(self.id_field, ""))


def _recipe_quality(items: list[dict]) -> dict:
    from agetech_data.recipes.validate import check_recipe

    return dict(Counter(check_recipe(r).status for r in items))


def _recipes(key, *, fetch, sleep, log, **_):
    return collect_recipes(key, fetch=fetch, sleep=sleep, log=log)


def _nutrition(key, *, fetch, sleep, log, **_):
    return nutrition_client.collect(key, fetch=fetch, sleep=sleep, log=log)


def _welfare(kind):
    def run(key, *, fetch, sleep, log, detail_budget=None, **_):
        return welfare.collect_welfare(kind, key, fetch=fetch, sleep=sleep, log=log, detail_budget=detail_budget,
                                       cache_path=paths.WELFARE_RAW_DIR / f"detail_cache_{kind}.json")
    return run


def _welfare_quality(items: list[dict]) -> dict:
    return {"detail_status": dict(Counter(i.get("detail_status") for i in items))}


SOURCES: dict[str, Source] = {
    s.name: s for s in [
        Source("recipes", "레시피 COOKRCP01 전체", paths.RECIPES_COLLECTED, ("FOODSAFETY_API_KEY",), "RCP_SEQ",
               _recipes, _recipe_quality),
        Source("nutrition", "식품영양성분DB 03 품목대표", paths.NUTRITION_RAW, (nutrition_client.KEY_NAME,), "FOOD_CD",
               _nutrition),
        Source("welfare_central", "중앙부처 복지 노년층", paths.WELFARE_CENTRAL_RAW,
               ("DATA_GO_KR_SERVICE_KEY", "WELFARE_API_KEY"), "servId", _welfare("central"), _welfare_quality,
               welfare.fingerprint),
        Source("welfare_local", "지자체 복지 노년층", paths.WELFARE_LOCAL_RAW,
               ("DATA_GO_KR_SERVICE_KEY", "WELFARE_API_KEY"), "servId", _welfare("local"), _welfare_quality,
               welfare.fingerprint),
    ]
}
