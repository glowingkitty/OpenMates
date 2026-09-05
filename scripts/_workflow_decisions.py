"""Shared scoped-decision receipts for workflow completion and continuation.

The existing session/Plan owns receipts; there is no separate approval store.
Original messages are read only to validate user provenance and content hashes.
Only exact target, surface and revision matches may suppress selected work.
See docs/architecture/agent-workflow-decisions.md for scope and rollback.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

DECISIONS = {"accept", "stop", "waive", "resume"}
SURFACES = {"appearance", "proof", "task"}


def read_user_message(source: dict) -> dict:
    """Read one original user message without modifying either agent's storage."""
    provider = source.get("provider")
    if provider == "opencode":
        path = Path.home() / ".local/share/opencode/opencode.db"
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT data FROM message WHERE id=? AND session_id=?",
                (source["message_id"], source["session_id"]),
            ).fetchone()
            if not row:
                raise ValueError("original decision message is unavailable")
            message = json.loads(row[0])
            parts = connection.execute(
                "SELECT data FROM part WHERE message_id=? AND session_id=? ORDER BY id",
                (source["message_id"], source["session_id"]),
            ).fetchall()
            texts = [
                p.get("text", "")
                for row in parts
                if (p := json.loads(row[0])).get("type") == "text"
                and not p.get("synthetic")
            ]
            return {"role": message.get("role"), "text": "\n".join(texts)}
    if provider == "codex":
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
        except (OSError, ValueError, KeyError, sqlite3.Error):
            if preserve_stop and receipt.get("decision") in {"stop", "waive"}:
                # Missing history cannot grant a verification pass, but it must
                # not silently reactivate work the user explicitly stopped.
                return {**receipt, "provenance_status": "unavailable"}
            valid = False
        if not valid:
            continue
        return receipt if receipt.get("decision") in {"stop", "waive"} else None
    return None
