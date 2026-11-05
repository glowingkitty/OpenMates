"""CLI Codex adapter configuration contract: repository mapping and doctor.

Temporary cache/config fixtures stand in for the foreground CLI's private files.
No CLI requests, model invocations or live project hook changes occur here.
See docs/architecture/cli-codex-adapter.md.
"""

import json
import pytest
from scripts import codex_cached_context as cached

THREAD = "00000000-0000-0000-0000-000000000001"
WORKER = "00000000-0000-0000-0000-000000000002"


# contract-test: tooling
def test_runtime_preflight_rejects_modified_hook_without_starting_inference(tmp_path):
    class RPC:
        def call(self, method, params):
            assert method == "hooks/list" and params == {"cwds": [str(tmp_path)]}
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": True, "trustStatus": "modified" if event == "sessionStart" else "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    result = cached.runtime_preflight(tmp_path, RPC())
    assert result["status"] == "needs_attention"
    assert result["hooks_needing_review"] == ["sessionStart"]
    assert "/hooks" in result["resolution"]


# contract-test: tooling
def test_runtime_preflight_requires_all_enabled_project_context_hooks(tmp_path):
    class RPC:
        def call(self, *_):
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": event != "postToolUse", "trustStatus": "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    assert cached.runtime_preflight(tmp_path, RPC())["missing_hooks"] == ["postToolUse"]


# contract-test: tooling
def test_runtime_preflight_accepts_reviewed_project_hooks(tmp_path):
    class RPC:
        def call(self, *_):
            return {"data": [{"hooks": [
                {"eventName": event, "enabled": True, "trustStatus": "trusted",
                 "sourcePath": str(tmp_path / ".codex/hooks.json"), "command": "bash claude-hook-bridge.sh"}
                for event in cached.REQUIRED_CONTEXT_HOOKS]}]}
    assert cached.runtime_preflight(tmp_path, RPC())["status"] == "ready"


# contract-test: tooling
def test_repository_cutover_covers_new_unregistered_chats(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENMATES_STATE_DIR', str(tmp_path / 'cli'))
    config = tmp_path / 'cli/codex-adapter.json'
    config.parent.mkdir()
    entry = {'enabled': True, 'all_threads': True, 'threads': [THREAD], 'snapshots': []}
    config.write_text(json.dumps({'repositories': {str(tmp_path.resolve()): entry}}))
    assert cached.configuration(tmp_path, WORKER) == entry
    entry['all_threads'] = False
    config.write_text(json.dumps({'repositories': {str(tmp_path.resolve()): entry}}))
    assert cached.configuration(tmp_path, WORKER) is None


# contract-test: tooling
def test_configure_persists_project_default_and_explicit_thread_membership(tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "cli"))
    snapshots = []
    for project in ("first", "second"):
        path = tmp_path / f"{project}.json"
        path.write_text(json.dumps({"schema_version": 1, "project_id": project, "tasks": []}))
        snapshots.extend(["--snapshot", str(path)])
    monkeypatch.setattr(sys, "argv", ["codex_cached_context.py", "configure", "--repository", str(tmp_path),
                                    "--thread", THREAD, "--all-threads", "--project", "second", *snapshots])
    assert cached.main() == 0
    config = cached.configuration(tmp_path, THREAD)
    assert config["presence_project_id"] == "second"
    assert config["thread_projects"] == {THREAD: ["second"]}
    assert not config.get("events_enabled")  # Visibility does not enable model starts.


# contract-test: tooling
def test_configure_rejects_project_outside_authenticated_snapshots(tmp_path, monkeypatch):
    import sys

    path = tmp_path / "first.json"
    path.write_text(json.dumps({"schema_version": 1, "project_id": "first", "tasks": []}))
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "cli"))
    monkeypatch.setattr(sys, "argv", ["codex_cached_context.py", "configure", "--repository", str(tmp_path),
                                    "--thread", THREAD, "--project", "foreign", "--snapshot", str(path)])
    with pytest.raises(SystemExit):
        cached.main()
    assert not (tmp_path / "cli/codex-adapter.json").exists()
