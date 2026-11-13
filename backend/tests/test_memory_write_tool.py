"""save_memory: validation, capability gate, loaded-only updates, client job contract, no plaintext logs.

Plan: docs/plans/assistant-memory-writes/plan.yml (T-TOOL)
Run: python3 -m pytest backend/tests/test_memory_write_tool.py -q
"""

# contract-test-file: infrastructure
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import memory_write_tool as tool
from backend.apps.ai.processing.memory_document import build_memory_document
from backend.shared.python_utils.memory_loader import parse_memory_md

TITLE = "Career profile Zebracorn"
WHEN = "Writing applications for Zebracorn roles"
BODY = "Prefers remote roles in Lisbon. Zebracorn-body-marker."
GOOD = {"action": "create", "title": TITLE, "when_to_use": WHEN, "content": BODY}
PRIVATE = (TITLE, WHEN, BODY, "Zebracorn")


def _prepare(args, loaded=frozenset()):
    return tool.prepare_memory_write(args, loaded_ids=set(loaded), chat_id="chat-1", message_id="msg-1")


def _request(**overrides):
    values = dict(user_id="user-1", user_id_hash="hash-1", chat_id="chat-1", message_id="msg-1",
                  client_capabilities=["memory_write_jobs"], is_incognito=False, is_anonymous=False,
                  is_external=False, is_sub_chat=False, is_sub_chat_continuation=False, sub_chat_depth=0,
                  turn_written_entries=[])
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeRedis:
    def __init__(self, store):
        self.store = store

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class FakeCache:
    """Cache double recording everything the server keeps or publishes."""

    def __init__(self):
        self.store = {}
        self.published = []
        self._redis = FakeRedis(self.store)

    @property
    async def client(self):
        return self._redis

    async def get(self, key):
        value = self.store.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    async def set(self, key, value, ttl=None):
        self.store[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        return True

    async def publish_event(self, channel, event):
        self.published.append((channel, event))
        return True


def test_create_builds_canonical_document_with_default_load_mode():
    job = _prepare(GOOD)
    parsed = parse_memory_md(job["document"], memory_id=job["memory_id"], source="personal")
    assert parsed.title == TITLE and parsed.when_to_use == WHEN and parsed.load_mode == "ask_first"
    assert tool.DEFAULT_ASSISTANT_MEMORY_LOAD_MODE == "ask_first"
    assert job["action"] == "create" and len(job["memory_id"]) == 36


def test_payload_shape():
    job = _prepare({**GOOD, "load_mode": "auto_include", "valid_until": "2027-12-31"})
    assert set(job) == {"protocol", "job_id", "action", "memory_id", "document", "title", "chat_id",
                        "message_id", "expires_at"}
    assert job["protocol"] == 1 and job["chat_id"] == "chat-1" and job["message_id"] == "msg-1"
    assert "load_mode: auto_include" in job["document"] and "valid_until" in job["document"]


def test_build_memory_document_load_mode_parameter_defaults_to_ask_first():
    assert "load_mode: ask_first" in build_memory_document("T", "W", "B")
    assert "load_mode: mention_only" in build_memory_document("T", "W", "B", load_mode="mention_only")


@pytest.mark.parametrize("bad, fragment", [
    ({**GOOD, "content": "api_key: abcdef123456"}, "secret"),
    ({**GOOD, "title": "token: abcdef123456"}, "secret"),
    ({**GOOD, "when_to_use": "password = hunter2hunter2"}, "secret"),
    ({**GOOD, "content": "x" * 8_001}, "too long"),
    ({**GOOD, "valid_from": "next tuesday"}, "ISO dates"),
    ({**GOOD, "valid_until": 20271231}, "ISO dates"),
    ({**GOOD, "valid_from": "2028-01-01", "valid_until": "2027-01-01"}, "valid document"),
    ({**GOOD, "load_mode": "always"}, "load_mode"),
    ({**GOOD, "action": "delete"}, "action"),
    ({**GOOD, "content": ""}, "required"),
    ({**GOOD, "title": "line\x07bell"}, "required"),
    ({**GOOD, "extra": "x"}, "Unknown"),
    (None, "object"),
])
def test_validation_rejects(bad, fragment):
    with pytest.raises(tool.MemoryWriteToolError) as exc:
        _prepare(bad)
    assert fragment in str(exc.value)
    assert not any(text in str(exc.value) for text in PRIVATE)


def test_update_requires_memory_loaded_in_this_turn():
    with pytest.raises(tool.MemoryWriteToolError) as exc:
        _prepare({**GOOD, "action": "update", "memory_id": "mem-9"}, loaded={"mem-1"})
    assert "not loaded" in str(exc.value) and "create a new Memory" in str(exc.value)
    with pytest.raises(tool.MemoryWriteToolError):
        _prepare({**GOOD, "action": "update"}, loaded={"mem-1"})
    job = _prepare({**GOOD, "action": "update", "memory_id": "mem-1"}, loaded={"mem-1"})
    assert job["memory_id"] == "mem-1" and job["action"] == "update"


def test_loaded_ids_are_personal_only():
    memories = [SimpleNamespace(id="mem-1", source="personal"), SimpleNamespace(id="p:1", source="project"),
                SimpleNamespace(id="app:x", source="app")]
    assert tool.loaded_personal_memory_ids(memories) == {"mem-1"}


@pytest.mark.parametrize("overrides, enabled", [
    ({}, True),
    ({"client_capabilities": ["task_update_jobs"]}, False),
    ({"client_capabilities": None}, False),
    ({"is_incognito": True}, False),
    ({"is_anonymous": True}, False),
    ({"is_external": True}, False),
    ({"is_sub_chat": True}, False),
    ({"is_sub_chat_continuation": True}, False),
    ({"sub_chat_depth": 1}, False),
    ({"user_id": None}, False),
])
def test_capability_gate(overrides, enabled):
    assert tool.save_memory_enabled(_request(**overrides)) is enabled


def test_tool_definition_and_names():
    definition = tool.save_memory_tool()["function"]
    assert definition["name"] == "save_memory"
    assert set(definition["parameters"]["required"]) == {"action", "title", "when_to_use", "content"}
    assert set(definition["parameters"]["properties"]) == {
        "action", "memory_id", "title", "when_to_use", "content", "load_mode", "valid_from", "valid_until"}
    assert tool.is_save_memory_tool_name("save-memory") and not tool.is_save_memory_tool_name("load_memories")


async def _client(cache, *, device="dev-a", status="applied", claim=True, report=True, memory_id=None):
    """Simulated capable client: waits for the job event, claims it, reports the outcome."""
    while not cache.published:
        await asyncio.sleep(0.01)
    _, event = cache.published[0]
    if not claim:
        return event
    granted, _ = await tool.claim_memory_write_job(cache, user_id="user-1", device_hash=device, payload={
        "protocol": 1, "job_id": event["job_id"], "chat_id": event["chat_id"]})
    assert granted
    if report:
        accepted, reason = await tool.record_memory_write_result(cache, user_id="user-1", device_hash=device, payload={
            "protocol": 1, "job_id": event["job_id"], "chat_id": event["chat_id"], "status": status,
            "memory_id": memory_id or event["memory_id"], "error_code": None if status == "applied" else "store_failed"})
        assert accepted, reason
    return event


async def _run(cache, request, args=GOOD, **client_kwargs):
    client = asyncio.create_task(_client(cache, **client_kwargs))
    result = await tool.dispatch_save_memory(arguments=args, request=request, approved_memories=[],
                                             cache_service=cache, claim_timeout=0.3, result_timeout=0.3)
    return result, await client


def test_applied_result_is_reported_and_recorded_for_postprocessing(caplog):
    caplog.set_level(logging.DEBUG)
    cache, request = FakeCache(), _request()
    result, event = asyncio.run(_run(cache, request))
    assert result["status"] == "applied" and result["memory_id"] == event["memory_id"]
    assert request.turn_written_entries == [{"kind": "memory", "target_id": event["memory_id"], "title": TITLE}]
    channel, published = cache.published[0]
    assert channel == "chat_stream::chat-1" and published["type"] == "memory_write_job_available"
    assert published["user_id_uuid"] == "user-1" and BODY in published["document"]
    # The server keeps ids/state only: no Memory text in Redis and none in logs.
    stored = json.dumps(cache.store)
    assert not any(text in stored for text in PRIVATE)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert not any(text in logged for text in PRIVATE)


def test_failed_result_is_reported_truthfully():
    cache, request = FakeCache(), _request()
    result, _ = asyncio.run(_run(cache, request, status="failed"))
    assert result["status"] == "failed" and result["error_code"] == "store_failed"
    assert request.turn_written_entries == []


def test_unclaimed_job_expires_and_cannot_be_claimed_later():
    cache, request = FakeCache(), _request()
    result, event = asyncio.run(_run(cache, request, claim=False))
    assert result["status"] == "not_saved" and "NOT saved" in result["message"]
    granted, reason = asyncio.run(tool.claim_memory_write_job(cache, user_id="user-1", device_hash="dev-a", payload={
        "protocol": 1, "job_id": event["job_id"], "chat_id": "chat-1"}))
    assert not granted and reason == "already_claimed"


def test_claimed_without_result_is_unconfirmed():
    cache, request = FakeCache(), _request()
    result, _ = asyncio.run(_run(cache, request, report=False))
    assert result["status"] == "unconfirmed" and "Do not say it was saved" in result["message"]
    assert request.turn_written_entries == []


def test_only_claiming_device_may_report_and_only_once():
    cache, request = FakeCache(), _request()
    _, event = asyncio.run(_run(cache, request))
    payload = {"protocol": 1, "job_id": event["job_id"], "chat_id": "chat-1", "status": "applied",
               "memory_id": event["memory_id"]}
    assert asyncio.run(tool.record_memory_write_result(cache, user_id="user-1", device_hash="dev-b", payload=payload)) \
        == (False, "not_claimed_by_device")
    assert asyncio.run(tool.record_memory_write_result(cache, user_id="user-1", device_hash="dev-a", payload=payload)) \
        == (False, "already_reported")
    assert asyncio.run(tool.record_memory_write_result(cache, user_id="user-2", device_hash="dev-a", payload=payload)) \
        == (False, "not_found")
    assert asyncio.run(tool.claim_memory_write_job(cache, user_id="user-1", device_hash="dev-b", payload={
        "protocol": 1, "job_id": event["job_id"], "chat_id": "other-chat"})) == (False, "not_found")


def test_rejected_call_publishes_nothing():
    cache, request = FakeCache(), _request()
    result = asyncio.run(tool.dispatch_save_memory(
        arguments={**GOOD, "action": "update", "memory_id": "mem-x"}, request=request, approved_memories=[],
        cache_service=cache))
    assert result["status"] == "rejected" and not cache.published and not cache.store


def test_workflow_writes_are_recorded_from_create_or_modify_results():
    request = _request()
    tool.record_workflow_writes(request, "workflows", "create-or-modify", [
        {"success": True, "status": "finished", "workflow": {"workflow_id": "wf-1", "title": "Weekly CFP alert"},
         "workflows": [{"workflow_id": "wf-1", "title": "Weekly CFP alert"}]},
        {"success": True, "status": "needs_clarification"},
        {"success": False, "status": "error"},
    ])
    tool.record_workflow_writes(request, "web", "search", [{"success": True, "workflow": {"workflow_id": "x"}}])
    assert request.turn_written_entries == [{"kind": "workflow", "target_id": "wf-1", "title": "Weekly CFP alert"}]


# --- Project target (Plan: docs/plans/press-release-focus-mode/plan.yml, T-TOOL-PROJECT) ---

def test_target_is_offered_only_with_project_target():
    personal = tool.save_memory_tool()["function"]["parameters"]["properties"]
    project = tool.save_memory_tool(project_target=True)["function"]["parameters"]["properties"]
    assert "target" not in personal
    assert project["target"]["enum"] == ["personal", "project"]


def test_project_target_becomes_one_canonical_project_memory_file():
    args = tool.project_memory_file_arguments({**GOOD, "target": "project", "load_mode": "auto_include"})
    assert set(args) == {"path", "expected_base", "content"} and args["expected_base"] is None
    assert args["path"].startswith(".openmates/memories/") and args["path"].endswith(".md")
    assert args["content"] == build_memory_document(TITLE, WHEN, BODY, load_mode="auto_include")
    parsed = parse_memory_md(args["content"], memory_id="draft", source="project", project_id="project-1")
    assert parsed.title == TITLE
    assert tool.project_memory_file_arguments({**GOOD, "target": "project"})["path"] != args["path"]


def test_project_memory_defaults_to_auto_include_so_the_project_loads_it():
    # contract-test: direct surface=rest_api assertions=app-memories.selection.source-scoped
    args = tool.project_memory_file_arguments({**GOOD, "target": "project"})
    assert parse_memory_md(args["content"], memory_id="draft", source="project", project_id="p").load_mode == "auto_include"
    mention = tool.project_memory_file_arguments({**GOOD, "target": "project", "load_mode": "mention_only"})
    assert "load_mode: mention_only" in mention["content"]


@pytest.mark.parametrize("args, reason", [
    ({**GOOD, "target": "project", "load_mode": "ask_first"}, "loads automatically"),
    ({**GOOD, "target": "project", "action": "update"}, "project_update_file"),
    ({**GOOD, "target": "project", "memory_id": "m-1"}, "Unknown"),
    ({**GOOD, "target": "project", "content": "api_key: abcdef123456"}, "secret"),
    ({**GOOD, "target": "project", "load_mode": "always"}, "load_mode"),
    ({**GOOD, "target": "personal"}, "target must be project"),
])
def test_project_target_rejections(args, reason):
    with pytest.raises(tool.MemoryWriteToolError, match=reason):
        tool.project_memory_file_arguments(args)


def test_project_target_without_project_focus_is_rejected_and_nothing_is_dispatched(caplog):
    published = []

    class Cache:
        async def set(self, *a, **k):
            raise AssertionError("no job may be stored")

        async def publish_event(self, *a, **k):
            published.append(a)

    caplog.set_level(logging.INFO)
    result = asyncio.run(tool.dispatch_save_memory(
        arguments={**GOOD, "target": "project"}, request=_request(), approved_memories=[], cache_service=Cache()))
    assert result["status"] == "rejected" and "Project Focus" in result["message"]
    assert not published
    assert not any(marker in caplog.text for marker in PRIVATE)


def test_personal_target_keeps_the_personal_job():
    job = _prepare({**GOOD, "target": "personal"})
    assert job["action"] == "create" and job["document"].startswith("---\n")


def test_main_processor_rewrites_project_saves_only_with_authorized_project_tools():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("apps/ai/processing/main_processor.py").read_text()
    gate = ("save_memory_project_target = bool(\n"
            "        save_memory_chat_allowed(request_data) and project_file_tools_enabled and active_project_focus)")
    assert gate in source
    assert "elif not save_memory_available:" in source
    rewrite = source.index("chunk.function_name = _canonicalize_tool_name(PROJECT_MEMORY_FILE_TOOL)")
    guard = source.rindex("save_memory_project_target", 0, rewrite)
    assert "_canonicalize_tool_name(PROJECT_MEMORY_FILE_TOOL) in iteration_allowed_tool_names" in source[guard:rewrite]
    assert rewrite < source.index("tool_calls_for_this_turn.append(chunk)", rewrite)


def test_project_only_tool_for_clients_without_personal_memory_jobs():
    project_only = tool.save_memory_tool(project_target=True, personal=False)["function"]
    assert project_only["parameters"]["properties"]["target"]["enum"] == ["project"]
    assert "target" in project_only["parameters"]["required"]
    assert "personal" not in project_only["description"].lower()
    with pytest.raises(ValueError):
        tool.save_memory_tool(project_target=False, personal=False)


def test_project_save_needs_no_personal_capability_but_a_normal_chat():
    assert tool.save_memory_chat_allowed(_request(client_capabilities=["project_file_jobs"]))
    assert not tool.save_memory_enabled(_request(client_capabilities=["project_file_jobs"]))
    for blocked in ({"is_incognito": True}, {"is_sub_chat": True}, {"is_anonymous": True}, {"user_id": None}):
        assert not tool.save_memory_chat_allowed(_request(**blocked))


def test_missing_target_defaults_to_project_only_without_personal_jobs():
    assert tool.with_default_project_target(GOOD, personal_available=False)["target"] == "project"
    assert "target" not in tool.with_default_project_target(GOOD, personal_available=True)
    explicit = {**GOOD, "target": "personal"}
    assert tool.with_default_project_target(explicit, personal_available=False) == explicit
