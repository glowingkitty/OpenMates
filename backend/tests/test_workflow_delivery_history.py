"""Focused v1 delivery acceptance: selected items, ACK memory, deletion and privacy."""
import json
import time
import uuid

import pytest

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService, WorkflowChatDeliveryStateError
from backend.core.api.app.services.workflow_delivery_history import canonical_result_identity
from backend.core.api.app.services.workflow_models import WorkflowRunDetail
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository, WorkflowNotFoundError
from backend.tests.workflow_test_utils import workflow_service


class Cipher:
    def __init__(self):
        self.payloads = []
    def encrypt_delivery(self, *, owner_id, delivery_id, payload):
        self.payloads.append(payload)
        return "vault-ciphertext:" + delivery_id


def setup():
    service = workflow_service(repository=InMemoryWorkflowRepository())
    workflow = service.create_workflow(user_id="alice", title="News", graph={"nodes":[
        {"id":"start","type":"manual_trigger","config":{}}, {"id":"end","type":"end","config":{}}],
        "edges":[{"from":"start","to":"end"}],"trigger_node_id":"start"})
    cipher = Cipher()
    deliveries = WorkflowChatDeliveryService(cipher=cipher)
    adapter = WorkflowActionAdapter(workflow_service=service, chat_delivery_service=deliveries)
    return service, workflow, cipher, deliveries, adapter


def context(service, workflow, run_id=None):
    run_id = run_id or str(uuid.uuid4())
    service.save_run("alice", WorkflowRunDetail(id=run_id,workflow_id=workflow.id,
        version_id=workflow.current_version_id,trigger_type="manual",status="running",started_at=int(time.time())))
    return {"workflow":{"workflow_id":workflow.id,"run_id":run_id,"node_id":"send"},"nodes":{
        "check":{"output":{"matched":False}},
        "weather":{"output":{"summary":"Rain after 15:00"}},
        "news":{"app_id":"news","output":{"results":[{"id":"story-1","provider":"example","title":"Story","url":"https://example.org/story"}]}}}}


def config():
    return {"title":"Daily update","message":"Today:","blocks":[
        {"id":"weather","source":"$nodes.weather.output.summary","include_if":"$nodes.check.output.matched"},
        {"id":"news","source":"$nodes.news.output.results","only_new_results":True}]}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=workflows.message.standard,workflows.history.delivered-membership,workflows.history.delete-forgets,workflows.content.encrypted-retained
