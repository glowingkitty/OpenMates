# backend/tests/test_websocket_integration.py
"""
Integration tests for WebSocket endpoint (/v1/ws).

Tests the WebSocket connection handshake and phased sync protocol
against the live dev server.

Requirements:
    - Dev server running (wss://api.dev.openmates.org)
    - For authenticated tests: OPENMATES_TEST_WS_REFRESH_TOKEN env var set
      (a valid auth_refresh_token from a logged-in test account session)

Usage:
    # Unauthenticated test only (always works):
    docker exec api python -m pytest backend/tests/test_websocket_integration.py -v -m integration -k "unauthenticated"

    # Full suite (needs refresh token in env):
    docker exec api python -m pytest backend/tests/test_websocket_integration.py -v -m integration
"""

import asyncio
import json
import os
import uuid

import pytest

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    websockets = None  # type: ignore[assignment]
    HAS_WEBSOCKETS = False

pytestmark = pytest.mark.integration

WS_BASE_URL = "wss://api.dev.openmates.org/v1/ws"
WS_REFRESH_TOKEN = os.getenv("OPENMATES_TEST_WS_REFRESH_TOKEN")
CONNECT_TIMEOUT = 10  # seconds


def _run_async(coro):
    """Run an async coroutine synchronously (works without pytest-asyncio)."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _connect_and_expect_rejection(url: str):
    """Connect to WS URL and verify the server rejects the connection."""
    try:
        async with websockets.connect(  # type: ignore[union-attr]
            url,
            open_timeout=CONNECT_TIMEOUT,
            additional_headers={"Origin": "https://app.dev.openmates.org"},
        ) as ws:
            # If we get here, connection was accepted.
            # Server should close it quickly after auth fails.
            try:
                await asyncio.wait_for(ws.recv(), timeout=5)
                pytest.fail("Expected WebSocket to be closed by server, but received data")
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code in (1008, 1011, 1006), (
                    f"Expected close code 1008/1011/1006, got {e.code}"
                )
    except websockets.exceptions.ConnectionClosed as e:
        # Connection closed during handshake
        assert e.code in (1008, 1011, 1006)
    except Exception as e:
        # websockets v15 uses InvalidStatus, v10 uses InvalidStatusCode
        # Both indicate the server rejected the WebSocket upgrade (401/403)
        err_str = str(e).lower()
        assert "403" in err_str or "401" in err_str or "rejected" in err_str, (
            f"Expected HTTP 401/403 rejection, got: {e}"
        )


@pytest.mark.skipif(not HAS_WEBSOCKETS, reason="websockets library not available")
class TestWebSocketConnection:
    """Test WebSocket connection handshake."""

    def test_unauthenticated_connection_rejected(self):
        """WebSocket connection without auth token should be rejected."""
        session_id = str(uuid.uuid4())
        url = f"{WS_BASE_URL}?sessionId={session_id}"
        _run_async(_connect_and_expect_rejection(url))

    def test_invalid_token_rejected(self):
        """WebSocket connection with invalid token should be rejected."""
        session_id = str(uuid.uuid4())
        url = f"{WS_BASE_URL}?sessionId={session_id}&token=invalid-token-12345"
        _run_async(_connect_and_expect_rejection(url))


@pytest.mark.skipif(not HAS_WEBSOCKETS, reason="websockets library not available")
@pytest.mark.skipif(not WS_REFRESH_TOKEN, reason="OPENMATES_TEST_WS_REFRESH_TOKEN not set")
class TestWebSocketPhasedSync:
    """Test WebSocket phased sync protocol (requires authenticated session)."""

    def test_phased_sync_phase1(self):
        """Authenticated WS connection should return phase 1 data on sync request."""
        _run_async(self._async_test_phased_sync_phase1())

    @staticmethod
    async def _async_test_phased_sync_phase1():
        session_id = str(uuid.uuid4())
        url = f"{WS_BASE_URL}?sessionId={session_id}&token={WS_REFRESH_TOKEN}"

        async with websockets.connect(  # type: ignore[union-attr]
            url,
            open_timeout=CONNECT_TIMEOUT,
            additional_headers={"Origin": "https://app.dev.openmates.org"},
        ) as ws:
            # Send phased sync request
            await ws.send(json.dumps({
                "type": "phased_sync_request",
                "payload": {
                    "phase": "1",
                    "client_chat_ids": [],
                    "client_chat_versions": {},
                    "client_suggestions_count": 0,
                    "client_embed_ids": [],
                },
            }))

            # Wait for phase 1 response (may take a few seconds for DB queries)
            response = await asyncio.wait_for(ws.recv(), timeout=30)
            data = json.loads(response)

            assert data["type"] == "phase_1_last_chat_ready", (
                f"Expected phase_1_last_chat_ready, got {data.get('type')}"
            )
            payload = data["payload"]
            assert "new_chat_suggestions" in payload
            assert "daily_inspirations" in payload
            assert payload["phase"] == "phase1"
