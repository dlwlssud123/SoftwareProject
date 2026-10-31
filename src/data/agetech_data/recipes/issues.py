"""품질 점검 결과 공통 형식과 점검 항목 정의.

수준(severity)
- error   : 서비스 노출 보류(hold) 후보. 원문 보완 전에는 앱에 노출하지 않는다.
- warning : 노출하되 이상을 표시(flagged)하고 원문 보완 요청 목록에 올린다.
- info    : 집계만 한다. 가공 결과에는 원문과 함께 남는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]

# code: (수준, 보고서용 설명)
ISSUE_RULES: dict[str, tuple[Severity, str]] = {
    # 기본 필드
    "name_missing": ("error", "메뉴명(RCP_NM) 없음"),
    # 조리 단계
    "steps_none": ("error", "조리 단계 문장이 하나도 없음"),
    "step_first_missing": ("error", "1단계(준비 과정) 누락"),
    "step_gap": ("warning", "마지막 단계 이전 번호가 비어 있음(중간 누락)"),
    "step_number_mismatch": ("warning", "원본 칸 번호(MANUALnn)와 문장 앞 번호가 다름"),
    "step_number_duplicate": ("warning", "문장 앞 번호가 중복됨"),
    "step_image_without_text": ("warning", "단계 이미지만 있고 문장이 없음"),
    "step_unnumbered": ("info", "문장 앞 번호 없음(칸 번호로 대체)"),
    "step_trailing_marker": ("info", "문장 끝 이미지 표식 문자(a/b/c 등)"),
    "step_text_without_image": ("info", "단계 문장은 있으나 이미지 없음"),
}


@dataclass
class Issue:
    code: str
    detail: dict = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return ISSUE_RULES[self.code][0]

    @property
    def label(self) -> str:
        return ISSUE_RULES[self.code][1]

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "label": self.label, **asdict(self)}
