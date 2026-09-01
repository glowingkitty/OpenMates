#!/usr/bin/env python3
"""Inspect one assistant speech segment with existing Directus service wiring."""

from __future__ import annotations

import asyncio
import json
import sys

from backend.apps.audio.assistant_speech.persistence import get_speech_segment
from backend.core.api.app.services.directus import DirectusService


SAFE_FIELDS = (
    "id",
    "segment_id",
    "chat_id",
    "assistant_message_id",
    "status",
    "execution_version",
    "lease_id",
    "lease_expires_at",
    "generated_asset_id",
    "pending_generated_asset_id",
    "pending_duration_seconds",
    "duration_seconds",
    "billing_usage_id",
    "error",
    "retryable",
)


async def main() -> int:
    if len(sys.argv) != 2:
        print("usage: inspect_assistant_speech_segment_tmp.py <segment_id>", file=sys.stderr)
        return 2
    directus = DirectusService()
    try:
        row = await get_speech_segment(directus, sys.argv[1])
    finally:
        await directus.close()
    if row is None:
        print(json.dumps({"found": False}, sort_keys=True))
        return 0
    safe = {field: row.get(field) for field in SAFE_FIELDS if field in row}
    safe["found"] = True
    print(json.dumps(safe, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
