from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)


class GuestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KakaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    access_token: SecretStr = Field(min_length=1, max_length=2048)

    @field_validator("access_token")
    @classmethod
    def validate_header_value(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if not token.isascii() or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError("Invalid access token")
        return value


class IdentityData(BaseModel):
    user_id: UUID
    role: Literal["user", "admin"]
    expires_at: AwareDatetime
    kakao_linked: bool = False


class SessionData(IdentityData):
    # Exclude the credential from repr; only the issuing HTTP response reveals it.
    access_token: SecretStr
    token_type: Literal["Bearer"] = "Bearer"


class RevokedData(BaseModel):
    revoked: Literal[True] = True
