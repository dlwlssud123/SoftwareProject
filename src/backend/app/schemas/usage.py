from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Feature = Literal[
    "app",
    "meal",
    "recipes",
    "nutrition",
    "assistant",
    "welfare",
    "playground",
    "shorts",
    "community",
    "guides",
    "meal_plan",
    "saved_recipes",
    "shopping",
    "settings",
    "account",
]
Event = Literal[
    "app_open",
    "app_error",
    "screen_view",
    "screen_exit",
    "request_started",
    "request_finished",
    "setting_changed",
    "read_aloud",
    "photo_selected",
    "food_selected",
    "video_open",
    "game_started",
    "game_completed",
]
Action = Literal[
    "view",
    "recommend",
    "save",
    "delete",
    "recognize",
    "calculate",
    "record",
    "ask",
    "open",
    "complete",
    "change",
    "start",
]
Outcome = Literal["success", "failure", "cancelled", "started"]
ErrorKind = Literal[
    "network",
    "timeout",
    "server",
    "unauthorized",
    "forbidden",
    "validation",
    "conflict",
    "cancelled",
    "bad_response",
    "unknown",
]


class UsageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    event_id: Annotated[UUID, Field(strict=False)]
    event: Event
    feature: Feature
    action: Action = "view"
    outcome: Outcome = "success"
    app_version: str = Field(
        pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:\+[0-9]{1,10})?$", max_length=32
    )
    platform: Literal["android", "ios", "web", "desktop"]
    duration_ms: int | None = Field(default=None, ge=0, le=3600000)
    error_kind: ErrorKind | None = None
    request_id: Annotated[UUID, Field(strict=False)] | None = None
    result_count: int | None = Field(default=None, ge=0, le=1000000)
    result_kind: Literal["generated", "references_only", "no_evidence"] | None = None

    setting_kind: Literal["text_size", "voice"] | None = None
    setting_value: (
        Literal["normal", "large", "largest", "enabled", "disabled"] | None
    ) = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.event == "request_started") != (self.outcome == "started"):
            raise ValueError("Only request_started has started outcome")
        if self.event == "request_finished" and self.duration_ms is None:
            raise ValueError("Finished requests require a duration")
        if self.error_kind is not None and self.outcome not in {"failure", "cancelled"}:
            raise ValueError("Only failed or cancelled events have an error")
        if self.event == "setting_changed":
            values = {
                "text_size": {"normal", "large", "largest"},
                "voice": {"enabled", "disabled"},
            }
            if self.setting_value not in values.get(self.setting_kind, set()):
                raise ValueError("Invalid accessibility setting")
        elif self.setting_kind is not None or self.setting_value is not None:
            raise ValueError("Only setting events include setting values")
        return self


class UsageBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    consent_version: Literal["usage-v1"]
    events: list[UsageInput] = Field(min_length=1, max_length=20)


class UsageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=7, ge=1, le=30)
    feature: Feature | None = None
    outcome: Outcome | None = None
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=20, ge=1, le=100)


class UsageAccepted(BaseModel):
    accepted: int = Field(ge=0, le=20)


class UsagePruned(BaseModel):
    removed: int = Field(ge=0)


class UsageRecord(UsageInput):
    created_at: AwareDatetime


class UsageFeatureStats(BaseModel):
    feature: Feature
    events: int = Field(ge=0)
    requests: int = Field(ge=0)
    success: int = Field(ge=0)
    failure: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    avg_ms: int | None


class UsageDateCount(BaseModel):
    day: date
    count: int = Field(ge=0)


class UsagePage(BaseModel):
    checked_at: AwareDatetime
    retention_days: Literal[30]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    app_opens: int = Field(ge=0)
    features: list[UsageFeatureStats]
    daily: list[UsageDateCount]
    items: list[UsageRecord]
