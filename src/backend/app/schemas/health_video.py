from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from app.schemas.catalog import ContractModel, PageQuery

VideoTopic = Literal["stretching", "hands", "healthy_life"]
SOURCE_HOSTS = {"www.seohae.go.kr", "www.youtube.com"}


class HealthVideoQuery(PageQuery):
    topic: VideoTopic | None = None


class HealthVideo(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)
    topic: VideoTopic
    title: str = Field(min_length=1, max_length=120)
    publisher: str = Field(min_length=1, max_length=100)
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    source_url: str = Field(max_length=1000)
    checked_on: date

    @field_validator("source_url")
    @classmethod
    def known_source(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in SOURCE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("Invalid source URL")
        return value


class HealthVideoEntry(HealthVideo):
    active: bool