async def test_preview_is_pure_and_only_acknowledged_run_memory_survives_payload_expiry_then_delete_forgets():
    service, workflow, cipher, deliveries, adapter = setup()
    first_context = context(service, workflow)
    preview = await adapter.preview_message(config(), first_context)
    assert "Story" in preview["text"] and "Rain after" not in preview["text"]
    assert cipher.payloads == []
    first = await adapter.send_chat_message(config(), first_context, "alice")
    retry = await adapter.send_chat_message(config(), first_context, "alice")
    assert (first["delivery_id"],first["chat_id"],first["message_id"]) == (retry["delivery_id"],retry["chat_id"],retry["message_id"])
    assert len(deliveries._repository._deliveries) == 1
    assert len(cipher.payloads[0]["embeds"]) == 1
    assert cipher.payloads[0]["embeds"][0]["embed_id"] in cipher.payloads[0]["message"]
    assert service.repository._delivery_history[0]["status"] == "reserved"
    assert "example.org" not in json.dumps(service.repository._delivery_history)
    assert "Story" not in json.dumps(service.repository._delivery_history)
    # A racing next run cannot send the reserved result.
    second_context = context(service, workflow)
    assert (await adapter.send_chat_message(config(), second_context, "alice"))["status"] == "no_new_results"
    claim = deliveries.claim_new_chat_delivery(delivery_id=first["delivery_id"],owner_id="alice",device_id="web")
    deliveries.persist_client_ciphertext(delivery_id=first["delivery_id"],owner_id="alice",claim=claim,device_id="web",encrypted_chat_metadata="chat-cipher",encrypted_message="message-cipher")
    assert service.repository._delivery_history[0]["status"] == "reserved"
    deliveries.acknowledge_delivery(delivery_id=first["delivery_id"],owner_id="alice",claim=claim,device_id="web")
    assert service.repository._delivery_history[0]["status"] == "delivered"
    service.repository.delete_encrypted_blob(service.repository.runs[first_context["workflow"]["run_id"]]["encrypted_content_ref"])
    assert (await adapter.send_chat_message(config(), context(service,workflow), "alice"))["status"] == "no_new_results"
    service.delete_run(workflow.id,first_context["workflow"]["run_id"],"alice")
    assert service.repository._delivery_history == []
    assert deliveries._repository.get_delivery(first["delivery_id"],"alice").status == "acknowledged"
    resent = await adapter.send_chat_message(config(), context(service,workflow), "alice")
    assert resent["selected_count"] == 1 and resent["chat_id"] != first["chat_id"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=workflows.history.delete-forgets,workflows.chat-delivery.claim-fenced,workflows.history.delivered-membership
async def test_pending_run_deletion_fences_late_claim_and_worker_save_and_preserves_other_target_memory():
    service, workflow, cipher, deliveries, adapter = setup()
    ctx = context(service,workflow)
    first = await adapter.send_chat_message(config(),ctx,"alice")
    claim = deliveries.claim_new_chat_delivery(delivery_id=first["delivery_id"],owner_id="alice",device_id="web")
    run = service.get_run(workflow.id,ctx["workflow"]["run_id"],"alice")
    service.delete_run(workflow.id,run.id,"alice")
    with pytest.raises(WorkflowChatDeliveryStateError):
        deliveries.persist_client_ciphertext(delivery_id=first["delivery_id"],owner_id="alice",claim=claim,encrypted_chat_metadata="cipher",encrypted_message="cipher")
    with pytest.raises(WorkflowNotFoundError):
        service.save_run("alice",run)
    assert all(item.id != run.id for item in service.list_runs(workflow.id,"alice"))
    # Existing chat targets have distinct membership slots.
    a = await adapter.send_chat_message({**config(),"chat_id":"chat-a"},context(service,workflow),"alice")
    b = await adapter.send_chat_message({**config(),"chat_id":"chat-b"},context(service,workflow),"alice")
    assert a["selected_count"] == b["selected_count"] == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=workflows.message.standard
async def test_all_conditional_blocks_excluded_does_not_send_header_only_chat():
    service, workflow, cipher, deliveries, adapter = setup()
    cfg = {**config(),"blocks":[config()["blocks"][0]]}
    result = await adapter.send_chat_message(cfg,context(service,workflow),"alice")
    assert result["status"] == "no_new_results"
    assert cipher.payloads == []


# contract-test: supporting surface=rest_api assertions=workflows.history.delivered-membership
def test_identity_ignores_url_tracking_and_never_uses_mutable_title():
    assert canonical_result_identity({"url":"https://example.org/story?utm_source=feed&b=2#a","title":"A"}) == canonical_result_identity({"url":"https://example.org/story?b=2","title":"B"})
    with pytest.raises(ValueError):
        canonical_result_identity({"title":"No stable identity"})


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=workflows.history.persisted-recovery,workflows.history.delete-forgets,workflows.execution.lifecycle-visible
async def test_lost_ack_keeps_committed_delivery_reserved_past_payload_expiry_and_recovers():
    service, workflow, cipher, deliveries, adapter = setup()
    ctx = context(service,workflow)
    first = await adapter.send_chat_message(config(),ctx,"alice")
    claim = deliveries.claim_new_chat_delivery(delivery_id=first["delivery_id"],owner_id="alice",device_id="web")
    deliveries.persist_client_ciphertext(delivery_id=first["delivery_id"],owner_id="alice",claim=claim,encrypted_chat_metadata="chat-cipher",encrypted_message="message-cipher")
    original = deliveries.get_delivery(delivery_id=first["delivery_id"],owner_id="alice")
    deliveries._clock = lambda: original.expires_at + 10
    expired_payload = deliveries.get_delivery(delivery_id=first["delivery_id"],owner_id="alice")
    assert expired_payload.status == "claimed" and expired_payload.encrypted_payload == ""
    assert (await adapter.send_chat_message(config(),context(service,workflow),"alice"))["status"] == "no_new_results"
    recovered = deliveries.claim_new_chat_delivery(delivery_id=first["delivery_id"],owner_id="alice",device_id="second")
    deliveries.acknowledge_delivery(delivery_id=first["delivery_id"],owner_id="alice",claim=recovered,device_id="second")
    projection = service.get_run(workflow.id,ctx["workflow"]["run_id"],"alice").output_summary["deliveries"]["send"]
    assert projection["status"] == "acknowledged" and projection["delivered_result_count"] == 1
    service.delete_run(workflow.id,ctx["workflow"]["run_id"],"alice")
    assert service.repository._delivery_history == []
