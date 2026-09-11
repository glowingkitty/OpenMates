"""Read-only session identity resolution. Never guess by recency."""
from pathlib import Path


def resolve_session(data, *, session_id="", thread_id="", host="", cwd=None, repo_id=""):
    sessions = data.get("sessions", {})
    if session_id:
        if session_id not in sessions:
            raise RuntimeError(f"Unknown session {session_id}")
        return session_id
    if thread_id:
        matches = [sid for sid, info in sessions.items()
                   if info.get("codex_task_id") == thread_id and info.get("codex_host") == host
                   and (not repo_id or info.get("repo_id", "openmates") == repo_id)]
    else:
        current = Path(cwd or Path.cwd()).resolve()
        matches = [sid for sid, info in sessions.items()
                   if (info.get("worktree") or {}).get("path")
                   and Path(info["worktree"]["path"]).resolve() == current]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise RuntimeError("Ambiguous session binding; supply --session")
    raise RuntimeError("No session bound to this task/workspace; run sessions.py start or supply --session")
