"""공공 API 호출 공통: HTTP 조회와 재시도. 키·키가 들어간 URL은 예외 메시지에 남기지 않는다.

응답 해석 함수(parse)가 결과를 돌려주면 성공, Retry 를 던지면 잠시 뒤 다시 시도, Fatal 을 던지면 즉시 실패한다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agetech_data.settings import redact

T = TypeVar("T")
# (url) -> (HTTP 상태, 본문). 테스트에서 가짜로 바꿔 끼운다.
Fetcher = Callable[[str], tuple[int, str]]
USER_AGENT = "ValueFlow-data-import/1.0"


class CollectError(RuntimeError):
    """수집 실패. 메시지에는 키가 들어가지 않는다."""


class Retry(Exception):
    """일시적 오류 — 다시 시도한다."""


class Fatal(Exception):
    """재시도해도 같은 오류 (인증키 미등록·형식 오류 등)."""


class Quota(Fatal):
    """일일 호출 한도 초과 (공공데이터포털 결과코드 22 등). 다음 날까지 같은 오류."""


class QuotaExceededError(CollectError):
    """일일 호출 한도 초과로 수집을 멈춤. 호출한 쪽이 '남은 것은 다음에'로 처리할 수 있다."""


def http_fetch(url: str, timeout: int = 60) -> tuple[int, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8-sig", "replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def fetch_with_retry(url: str, parse: Callable[[int, str], T], *, what: str, secrets: tuple[str, ...] = (),
                     fetch: Fetcher = http_fetch, retries: int = 5, backoff: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep) -> T:
    last = ""
    for attempt in range(1, retries + 1):
        try:
            status, text = fetch(url)
            if status >= 500:
                raise Retry(f"HTTP {status}")
            # 429 등 4xx 는 본문에 사유(공공데이터포털: 일일 한도 초과 코드 22)가 있으므로 해석 함수가 판단한다
            return parse(status, text)
        except Retry as e:
            last = str(e)
        except Quota as e:
            raise QuotaExceededError(redact(f"{what} 중단 ({e})", *secrets)) from None
        except Fatal as e:
            raise CollectError(redact(f"{what} 실패 ({e})", *secrets)) from None
        except (URLError, TimeoutError, OSError) as e:
            last = f"네트워크 오류 {type(e).__name__}"
        except ValueError:
            last = "응답 해석 실패"
        if attempt < retries:
            sleep(backoff * attempt)
    raise CollectError(redact(f"{what} 실패 ({last}, {retries}회 시도)", *secrets))
