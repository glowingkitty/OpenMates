"""Actual Starlette socket state after session-watchers send a close frame."""

import asyncio
import json

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect

from backend.core.api.app.utils.websocket_lifecycle import receive_json_or_disconnect


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("close_code", [1008, 4406])
def test_server_close_while_receiving_uses_disconnect_cleanup(close_code):
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []
        connecting = True

        async def receive():
            nonlocal connecting
            if connecting:
                connecting = False
                return {"type": "websocket.connect"}
            entered.set()
            await release.wait()
            return {"type": "websocket.receive", "text": json.dumps({"type": "ping"})}

        async def send(message):
            sent.append(message)

        socket = WebSocket({"type": "websocket"}, receive, send)
        await socket.accept()
        entered.clear()
        release.clear()
        pending = asyncio.create_task(receive_json_or_disconnect(socket))
        await entered.wait()
        await socket.close(code=close_code)
        release.set()
        assert await pending == {"type": "ping"}
        with pytest.raises(WebSocketDisconnect):
            await receive_json_or_disconnect(socket)
        assert [message for message in sent if message["type"] == "websocket.close"] == [
            {"type": "websocket.close", "code": close_code, "reason": ""},
        ]

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_unaccepted_socket_still_reports_programming_error():
    async def receive():
        raise AssertionError("Unaccepted socket should not receive")

    socket = WebSocket({"type": "websocket"}, receive, receive)
    with pytest.raises(RuntimeError, match="accept"):
        asyncio.run(receive_json_or_disconnect(socket))


# contract-test: supporting surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
@pytest.mark.parametrize(
    "case, expected_category, expected_status, expected_reason",
    [
        ("link_missing", "session_link_missing", 0, "Session invalid"),
        ("link_mismatch", "session_link_mismatch", 0, "Session invalid"),
        ("state_missing", "state_missing", 0, "Session invalid"),
        ("risk_pending", "risk_pending", 0, "Session invalid"),
        ("revoked", "authority_rejected", 401, "Session unavailable"),
        ("forbidden", "authority_rejected", 403, "Session unavailable"),
        ("authority_unavailable", "authority_unavailable", 503, "Session unavailable"),
        ("authority_error", "authority_unavailable", 0, "Session unavailable"),
        ("valid", None, None, None),
    ],
)
# contract-test: supporting surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
def test_actual_session_watcher_logs_safe_category_without_changing_closure(
    case, expected_category, expected_status, expected_reason, caplog,
):
    import ast
    import logging
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException, status
    from backend.core.api.app.services.cache_user_mixin import canonical_session_user_id
    from backend.core.api.app.utils.websocket_lifecycle import (
        SessionAuthorityCloseCategory, log_session_authority_close,
    )

    # Execute the actual nested production watcher without starting unrelated
    # route listeners or auth/database services. This does not mirror its logic.
    route = Path(__file__).parents[1] / "core/api/app/routes/websockets.py"
    tree = ast.parse(route.read_text())
    watchers = [node for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "watch_session_authority"]
    assert len(watchers) == 1
    module = ast.Module(body=watchers, type_ignores=[])
    canary = "TOKEN_COOKIE_KEY_PAYLOAD_PRIVATE_CANARY"
    user_id = "owner"
    link = {"user_id": user_id, "private": canary}
    state = {"user_id": user_id, "risk_pending": False, "private": canary}
    if case == "link_missing":
        link = None
    elif case == "link_mismatch":
        link = {"user_id": "another-owner", "private": canary}
    elif case == "state_missing":
        state = None
    elif case == "risk_pending":
        state["risk_pending"] = True
    errors = {
        "revoked": HTTPException(401, canary),
        "forbidden": HTTPException(403, canary),
        "authority_unavailable": HTTPException(503, canary),
        "authority_error": RuntimeError(canary),
    }
    reads = AsyncMock(return_value=state, side_effect=errors.get(case))
    cache = SimpleNamespace(get=AsyncMock(return_value=link))
    closes = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError()

    async def close(*, code, reason):
        # Diagnostic is emitted immediately before the unchanged close.
        assert len(caplog.records) == 1
        closes.append({"code": code, "reason": reason})

    logger = logging.getLogger("test.session.watcher")
    caplog.set_level(logging.WARNING, logger=logger.name)
    namespace = {
        "asyncio": SimpleNamespace(sleep=sleep), "cache_service": cache,
        "session_hash": canary, "directus_service": object(), "user_id": user_id,
        "get_session_state_cached": reads,
        "canonical_session_user_id": canonical_session_user_id,
        "logger": logger, "device_fingerprint_hash": "a" * 64,
        "websocket": SimpleNamespace(close=close), "status": status,
        "HTTPException": HTTPException,
        "SessionAuthorityCloseCategory": SessionAuthorityCloseCategory,
        "log_session_authority_close": log_session_authority_close,
    }
    exec(compile(module, str(route), "exec"), namespace)
    if case == "valid":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(namespace["watch_session_authority"]())
        assert sleeps == [10, 10]
        assert closes == []
        assert caplog.records == []
    else:
        asyncio.run(namespace["watch_session_authority"]())
        assert sleeps == [10]
        assert closes == [{"code": 1008, "reason": expected_reason}]
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.close_category == expected_category
        assert record.authority_status == expected_status
        assert record.connection_hash == "a" * 64
        assert record.event_type == "ws_session_authority_close"
        assert canary not in str(vars(record))
        assert "another-owner" not in str(vars(record))
    cache.get.assert_awaited_once_with("session:" + canary)
    reads.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=auth.session.authoritative-enforcement
def test_watcher_diagnostic_rejects_unsafe_correlation_and_status(caplog):
    import logging
    from backend.core.api.app.utils.websocket_lifecycle import (
        SessionAuthorityCloseCategory, log_session_authority_close,
    )

    canary = "PRIVATE_TOKEN_COOKIE_CANARY"
    log_session_authority_close(
        logging.getLogger("test.session.watcher"),
        connection_hash=canary,
        category=SessionAuthorityCloseCategory.AUTHORITY_UNAVAILABLE,
        authority_status=canary,
    )
    assert len(caplog.records) == 1
    assert caplog.records[0].connection_hash == "unavailable"
    assert caplog.records[0].authority_status == 0
    assert canary not in str(vars(caplog.records[0]))


# contract-test: supporting surface=rest_api assertions=auth.session.authoritative-enforcement
def test_watcher_diagnostic_failure_does_not_replace_authority_decision():
    from unittest.mock import Mock
    from backend.core.api.app.utils.websocket_lifecycle import (
        SessionAuthorityCloseCategory, log_session_authority_close,
    )

    logger = Mock()
    logger.warning.side_effect = RuntimeError("PRIVATE_LOGGER_FAILURE")
    log_session_authority_close(
        logger, connection_hash="a" * 64,
        category=SessionAuthorityCloseCategory.SESSION_LINK_MISSING,
    )
    logger.warning.assert_called_once()
