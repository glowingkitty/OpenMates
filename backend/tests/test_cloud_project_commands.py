# backend/tests/test_cloud_project_commands.py
#
# Cloud Project commands (code.run target e2b with argv): the file-command
# refusal, limits, snapshot handoff, workspace sync planning and change
# detection, the apply_changes argument checks and the parked completion.
# Spec: feature.app-skill.code-run code-run.commands.files-through-file-tools,
# code-run.cloud.commands, code-run.cloud.workspace, code-run.cloud.command-changes-sync-back.

import asyncio

import pytest

from backend.apps.ai.processing import project_test_snapshot as pts
from backend.apps.code.cloud_command import cloud_command_limits, command_display, file_command_refusal
from backend.apps.code.tasks import cloud_command_execution as cce
from backend.core.api.app.services.project_file_operation_service import (
    ProjectFileOperationError,
    ProjectFileOperationService,
)
from backend.shared.providers.e2b_project_workspace import (
    content_sha256,
    detect_changes,
    plan_sync,
    truncate_for_model,
)


class FakeCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.parametrize("argv", [
    ["cat", "src/app.js"],
    ["/usr/bin/head", "-n", "5", "README.md"],
    ["sed", "-i", "s/a/b/", "x.js"],
    ["perl", "-pi", "-e", "s/a/b/", "x.js"],
    ["tee", "out.txt"],
    ["nano", "x.js"],
    ["bash", "-c", "echo hi > notes.txt"],
    ["sh", "-lc", "npm test && cat package.json"],
])
# contract-test: supporting surface=rest_api assertions=code-run.commands.files-through-file-tools
def test_file_reads_and_edits_are_refused(argv):
    refusal = file_command_refusal(argv)
    assert refusal and "Project file tools" in refusal


@pytest.mark.parametrize("argv", [
    ["npm", "install"],
    ["npm", "run", "build"],
    ["npx", "vitest", "run"],
    ["bash", "-c", "npm test 2>&1"],
    ["bash", "-c", "npm run build > /dev/null"],
    ["sed", "--version"],
])
# contract-test: supporting surface=rest_api assertions=code-run.commands.files-through-file-tools
def test_execution_commands_pass(argv):
    assert file_command_refusal(argv) is None


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_limits_bound_foreground_and_require_ready_url_for_background():
    assert cloud_command_limits(background=False, timeout_seconds=600, ready_url=None) == (600, None)
    assert cloud_command_limits(background=False, timeout_seconds=4000, ready_url=None)[1]
    assert cloud_command_limits(background=True, timeout_seconds=600, ready_url=None)[1]
    assert cloud_command_limits(background=True, timeout_seconds=600, ready_url="https://example.org")[1]
    assert cloud_command_limits(background=True, timeout_seconds=600, ready_url="http://localhost:5173") == (300, None)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_command_display_shows_cwd():
    assert command_display(["npm", "test"], "web-app") == "$ cd web-app && npm test\n"
    assert command_display(["npm", "test"], ".") == "$ npm test\n"


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands,code-run.cloud.workspace
def test_cloud_command_snapshot_handoff_takes_whole_project_and_drops_forged_files():
    forged = {"target": "e2b", "argv": ["npm", "test"], "files": [{"path": "x", "code": "y"}], "project_snapshot": True}
    cleaned = pts.without_forged_snapshot(forged)
    assert "files" not in cleaned and "project_snapshot" not in cleaned
    assert pts.needs_snapshot(cleaned)
    assert pts.snapshot_prefix(cleaned) is None
    injected = pts.inject_snapshot(cleaned, {"files": [{"path": "web-app/package.json", "code": "{}", "revision": "r1"}]})
    assert injected["project_snapshot"] is True
    assert injected["files"] == [{"path": "web-app/package.json", "code": "{}"}]
    assert not pts.needs_snapshot(injected)
    remote = {"target": "remote_source", "argv": ["npm", "test"], "files": []}
    assert pts.without_forged_snapshot(remote) == remote


