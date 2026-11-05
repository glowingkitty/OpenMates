"""
Development-only handoff of admin issue reports to a Claude Code chat.

When an administrator reports an issue on the development server with
"Send to Claude chat" enabled, the API writes a minimal request file into a
host-mounted queue directory. The host-side dispatcher
(``scripts/claude_dispatch.py issues``) consumes the file and opens a new
Remote Control Claude Code chat that investigates the issue through the normal
``debug.py issue`` tooling.

Security boundary:
- Only authenticated admins on ``SERVER_ENVIRONMENT=development`` can queue.
- The queue file carries identifiers only (never report text), so the host
  dispatcher builds its prompt from validated IDs, not request content.
- The queue directory exists only through the development compose override;
  production has no mount and no ``CLAUDE_DISPATCH_QUEUE_DIR``.

Architecture: docs/architecture/infrastructure/claude-dispatch.md
Tests: backend/tests/test_claude_issue_dispatch.py
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

QUEUE_DIR_ENV = "CLAUDE_DISPATCH_QUEUE_DIR"
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SHORT_ID_RE = re.compile(r"^[A-HJ-NP-Z2-9]{5}$")

ClaudeChatStatus = Literal["queued", "unavailable"]


@dataclass(frozen=True)
class ClaudeDispatchResult:
    status: ClaudeChatStatus
    detail: str


def is_development_server() -> bool:
    # Fail closed: an unset environment never counts as development here.
    return os.getenv("SERVER_ENVIRONMENT", "production").strip().lower() == "development"


def queue_issue_for_claude_chat(
    *,
    issue_id: str,
    short_issue_id: str,
    queue_dir: str | None = None,
    now: datetime | None = None,
) -> ClaudeDispatchResult:
    """Atomically write one issue dispatch request into the host queue."""
    if not _UUID_RE.match(issue_id or ""):
        raise ValueError("issue_id must be a UUID")
    if not _SHORT_ID_RE.match(short_issue_id or ""):
        raise ValueError("short_issue_id must be a 5-character report ID")

    configured = queue_dir if queue_dir is not None else os.getenv(QUEUE_DIR_ENV, "")
    if not configured:
        return ClaudeDispatchResult("unavailable", f"{QUEUE_DIR_ENV} is not configured")
    directory = Path(configured)
    if not directory.is_dir():
        return ClaudeDispatchResult("unavailable", f"queue directory {directory} does not exist")

    payload = {
        "kind": "issue",
        "issue_id": issue_id,
        "short_issue_id": short_issue_id,
        "queued_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    target = directory / f"issue-{short_issue_id}.json"
    temporary = directory / f".issue-{short_issue_id}.json.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    # The host dispatcher runs as a different uid than the container (root).
    temporary.chmod(0o644)
    temporary.replace(target)
    return ClaudeDispatchResult("queued", str(target))


def handoff_admin_issue(
    *,
    requested: bool,
    is_admin: bool,
    issue_id: str,
    short_issue_id: str,
) -> ClaudeDispatchResult | None:
    """Apply the admin + development gate; None means the handoff does not apply."""
    if not (requested and is_admin and is_development_server()):
        return None
    try:
        return queue_issue_for_claude_chat(issue_id=issue_id, short_issue_id=short_issue_id)
    except OSError as exc:
        return ClaudeDispatchResult("unavailable", f"could not write queue file: {exc}")
