"""COOKRCP01 조리 단계(MANUAL01~20) 추출과 누락 검출.

원칙
- 원본 칸 이름·칸 번호·문장 앞 번호·원문 문장을 그대로 보존한다. 번호를 다시 매기지 않는다.
- 비어 있는 단계는 채우지 않고 번호만 `missing_nos` 로 기록한다.
- `text_clean` 은 문장 앞 번호와 끝의 이미지 표식 문자만 떼어 낸 표시용 문장이다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from agetech_data.recipes.issues import Issue
from agetech_data.textutil import clean_text, is_blank

MAX_STEPS = 20

_LEADING_NO = re.compile(r"^\s*(\d+)\s*[.)]\s*")
# 원천 데이터 끝에 붙는 이미지 표식(예: "…찐다.a"). 한글·문장부호 뒤의 영문 소문자 한 글자만.
_TRAILING_MARKER = re.compile(r"(?<=[가-힣.!?)\s])([a-z])\s*$")


@dataclass
class Step:
    source_field: str          # "MANUAL02"
    source_no: int             # 2 (원본 칸 번호)
    stated_no: int | None      # 문장 앞에 적힌 번호, 없으면 None
    text_raw: str              # 원문 그대로
    text_clean: str            # 표시용 (앞 번호·끝 표식 제거)
    image_field: str
    image_url: str | None
    trailing_marker: str | None = None

    @property
    def number(self) -> int:
        """누락 계산에 쓰는 번호: 문장 앞 번호 우선, 없으면 칸 번호."""
        return self.stated_no if self.stated_no is not None else self.source_no


@dataclass
class StepResult:
    steps: list[Step]
    missing_nos: list[int]
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "steps": [asdict(s) for s in self.steps],
            "missing_step_nos": self.missing_nos,
        }


def clean_step_text(text: str) -> tuple[str, int | None, str | None]:
    """(표시용 문장, 문장 앞 번호, 끝 표식 문자)."""
    t = clean_text(text).replace("\n", " ")
    stated = None
    m = _LEADING_NO.match(t)
    if m:
        stated = int(m.group(1))
        t = t[m.end():]
    marker = None
    mm = _TRAILING_MARKER.search(t)
    if mm:
        marker = mm.group(1)
        t = t[: mm.start()]
    return t.strip(), stated, marker


def extract_steps(row: dict) -> StepResult:
    steps: list[Step] = []
    issues: list[Issue] = []
    for i in range(1, MAX_STEPS + 1):
        field_name, image_field = f"MANUAL{i:02d}", f"MANUAL_IMG{i:02d}"
        raw = row.get(field_name)
        image = row.get(image_field)
        image_url = image.strip() if isinstance(image, str) and image.strip() else None
        if is_blank(raw):
            if image_url:
                issues.append(Issue("step_image_without_text", {"source_field": field_name}))
            continue
        text_clean, stated, marker = clean_step_text(raw)
        steps.append(Step(field_name, i, stated, raw, text_clean, image_field, image_url, marker))

    if not steps:
        issues.append(Issue("steps_none"))
        return StepResult([], [], issues)

    for s in steps:
        if s.stated_no is None:
            issues.append(Issue("step_unnumbered", {"source_field": s.source_field}))
        elif s.stated_no != s.source_no:
            issues.append(Issue("step_number_mismatch",
                                {"source_field": s.source_field, "stated_no": s.stated_no}))
        if s.trailing_marker:
            issues.append(Issue("step_trailing_marker",
                                {"source_field": s.source_field, "marker": s.trailing_marker}))
        if s.image_url is None:
            issues.append(Issue("step_text_without_image", {"source_field": s.source_field}))

    numbers = [s.number for s in steps]
    dups = sorted({n for n in numbers if numbers.count(n) > 1})
    if dups:
        issues.append(Issue("step_number_duplicate", {"numbers": dups}))

    present = set(numbers)
    missing = [n for n in range(1, max(present) + 1) if n not in present]
    if missing:
        issues.append(Issue("step_gap", {"missing_nos": missing}))
        if 1 in missing:
            issues.append(Issue("step_first_missing"))
    return StepResult(steps, missing, issues)
