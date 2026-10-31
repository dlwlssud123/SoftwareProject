"""비밀값(API 키) 읽기. 값은 로그·예외 메시지·출력 파일에 남기지 않는다.

우선순위: 프로세스 환경변수 → 레포 루트 .env (gitignore 대상).
src/frontend/tool/api_config.py 와 같은 규칙이라 두 쪽 스크립트가 같은 .env 를 쓴다.
"""

from __future__ import annotations

import os
from pathlib import Path

from agetech_data import paths


def load_secret(name: str, env_file: Path | None = None) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = env_file or paths.REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == name:
                return val.strip().strip("\"'")
    return ""


def redact(text: str, *secrets: str) -> str:
    """메시지에 섞였을 수 있는 비밀값(원문·URL 인코딩)을 *** 로 가린다."""
    from urllib.parse import quote

    for s in secrets:
        if s:
            for form in {s, quote(s, safe=""), quote(s)}:
                text = text.replace(form, "***")
    return text
