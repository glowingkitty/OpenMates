"""Source isolation and honest Memory receipts, including legacy client input."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend.apps.ai.processing.rule_context import parse_custom_rule_documents, applied_rule_receipt, authorized_project_memory_documents, select_rules_with_jev
from backend.shared.python_utils.memory_loader import load_app_memories
from backend.shared.python_utils.agent_context_history import sanitize_agent_context_message
from backend.core.api.app.services.project_recommendation_service import project_item_revision
from backend.tests.test_memory_loader import DOCUMENT

# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.conversation.explicit-approval
def test_legacy_personal_payload_never_bypasses_private_memory_consent():
    assert parse_custom_rule_documents([{"id":"personal:private", "source":"personal", "document":DOCUMENT}],
        authenticated_first_party=True, active_project_id="acme") == []

# contract-test: supporting surface=rest_api assertions=app-memories.catalog.declared-types-only
def test_client_cannot_claim_published_app_memory():
    with pytest.raises(ValueError):
        parse_custom_rule_documents([{"id":"app:code:svelte", "source":"app", "document":DOCUMENT}],
            authenticated_first_party=True, active_project_id=None)

# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_project_document_requires_current_owned_source_revision():
    row={"project_item_id":"memory-1", "item_type":"embed", "encrypted_metadata":"ciphertext", "updated_at":2}
    directus=SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[row])))
    binding={"project_id":"acme", "team_id":None}
    document={"id":"memory-1", "source":"project", "project_id":"acme", "document":DOCUMENT, "item_revision":project_item_revision(row)}
    assert await authorized_project_memory_documents([document],project=binding,user_id="owner",directus=directus)==[document]
    row["updated_at"]=3
    assert await authorized_project_memory_documents([document],project=binding,user_id="owner",directus=directus)==[]
    assert await authorized_project_memory_documents([document],project=None,user_id="owner",directus=directus)==[]

# contract-test: supporting surface=rest_api assertions=app-memories.transparency.loaded-set,app-memories.privacy.client-encrypted
def test_actual_loaded_receipt_is_distinct_from_consent_and_history_is_content_free():
    memories=load_app_memories(["design"])
    receipt=applied_rule_receipt(memories)
    assert receipt["type"]=="memories_loaded" and receipt["count"]==2
    assert receipt["memories"][0]["body"]==memories[0].body
    assert "action" not in receipt
    assert applied_rule_receipt(memories,previous_set_key=receipt["set_key"]) is None
    projected=json.loads(sanitize_agent_context_message({"role":"system","content":json.dumps(receipt)})["content"])
    assert projected["replayed_receipt"] is True
    assert projected["memories"]==[{"id":m.id,"revision":m.revision} for m in memories]
    assert all("body" not in memory for memory in projected["memories"])
    assert receipt["memories"][0]["body"]==memories[0].body

# contract-test: supporting surface=rest_api assertions=app-memories.conversation.explicit-approval
@pytest.mark.asyncio
async def test_personal_memory_is_ineligible_even_with_a_refresh_callback():
    from backend.shared.python_utils.memory_loader import parse_memory_md
    personal = parse_memory_md(DOCUMENT, memory_id="personal:private", source="personal")
    refresh = AsyncMock(return_value=[personal])
    assert await select_rules_with_jev(model_id="test", secrets_manager=None, rules=[personal], request_text="Python", refresh_catalog=refresh) == []
    refresh.assert_not_awaited()
