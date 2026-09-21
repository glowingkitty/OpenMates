"""Post-commit sync uses normal ciphertext caches and owner-authorized wrappers."""
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from backend.core.api.app.routes.handlers.websocket_handlers.workflow_chat_delivery_handlers import _existing_delivery_chat, _project_committed_delivery
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDelivery, WorkflowChatClientPersistence


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.sync-projection,workflows.chat-delivery.key-recovery,workflows.access.boundaries
async def test_committed_delivery_refreshes_cache_and_broadcasts_client_ciphertext_without_plaintext():
    owner = hashlib.sha256(b"alice").hexdigest()
    delivery = WorkflowChatDelivery(delivery_id="delivery",chat_id="chat",message_id="message",owner_id="alice",encrypted_payload="vault-cipher",created_at=10,expires_at=100,workflow_id="workflow",run_id="run",node_id="send",
        client_persistence=WorkflowChatClientPersistence(encrypted_chat_metadata="{}",encrypted_message=json.dumps({"encrypted_content":"message-cipher","embeds":[]}),persisted_at=20))
    directus = AsyncMock()
    directus.get_items.return_value=[{"id":"chat","hashed_user_id":owner,"encrypted_chat_key":"wrapped-key","encrypted_title":"title-cipher","encrypted_category":"category-cipher","messages_v":7,"title_v":2,"created_at":5,"last_edited_overall_timestamp":30}]
    cache = AsyncMock()
    for name in ("add_chat_to_ids_versions","delete_chat_list_item_data","set_chat_version_component","append_sync_message_to_history"):
        getattr(cache,name).return_value=True
    manager = AsyncMock()
    await _project_committed_delivery(manager,cache,directus,delivery,"alice","cli")
    cache.add_chat_to_ids_versions.assert_awaited_once_with("alice","chat",30)
    assert cache.set_chat_version_component.await_args_list[0].args == ("alice","chat","messages_v",7)
    event = manager.broadcast_to_user.await_args.kwargs
    assert event["exclude_device_hash"] == "cli"
    assert event["message"]["payload"]["encrypted_content"] == "message-cipher"
    assert event["message"]["payload"]["content"] == ""
    assert event["message"]["payload"]["encrypted_chat_key"] == "wrapped-key"
    assert "vault-cipher" not in json.dumps(event)
    directus.get_items.return_value[0]["hashed_user_id"] = "different-owner"
    with pytest.raises(PermissionError):
        await _existing_delivery_chat(directus,delivery,"alice")
