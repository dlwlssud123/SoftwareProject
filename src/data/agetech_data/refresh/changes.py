"""판본 간 변경 감지와 급감 방지."""

from __future__ import annotations

from collections.abc import Callable

from agetech_data.textutil import sha256_json

IdOf = Callable[[dict], str]
ContentOf = Callable[[dict], object]


def item_hashes(items: list[dict], id_of: IdOf, content_of: ContentOf | None = None) -> dict[str, str]:
    return {str(id_of(it)): sha256_json(content_of(it) if content_of else it) for it in items}


def diff(old_items: list[dict] | None, new_items: list[dict], id_of: IdOf, sample: int = 20,
         content_of: ContentOf | None = None) -> dict:
    """ID 기준 추가·삭제·변경 건수와 예시 ID. 이전 판본이 없으면 전부 '추가'.
    content_of 로 비교할 내용을 고를 수 있다 (예: 조회수처럼 매일 바뀌는 필드 제외)."""
    old = item_hashes(old_items or [], id_of, content_of)
    new = item_hashes(new_items, id_of, content_of)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(new) & set(old) if new[k] != old[k])
    return {
        "first_snapshot": old_items is None,
        "added": len(added), "removed": len(removed), "changed": len(changed),
        "unchanged": len(set(new) & set(old)) - len(changed),
        "samples": {"added": added[:sample], "removed": removed[:sample], "changed": changed[:sample]},
    }


def drop_guard(previous_count: int | None, new_count: int, min_ratio: float) -> str | None:
    """새 건수가 이전 정상본의 min_ratio 미만이면 게시하지 않는다 (빈 응답·부분 응답 방어)."""
    if previous_count and new_count < previous_count * min_ratio:
        return (f"건수 급감: 이전 {previous_count}건 → 이번 {new_count}건 "
                f"(기준 {min_ratio:.0%} 미만). 원천 확인 후 --min-ratio 를 낮춰 다시 실행하세요.")
    return None
