"""Configuration and runtime doctor for the OpenMates CLI Codex Task adapter.

The foreground CLI owns snapshots. ``configure`` maps a repository identity to
explicit account-scoped snapshot files in ``~/.openmates/codex-adapter.json``,
which the CLI uses to start ``codex_task_adapter.py``; ``doctor`` checks the
Codex runtime before event execution is enabled. No Task writes, remote
requests, transcript scans or model calls occur here.
See docs/architecture/cli-codex-adapter.md.
"""

from __future__ import annotations
import argparse
import json
import os
import socket
import time
from pathlib import Path
import tempfile
import uuid


def state_root() -> Path:
    return Path(os.environ.get("OPENMATES_STATE_DIR") or Path.home() / ".openmates")


def configuration(root: Path, thread: str) -> dict | None:
    try:
        config = json.loads((state_root() / "codex-adapter.json").read_text())
    except FileNotFoundError:
        return None
    entry = config.get("repositories", {}).get(str(root.resolve()))
    if not entry or not entry.get("enabled"):
        return None
    return (
        entry
        if entry.get("all_threads") or thread in entry.get("threads", [])
        else None
    )


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".context-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


REQUIRED_CONTEXT_HOOKS = {"sessionStart", "userPromptSubmit", "preToolUse", "postToolUse"}


def runtime_preflight(root: Path, rpc) -> dict:
    """Reject silently skipped context hooks before enabling event execution."""
    response = rpc.call("hooks/list", {"cwds": [str(root.resolve())]})
    source = str(root.resolve() / ".codex" / "hooks.json")
    hooks = [hook for entry in response.get("data", []) for hook in entry.get("hooks", [])
             if hook.get("sourcePath") == source and "claude-hook-bridge.sh" in hook.get("command", "")]
    available = {hook.get("eventName") for hook in hooks if hook.get("enabled")}
    missing = sorted(REQUIRED_CONTEXT_HOOKS - available)
    review = sorted({hook["eventName"] for hook in hooks
                     if hook.get("eventName") in REQUIRED_CONTEXT_HOOKS
                     and hook.get("enabled") and hook.get("trustStatus") != "trusted"})
    return {"status": "ready" if not missing and not review else "needs_attention",
            "missing_hooks": missing, "hooks_needing_review": review,
            "resolution": None if not missing and not review else
            "Open Codex in this repository and use /hooks to review the installed definitions. "
            "Trust only reviewed hooks; do not bypass hook trust. Re-run this check before enabling continuation."}


def inspect_runtime(root: Path) -> dict:
    try:
        from scripts.codex_rpc import CodexRPC
    except ModuleNotFoundError:
        from codex_rpc import CodexRPC
    with CodexRPC() as rpc:
        return runtime_preflight(root, rpc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enabled", "configure", "doctor"])
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--snapshot", action="append", default=[])
    parser.add_argument("--project", help="Explicit default Project for repository chat presence")
    parser.add_argument(
        "--all-threads",
        action="store_true",
        help="Use cached context for every chat in this repository after pilot cutover",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Register this chat for the local foreground event adapter",
    )
    parser.add_argument(
        "--auto-wake",
        action="store_true",
        help="Enable automatic continuation after the runtime pilot passes",
    )
    parser.add_argument(
        "--session", help="Existing repository orchestration registry to migrate"
    )
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path(__file__).with_name("codex_task_adapter.py"),
    )
    args = parser.parse_args()
    uuid.UUID(args.thread)
    if args.action == "doctor":
        result = inspect_runtime(args.repository)
        print(json.dumps(result))
        return 0 if result["status"] == "ready" else 2
    if args.action == "enabled":
        return 0 if configuration(args.repository, args.thread) else 1
    if not args.snapshot:
        parser.error(
            "configure requires --snapshot pointing to an account-scoped snapshot.json"
        )
    snapshots = [str(Path(path).resolve()) for path in args.snapshot]
    projects = set()
    for path in snapshots:
        snapshot = json.loads(Path(path).read_text())
        if snapshot.get("schema_version") != 1:
            parser.error("unsupported snapshot schema")
        projects.add(snapshot["project_id"])
    if args.project and args.project not in projects:
        parser.error("--project must identify one of the configured Project snapshots")
    path = state_root() / "codex-adapter.json"
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        config = {"schema_version": 1, "repositories": {}}
    repository = config["repositories"].setdefault(
        str(args.repository.resolve()), {"enabled": True, "threads": []}
    )
    repository["snapshots"] = snapshots
    repository["presence_enabled"] = True
    if args.project or len(projects) == 1:
        repository["presence_project_id"] = args.project or next(iter(projects))
    elif repository.get("presence_project_id") not in projects:
        repository.pop("presence_project_id", None)
    if args.project:
        repository.setdefault("thread_projects", {})[args.thread] = [args.project]
    repository["threads"] = sorted(set(repository["threads"]) | {args.thread})
    if args.all_threads:
        repository["all_threads"] = True
    if args.events:
        if not args.runtime.is_file():
            parser.error("Adapter runtime script does not exist")
        readiness = inspect_runtime(args.repository)
        if readiness["status"] != "ready":
            parser.error(json.dumps(readiness))
        repository.update(events_enabled=True, runtime=str(args.runtime.resolve()))
        repository.setdefault("activated_at", time.time())
        repository.setdefault("execution_hosts", {})[args.thread] = socket.gethostname()
        if args.auto_wake:
            repository["auto_wake"] = True
    if args.auto_wake and not args.events:
        parser.error("--auto-wake requires --events")
    if args.session:
        if not all(c.isalnum() or c in "_-" for c in args.session):
            parser.error("Invalid session ID")
        repository["sessions"] = sorted(
            set(repository.get("sessions", [])) | {args.session}
        )
        try:
            from scripts.agent_state import transaction
        except ModuleNotFoundError:
            from agent_state import transaction
        registry = (
            args.repository.resolve()
            / "logs/codex-orchestration"
            / args.session
            / "state.json"
        )
        if not registry.exists():
            parser.error("Register the orchestration session before migrating it")
        with transaction(registry) as state:
            state["adapter_mode"] = "task_cache"
    _save(path, config)
    print(f"Enabled cached Task context for Codex chat {args.thread}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
