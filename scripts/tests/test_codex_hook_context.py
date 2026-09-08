"""Exercise Codex hook routing with isolated session metadata.

These tests inspect executable shell and patch rewrites, not config strings.
They preserve shared read-only control-plane access and parent identity.
No live task, worktree, Docker service or hook configuration is mutated.
See docs/plans/codex-session-runtime-isolation/plan.yml.
"""

# contract-test-file: tooling
import pytest
from scripts import codex_hook_context as hooks


def test_shell_routes_relative_work_to_bound_workspace(tmp_path):
    output = hooks.route(
        "PreToolUse",
        {"tool_name": "Bash", "tool_input": {"command": "pwd"}, "cwd": "/root"},
        tmp_path,
        "abcd",
    )
    command = output["hookSpecificOutput"]["updatedInput"]["command"]
    assert command.endswith("&&\npwd")
    assert str(tmp_path) in command


def test_patch_outside_binding_is_denied(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        hooks.route(
            "PreToolUse",
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Update File: /other/file.py\n@@\n-a\n+b"
                },
            },
            tmp_path,
            "abcd",
        )


def test_relative_patch_is_anchored_and_parent_metadata_is_context(tmp_path):
    output = hooks.route(
        "PreToolUse",
        {
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Add File: file.py\n+hello"},
        },
        tmp_path,
        "abcd",
    )
    assert (
        f"*** Add File: {tmp_path}/file.py"
        in output["hookSpecificOutput"]["updatedInput"]["command"]
    )
    context = hooks.route("SessionStart", {}, tmp_path, "abcd")["hookSpecificOutput"][
        "additionalContext"
    ]
    assert "--session abcd" in context and str(tmp_path) in context


def test_shell_preserves_explicit_package_directory(tmp_path):
    package = tmp_path / "frontend"
    package.mkdir()
    output = hooks.route(
        "PreToolUse",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "pwd", "workdir": str(package)},
        },
        tmp_path,
        "abcd",
    )
    assert str(package) in output["hookSpecificOutput"]["updatedInput"]["command"]


def test_merge_preserves_guard_denial_over_routing_allow():
    import json

    outputs = [
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "shared guard",
            }
        },
        {"decision": "block", "reason": "lease belongs to another task"},
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {"command": "pwd"},
            }
        },
    ]
    result = hooks.merge_outputs(
        "PreToolUse", "\n".join(json.dumps(item) for item in outputs)
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "updatedInput" not in result["hookSpecificOutput"]
    assert "shared guard" in result["hookSpecificOutput"]["additionalContext"]


def test_task_context_is_bounded_cached_and_preserves_activity(tmp_path):
    from scripts.codex_task_context import task_context

    calls = []

    def reader(root, args):
        calls.append(args)
        if args[0] == "activity":
            return {"entries": [{"message": "Required check remains"}]}
        return {
            "complete": True,
            "tasks": [
                {"short_id": "TASK-1", "title": "Assigned goal", "status": "in_progress"}
            ]
        }

    tid = "00000000-0000-0000-0000-000000000001"
    first = task_context(tmp_path, tid, True, 100, reader, activities=True)
    second = task_context(tmp_path, tid, False, 101, reader)
    assert len(calls) == 2 and "Required check remains" in second
    assert "TASK-1" in first and "stable-sha256" in first


def test_stop_merge_uses_only_supported_wire_fields():
    import json

    result = hooks.merge_outputs("Stop", json.dumps({"decision": "block", "reason": "Persist outcome"}))
    assert result == {"decision": "block", "reason": "Persist outcome"}
