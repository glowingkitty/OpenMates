"""Offline connection-boundary tests for the fixed E2B browser transport.

No browser, provider or OpenMates endpoint is contacted. The tests assert the
actual socket destination and rejection behavior, rather than resolver syntax.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx

from backend.shared.providers import web_browse_runtime as runtime


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.delivery-and-evidence
@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["http11", "http2"])
async def test_rpc_timing_ignores_sensitive_trace_payloads_and_remote_spoofing(
    monkeypatch, protocol
):
    from backend.shared.providers.e2b_browser import E2BBrowser

    async def respond(request):
        trace = request.extensions["trace"]
        private = {
            "request": request,
            "headers": {"Authorization": "private-trace-token"},
        }
        for event in [
            "connection.connect_tcp",
            "connection.start_tls",
            protocol + ".receive_response_headers",
            protocol + ".receive_response_body",
        ]:
            await trace(event + ".started", private)
            await trace(event + ".complete", private)
        await trace("unrecognized.private.complete", private)
        return httpx.Response(
            200, json={"executed": True, "_rpc_timings": {"secret": "remote-spoof"}}
        )

    native = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: native(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await E2BBrowser("placeholder").rpc(
        {
            "rpc_url": "https://private-sandbox.invalid/rpc",
            "token": "private-token",
            "traffic_access_token": "private-ingress",
        },
        {"operation": "observe"},
    )
    assert result["executed"] is True
    timing = result["_rpc_timings"]
    assert set(timing) == {
        "connect_tcp_seconds",
        "tls_seconds",
        "response_headers_seconds",
        "response_body_seconds",
        "total_seconds",
    }
    assert all(
        isinstance(value, (int, float)) and 0 <= value < 10 for value in timing.values()
    )
    assert "private" not in json.dumps(timing) and "remote" not in json.dumps(timing)


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.private-storage-and-api
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,retryable", [(401, False), (409, False), (502, True), (503, True)]
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.private-storage-and-api
async def test_rpc_retains_safe_status_without_replaying_an_action(
    monkeypatch, status, retryable
):
    from backend.shared.providers.e2b_browser import E2BBrowser, BrowserRpcUnavailable

    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "private-upstream-content"})

    native = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: native(transport=httpx.MockTransport(reject), **kwargs),
    )
    provider = {
        "rpc_url": "https://private-sandbox.invalid/rpc",
        "token": "private-token",
        "traffic_access_token": "private-ingress",
    }
    with pytest.raises(BrowserRpcUnavailable) as exc:
        await E2BBrowser("placeholder").rpc(
            provider, {"operation": "act", "kind": "click", "target": "0"}
        )
    assert len(requests) == 1
    assert exc.value.status_code == status and exc.value.retryable is retryable
    assert "private" not in str(exc.value)


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.session-and-run
@pytest.mark.asyncio
async def test_native_resume_waits_for_ingress_using_metadata_without_repeating_input(
    monkeypatch,
):
    from e2b import Sandbox
    from backend.shared.providers.e2b_browser import E2BBrowser, BrowserRpcUnavailable

    monkeypatch.setattr(
        Sandbox,
        "connect",
        Mock(
            return_value=SimpleNamespace(
                traffic_access_token="private-ingress",
                get_host=Mock(return_value="resumed-sandbox.invalid"),
            )
        ),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    browser = E2BBrowser("placeholder")
    browser.rpc = AsyncMock(
        side_effect=[
            BrowserRpcUnavailable(retryable=True, status_code=502),
            {},
        ]
    )
    provider = {"sandbox_id": "private-sandbox"}
    resumed = AsyncMock()
    await browser.resume(provider, on_resumed=resumed)
    assert provider["running_since"] is not None
    resumed.assert_awaited_once_with(provider)
    assert provider["rpc_url"] == "https://resumed-sandbox.invalid"
    assert browser.rpc.await_count == 2
    assert all(
        c.args[1] == {"operation": "metadata"} for c in browser.rpc.await_args_list
    )


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_resume_does_not_retry_a_rejected_runtime_credential(monkeypatch):
    from e2b import Sandbox
    from backend.shared.providers.e2b_browser import E2BBrowser, BrowserRpcUnavailable

    monkeypatch.setattr(
        Sandbox,
        "connect",
        Mock(
            return_value=SimpleNamespace(
                traffic_access_token="private-ingress",
                get_host=Mock(return_value="resumed-sandbox.invalid"),
            )
        ),
    )
    browser = E2BBrowser("placeholder")
    browser.rpc = AsyncMock(side_effect=BrowserRpcUnavailable(status_code=401))
    with pytest.raises(BrowserRpcUnavailable):
        await browser.resume({"sandbox_id": "private-sandbox"})
    browser.rpc.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.asyncio
async def test_navigation_retries_only_the_destroyed_observation(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    old = SimpleNamespace(
        evaluate=AsyncMock(side_effect=RuntimeError("Execution context was destroyed")),
        dispose=AsyncMock(),
    )
    fresh = SimpleNamespace(
        evaluate=AsyncMock(return_value={"url": "https://example.com/next"}),
        dispose=AsyncMock(),
    )
    page = SimpleNamespace(
        evaluate_handle=AsyncMock(side_effect=[old, fresh]),
        wait_for_load_state=AsyncMock(),
        mouse=SimpleNamespace(click=AsyncMock()),
    )
    handle, observed = await runtime.capture_page_snapshot(page)
    assert handle is fresh and observed["url"].endswith("/next")
    old.dispose.assert_awaited_once()
    page.wait_for_load_state.assert_awaited_once_with("domcontentloaded", timeout=5000)
    page.mouse.click.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_navigation_observation_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    page = SimpleNamespace(
        evaluate_handle=AsyncMock(
            side_effect=RuntimeError("Execution context was destroyed")
        ),
        wait_for_load_state=AsyncMock(),
    )
    with pytest.raises(RuntimeError):
        await runtime.capture_page_snapshot(page)
    assert page.evaluate_handle.await_count == 3
    assert page.wait_for_load_state.await_count == 2


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.network-and-content
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    ["Crawler access denied", "Target page, context or browser has been closed"],
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.network-and-content
async def test_observation_does_not_retry_access_denials_or_a_lost_page(error):
    page = SimpleNamespace(
        evaluate_handle=AsyncMock(side_effect=RuntimeError(error)),
        wait_for_load_state=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match=error):
        await runtime.capture_page_snapshot(page)
    page.evaluate_handle.assert_awaited_once()
    page.wait_for_load_state.assert_not_awaited()


class Writer:
    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, value):
        self.written.extend(value)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.session-and-run
@pytest.mark.asyncio
@pytest.mark.parametrize("prebooted", [False, True])
async def test_controller_is_not_limited_to_the_sdk_default_command_lifetime(
    monkeypatch,
    prebooted,
):
    from datetime import datetime, timezone
    from e2b import Sandbox
    from backend.shared.providers.e2b_browser import E2BBrowser

    sandbox = SimpleNamespace(
        sandbox_id="private-sandbox",
        traffic_access_token="private-ingress",
        get_host=Mock(return_value="private-sandbox.invalid"),
        get_info=Mock(
            return_value=SimpleNamespace(
                cpu_count=2, memory_mb=4096, started_at=datetime.now(timezone.utc)
            )
        ),
        commands=SimpleNamespace(run=Mock()),
        files=SimpleNamespace(write=Mock()),
        kill=Mock(),
    )
    monkeypatch.setattr(Sandbox, "create", Mock(return_value=sandbox))
    monkeypatch.setenv("E2B_BROWSE_TEMPLATE", "prepared-template")
    monkeypatch.setenv("E2B_BROWSE_PREBOOTED", "true" if prebooted else "false")
    browser = E2BBrowser("placeholder")
    browser.rpc = AsyncMock(
        return_value={"runtime_protocol": "preboot-v1", "pristine": True}
    )
    await browser.create(session_id="session", owner="owner", on_created=AsyncMock())
    server = [
        c for c in sandbox.commands.run.call_args_list if c.kwargs.get("background")
    ]
    if prebooted:
        sandbox.commands.run.assert_not_called()
        assert len(sandbox.files.write.call_args_list) == 1
        assert sandbox.files.write.call_args.args[0].endswith("/config.json")
        assert browser.rpc.await_args.args[1]["check_ready"] is True
        assert browser.rpc.await_args.args[1]["require_pristine"] is True
    else:
        assert len(server) == 1 and server[0].kwargs["timeout"] == 0


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run
def test_preboot_snapshot_has_no_shared_bearer_and_binding_cannot_be_replaced(tmp_path):
    config = tmp_path / "config.json"
    authorization = runtime.SessionAuthorization(config)
    assert not authorization.permits("")
    assert not authorization.permits("Bearer None")
    token = "session-a-" * 5
    config.write_text(json.dumps({"token": token}))
    assert not authorization.permits("Bearer another-session")
    assert authorization.permits("Bearer " + token)
    config.write_text(json.dumps({"token": "session-b-" * 5}))
    assert authorization.permits("Bearer " + token)
    assert not authorization.permits("Bearer " + "session-b-" * 5)


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api
@pytest.mark.parametrize(
    "content",
    ["bad json", "[]", "{}", '{"token":null}', '{"token":""}', '{"token":"short"}'],
)
def test_unclaimed_or_malformed_runtime_never_accepts_a_default_bearer(
    tmp_path, content
):
    config = tmp_path / "config.json"
    config.write_text(content)
    assert not runtime.SessionAuthorization(config).permits("Bearer ")


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_provider_admission_preserves_known_rejection_without_allocating_or_retrying(
    monkeypatch,
):
    from e2b import Sandbox
    from e2b.exceptions import SandboxException
    from backend.shared.providers.e2b_browser import (
        E2BBrowser,
        BrowserAdmissionRejected,
    )
    from unittest.mock import Mock

    create = Mock(side_effect=SandboxException("Rejected", status_code=400))
    monkeypatch.setattr(Sandbox, "create", create)
    monkeypatch.setenv("E2B_BROWSE_TEMPLATE", "test-public-template")
    created = AsyncMock()
    with pytest.raises(BrowserAdmissionRejected):
        await E2BBrowser("placeholder").create(
            session_id="test-session", owner="test-owner", on_created=created
        )
    create.assert_called_once()
    assert create.call_args.kwargs["retries"] == 0
    assert create.call_args.kwargs["envs"] == {
        "PLAYWRIGHT_BROWSERS_PATH": "/opt/openmates-browser/browsers"
    }
    created.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private",
    [
        "0.0.0.0",
        "0.1.2.3",
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "192.168.1.1",
        "100.64.0.1",
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
async def test_mixed_or_private_dns_never_reaches_a_socket(monkeypatch, private):
    resolver = AsyncMock(
        return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", (private, 443)),
        ]
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    dial = AsyncMock()
    monkeypatch.setattr(asyncio, "open_connection", dial)
    reader = SimpleNamespace(
        readuntil=AsyncMock(return_value=b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    )
    writer = Writer()
    await runtime.connect_public_https(reader, writer)
    assert writer.written.startswith(b"HTTP/1.1 502") and writer.closed
    dial.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
@pytest.mark.asyncio
async def test_connect_dials_the_validated_ip_once_and_relays_bytes_without_resolving_again(
    monkeypatch,
):
    resolver = AsyncMock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    upstream_reader = asyncio.StreamReader()
    upstream_reader.feed_data(b"opaque TLS records")
    upstream_reader.feed_eof()
    upstream_writer = Writer()
    dial = AsyncMock(return_value=(upstream_reader, upstream_writer))
    monkeypatch.setattr(asyncio, "open_connection", dial)
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n"
    )
    writer = Writer()
    await runtime.connect_public_https(reader, writer)
    resolver.assert_awaited_once()
    dial.assert_awaited_once_with("93.184.216.34", 443, family=runtime.socket.AF_INET)
    assert (
        bytes(writer.written)
        == b"HTTP/1.1 200 Connection Established\r\n\r\nopaque TLS records"
    )
    assert writer.closed and upstream_writer.closed


# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proxy_request",
    [
        b"GET https://example.com/ HTTP/1.1",
        b"CONNECT example.com:80 HTTP/1.1",
        b"CONNECT user:secret@example.com:443 HTTP/1.1",
        b"CONNECT example.com:443/path HTTP/1.1",
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.network-and-content
async def test_proxy_rejects_non_https_and_credentialed_requests_before_dns(
    monkeypatch, proxy_request
):
    resolver = AsyncMock()
    monkeypatch.setattr(runtime, "public_ipv4", resolver)
    writer = Writer()
    await runtime.connect_public_https(
        SimpleNamespace(readuntil=AsyncMock(return_value=proxy_request + b"\r\n\r\n")),
        writer,
    )
    resolver.assert_not_awaited()
    assert (
        writer.written.startswith(b"HTTP/1.1 502") and b"secret" not in writer.written
    )
