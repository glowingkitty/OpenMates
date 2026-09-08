#!/usr/bin/env python3
"""Codex adapter for the existing shared hook bridge.

Resolve durable parent task identity and anchor supported tool inputs to its
managed workspace. Hooks provide routing and diagnostics, not an OS sandbox.
Docker admission must still be enforced by a separate privileged host broker.
See docs/plans/codex-session-runtime-isolation/plan.yml.
"""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import re
import sys


def route(event: str, payload: dict, workspace: Path, session_id: str) -> dict:
    context = (
        f"OpenMates workspace: {workspace}. Use sessions.py --session {session_id}; "
        "reuse this binding, including in child tasks. Shared runtime mutation requires "
        "the explicit runtime target and coordinator lease."
    )
    if payload.get("turn_id"):
        context += f" Current Codex turn: {payload['turn_id']}."
    result = {"hookEventName": event, "additionalContext": context}
    if event == "PreToolUse":
        tool = payload.get("tool_name")
        inputs = dict(payload.get("tool_input") or {})
        command = inputs.get("command")
        if tool in {"Bash", "bash"}:
            if not isinstance(command, str):
                raise ValueError("Unsupported Codex shell payload; command is required")
            if re.search(r"\b(?:node|bun|tsx|ts-node)\b[^;\n]*(?:src|dist)/cli\.(?:ts|js)\b", command):
                raise ValueError("Use the globally installed openmates executable; source/dist CLI execution is prohibited")
            requested = Path(
                inputs.get("workdir")
                or inputs.get("cwd")
                or payload.get("cwd")
                or workspace
            )
            requested = (
                requested if requested.is_absolute() else workspace / requested
            ).resolve()
            directory = requested if requested.is_relative_to(workspace) else workspace
            inputs["command"] = f"cd -- {shlex.quote(str(directory))} &&\n{command}"
        elif tool == "apply_patch":
            if not isinstance(command, str):
                raise ValueError("Unsupported Codex patch payload; command is required")
            lines = []
            for line in command.splitlines(keepends=True):
                for prefix in (
                    "*** Add File: ",
                    "*** Update File: ",
                    "*** Delete File: ",
                    "*** Move to: ",
                ):
                    if line.startswith(prefix):
                        raw = Path(line[len(prefix) :].rstrip("\r\n"))
                        target = (
                            raw if raw.is_absolute() else workspace / raw
                        ).resolve()
                        if not target.is_relative_to(workspace):
                            raise ValueError(
                                "Patch targets a file outside the bound workspace"
                            )
                        line = (
                            prefix + str(target) + ("\n" if line.endswith("\n") else "")
                        )
                        break
                lines.append(line)
            inputs["command"] = "".join(lines)
        else:
            return {"hookSpecificOutput": result}
        result.update(permissionDecision="allow", updatedInput=inputs)
    return {"hookSpecificOutput": result}


def merge_outputs(event: str, stream: str) -> dict:
    """Emit one hook response; a shared guard denial always beats routing."""
    decoder = json.JSONDecoder()
    contexts, warnings, denials = [], [], []
    rewritten = None
    while stream.strip():
        stream = stream.lstrip()
        if not stream.startswith("{"):
            line, _, stream = stream.partition("\n")
            contexts.append(line)
            continue
        value, end = decoder.raw_decode(stream)
        stream = stream[end:]
        if not isinstance(value, dict):
            raise ValueError("Shared hook emitted a non-object response")
        detail = value.get("hookSpecificOutput") or {}
        if detail.get("additionalContext"):
            contexts.append(str(detail["additionalContext"]))
        if value.get("systemMessage"):
            warnings.append(str(value["systemMessage"]))
        if (
            value.get("decision") == "block"
            or detail.get("permissionDecision") == "deny"
        ):
            denials.append(
                str(
                    detail.get("permissionDecisionReason")
                    or value.get("reason")
                    or "Shared hook denied the operation"
                )
            )
        if detail.get("permissionDecision") == "allow" and "updatedInput" in detail:
            rewritten = detail["updatedInput"]
    detail = {"hookEventName": event}
    if contexts:
        detail["additionalContext"] = "\n".join(contexts)
    # Stop accepts universal output plus decision/reason, and rejects unknown
    # fields. An empty hookSpecificOutput silently defeats continuation in the
    # runtime. Preserve any informational context as a universal systemMessage.
    result = {} if event == "Stop" else {"hookSpecificOutput": detail}
    if event == "Stop":
        warnings.extend(contexts)
    if warnings:
        result["systemMessage"] = "\n".join(warnings)
    if denials:
        if event == "PreToolUse":
            detail.update(
                permissionDecision="deny", permissionDecisionReason="\n".join(denials)
            )
        else:
            result.update(decision="block", reason="\n".join(denials))
    elif rewritten is not None:
        detail.update(permissionDecision="allow", updatedInput=rewritten)
    return result


