from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from app.schemas.catalog import ContractModel, PageQuery
from app.schemas.content import GuideDetail, GuideSummary

ReviewStatus = Literal["draft", "review", "approved", "rejected"]
GuideAction = Literal["submit", "approve", "reject", "publish", "unpublish"]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Version = Annotated[StrictInt, Field(ge=1, le=2147483646)]


class GuideStep(ContractModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]
    title: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None


class GuideContent(ContractModel):
    title: ShortText
    source_reference: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    checked_on: date
    steps: list[GuideStep] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_check_date(self):
        if self.checked_on > (datetime.now(UTC) + timedelta(hours=9)).date():
            raise ValueError("checked_on must not be in the future")
        return self


class GuideCreate(GuideContent):
    slug: str = Field(
        min_length=1, max_length=128, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )


class GuideEdit(GuideContent):
    expected_version: Version


class GuideCommand(ContractModel):
    expected_version: Version
    action: GuideAction
    note: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def decision_note(self):
        if self.action == "reject" and self.note is None:
            raise ValueError("a rejection needs a reason")
        if self.note is not None and self.action not in ("approve", "reject"):
            raise ValueError("only a review decision accepts a note")
        return self


class GuideAdminQuery(PageQuery):
    review_status: ReviewStatus | None = None
    is_published: bool | None = None


class GuideAdminSummary(GuideSummary):
    version: int
    review_status: ReviewStatus
    is_published: bool
    reviewed_by: UUID | None
    reviewed_at: AwareDatetime | None
    updated_at: AwareDatetime


class GuideAdminDetail(GuideAdminSummary, GuideDetail):
    review_note: str | None


class GuideAuditRecord(ContractModel):
    id: UUID
    guide_id: UUID
    actor_id: UUID | None
    action: Literal[
        "create", "edit", "submit", "approve", "reject", "publish", "unpublish"
    ]
    before_state: dict | None
    after_state: dict
    request_id: UUID
    created_at: AwareDatetime
