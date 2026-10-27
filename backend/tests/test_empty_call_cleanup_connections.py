"""Known legacy recipients must never receive automatic chat deletion."""
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
    guarded = {'type': 'chat_deleted', 'payload': {'chat_id': 'chat', 'empty_call_cleanup': {}}}
    async with manager.empty_call_cleanup_gate('owner'):
        assert manager.all_user_connections_support_empty_call_cleanup('owner')
        joining = asyncio.create_task(manager.connect(legacy, 'owner', 'legacy'))
        await asyncio.wait_for(legacy.accepted.wait(), 1)
        assert 'legacy' not in manager.active_connections['owner']
        # These methods must remain non-reentrant while the owner gate is held.
        await asyncio.wait_for(manager.send_personal_message({'type': 'receipt'}, 'owner', 'current'), 1)
        await asyncio.wait_for(manager.broadcast_to_user(guarded, 'owner'), 1)
        legacy.send_json.assert_not_awaited()
    await asyncio.wait_for(joining, 1)
    assert not manager.all_user_connections_support_empty_call_cleanup('owner')
    await manager.broadcast_to_user(guarded, 'owner')
    legacy.send_json.assert_not_awaited()
    await manager.broadcast_to_user({'type': 'new_system_message'}, 'owner')
    legacy.send_json.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_unavailable_rollout_authority_preserves_even_after_unknown_peer_leaves():
    manager = ConnectionManager()
    await manager.connect(socket(), 'owner', 'current', supports_empty_call_cleanup=True)
    assert manager.all_user_connections_support_empty_call_cleanup('owner')
    manager.empty_call_cleanup_unsafe_owners.add('owner')
    assert not manager.all_user_connections_support_empty_call_cleanup('owner')
