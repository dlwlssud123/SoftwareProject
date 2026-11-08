from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, SecretStr


class GuestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityData(BaseModel):
    user_id: UUID
    role: Literal["user", "admin"]
    expires_at: AwareDatetime


class SessionData(IdentityData):
    # Exclude the credential from repr; only the issuing HTTP response reveals it.
    access_token: SecretStr
    token_type: Literal["Bearer"] = "Bearer"


class RevokedData(BaseModel):
    revoked: Literal[True] = True
