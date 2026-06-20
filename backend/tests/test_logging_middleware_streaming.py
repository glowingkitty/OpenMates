"""
backend/tests/test_logging_middleware_streaming.py

Regression tests for request logging middleware streaming semantics.
Anonymous chat depends on early Server-Sent Events reaching the browser before
the AI task finishes, so middleware must not consume StreamingResponse bodies
into memory before returning them to ASGI.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware


class FakeMetricsService:
    def track_api_request(self, _method: str, _path: str, _status_code: int) -> None:
        pass

    def track_request_duration(self, _method: str, _path: str, _duration: float) -> None:
        pass


@pytest.mark.asyncio
async def test_logging_middleware_preserves_early_sse_body_frames() -> None:
    release_final_chunk = asyncio.Event()

    async def stream_endpoint(_request: Any) -> StreamingResponse:
        async def body():
            yield b"data: early\n\n"
            await release_final_chunk.wait()
            yield b"data: done\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    app = Starlette(routes=[Route("/stream", stream_endpoint)])
    app.state.metrics_service = FakeMetricsService()
    app.add_middleware(LoggingMiddleware)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/stream",
        "raw_path": b"/stream",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    sent_messages: list[dict[str, Any]] = []
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(60)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    app_task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(
            _wait_for_body(sent_messages, b"data: early\n\n"),
            timeout=0.5,
        )
    finally:
        release_final_chunk.set()
        await asyncio.wait_for(app_task, timeout=1)

    body_messages = [message for message in sent_messages if message["type"] == "http.response.body"]
    assert body_messages[0]["body"] == b"data: early\n\n"
    assert body_messages[0].get("more_body") is True


async def _wait_for_body(sent_messages: list[dict[str, Any]], expected_body: bytes) -> None:
    while True:
        if any(
            message.get("type") == "http.response.body" and message.get("body") == expected_body
            for message in sent_messages
        ):
            return
        await asyncio.sleep(0.01)
