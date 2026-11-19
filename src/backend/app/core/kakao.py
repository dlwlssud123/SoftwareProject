import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import AppError


class KakaoTokenInfo(BaseModel):
    app_id: int = Field(strict=True, gt=0, lt=2**63)
    id: int = Field(strict=True, gt=0, lt=2**63)
    expires_in: int = Field(strict=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _invalid_token() -> AppError:
    return AppError(
        401, "KAKAO_TOKEN_INVALID", "카카오 인증이 만료됐거나 유효하지 않아요."
    )


def _unavailable() -> AppError:
    return AppError(
        503,
        "KAKAO_UNAVAILABLE",
        "카카오 로그인에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.",
        retryable=True,
    )


def verify_kakao_token(token: str, expected_app_id: int) -> int:
    request = Request(
        "https://kapi.kakao.com/v1/user/access_token_info",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            info = KakaoTokenInfo.model_validate(json.loads(response.read(8192)))
    except HTTPError as error:
        error.close()
        if error.code == 401:
            raise _invalid_token() from None
        raise _unavailable() from None
    except (URLError, OSError, ValueError, ValidationError):
        raise _unavailable() from None
    if info.app_id != expected_app_id or info.expires_in <= 0:
        raise _invalid_token()
    return info.id
