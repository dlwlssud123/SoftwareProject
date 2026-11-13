"""공통 텍스트 처리: 유니코드 정규화·공백 정리·수량 숫자 파싱·해시."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from fractions import Fraction
from typing import Any


def nfc(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")


def clean_text(s: str | None) -> str:
    """NFC·줄바꿈 통일·연속 공백 축소 (줄바꿈은 유지). 글자 내용은 바꾸지 않는다."""
    s = nfc(s).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


_FRACTION_CHARS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅛": "1/8"}


def parse_number(s: str | None) -> float | None:
    """'1/2', '1과1/2', '1 1/2', '0.5', '1½', '2~3'(평균) → float. 실패 시 None."""
    if s is None:
        return None
    s = nfc(str(s)).strip()
    for k, v in _FRACTION_CHARS.items():
        s = s.replace(k, f" {v}")
    s = s.replace(",", "").replace("과", " ").replace("와", " ").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    try:
        return float(sum((Fraction(part) for part in s.split()), Fraction(0)))
    except (ValueError, ZeroDivisionError):
        return None


def sha256_json(obj: Any) -> str:
    """원본 행 추적용 해시. 키 순서와 무관하게 같은 내용이면 같은 값."""
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
