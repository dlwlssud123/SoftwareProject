"""Small reviewed catalog; videos remain on their official publisher's platform."""

import json
from pathlib import Path

from app.schemas.health_video import HealthVideo, HealthVideoEntry

CATALOG = Path(__file__).resolve().parents[1] / "resources" / "health_videos.json"


def published_videos() -> list[HealthVideo]:
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("Invalid video catalog")
    rows = [HealthVideoEntry.model_validate(row) for row in entries]
    if len({row.id for row in rows}) != len(rows):
        raise ValueError("Duplicate video identifier")
    return [
        HealthVideo.model_validate(row.model_dump(exclude={"active"}))
        for row in rows
        if row.active
    ]
