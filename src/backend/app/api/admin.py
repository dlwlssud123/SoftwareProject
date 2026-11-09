from fastapi import APIRouter, Request, Response

from app.core.auth import AdminAuth
from app.schemas.auth import IdentityData
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/me",
    response_model=SuccessResponse[IdentityData],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 500, 503)},
)
def admin_identity(request: Request, response: Response, auth: AdminAuth):
    response.headers["Cache-Control"] = "no-store"
    return SuccessResponse(
        data=IdentityData(
            user_id=auth.user.id,
            role=auth.user.role,
            expires_at=auth.session.expires_at,
        ),
        meta=build_meta(request),
    )
