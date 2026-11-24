from typing import Annotated, Literal
from uuid import UUID

from pydantic import UUID4, AwareDatetime, Field, StringConstraints, field_validator

from app.schemas.catalog import ContractModel, PageQuery
from app.schemas.guide_management import Version

Category = Literal["meal", "daily"]
PostState = Literal["published", "hidden", "deleted"]
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
Body = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class PostText(ContractModel):
    category: Category
    title: Title
    body: Body

    @field_validator("title", "body")
    @classmethod
    def readable_text(cls, value, info):
        allowed = "\n\t" if info.field_name == "body" else ""
        if any(
            (ord(char) < 32 and char not in allowed) or ord(char) == 127
            for char in value
        ):
            raise ValueError("Invalid control character")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid text encoding") from None
        return value


class PostCreate(PostText):
    submission_id: UUID4


class PostEdit(PostText):
    expected_version: Version


class PostVersion(ContractModel):
    expected_version: Version


class PostQuery(PageQuery):
    category: Category | None = None


class PostRecord(ContractModel):
    id: UUID
    category: Category
    title: str
    body: str
    author_label: str
    is_mine: bool
    status: PostState
    version: int
    created_at: AwareDatetime
    updated_at: AwareDatetime


class PostCreated(ContractModel):
    post: PostRecord
    replayed: bool


class ReportCreate(ContractModel):
    reason: Literal["spam", "abuse", "misinformation", "privacy", "other"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""

    @field_validator("note")
    @classmethod
    def valid_note(cls, value):
        if "\x00" in value:
            raise ValueError("Invalid note")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid text encoding") from None
        return value


class ReportReceipt(ContractModel):
    id: UUID
    status: Literal["received", "dismissed", "actioned"]


class BlockRecord(ContractModel):
    id: UUID
    author_label: str
    created_at: AwareDatetime


class ReportQuery(PageQuery):
    status: Literal["received", "dismissed", "actioned"] | None = None


class AdminReport(ReportReceipt):
    reason: str
    note: str
    post: PostRecord
    resolution: str
    created_at: AwareDatetime
    reviewed_at: AwareDatetime | None


class ReportResolve(ContractModel):
    decision: Literal["hide", "dismiss"]
    expected_post_version: Annotated[int, Field(strict=True, ge=1)]
    resolution: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]

    @field_validator("resolution")
    @classmethod
    def valid_resolution(cls, value):
        return ReportCreate.valid_note(value)
