"""Read API credentials from the process or Git-ignored repository .env."""

import os
from pathlib import Path


def load_api_key(name):
    value = os.environ.get(name, "").strip()
    if value:
        return value
    environment = Path(__file__).resolve().parents[3] / ".env"
    if environment.is_file():
        for line in environment.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip("\"'")
    return ""
