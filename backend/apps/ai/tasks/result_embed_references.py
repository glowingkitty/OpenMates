# backend/apps/ai/tasks/result_embed_references.py
"""Show the result embeds of a completed async skill in the continuation reply.

A test run creates its test_result embed in the code worker; the model only
learns its id from the tool result and rarely links it. Without a reference in
the reply, no client shows the result (with its video and steps) in the chat.
The stream consumer appends one reference block per result embed the reply does
not already contain. Spec: feature.projects (agentic coding test results).
"""
from __future__ import annotations

import json
from typing import Iterable


def append_result_embed_references(text: str, embed_type: str, embed_ids: Iterable[str]) -> str:
    """Return ``text`` with a reference block for each id it does not mention yet."""
    missing = [embed_id for embed_id in dict.fromkeys(embed_ids) if embed_id and embed_id not in text]
    if not missing:
        return text
    blocks = "\n\n".join(
        "```json\n" + json.dumps({"type": embed_type, "embed_id": embed_id}) + "\n```" for embed_id in missing
    )
    return f"{text.rstrip()}\n\n{blocks}" if text.strip() else blocks
