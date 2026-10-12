"""Read-only, bounded Codex chat presence for the foreground Task adapter.

Inventory and local session records provide metadata only. No thread is resumed,
subscribed, or given execution permission by this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time
import uuid

PAGE_SIZE = 100
MAX_PAGES = 20
MAX_FILES = 24
MAX_PATH_LENGTH = 240
INVENTORY_TIMEOUT = 5.0


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def repository_checkout(root, location):
    """Accept the canonical checkout or a worktree linked to its Git common dir."""
    root = Path(root).resolve()
    try:
        checkout = Path(location).resolve()
        if checkout.is_relative_to(root):
            relative = checkout.relative_to(root)
            if not relative.parts or relative.parts[0] not in {
                ".openmates-agent-worktrees", ".agent-worktrees"
            }:
                return True
        for candidate in (checkout, *checkout.parents):
            pointer = candidate / ".git"
            if not pointer.is_file():
                continue
            value = pointer.read_text().strip()
            if not value.startswith("gitdir: "):
                return False
            gitdir = (candidate / value[len("gitdir: "):]).resolve()
            if not gitdir.is_relative_to((root / ".git/worktrees").resolve()):
                return False
            common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
            return common == (root / ".git").resolve()
    except (OSError, ValueError):
        pass
    return False


def _thread_id(value):
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _project_id(value):
    return value if isinstance(value, str) and value.strip() else None


def _safe_path(value, workspace):
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.relative_to(workspace)
        except ValueError:
            return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _binding_time(record, worktree):
    """Compare durable session activity without trusting JSON insertion order."""
    values = []
    for raw in (
        record.get("last_active"), worktree.get("last_active"),
        record.get("binding_updated_at"), record.get("started"),
        worktree.get("created_at"),
    ):
        if not isinstance(raw, str):
            continue
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if moment.tzinfo:
                values.append(moment.timestamp())
        except ValueError:
            pass
    return max(values) if values else None


def _canonical_cwd(root, cwd):
    """A nested linked worktree is distinct even when stored below root."""
    root = Path(root).resolve()
    if not cwd.is_relative_to(root):
        return False
    for candidate in (cwd, *cwd.parents):
        if candidate == root:
            break
        if (candidate / ".git").is_file():
            return False
    return True


def _select_binding(bindings, cwd, canonical):
    candidates = bindings if canonical else [
        binding for binding in bindings if cwd.is_relative_to(binding["workspace"])
    ]
    if not candidates:
        return None
    dated = [binding for binding in candidates if binding["updated_at"] is not None]
    if dated:
        latest = max(binding["updated_at"] for binding in dated)
        selected = [binding for binding in dated if binding["updated_at"] == latest]
    else:
        selected = candidates
    # An equal-time conflict has no demonstrable owner; leave RPC cwd alone.
    return selected[0] if len(selected) == 1 else None


def _session_scopes(root):
    """Read advisory workspace/file claims without changing live session state."""
    path = Path(root) / ".claude/sessions.json"
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("invalid sessions")
        records = data.get("sessions", {})
        if not isinstance(records, dict):
            raise ValueError("invalid sessions")
    except (OSError, ValueError, TypeError):
        return {}, "Session metadata unavailable"
    scopes = {}
    leases = data.get("edit_leases") or {}
    if not isinstance(leases, dict):
        leases = {}
    for session_id, record in records.items():
        if not isinstance(record, dict):
            continue
        thread = _thread_id(record.get("codex_task_id"))
        worktree = record.get("worktree") or {}
        location = worktree.get("path") if isinstance(worktree, dict) else None
        if (
            not thread
            or record.get("codex_host") != socket.gethostname()
            or not isinstance(location, str)
            or worktree.get("status") not in {None, "active", "merged", "changes_pending"}
            or not repository_checkout(root, location)
        ):
            continue
        workspace = Path(location).resolve()
        if not workspace.is_dir():
            continue
        files = []
        for field in ("modified_files", "writing"):
            claims = record.get(field) or []
            if isinstance(claims, str):
                claims = [claims]
            if isinstance(claims, dict):
                claims = list(claims)
            if not isinstance(claims, (list, tuple, set)):
                continue
            for claim in claims:
                safe = _safe_path(claim, workspace)
                if safe and safe not in files:
                    files.append(safe)
                if len(files) >= MAX_FILES:
                    break
            if len(files) >= MAX_FILES:
                break
        if len(files) < MAX_FILES:
            for claim, lease in leases.items():
                if not isinstance(lease, dict) or lease.get("session_id") != session_id:
                    continue
                safe = _safe_path(claim, workspace)
                if safe and safe not in files:
                    files.append(safe)
                if len(files) >= MAX_FILES:
                    break
        scopes.setdefault(thread, []).append({
            "workspace": workspace,
            "files": files,
            "updated_at": _binding_time(record, worktree),
        })
    return scopes, None


def _task_projects(config):
    """Snapshot links establish membership even when remote Task sync is down."""
    projects, tasks, configured_projects = {}, {}, set()
    errors = []
    for source in config.get("snapshots", []):
        try:
            snapshot = json.loads(Path(source).read_text())
            if not isinstance(snapshot, dict):
                raise ValueError("invalid snapshot")
            project = _project_id(snapshot.get("project_id"))
            rows = snapshot.get("tasks", [])
            if not project or not isinstance(rows, list):
                raise ValueError("invalid snapshot")
            configured_projects.add(project)
            for task in rows:
                if not isinstance(task, dict):
                    continue
                link = task.get("external_chat") or {}
                if not isinstance(link, dict) or link.get("provider") != "codex":
                    continue
                thread = _thread_id(link.get("id"))
                if not thread:
                    continue
                projects.setdefault(thread, set()).add(project)
                if all(isinstance(task.get(key), str) for key in ("task_id", "title", "status")):
                    item = {"project_id": project, **{
                        key: task[key] for key in ("task_id", "title", "status")
                    }}
                    bucket = tasks.setdefault(thread, [])
                    if item not in bucket:
                        bucket.append(item)
        except (OSError, ValueError, TypeError):
            errors.append("Task project snapshot unavailable")
    return projects, tasks, configured_projects, errors


def _inventory(rpc):
    entries = {}
    cursor = None
    seen = set()
    deadline = time.monotonic() + INVENTORY_TIMEOUT
    for _ in range(MAX_PAGES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return entries, "Codex inventory deadline exceeded", False
        params = {
            "limit": PAGE_SIZE,
            "archived": False,
            "sortKey": "updated_at",
            "useStateDbOnly": True,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            page = rpc.call("thread/list", params, timeout=remaining)
        except TimeoutError:
            return entries, "Codex inventory deadline exceeded", False
        except (OSError, RuntimeError, ValueError, TypeError):
            return entries, "Codex inventory unavailable", False
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            return entries, "Codex inventory invalid", False
        for row in page["data"]:
            if isinstance(row, dict):
                thread = _thread_id(row.get("id"))
                if thread:
                    entries[thread] = row
        next_cursor = page.get("nextCursor")
        if not next_cursor:
            return entries, None, True
        if not isinstance(next_cursor, str) or next_cursor in seen:
            return entries, "Codex inventory cursor repeated", False
        seen.add(next_cursor)
        cursor = next_cursor
    return entries, "Codex inventory truncated", False


def _unknown_rows(previous):
    rows = {}
    if not isinstance(previous, dict) or not isinstance(previous.get("threads"), dict):
        return rows
    for thread, row in previous["threads"].items():
        if not _thread_id(thread) or not isinstance(row, dict):
            continue
        projects = row.get("project_ids")
        if not isinstance(projects, list):
            continue
        projects = sorted({_project_id(value) for value in projects if _project_id(value)})
        if not projects:
            continue
        files = row.get("files")
        files = [value for value in files if isinstance(value, str)][:MAX_FILES] if isinstance(files, list) else []
        retained = {
            "project_ids": projects,
            "title": row.get("title") if isinstance(row.get("title"), str) else "",
            "status": "unknown",
            "parent_id": _thread_id(row.get("parent_id")),
            "workspace": row.get("workspace") if isinstance(row.get("workspace"), str) else "",
            "files": files,
            "checked_at": row.get("checked_at") if isinstance(row.get("checked_at"), str) else "",
        }
        tasks = row.get("tasks")
        if isinstance(tasks, list):
            selected = [
                {key: task[key] for key in ("project_id", "task_id", "title", "status")}
                for task in tasks if isinstance(task, dict)
                and all(isinstance(task.get(key), str) for key in ("project_id", "task_id", "title", "status"))
                and task["project_id"] in projects
            ][:24]
            if selected:
                retained["tasks"] = selected
        rows[thread] = retained
    return rows


def unavailable(previous, reason="Codex connection unavailable"):
    """Retain display metadata but revoke all old claims of live activity."""
    return {
        "schema_version": 1,
        "checked_at": now_iso(),
        "connection": "unavailable",
        "complete": False,
        "threads": _unknown_rows(previous or {}),
        "reason": reason,
    }


def collect_once(rpc, root, config, previous=None):
    """Refresh one bounded inventory; callers may persist the returned metadata."""
    previous = previous or {}
    checked_at = now_iso()
    entries, inventory_error, complete = _inventory(rpc)
    linked, tasks, configured_projects, snapshot_errors = _task_projects(config)
    scopes, session_error = _session_scopes(root)
    errors = [error for error in (inventory_error, *snapshot_errors, session_error) if error]
    if errors:
        complete = False
    rows = {} if complete else _unknown_rows(previous)
    default = _project_id(config.get("presence_project_id"))
    if not default and len(configured_projects) == 1:
        default = next(iter(configured_projects))
    overrides = config.get("thread_projects") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    for thread, entry in entries.items():
        cwd = entry.get("cwd")
        if not isinstance(cwd, str) or not repository_checkout(root, cwd):
            continue
        if thread in overrides:
            values = overrides[thread]
            projects = (
                sorted({_project_id(value) for value in values if _project_id(value)})
                if isinstance(values, list) else []
            )
        elif thread in linked:
            projects = sorted(linked[thread])
        else:
            projects = [default] if default else []
        if not projects:
            continue
        status = entry.get("status")
        status = status.get("type") if isinstance(status, dict) else None
        rpc_workspace = Path(cwd).resolve()
        binding = _select_binding(
            scopes.get(thread, []), rpc_workspace,
            _canonical_cwd(root, rpc_workspace),
        )
        workspace = binding["workspace"] if binding else rpc_workspace
        files = binding["files"] if binding else []
        row = {
            "project_ids": projects,
            "title": entry.get("name") if isinstance(entry.get("name"), str) else "",
            "status": status if isinstance(status, str) and status else "unknown",
            "parent_id": _thread_id(entry.get("forkedFromId")),
            "workspace": str(workspace),
            "files": files,
            "checked_at": checked_at,
        }
        selected_tasks = [task for task in tasks.get(thread, []) if task["project_id"] in projects][:24]
        if selected_tasks:
            row["tasks"] = selected_tasks
        rows[thread] = row
    result = {
        "schema_version": 1,
        "checked_at": checked_at,
        "connection": (
            "unavailable" if inventory_error in {
                "Codex inventory unavailable", "Codex inventory deadline exceeded"
            }
            else "connected"
        ),
        "complete": complete,
        "threads": rows,
    }
    if errors:
        result["reason"] = "; ".join(dict.fromkeys(errors))
    return result


def observe_notification(presence, message):
    """Apply daemon runtime signals only to already inventoried threads."""
    params = message.get("params") or {}
    thread = _thread_id(params.get("threadId"))
    rows = presence.get("threads") or {}
    if thread not in rows:
        return
    method = message.get("method")
    if method == "thread/deleted":
        del rows[thread]
    elif method == "thread/status/changed":
        status = params.get("status")
        status = status.get("type") if isinstance(status, dict) else None
        rows[thread]["status"] = status if isinstance(status, str) and status else "unknown"
        rows[thread]["checked_at"] = now_iso()
    elif method == "turn/completed":
        turn = params.get("turn") or {}
        rows[thread]["status"] = "idle" if turn.get("status") == "completed" else "attention"
        rows[thread]["checked_at"] = now_iso()
