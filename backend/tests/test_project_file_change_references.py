"""Reference-only chat events for applied Project file changes."""

import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.apps.ai.processing import project_file_change_references as changes
from backend.apps.ai.processing.project_file_change_references import (
    build_project_file_change_preview, publish_inline_project_file_change,
    publish_project_file_change_preview,
)

REVISION = "a" * 64


def context(skill="project_update_file", arguments=None):
    return {
        "app_id": "system", "skill_id": skill, "tool_arguments": arguments or {"path": "src/app.py"},
        "request_data": {"active_project_focus": {"project_id": "project"}, "team_id": "team",
                         "project_focus_candidates": [{"project_id": "project", "name": "Shop"}]},
    }


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_applied_update_row_has_locations_and_revision_only() -> None:
    preview = build_project_file_change_preview(
        context=context(), result_status="completed",
        completed_results=[{"status": "completed", "expected_base": REVISION,
                            "content": "DO_NOT_COPY", "diff": "DO_NOT_COPY"}],
    )
    assert preview["origin"] == "file_tool"
    assert preview["results"] == [{"project_id": "project", "project_name": "Shop", "path": "src/app.py",
                                   "action": "updated", "expected_base": REVISION, "team_id": "team"}]
    assert "DO_NOT_COPY" not in json.dumps(preview)


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_rename_carries_from_path_and_bad_revision_is_dropped() -> None:
    preview = build_project_file_change_preview(
        context=context("project_rename_file", {"path": "a.py", "new_path": "b/c.py"}),
        result_status="completed", completed_results=[{"status": "completed", "revision": "short"}],
    )
    row = preview["results"][0]
    assert (row["action"], row["path"], row["from_path"]) == ("renamed", "b/c.py", "a.py")
    assert "expected_base" not in row


@pytest.mark.parametrize("result", [
    {"status": "rejected"}, {"status": "completed", "idempotent": True},
    {"status": "completed", "refused": True}, {"status": "failed"},
])
# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_refused_idempotent_and_failed_steps_publish_no_row(result) -> None:
    assert build_project_file_change_preview(
        context=context(), result_status="completed", completed_results=[result]) is None


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
@pytest.mark.parametrize("path", ["../x", "/abs", "a//b", "a\\b", "./a", ""])
def test_unsafe_paths_are_not_published(path) -> None:
    assert build_project_file_change_preview(
        context=context(arguments={"path": path}), result_status="completed",
        completed_results=[{"status": "completed"}]) is None


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_deleted_row_has_no_revision() -> None:
    preview = build_project_file_change_preview(
        context=context("project_delete_file", {"path": "old.txt"}), result_status="completed",
        completed_results=[{"status": "completed", "expected_base": REVISION}])
    assert preview["results"][0]["action"] == "deleted"
    assert "expected_base" not in preview["results"][0]


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_command_write_back_is_one_batch_of_committed_and_merged_paths() -> None:
    ctx = {"app_id": "code", "skill_id": "run", "request_data": context()["request_data"]}
    preview = build_project_file_change_preview(
        context=ctx, result_status="completed",
        completed_results=[{"write_back": {"committed": ["a.py", "../bad"], "merged": ["b.py", "a.py"],
                                           "conflicts": [{"path": "c.py"}], "rejected": []},
                            "changed_files": [{"path": "a.py", "kind": "created"}]}])
    assert preview["origin"] == "command"
    assert [(r["path"], r["action"]) for r in preview["results"]] == [("a.py", "created"), ("b.py", "updated")]
    assert build_project_file_change_preview(
        context=ctx, result_status="completed", completed_results=[{"write_back": {"committed": []}}]) is None


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
def test_sandbox_rows_only_for_committed_paths() -> None:
    ok = {"status": "completed", "write_back": {"committed": ["n.py"], "merged": [], "conflicts": [], "rejected": []}}
    assert changes.sandbox_change_rows("create_file", {"path": "n.py"}, ok) == [{"path": "n.py", "action": "created"}]
    refused = {**ok, "write_back": {"committed": [], "rejected": [{"path": "n.py"}]}}
    assert changes.sandbox_change_rows("create_file", {"path": "n.py"}, refused) == []
    assert changes.sandbox_change_rows("read_text", {"path": "n.py"}, ok) == []


