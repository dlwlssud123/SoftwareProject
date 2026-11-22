from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from app.schemas.catalog import ContractModel, PageQuery
from app.schemas.guide_management import GuideCommand

CatalogKind = Literal["meal-facilities", "seasonal-foods"]
CatalogReviewStatus = Literal["legacy", "review", "approved", "rejected"]


class CatalogReviewCommand(GuideCommand):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class CatalogAdminQuery(PageQuery):
    review_status: CatalogReviewStatus | None = None
    month: int | None = Field(default=None, ge=1, le=12)


class CatalogAdminSummary(ContractModel):
    id: UUID
    kind: CatalogKind
    name: str
    provider: str | None
    source_id: str | None
    source_url: str
    checked_on: date
    content_sha256: str | None
    source_run_id: UUID | None
    month: int | None
    sido: str | None
    sigungu: str | None
    source_revision: str
    source_is_published: bool
    is_published: bool
    review_version: int
    review_status: CatalogReviewStatus
    review_required: bool
    reviewed_by: UUID | None
    reviewed_at: AwareDatetime | None
    review_updated_at: AwareDatetime


class CatalogAdminDetail(CatalogAdminSummary):
    review_note: str | None
    content: dict[str, JsonValue]


class CatalogAuditRecord(ContractModel):
    id: UUID
    kind: CatalogKind
    target_id: UUID
    actor_id: UUID | None
    action: Literal["submit", "approve", "reject", "publish", "unpublish"]
    before_state: dict[str, JsonValue]
    after_state: dict[str, JsonValue]
    request_id: UUID
    created_at: AwareDatetime
