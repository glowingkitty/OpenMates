"""Empty-call deletion fans out a guard only to clients that implement it."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState
from backend.core.api.app.routes.connection_manager import ConnectionManager


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def socket():
    accepted = asyncio.Event()
    async def accept():
        accepted.set()
    return SimpleNamespace(accept=accept, accepted=accepted, close=AsyncMock(),
        send_json=AsyncMock(), application_state=WebSocketState.CONNECTED)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_connection_membership_cannot_change_during_conditional_fence_and_fanout():
    manager = ConnectionManager()
    current, legacy = socket(), socket()
    await manager.connect(current, 'owner', 'current', supports_empty_call_cleanup=True)
    guarded = {'type': 'chat_deleted', 'payload': {'chat_id': 'chat', 'empty_call_cleanup': {'call_id': None}}}
    async with manager.empty_call_cleanup_gate('owner'):
        joining = asyncio.create_task(manager.connect(legacy, 'owner', 'legacy'))
        await asyncio.wait_for(legacy.accepted.wait(), 1)
        assert 'legacy' not in manager.active_connections['owner']
        # These methods must remain non-reentrant while the owner gate is held.
        await asyncio.wait_for(manager.send_personal_message({'type': 'receipt'}, 'owner', 'current'), 1)
        await asyncio.wait_for(manager.broadcast_to_user(guarded, 'owner'), 1)
        legacy.send_json.assert_not_awaited()
    await asyncio.wait_for(joining, 1)
    current.send_json.reset_mock()
    await manager.broadcast_to_user(guarded, 'owner')
    current.send_json.assert_awaited_once_with(guarded)
    # CLI/TUI/native recipients get an ordinary deletion so they close the chat.
    legacy.send_json.assert_awaited_once_with({'type': 'chat_deleted', 'payload': {'chat_id': 'chat'}})