@pytest.fixture
def turn_key_import(monkeypatch):
    module = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    module.async_skill_latest_user_turn_key = lambda user, chat: f"turn:{user}:{chat}"
    monkeypatch.setitem(sys.modules, module.__name__, module)


def request(continuation=True):
    return SimpleNamespace(active_project_focus={"project_id": "project"}, is_async_skill_continuation=continuation,
                           user_id="u", chat_id="c", message_id="m", user_id_hash="h",
                           project_focus_candidates=[{"project_id": "project", "name": "Shop"}])


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
@pytest.mark.asyncio
async def test_publication_call_shape_and_fencing(monkeypatch, turn_key_import) -> None:
    create = AsyncMock(return_value={"embed_reference": "REF"})
    service = MagicMock(create_embeds_from_skill_results=create)
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", lambda *a: service)
    preview = {"project_id": "project", "origin": "command", "results": [
        {"project_id": "project", "project_name": "Shop", "path": "a.py", "action": "updated",
         "expected_base": REVISION, "content": "LEAK", "snippet": "LEAK"},
        {"project_id": "other", "path": "x.py", "action": "updated"}]}
    cache = MagicMock(get=AsyncMock(return_value="turn-1"))
    monkeypatch.setattr("backend.shared.python_utils.recent_work_summary_client.authoritative_context_turn_id",
                        lambda req: "turn-1")
    ref = await publish_project_file_change_preview(
        preview=preview, request_data=request(), cache_service=cache, directus_service=object(),
        encryption_service=object(), user_vault_key_id="k", task_id="t", log_prefix="p")
    assert ref == "REF"
    kwargs = create.await_args.kwargs
    assert (kwargs["app_id"], kwargs["skill_id"]) == ("projects", "change")
    assert kwargs["request_metadata"] == {"origin": "command"}
    assert kwargs["results"] == [{"project_id": "project", "project_name": "Shop", "path": "a.py",
                                  "action": "updated", "expected_base": REVISION}]
    cache.get = AsyncMock(return_value="newer-turn")
    with pytest.raises(Exception, match="superseded"):
        await publish_project_file_change_preview(
            preview=preview, request_data=request(), cache_service=cache, directus_service=object(),
            encryption_service=object(), user_vault_key_id="k", task_id="t", log_prefix="p")


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,code-run.cloud.command-changes-sync-back
@pytest.mark.asyncio
async def test_inline_sandbox_write_publishes_file_tool_origin(monkeypatch) -> None:
    create = AsyncMock(return_value={"embed_reference": "INLINE"})
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService",
                        lambda *a: MagicMock(create_embeds_from_skill_results=create))
    envelope = {"status": "completed", "write_back": {"committed": ["n.py"], "merged": []}}
    args = dict(request_data=request(continuation=False), operation="create_file",
                operation_arguments={"path": "n.py"}, dispatch_focus={"project_id": "project", "team_id": "t1"},
                cache_service=object(), directus_service=object(), encryption_service=object(),
                user_vault_key_id="k", task_id="t", log_prefix="p")
    assert await publish_inline_project_file_change(envelope=envelope, **args) == "INLINE"
    kwargs = create.await_args.kwargs
    assert kwargs["request_metadata"] == {"origin": "file_tool"}
    assert kwargs["results"][0]["action"] == "created" and kwargs["results"][0]["team_id"] == "t1"
    create.reset_mock()
    assert await publish_inline_project_file_change(
        envelope={"status": "completed", "write_back": {"committed": []}}, **args) is None
    create.assert_not_awaited()
