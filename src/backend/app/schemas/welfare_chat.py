"""Welfare answers carry server-selected published sources, never model URLs."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.ai import ChatAnswer, ChatRequest
from app.schemas.catalog import ContractModel

RegionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class WelfareChatRequest(ChatRequest):
    region: RegionText | None = None
    district: RegionText | None = None

    @field_validator("region", "district")
    @classmethod
    def valid_region_text(cls, value):
        return ChatRequest.valid_text(value) if value is not None else None

    @model_validator(mode="after")
    def district_requires_region(self):
        if self.district and not self.region:
            raise ValueError("A district requires a province")
        return self


class WelfareGroundedAnswer(ChatAnswer):
    citations: list[Annotated[int, Field(strict=True, ge=1, le=5)]] = Field(
        min_length=1, max_length=5
    )

    @field_validator("citations")
    @classmethod
    def unique_citations(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate citation")
        return value


class WelfareChatSource(ContractModel):
    number: int
    service_id: str
    scope: Literal["welfare_central", "welfare_local"]
    title: str
    excerpt: str
    url: str | None = None
    checked_at: AwareDatetime | None = None

    @field_validator("url", mode="before")
    @classmethod
    def official_https_only(cls, value):
        if not isinstance(value, str):
            return None
        try:
            parts = urlsplit(value)
            host = (parts.hostname or "").lower()
            if (
                parts.scheme != "https"
                or parts.username is not None
                or parts.password is not None
                or parts.port not in (None, 443)
                or len(value) > 2000
                or any(c.isspace() or ord(c) < 32 for c in value)
            ):
                return None
            return (
                value
                if host.endswith(".go.kr")
                or host == "bokjiro.go.kr"
                or host.endswith(".bokjiro.go.kr")
                else None
            )
        except ValueError:
            return None


class WelfareChatResult(ChatAnswer):
    provider: Literal["NVIDIA", "references"]
    model: str | None = None
    answer_status: Literal["generated", "references_only", "no_evidence"]
    evidence_status: Literal["ok", "weak", "none"]
    index_version: str
    region: str | None = None
    district: str | None = None
    notes: list[str] = Field(default_factory=list)
    sources: list[WelfareChatSource] = Field(default_factory=list, max_length=5)
    notice: str = "공식 자료를 찾은 참고 안내예요. 실제 지원 대상·신청 가능 여부는 담당 기관에서 확인해 주세요."
