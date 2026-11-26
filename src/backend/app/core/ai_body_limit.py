"""Bound streamed AI JSON bodies before a model request or image decode."""

from uuid import uuid4

from starlette.requests import Request

from app.core.errors import error_response


class AIBodyLimit:
    def __init__(
        self,
        app,
        max_bytes=2900000,
        prefix="/api/v1/ai/",
        code="AI_BODY_TOO_LARGE",
        message="사진이 너무 커요. 2MB 이하의 음식 사진을 골라 주세요.",
    ):
        self.app = app
        self.max_bytes = max_bytes
        self.prefix = prefix
        self.code = code
        self.message = message

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                request = Request(scope)
                request.state.request_id = str(uuid4())
                response = error_response(
                    request,
                    status_code=413,
                    code=self.code,
                    message=self.message,
                    headers={
                        "Cache-Control": "no-store",
                        "X-Request-ID": request.state.request_id,
                    },
                )
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def limited_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return await self.app(scope, limited_receive, send)
