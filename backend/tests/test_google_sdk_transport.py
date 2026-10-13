"""Exercise the pinned Google SDK's real traced aiohttp streaming transport."""
# contract-test-file: infrastructure
import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest
from aiohttp import web
from google import genai

from backend.apps.ai.llm_providers import google_client


@pytest.mark.asyncio
async def test_custom_transport_streams_reuses_connections_and_closes(monkeypatch):
    connections = []

    async def stream(request):
        connections.append(request.transport)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        event = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ready"}]},
                                  "finishReason": "STOP"}]}
        await response.write(f"data: {json.dumps(event)}\n\n".encode())
        await response.write_eof()
        return response

    application = web.Application()
    application.router.add_post("/{path:.*}", stream)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    real_client = genai.Client

    def local_client(**kwargs):
        kwargs["http_options"].base_url = f"http://127.0.0.1:{port}"
        return real_client(**kwargs)

    monkeypatch.setattr(google_client.genai, "Client", local_client)
    phases = []
    monkeypatch.setattr(google_client, "_google_stream_phase", lambda _timing, phase, *_duration: phases.append(phase))
    token = google_client._active_google_stream.set(
        google_client._GoogleStreamTiming("unit-stream", "google_ai_studio", "test-model", 0))
    google_client.register_google_client_loop(asyncio.get_running_loop())
    session = None
    try:
        client, unmanaged = await google_client._get_loop_google_client("google_ai_studio", api_key="unit-test-key")
        reused, reused_unmanaged = await google_client._get_loop_google_client("google_ai_studio", api_key="unit-test-key")
        assert reused is client and unmanaged is None and reused_unmanaged is None
        session = next(iter(google_client._google_clients_by_loop[asyncio.get_running_loop()].values()))[1]
        for _ in range(2):
            chunks = await client.aio.models.generate_content_stream(model="test-model", contents="Ping")
            assert [chunk.text async for chunk in chunks] == ["ready"]
        assert len(connections) == 2 and connections[0] is connections[1]
        assert phases.count("http_request_start") == 2
        assert phases.count("http_response_headers") == 2
        assert phases.count("http_connect_start") == 1
        assert phases.count("http_connect_end") == 1
        assert phases.count("http_connection_reused") == 1
        assert phases.count("http_request_headers_sent") == 2
        await google_client.close_google_clients_for_current_loop()
        assert session.closed
    finally:
        google_client._active_google_stream.reset(token)
        await google_client.close_google_clients_for_current_loop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_transport_trace_is_request_scoped_private_and_nonfatal(monkeypatch, caplog):
    timing = google_client._GoogleStreamTiming("safe-task", "google_ai_studio", "test-model", time.monotonic())
    private = SimpleNamespace(url="https://private.invalid?key=private-key", headers={"secret": "private-header"},
                              body="private-body", exception=RuntimeError("private-exception"))
    context = SimpleNamespace()
    monkeypatch.setattr(google_client.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(google_client.logger, "propagate", False)
    token = google_client._active_google_stream.set(timing)
    try:
        with caplog.at_level(logging.INFO, logger=google_client.__name__):
            await google_client._on_google_http_request_start(None, context, private)
            for interval in ["dns", "connect", "pool_wait"]:
                await google_client._google_transport_trace("http_" + interval + "_start", interval)(None, context, private)
                await google_client._google_transport_trace("http_" + interval + "_end", interval, end=True)(None, context, private)
            await google_client._on_google_http_request_end(None, context, private)
        assert context.google_phase_starts == {}
        durations = [float(record.getMessage().rsplit("duration_ms=", 1)[1])
                     for record in caplog.records if "duration_ms=" in record.getMessage()]
        assert len(durations) == 3 and all(duration >= 0 for duration in durations)
        assert "safe-task" in caplog.text
        for value in ["private.invalid", "private-key", "private-header", "private-body", "private-exception"]:
            assert value not in caplog.text
        def broken_logger(*_args, **_kwargs):
            raise RuntimeError("diagnostic failure")
        monkeypatch.setattr(google_client.logger, "info", broken_logger)
        await google_client._on_google_http_request_start(None, context, private)
        await google_client._google_transport_trace("http_dns_start", "dns")(None, context, private)
        await google_client._on_google_http_request_exception(None, context, private)
        assert context.google_phase_starts == {} and context.google_timing is None
        await google_client._on_google_http_response_chunk(None, context, private)
    finally:
        google_client._active_google_stream.reset(token)
