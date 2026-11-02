"""Shared scoped-decision receipts for workflow completion and continuation.

The existing session/Plan owns receipts; there is no separate approval store.
Original messages are read only to validate user provenance and content hashes:
Claude Code transcripts (``~/.claude/projects/<slug>/<session>.jsonl``, message
id = the turn's ``uuid``) and, for historical receipts, Codex session logs.
Only exact target, surface and revision matches may suppress selected work.
See docs/architecture/agent-workflow-decisions.md for scope and rollback.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

DECISIONS = {"accept", "stop", "waive", "resume"}
SURFACES = {"appearance", "proof", "task", "specification-approval-prompt"}


PROVIDERS = ("claude", "codex")
_UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"


def _claude_transcript(session_id: str) -> Path:
    """Locate one Claude Code transcript by its session UUID (never a free path)."""
    import re

    if not re.fullmatch(_UUID, session_id or ""):
        raise ValueError("invalid Claude session id")
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    paths = sorted((home / "projects").glob(f"*/{session_id}.jsonl"))
    if len(paths) != 1:
        raise ValueError("original Claude session is unavailable or ambiguous")
    return paths[0]


def _claude_human_messages(session_id: str):
    """Yield (uuid, text) for typed human turns; tool results and injected context are skipped."""
    with _claude_transcript(session_id).open() as handle:
        for line in handle:
            row = json.loads(line)
            message = row.get("message") or {}
            if (
                row.get("type") != "user"
                or message.get("role") != "user"
                or row.get("isMeta")
                or row.get("isSidechain")
                or row.get("sessionId", session_id) != session_id
            ):
                continue
            origin = row.get("origin")
            if isinstance(origin, dict):
                if origin.get("kind") != "human":
                    continue
            elif row.get("promptSource") == "system":
                continue
            content = message.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list) and all(
                isinstance(part, dict) and part.get("type") == "text" for part in content
            ):
                text = "\n".join(part.get("text", "") for part in content)
            else:
                continue
            if row.get("uuid") and text.strip():
                yield row["uuid"], text


def find_user_message_id(source: dict, quote: str) -> str:
    """Return the newest human message in a Claude session containing ``quote``."""
    if source.get("provider") != "claude":
        raise ValueError("message lookup by quote is only supported for Claude sessions")
    if not quote.strip():
        raise ValueError("decision needs an exact quote")
    found = ""
    for message_id, text in _claude_human_messages(source.get("session_id", "")):
        if quote in text:
            found = message_id
    if not found:
        raise ValueError("no original Claude user message contains the quote")
    return found


def read_user_message(source: dict) -> dict:
    """Read one original user message without modifying either agent's storage."""
    provider = source.get("provider")
    if provider == "claude":
        for message_id, text in _claude_human_messages(source.get("session_id", "")):
            if message_id == source.get("message_id"):
                return {"role": "user", "text": text}
        raise ValueError("original Claude message is unavailable")
    if provider == "codex":
        # Historical receipts recorded by the retired Codex workflow.
        root = (
            Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"
        )
        # A receipt names a thread, never an arbitrary filesystem path.
        thread = source.get("session_id", "")
        import re

        if not re.fullmatch(r"[a-zA-Z0-9-]+", thread):
            raise ValueError("invalid Codex thread id")
        paths = list(root.rglob(f"*{thread}.jsonl"))
        if len(paths) != 1:
            raise ValueError("original Codex thread is unavailable or ambiguous")
        with paths[0].open() as handle:
            for line in handle:
                row = json.loads(line)
                payload = row.get("payload", {})
                if (
                    row.get("type") == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") == "user"
                ):
                    text = "\n".join(
                        p.get("text", "")
                        for p in payload.get("content", [])
                        if p.get("type") == "input_text"
                    )
                    if (
                        hashlib.sha256(text.encode()).hexdigest()
                        == source["message_id"]
                    ):
                        return {"role": "user", "text": text}
        raise ValueError("original Codex message is unavailable")
    raise ValueError("unsupported decision source")


def make_receipt(
    *, target, surface, revision, decision, source, quote, read_message=None
):
    read_message = read_message or read_user_message
    if (
        not target
        or not revision
        or surface not in SURFACES
        or decision not in DECISIONS
    ):
        raise ValueError(
            "decision needs an exact target, supported surface and revision"
        )
    if decision in {"stop", "waive"} and surface == "appearance":
        raise ValueError("appearance acceptance is separate from a proof waiver")
    if (
        not all(source.get(k) for k in ("provider", "session_id", "message_id"))
        or not quote.strip()
    ):
        raise ValueError("decision needs original user provenance and an exact quote")
    message = read_message(source)
    if message.get("role") != "user" or quote not in message.get("text", ""):
        raise ValueError("decision quote must come from the original user message")
    provenance = {k: source[k] for k in ("provider", "session_id", "message_id")}
    provenance["text_sha256"] = hashlib.sha256(message["text"].encode()).hexdigest()
    scope = dict(
        target=target,
        surface=surface,
        revision=revision,
        decision=decision,
        source=provenance,
    )
    identity = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[
        :24
    ]
    return {
        "id": f"DEC-{identity}",
        "status": "confirmed",
        "reason": "Explicit scoped user instruction",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        **scope,
    }


def matching_receipt(
    receipts, *, target, surface, revision, read_message=None, preserve_stop=False
):
    """Return the newest valid stop/waiver for exactly this work; never a blanket pass."""
    read_message = read_message or read_user_message
    for receipt in reversed(receipts or []):
        if not isinstance(receipt, dict) or any(
            receipt.get(k) != v
            for k, v in {
                "target": target,
                "surface": surface,
                "revision": revision,
                "status": "confirmed",
            }.items()
        ):
            continue
        source = receipt.get("source") or {}
        try:
            message = read_message(source)
            valid = message.get("role") == "user" and hashlib.sha256(
                message.get("text", "").encode()
            ).hexdigest() == source.get("text_sha256")
        except (OSError, ValueError, KeyError):
            if preserve_stop and receipt.get("decision") in {"stop", "waive"}:
                # Missing history cannot grant a verification pass, but it must
                # not silently reactivate work the user explicitly stopped.
                return {**receipt, "provenance_status": "unavailable"}
            valid = False
        if not valid:
            continue
        return receipt if receipt.get("decision") in {"stop", "waive"} else None
    return None
