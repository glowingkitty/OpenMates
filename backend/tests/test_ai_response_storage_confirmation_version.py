"""
The durable AI-response confirmation reports the stored messages_v.

The page persists an assistant reply with a messages_v it computed itself. The
client core that builds the next (voice) turn never computed that version; it
learns it only from this confirmation. Without it the next turn is refused with
version_conflict and the call ends.
"""

import asyncio

from backend.core.api.app.routes.handlers.websocket_handlers import (
    ai_response_completed_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.ai_response_completed_handler import (
    handle_ai_response_completed,
)
from backend.tests.test_ai_response_completed_key_guard import (
    FakeCacheService,
    FakeCutoverController,
    FakeDirectusService,
    FakeManager,
    install_durable_persistence_spy,
    make_payload,
    reset_cutover_controller,
)


# contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts
def test_durable_confirmation_carries_the_stored_messages_v(monkeypatch):
    asyncio.run(_run_durable_confirmation_carries_the_stored_messages_v(monkeypatch))


async def _run_durable_confirmation_carries_the_stored_messages_v(monkeypatch):
    persisted_calls = install_durable_persistence_spy(monkeypatch)
    monkeypatch.setattr(
        ai_response_completed_handler,
        "ChatRecoveryCutoverController",
        FakeCutoverController,
    )
    reset_cutover_controller(epoch=1, authorized=True)
    manager = FakeManager()

    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c"),
    )

    assert len(persisted_calls) == 1
    confirmation = manager.personal_messages[0][0]
    assert confirmation["type"] == "ai_response_storage_confirmed"
    assert confirmation["payload"]["chat_id"] == "chat-123"
    assert confirmation["payload"]["messages_v"] == 4
