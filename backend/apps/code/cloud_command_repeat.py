"""Same-turn repeat guard for cloud Project commands (code-run.cloud.commands).

A model can call the same command again after it already succeeded, for
example after each Project snapshot pause, which spends E2B time and credits
and loops the turn. A command is identified by its argv, its cwd and the exact
Project snapshot it ran against. When that identical command already exited 0
in this turn, the repeat call does not start a sandbox again: it returns the
earlier outcome and tells the assistant to answer. Any changed Project file
(including files a command synced back) gives a new fingerprint, so a rerun
after an edit always runs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The guard lives as long as one turn can run cloud commands.
REPEAT_GUARD_TTL_SECONDS = 3600
# Enough output tail for the assistant to report the earlier result.
REPEAT_OUTPUT_TAIL_CHARS = 2000


def normalized_cwd(cwd: str | None) -> str:
    cleaned = (cwd or "").replace("\\", "/").strip().strip("/")
    return "" if cleaned in {"", "."} else cleaned


def command_fingerprint(argv: list[str], cwd: str | None, files: list[tuple[str, str]]) -> str:
    """Hash of argv, cwd and the snapshot (path, content) pairs the command runs against."""
    digest = hashlib.sha256()
    digest.update(json.dumps([list(argv), normalized_cwd(cwd)], ensure_ascii=False).encode("utf-8"))
    for path, content in sorted(files):
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content.encode("utf-8")).digest())
    return digest.hexdigest()


def repeat_key(chat_id: str, message_id: str, fingerprint: str) -> str:
    return f"cloud_command_succeeded:{chat_id}:{message_id}:{fingerprint}"


def success_summary(completion: dict[str, Any]) -> dict[str, Any]:
    """The part of a successful command result the repeat answer quotes."""
    output = completion.get("output") if isinstance(completion.get("output"), str) else ""
    return {
        "command": completion.get("command"),
        "exit_code": 0,
        "output_tail": output[-REPEAT_OUTPUT_TAIL_CHARS:],
        "changed_files": completion.get("changed_files") or [],
    }


async def remember_success(
    cache: Any, *, chat_id: str, message_id: str, fingerprint: str, completion: dict[str, Any],
) -> None:
    await cache.set(
        repeat_key(chat_id, message_id, fingerprint), success_summary(completion),
        ttl=REPEAT_GUARD_TTL_SECONDS,
    )


async def previous_success(
    cache: Any, *, chat_id: str, message_id: str, fingerprint: str,
) -> dict[str, Any] | None:
    summary = await cache.get(repeat_key(chat_id, message_id, fingerprint))
    return summary if isinstance(summary, dict) else None


def repeat_note(summary: dict[str, Any]) -> str:
    return (
        f"Not run again: `{summary.get('command') or 'this command'}` already succeeded (exit code 0) in this "
        "turn against the same Project files; previous_result holds its outcome. Do not repeat it. "
        "Run a different command only if the task still needs one, otherwise answer the user now."
    )
