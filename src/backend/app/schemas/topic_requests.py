from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    UUID4,
    AwareDatetime,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.catalog import ContractModel, PageQuery
from app.schemas.content import GuideSummary
from app.schemas.guide_management import Version

TopicKind = Literal["life_guide", "video"]
TopicState = Literal["received", "reviewing", "completed", "declined", "withdrawn"]


class TopicCreate(ContractModel):
    submission_id: UUID4
    kind: TopicKind
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]

    @field_validator("topic")
    @classmethod
    def single_line(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Use a single-line topic")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid text encoding") from None
        return value


class TopicQuery(PageQuery):
    kind: TopicKind | None = None
    status: TopicState | None = None
    submission_id: UUID4 | None = None


class TopicReview(ContractModel):
    expected_version: Version
    status: Literal["reviewing", "completed", "declined"]
    reply: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
        ]
        | None
    ) = None
    guide_id: UUID | None = None

    @model_validator(mode="after")
    def decision(self):
        if self.status in ("completed", "declined") and self.reply is None:
            raise ValueError("A decision needs a reply")
        if self.guide_id is not None and self.status != "completed":
            raise ValueError("A guide link requires completion")
        if self.reply is not None:
            if "\x00" in self.reply:
                raise ValueError("Invalid reply text")
            try:
                self.reply.encode("utf-8")
            except UnicodeError:
                raise ValueError("Invalid reply encoding") from None
        return self


class TopicRecord(ContractModel):
    id: UUID
    kind: TopicKind
    topic: str | None
    status: TopicState
    version: int
    reply: str | None
    guide: GuideSummary | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TopicCreated(ContractModel):
    request: TopicRecord
    replayed: bool


class AdminTopicRecord(TopicRecord):
    guide_id: UUID | None


class TopicAuditRecord(ContractModel):
    id: UUID
    actor_id: UUID | None
    action: Literal["create", "review", "withdraw"]
    before_state: dict | None
    after_state: dict
    request_id: UUID
    created_at: AwareDatetime
