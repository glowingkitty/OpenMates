"""Focused v1 delivery acceptance: selected items, ACK memory, deletion and privacy."""
import json
import time
import uuid

import pytest

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService, WorkflowChatDeliveryStateError
from backend.core.api.app.services.workflow_delivery_history import canonical_result_identity
from backend.core.api.app.services.workflow_result_selection import prepare_ask_destinations, sanitize_workflow_ai_answer
from backend.core.api.app.services.workflow_runner import WorkflowRunner
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


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.message.standard,workflows.results.selective-embeds,workflows.ai-ask.execution
async def test_inline_results_render_at_token_and_ask_receives_only_reserved_items():
    from types import SimpleNamespace
    service, workflow, cipher, _, adapter = setup()
    first = context(service, workflow)
    event = {"id": "event-1", "provider": "example", "title": "AI meetup",
             "date_start": "2026-10-01T18:00:00+02:00", "location": "Berlin",
             "url": "https://example.org/events/1", "event_type": "PHYSICAL"}
    first["nodes"]["events"] = {"app_id": "events", "skill_id": "search", "output": {"results": [event]}}
    prompt = "Summarize {{ $nodes.events.output.results }}"
    send = SimpleNamespace(id="send", config={"title": "Events", "message": "{{ $nodes.ask.output.answer }}"})
    selected = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=first["workflow"]["run_id"],
        ask_node_id="ask", prompt=prompt, context=first, user_id="alice", send_nodes=[send],
    )
    assert selected["send"]["selected_lists"]["$nodes.events.output.results"] == [event]
    ai_item = selected["send"]["ai_lists"]["$nodes.events.output.results"][0]
    assert ai_item["embed_ref"] and ai_item["title"] == "AI meetup"
    assert "event_type" not in ai_item
    ref = ai_item["embed_ref"]
    answer = sanitize_workflow_ai_answer(
        f"See [AI meetup](embed:{ref}) and [unknown](embed:unselected).\n"
        f"```embeds_results_view\ntitle: Berlin events\nembeds: {ref}, unselected\n```",
        {ref},
    )
    assert f"[AI meetup](embed:{ref})" in answer and "[unknown](embed:" not in answer
    assert f"embeds: {ref}\n" in answer
    first["nodes"]["ask"] = {"output": {"answer": answer, "answers_by_destination": {"send": answer}}}
    first["workflow"]["prepared"] = selected
    delivery = await adapter.send_chat_message(send.config, first, "alice")
    assert delivery["selected_count"] == 1
    assert cipher.payloads[0]["embeds"][0]["content"] == event
    assert cipher.payloads[0]["embeds"][0]["embed_id"] == ref
    assert answer in cipher.payloads[0]["message"]

    next_run = context(service, workflow)
    next_run["nodes"]["events"] = first["nodes"]["events"]
    repeat = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=next_run["workflow"]["run_id"],
        ask_node_id="ask", prompt=prompt, context=next_run, user_id="alice", send_nodes=[send],
    )
    assert repeat["send"]["skip"] is True

    # A branch that never reaches Send must free its separate selection.
    branch_run = context(service, workflow)
    branch_run["nodes"]["events"] = {"app_id": "events", "skill_id": "search", "output": {"results": [{**event, "id": "event-2"}]}}
    branch_run["workflow"]["prepared"] = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=branch_run["workflow"]["run_id"],
        ask_node_id="ask", prompt=prompt, context=branch_run, user_id="alice", send_nodes=[send],
    )
    await WorkflowRunner(service)._release_undelivered_prepared(branch_run, [], "alice")
    another_run = context(service, workflow)
    another_run["nodes"]["events"] = branch_run["nodes"]["events"]
    selectable_again = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=another_run["workflow"]["run_id"],
        ask_node_id="ask", prompt=prompt, context=another_run, user_id="alice", send_nodes=[send],
    )
    assert selectable_again["send"]["skip"] is False


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.results.selective-embeds,workflows.chat-delivery.client-encrypted,workflows.ai-ask.execution
async def test_prepared_ask_encrypts_every_reserved_result_even_when_answer_cites_only_four():
    from types import SimpleNamespace
    service, workflow, cipher, _, adapter = setup()
    ctx = context(service, workflow)
    events = [
        {"id": f"event-{index}", "provider": "example", "title": f"Event {index}",
         "url": f"https://example.org/events/{index}"}
        for index in range(10)
    ]
    ctx["nodes"]["events"] = {"app_id": "events", "skill_id": "search", "output": {"results": events}}
    send = SimpleNamespace(id="send", config={"title": "Events", "message": "{{ steps.ask.answer }}"})
    prepared = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=ctx["workflow"]["run_id"],
        ask_node_id="ask", prompt="Summarize {{ steps.events.results }}", context=ctx,
        user_id="alice", send_nodes=[send],
    )
    assert len(prepared["send"]["embeds"]) == 10
    refs = [embed["embed_id"] for embed in prepared["send"]["embeds"]]
    answer = "Four highlights: " + ", ".join(f"[Event {index}](embed:{ref})" for index, ref in enumerate(refs[:4]))
    ctx["nodes"]["ask"] = {"output": {"answer": answer, "answers_by_destination": {"send": answer}}}
    ctx["workflow"]["prepared"] = prepared

    delivery = await adapter.send_chat_message(send.config, ctx, "alice")
    payload = cipher.payloads[0]
    assert delivery["selected_count"] == 10
    assert len(payload["embeds"]) == 10
    assert {embed["embed_id"] for embed in payload["embeds"]} == set(refs)
    assert all(ref in payload["message"] for ref in refs[:4])
    assert all(ref not in payload["message"] for ref in refs[4:])
    assert len([row for row in service.repository._delivery_history if row["status"] == "reserved"]) == 10


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.results.selective-embeds,workflows.history.delivered-membership
async def test_ask_and_direct_send_reserve_only_results_with_persistable_embeds():
    from types import SimpleNamespace
    service, workflow, cipher, _, adapter = setup()
    event = {"id": "event-supported", "provider": "example", "title": "Event", "url": "https://example.org/event"}
    task = {"id": "task-unsupported", "provider": "example", "title": "Task", "url": "https://example.org/task"}
    first = context(service, workflow)
    first["nodes"]["events"] = {"app_id": "events", "skill_id": "search", "output": {"results": [event]}}
    first["nodes"]["tasks"] = {"app_id": "tasks", "skill_id": "search", "output": {"results": [task]}}
    send = SimpleNamespace(id="send", config={"title": "Mixed", "message": "{{ steps.ask.answer }}"})
    prepared = await prepare_ask_destinations(
        workflow_service=service, workflow_id=workflow.id, run_id=first["workflow"]["run_id"],
        ask_node_id="ask", prompt="{{ steps.events.results }} {{ steps.tasks.results }}",
        context=first, user_id="alice", send_nodes=[send],
    )
    assert list(prepared["send"]["selected_lists"]) == ["steps.events.results"]
    assert len(prepared["send"]["embeds"]) == 1
    assert len(service.repository._delivery_history) == 1
    first["nodes"]["ask"] = {"output": {"answer": "One event", "answers_by_destination": {"send": "One event"}}}
    first["workflow"]["prepared"] = prepared
    await adapter.send_chat_message(send.config, first, "alice")
    assert len(cipher.payloads[-1]["embeds"]) == 1

    second = context(service, workflow)
    second["nodes"]["events"] = {"app_id": "events", "skill_id": "search", "output": {"results": [{**event, "id": "event-direct", "url": "https://example.org/direct"}]}}
    second["nodes"]["tasks"] = first["nodes"]["tasks"]
    direct = await adapter.send_chat_message(
        {"title": "Mixed direct", "message": "{{ steps.events.results }}\n{{ steps.tasks.results }}"}, second, "alice",
    )
    assert direct["selected_count"] == 1
    assert len(cipher.payloads[-1]["embeds"]) == 1
    assert len(service.repository._delivery_history) == 2


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.message.standard
async def test_inline_result_group_replaces_variable_with_embed_view():
    service, workflow, cipher, _, adapter = setup()
    ctx = context(service, workflow)
    ctx["nodes"]["news"]["output"]["results"][0]["description"] = "Full card content"
    result = await adapter.send_chat_message(
        {"title": "News", "message": "Here are the stories: {{ $nodes.news.output.results }}"}, ctx, "alice",
    )
    assert result["selected_count"] == 1
    message = cipher.payloads[0]["message"]
    assert message.startswith("Here are the stories:")
    assert "```embeds_results_view" in message
    assert "Full card content" not in message


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.message.standard,workflows.results.selective-embeds
async def test_inline_result_group_keeps_correct_embed_when_first_result_was_sent_before():
    service, workflow, cipher, _, adapter = setup()
    old = {"id": "story-1", "provider": "example", "title": "Old", "url": "https://example.org/old"}
    new = {"id": "story-2", "provider": "example", "title": "New", "url": "https://example.org/new"}
    first = context(service, workflow)
    first["nodes"]["news"]["output"]["results"] = [old]
    await adapter.send_chat_message({"title": "News", "message": "{{ $nodes.news.output.results }}"}, first, "alice")

    second = context(service, workflow)
    second["nodes"]["news"]["output"]["results"] = [old, new]
    delivery = await adapter.send_chat_message({"title": "News", "message": "{{ $nodes.news.output.results }}"}, second, "alice")
    assert delivery["selected_count"] == 1
    assert cipher.payloads[-1]["embeds"][0]["content"] == new
    assert cipher.payloads[-1]["embeds"][0]["embed_id"] in cipher.payloads[-1]["message"]


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.chat-delivery.run-provenance
async def test_legacy_chat_and_report_actions_include_run_provenance():
    service, workflow, cipher, _, adapter = setup()
    ctx = context(service, workflow)
    await adapter.start_new_chat({"title": "Daily", "message": "Update"}, ctx, "alice")
    await adapter.create_chat_report({"title": "Report", "summary": "Summary"}, ctx, "alice")
    expected = f"run-id={ctx['workflow']['run_id']}"
    assert all(expected in payload["message"] for payload in cipher.payloads)


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


# contract-test: supporting surface=rest_api assertions=workflows.message.standard,workflows.control.check
@pytest.mark.asyncio
@pytest.mark.parametrize("flag,expected", [(True, True), (False, False), (None, False)])
async def test_optional_nullable_boolean_block_preserves_equality_check_behavior(flag, expected):
    _, _, _, _, adapter = setup()
    preview = await adapter.preview_message(
        {"title": "Weather", "message": "Update", "blocks": [{"id": "rain", "source": "$nodes.weather.output.summary", "include_if": "$nodes.weather.output.rain_expected"}]},
        {"nodes": {"weather": {"output": {"rain_expected": flag, "summary": "Rain today"}}}},
    )
    assert ("Rain today" in preview["text"]) is expected
