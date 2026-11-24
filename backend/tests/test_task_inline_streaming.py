"""Task fences create and edit Tasks through the stream consumer, never through a tool call."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


from backend.apps.ai.processing.focus_mode_routing import SPEC_AUTHORING_FOCUS_ID
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer, task_fence_runtime
from backend.apps.ai.utils.task_fences import task_validation_feedback
from backend.core.api.app.services.directus.user_plan_methods import hash_id

REF = '{"type":"task","embed_id":"task-embed-1"}'


def _request(**extra):
    return AskSkillRequest(chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1",
                           message_history=[], is_incognito=True,
                           project_focus_candidates=[{"project_id": "project-1", "name": "Kitchen renovation"}], **extra)


class FakeEmbedService:
    create_code_embed_placeholder = AsyncMock()
    update_code_embed_content = AsyncMock()

    def __init__(self, *_args, **_kwargs):
        pass


def _install(monkeypatch, chunks):
    async def main_stream(**_kwargs):
        for chunk in chunks:
            yield chunk

    FakeEmbedService.create_json_content_embed_placeholder = AsyncMock(
        return_value={"embed_id": "task-embed-1", "embed_reference": REF})
    FakeEmbedService.update_json_content_embed_content = AsyncMock(return_value=True)
    execute = AsyncMock(return_value={"status": "pending_client_persistence", "event": {"event_type": "created"},
                                      "job": {"job_id": "job-1", "task_id": "task-1"}})
    publish = AsyncMock()
    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
    monkeypatch.setattr(task_fence_runtime, "execute_task_tool_call", execute)
    monkeypatch.setattr(task_fence_runtime, "publish_task_tool_result", publish)
    return execute, publish


class FakeCache:
    """Every cache call is an awaited no-op; the stream only publishes and stores chunks."""

    def __getattr__(self, name):
        mock = AsyncMock(return_value=None)
        setattr(self, name, mock)
        return mock


def _consume(request):
    response, *_ = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=SimpleNamespace(), encryption_service=SimpleNamespace(),
        user_vault_key_id="vault-1", all_mates_configs=[], discovered_apps_metadata={}, cache_service=FakeCache(),
    ))
    return response


def _fence(payload):
    return f"```openmates_task\n{json.dumps(payload)}\n```\n\n"


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_valid_fence_stages_one_create_and_streams_embed_reference(monkeypatch):
    execute, publish = _install(monkeypatch, [_fence({
        "title": "Three minutes by an open window", "due_date": "2026-11-24", "project": "Kitchen renovation"})])
    response = _consume(_request())
    assert response.count(REF) == 1 and "openmates_task" not in response and "Three minutes" not in response
    execute.assert_awaited_once()
    args = execute.await_args.kwargs["args"]
    assert execute.await_args.kwargs["tool_name"] == "task_create"
    assert args["title"] == "Three minutes by an open window" and args["link_to_chat"] is True
    assert args["due_at"] == 1795478400 and args["linked_project_ids"] == ["project-1"]
    assert publish.await_args.kwargs["publish_chat_event"] is False
    finished = [c.kwargs for c in FakeEmbedService.update_json_content_embed_content.await_args_list
                if c.kwargs.get("status") == "finished"]
    assert len(finished) == 1
    content = finished[0]["task_content"]
    assert content["task_id"] == "task-1" and content["validation"]["status"] == "valid"
    assert finished[0]["source_language"] == "openmates_task"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_invalid_fence_creates_no_task_and_shows_errors(monkeypatch):
    execute, _ = _install(monkeypatch, [_fence({"title": "", "status": "done"})])
    response = _consume(_request())
    assert response.count(REF) == 1
    execute.assert_not_awaited()
    final = FakeEmbedService.update_json_content_embed_content.await_args_list[-1].kwargs
    assert final["status"] == "error" and final["task_content"]["validation"]["status"] == "invalid"
    codes = [e["code"] for e in final["task_content"]["validation"]["errors"]]
    assert codes == ["missing_title", "invalid_status"]


# contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
@pytest.mark.parametrize(("plan_chat", "plan_project", "accepted"), [
    ("chat-1", "project-1", True),
    ("other-chat", "project-1", False),
    ("chat-1", "other-project", False),
])
async def test_spec_follow_up_uses_only_the_saved_plans_authorized_project(
    monkeypatch, plan_chat, plan_project, accepted,
):
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService

    execute, publish = _install(monkeypatch, [])
    focus = AsyncMock(return_value={"project_id": "project-1"})
    monkeypatch.setattr(ProjectWriteAuthorizationService, "get_active_focus", focus)
    request = _request(active_focus_id=SPEC_AUTHORING_FOCUS_ID, is_sub_chat_continuation=True)
    request.is_incognito = False
    lookup = AsyncMock(return_value={
        "hashed_primary_chat_id": hash_id(plan_chat), "linked_project_hashes": [hash_id(plan_project)],
    })
    embed_service = FakeEmbedService()

    await task_fence_runtime.finalize_task_fence_embed(
        embed_service=embed_service, embed_id="task-embed-1",
        source=json.dumps({"title": "Wire watering alerts", "plan": "plan-1", "project": "Guessed name"}),
        request_data=request, cache_service=FakeCache(),
        directus_service=SimpleNamespace(user_plan=SimpleNamespace(get_plan=lookup)),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1", log_prefix="test",
    )

    lookup.assert_awaited_once_with("plan-1", request.user_id)
    card = embed_service.update_json_content_embed_content.await_args.kwargs
    if accepted:
        focus.assert_awaited_once_with(user_id=request.user_id, chat_id=request.chat_id)
        execute.assert_awaited_once()
        assert execute.await_args.kwargs["args"]["linked_project_ids"] == ["project-1"]
        publish.assert_awaited_once()
        assert card["status"] == "finished"
    else:
        execute.assert_not_awaited()
        publish.assert_not_awaited()
        assert card["task_content"]["validation"]["errors"][0]["code"] == "unknown_project"


# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local,tasks.surface.semantic-parity
def test_team_inline_task_shows_scope_error_before_staging(monkeypatch):
    execute, publish = _install(monkeypatch, [_fence({"title": "Call Ada"})])
    assert _consume(_request(team_id="team-1")).count(REF) == 1
    execute.assert_not_awaited()
    publish.assert_not_awaited()
    final = FakeEmbedService.update_json_content_embed_content.await_args_list[-1].kwargs
    assert final["status"] == "error"
    assert final["task_content"]["validation"]["errors"][0]["code"] == "team_tasks_unsupported"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_history_text_carries_errors_for_invalid_and_source_for_valid():
    errors = [{"field": "title", "code": "missing_title", "message": "The task needs a title."}]
    invalid = task_fence_runtime.task_embed_history_text(
        {"validation": {"status": "invalid", "errors": errors}, "task_source": "{}"}, "tasks-1")
    assert task_validation_feedback(errors) in invalid and "task_source" in invalid
    valid = task_fence_runtime.task_embed_history_text({"validation": {"status": "valid"}, "task_source": '{"title": "x"}'}, "tasks-1")
    assert '"title": "x"' in valid and "NOT applied" not in valid


CURRENT = {"type": "task", "task_id": "task-1", "task_version": 1, "title": "Call Ada", "status": "todo",
           "task_source": json.dumps({"title": "Call Ada", "status": "todo", "assignee": "user"}, indent=2),
           "validation": {"status": "valid", "errors": [], "warnings": []}}


def _apply(monkeypatch, new_source, current=CURRENT):
    execute = AsyncMock(return_value={"job": {"job_id": "job-2", "task_id": "task-1"}, "event": {}})
    monkeypatch.setattr(task_fence_runtime, "execute_task_tool_call", execute)
    monkeypatch.setattr(task_fence_runtime, "publish_task_tool_result", AsyncMock())
    service = SimpleNamespace(update_json_content_embed_content=AsyncMock(return_value=True))
    note = asyncio.run(task_fence_runtime.apply_task_embed_diff(
        embed_id="task-embed-1", current=current, new_source=new_source, new_version=2,
        version_history_rows=[{"version_number": 2}], content_hash="h", request_data=_request(),
        embed_service=service, cache_service=SimpleNamespace(), directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1", log_prefix="",
    ))
    return note, execute, service.update_json_content_embed_content


# contract-test: direct surface=rest_api assertions=task-inline.edit.diff-versioned
def test_valid_diff_stages_update_and_writes_version_two(monkeypatch):
    note, execute, update = _apply(monkeypatch, json.dumps({"title": "Call Ada", "status": "done", "assignee": "user"}))
    assert note is None
    args = execute.await_args.kwargs["args"]
    assert execute.await_args.kwargs["tool_name"] == "task_update"
    assert args["task_id"] == "task-1" and args["status"] == "done" and args["expected_version"] == 1
    kwargs = update.await_args.kwargs
    assert kwargs["version_number"] == 2 and kwargs["version_history_rows"] == [{"version_number": 2}]
    assert kwargs["task_content"]["status"] == "done" and kwargs["task_content"]["task_update_job_id"] == "job-2"


# contract-test: direct surface=rest_api assertions=task-inline.edit.diff-versioned
def test_invalid_diff_keeps_task_and_marks_embed_invalid(monkeypatch):
    note, execute, update = _apply(monkeypatch, json.dumps({"title": "Call Ada", "status": "someday"}))
    assert note and "not applied" in note
    execute.assert_not_awaited()
    kwargs = update.await_args.kwargs
    assert "version_number" not in kwargs and kwargs["status"] == "error"
    assert kwargs["task_content"]["validation"]["status"] == "invalid"
    assert json.loads(kwargs["source_json"])["status"] == "todo"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back,task-inline.edit.diff-versioned
def test_diff_that_fixes_an_invalid_task_creates_it(monkeypatch):
    never_created = {**CURRENT, "task_id": "", "validation": {"status": "invalid", "errors": [
        {"field": "status", "code": "invalid_status", "message": "Unknown status."}], "warnings": []}}
    note, execute, update = _apply(monkeypatch, json.dumps({"title": "Call Ada", "status": "todo", "assignee": "user"}),
                                   current=never_created)
    assert note is None
    assert execute.await_args.kwargs["tool_name"] == "task_create"
    content = update.await_args.kwargs["task_content"]
    assert content["task_id"] == "task-1" and content["validation"]["status"] == "valid"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_refused_staging_shows_on_the_card_instead_of_failing_the_reply(monkeypatch):
    monkeypatch.setattr(task_fence_runtime, "execute_task_tool_call",
                        AsyncMock(side_effect=ValueError("Plan plan-9 was not found for this user.")))
    monkeypatch.setattr(task_fence_runtime, "publish_task_tool_result", AsyncMock())
    service = SimpleNamespace(update_json_content_embed_content=AsyncMock(return_value=True))
    asyncio.run(task_fence_runtime.finalize_task_fence_embed(
        embed_service=service, embed_id="task-embed-1", source=json.dumps({"title": "Build it", "plan": "plan-9"}),
        request_data=_request(), cache_service=SimpleNamespace(), directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1", log_prefix="",
    ))
    kwargs = service.update_json_content_embed_content.await_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["task_content"]["validation"]["errors"][0]["field"] == "plan"
    assert kwargs["task_content"]["task_id"] == ""


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_sub_chat_task_link_names_a_task_from_this_reply_by_title(monkeypatch):
    from backend.apps.ai import sub_chat_focus_links

    request = _request()
    task_fence_runtime.remember_reply_task(request, "Build the importer", "task-7")
    directus = SimpleNamespace(
        user_task=SimpleNamespace(get_task=AsyncMock(
            return_value={"id": "record-7", "task_id": "task-7", "plan_id": "plan-1"}
        )),
        update_item=AsyncMock(),
    )
    child = {"id": "child-1"}
    link = {"kind": "task", "plan_id": "plan-1", "id": "build the importer"}
    linked = asyncio.run(sub_chat_focus_links._link_task(directus, None, request, child, link, ""))
    assert linked is True
    assert directus.user_task.get_task.await_args.args[0] == "task-7"
    directus.update_item.assert_awaited_once_with(
        "user_tasks", "record-7", {"linked_sub_chat_id": "child-1"}, admin_required=True,
    )
    assert link["id"] == "task-7"
    assert task_fence_runtime.reply_task_id_for_title(SimpleNamespace(chat_id="chat-1", message_id="message-2"), "Build the importer") is None