# contract-test: supporting surface=rest_api assertions=code-run.cloud.workspace
def test_plan_sync_writes_changed_and_deletes_only_previously_synced():
    snapshot = {"a.js": "1", "b.js": "2"}
    synced = {"a.js": content_sha256("1"), "gone.js": content_sha256("x")}
    writes, deletes = plan_sync(snapshot, synced)
    assert writes == ["b.js"]
    assert deletes == ["gone.js"]


# contract-test: supporting surface=rest_api assertions=code-run.cloud.command-changes-sync-back
def test_detect_changes_reports_create_update_delete_and_unsynced_once():
    snapshot_shas = {"package.json": content_sha256("{}"), "old.js": content_sha256("o")}
    scanned = {"package.json": content_sha256('{"a":1}'), "package-lock.json": content_sha256("{}"), "logo.png": "binary"}
    changed, deleted, not_synced, unsynced = detect_changes(scanned, snapshot_shas, {})
    assert changed == [("package-lock.json", "create"), ("package.json", "update")]
    assert deleted == ["old.js"]
    assert not_synced == [{"path": "logo.png", "reason": "binary_file"}]
    _, _, not_synced_again, _ = detect_changes(scanned, snapshot_shas, unsynced)
    assert not_synced_again == []


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_truncate_for_model_keeps_head_and_tail():
    text, truncated = truncate_for_model("a" * 50 + "b" * 50, limit=20)
    assert truncated and text.startswith("a" * 10) and text.endswith("b" * 10) and "omitted" in text
    assert truncate_for_model("short", limit=20) == ("short", False)


def _valid_apply_changes():
    return {"origin": "command", "execution_id": "exec-1", "changes": [
        {"path": "web-app/package-lock.json", "kind": "create", "expected_base": None, "content": "{}"},
        {"path": "web-app/package.json", "kind": "update", "expected_base": "a" * 64, "content": "{}"},
        {"path": "web-app/old.js", "kind": "delete", "expected_base": "b" * 64},
    ]}


# contract-test: supporting surface=rest_api assertions=code-run.cloud.command-changes-sync-back
def test_apply_changes_arguments_are_validated():
    ProjectFileOperationService._validate_apply_changes(_valid_apply_changes())
    bad_cases = []
    for mutate in (
        lambda a: a.update(origin="model"),
        lambda a: a["changes"].append(dict(a["changes"][0])),
        lambda a: a["changes"][0].update(path="../escape.js"),
        lambda a: a["changes"][1].update(expected_base="not-a-hash"),
        lambda a: a["changes"][2].update(content="x"),
        lambda a: a.update(changes=[]),
    ):
        args = _valid_apply_changes()
        mutate(args)
        bad_cases.append(args)
    too_many = _valid_apply_changes()
    too_many["changes"] = [
        {"path": f"f{i}.js", "kind": "create", "expected_base": None, "content": ""} for i in range(21)
    ]
    bad_cases.append(too_many)
    for args in bad_cases:
        with pytest.raises(ProjectFileOperationError):
            ProjectFileOperationService._validate_apply_changes(args)


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_command_completion_bounds_output_and_hides_snapshot_paths():
    completion = {"output": "x" * 70_000, "files": ["a.js", "b.js"], "status": "finished"}
    final_status = {"changed_files": [{"path": "package-lock.json", "kind": "create"}], "workspace": {"reused": True}}
    result = cce.command_completion(completion, final_status, {"argv": ["npm", "run", "build"], "cwd": "web-app"})
    assert result["command"] == "$ cd web-app && npm run build"
    assert result["files"] == []
    assert result["output_truncated"] is True and len(result["output"]) < 70_000
    assert result["changed_files"] == final_status["changed_files"]
    assert result["workspace"] == {"reused": True}


