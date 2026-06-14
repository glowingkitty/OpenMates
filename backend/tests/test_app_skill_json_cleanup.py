"""Regression tests for app-skill JSON references in streamed answers.

The frontend turns fenced `app_skill_use` JSON blocks into embed nodes. Final
streaming cleanup must preserve successful refs so embeds remain visible after
the assistant message is finalized.
"""

from __future__ import annotations

from pathlib import Path


STREAM_CONSUMER = Path(__file__).resolve().parents[1] / "apps/ai/tasks/stream_consumer.py"

def test_successful_app_skill_json_blocks_are_persisted() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}
```

Here are the best matches.
"""

    assert "app_skill_use" in text
    assert "embed_id" in text
    assert "Here are the best matches." in text


def test_successful_app_skill_json_blocks_keep_nested_payloads() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"travel","skill_id":"search_connections","providers":[{"id":"google_flights","name":"Google Flights"}]}
```

The afternoon flight is the best option.
"""

    assert "app_skill_use" in text
    assert "google_flights" in text
    assert "The afternoon flight is the best option." in text


def test_inline_embed_links_remain_supported() -> None:
    text = "See [the Vueling flight](embed:vueling-2026-abc) for details."

    assert "embed:vueling-2026-abc" in text


def test_stream_consumer_does_not_strip_successful_app_skill_refs() -> None:
    source = STREAM_CONSUMER.read_text(encoding="utf-8")

    assert "APP_SKILL_JSON_CLEANUP" not in source
    assert "_strip_successful_app_skill_json_blocks" not in source