def main() -> int:
    # Direct invocation resolves the same immutable coordinator as the bridge.
    import sessions

    try:
        if sys.argv[1] == "--merge":
            print(json.dumps(merge_outputs(sys.argv[2], sys.stdin.read())))
            return 0
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Codex hook input must be an object")
        event = sys.argv[1]
        task_id = payload.get("session_id") or sessions._codex_task_identity()
        if not task_id:
            return 0
        matched = sessions.session_for_codex(sessions._load_sessions(), task_id)
        if not matched:
            if event in {"SessionStart", "UserPromptSubmit"}:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": event,
                                "additionalContext": "No Codex repository binding exists. Before writing, start a sessions.py session "
                                "or explicitly adopt the reviewed existing worktree. Read-only investigation can continue.",
                            }
                        }
                    )
                )
            elif event == "PreToolUse" and payload.get("tool_name") == "apply_patch":
                raise ValueError(
                    "No Codex workspace binding; start or adopt a session before editing"
                )
            return 0
        sid, record = matched
        workspace = sessions._session_checkout_root(record).resolve()
        if not workspace.is_dir():
            raise ValueError(
                "Bound Codex workspace is missing; reconcile it before writing"
            )
        result = route(event, payload, workspace, sid)
        from codex_task_context import task_context
        from codex_orchestration import (
            canonical_root,
            context as orchestration_context,
            output_guard,
        )

        root = canonical_root(workspace)
        extra = task_context(
            root,
            task_id,
            refresh=event in {"SessionStart", "UserPromptSubmit"},
            activities=event == "SessionStart",
        )
        if event in {"SessionStart", "UserPromptSubmit", "Stop"}:
            from codex_task_lifecycle import hook as task_lifecycle
            lifecycle_result = task_lifecycle(root, sid, task_id, event, payload, sessions)
            if lifecycle_result.get("decision") == "block":
                print(json.dumps(lifecycle_result))
                return 0
        role = orchestration_context(root, sid, task_id)
        result["hookSpecificOutput"]["additionalContext"] += (
            "\n" + extra + ("\n" + role if role else "")
        )
        if event == "Stop" and role:
            result.update(output_guard(root, sid, task_id, payload))
        if payload.get("tool_name") == "apply_patch" and event == "PreToolUse":
            patch = result["hookSpecificOutput"]["updatedInput"]["command"]
            prefixes = (
                "*** Add File: ",
                "*** Update File: ",
                "*** Delete File: ",
                "*** Move to: ",
            )
            files = [
                line[len(prefix) :]
                for line in patch.splitlines()
                for prefix in prefixes
                if line.startswith(prefix)
            ]
            state = sessions._load_sessions()
            for filename in files:
                relative = sessions._normalize_edit_lease_path(filename, record)
                conflict = sessions._manual_write_claim_conflict(
                    relative, sid, state["sessions"]
                )
                if conflict:
                    raise RuntimeError(conflict)
                lease = state.get("edit_leases", {}).get(relative)
                if (
                    lease
                    and sessions._edit_lease_is_active(lease)
                    and lease.get("session_id") != sid
                ):
                    raise RuntimeError(
                        sessions._format_edit_lease_conflict(
                            relative, lease, state["sessions"]
                        )
                    )
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Codex workspace routing: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