# contract-test: supporting surface=rest_api assertions=code-run.cloud.command-changes-sync-back
def test_parked_completion_is_taken_once_with_sync_back_outcome():
    cache = FakeCache()
    key = cce.parked_completion_key("op-1")
    cache.values[key] = {"completion": {"execution_id": "exec-1"}, "result_status": "finished",
                         "request_metadata": {"chat_id": "c"}}
    taken = asyncio.run(cce.take_parked_completion(cache, "op-1", "completed", {"applied": 2, "refused": 0, "files": "x"}))
    assert taken["completed_results"] == [{"execution_id": "exec-1",
                                          "sync_back": {"status": "completed", "applied": 2, "refused": 0}}]
    assert taken["result_status"] == "finished" and taken["request_metadata"] == {"chat_id": "c"}
    assert asyncio.run(cce.take_parked_completion(cache, "op-1", "completed", {})) is None


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands,code-run.cloud.workspace
def test_snapshot_result_quotes_the_paused_call_once():
    paused = {"argv": ["npm", "install"], "cwd": "web-app", "files": [{"path": "x", "code": "y"}],
              "_chat_id": "c", "project_snapshot": True, "timeout_seconds": None}
    call = pts.repeatable_call(paused)
    assert call == {"argv": ["npm", "install"], "cwd": "web-app"}
    result = pts.compact_snapshot_result("op-1", [{"path": "a"}], False, call)
    assert result["repeat_call"] == call
    assert '"argv": ["npm", "install"]' in result["message"] and "exactly" in result["message"]
    assert "repeat_call" not in pts.compact_snapshot_result("op-1", [], False)
    cache = FakeCache()
    cache.values[pts.repeat_call_key("op-1")] = call
    assert asyncio.run(pts.take_repeat_call(cache, "op-1")) == call
    assert asyncio.run(pts.take_repeat_call(cache, "op-1")) is None


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_identical_successful_command_is_not_run_again_in_the_turn():
    from backend.apps.code import cloud_command_repeat as repeat

    files = [("web-app/package.json", "{}"), ("web-app/src/App.jsx", "x")]
    fp = repeat.command_fingerprint(["npm", "run", "build"], "web-app", files)
    assert fp == repeat.command_fingerprint(["npm", "run", "build"], "web-app/", list(reversed(files)))
    assert fp != repeat.command_fingerprint(["npm", "run", "build"], None, files)
    assert fp != repeat.command_fingerprint(["npm", "run", "build"], "web-app", [*files, ("web-app/package-lock.json", "{}")])
    assert fp != repeat.command_fingerprint(["npm", "run", "build"], "web-app", [(files[0][0], '{"a":1}'), files[1]])
    cache = FakeCache()
    payload = {"chat_id": "c", "message_id": "m", "command_run": {"repeat_fingerprint": fp, "background": False}}
    completion = {"command": "$ cd web-app && npm run build", "output": "x" * 5000 + "built", "changed_files": []}
    asyncio.run(cce.remember_if_succeeded(cache, payload=payload, final_status={"status": "failed", "exit_code": 1},
                                          completion=completion))
    assert asyncio.run(repeat.previous_success(cache, chat_id="c", message_id="m", fingerprint=fp)) is None
    asyncio.run(cce.remember_if_succeeded(cache, payload=payload, final_status={"status": "finished", "exit_code": 0},
                                          completion=completion))
    previous = asyncio.run(repeat.previous_success(cache, chat_id="c", message_id="m", fingerprint=fp))
    assert previous["exit_code"] == 0 and previous["output_tail"].endswith("built")
    assert len(previous["output_tail"]) == repeat.REPEAT_OUTPUT_TAIL_CHARS
    assert "npm run build" in repeat.repeat_note(previous) and "answer the user" in repeat.repeat_note(previous)
    assert asyncio.run(repeat.previous_success(cache, chat_id="c", message_id="other", fingerprint=fp)) is None
    background = {**payload, "command_run": {"repeat_fingerprint": "bg", "background": True}}
    asyncio.run(cce.remember_if_succeeded(cache, payload=background, final_status={"status": "finished", "exit_code": 0},
                                          completion=completion))
    assert asyncio.run(repeat.previous_success(cache, chat_id="c", message_id="m", fingerprint="bg")) is None
