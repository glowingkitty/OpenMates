"""Bound transient decision JSON bodies before FastAPI parses inline image data."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.shared.providers.typesafe.assets import MAX_DECISION_BODY_BYTES

DECISION_POST_PATHS = frozenset({
    "/v1/apps/workspace/interpret",
    "/v1/apps/workspace/rank",
    "/v1/apps/ai/skills/decide",
    "/v1/anonymous/apps/ai/skills/decide",
    "/v1/anonymous/apps/ai/skills/decide/availability",
})


class AIDecideBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").rstrip("/")
        if scope["type"] != "http" or scope.get("method") != "POST" or path not in DECISION_POST_PATHS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        if headers.get(b"content-type", b"application/json").split(b";", 1)[0].strip().lower() != b"application/json":
            await JSONResponse(status_code=415, content={"detail": {"code": "decision_json_required"}})(scope, receive, send)
            return
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_DECISION_BODY_BYTES):
            await self._too_large(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_DECISION_BODY_BYTES:
                await self._too_large(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(status_code=413, content={"detail": {"code": "decision_body_too_large"}})(scope, receive, send)
