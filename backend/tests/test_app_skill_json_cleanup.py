"""Regression tests for app-skill JSON cleanup in streamed answers.

Successful app skill embeds are rendered from structured metadata. Raw fenced
`app_skill_use` blocks in assistant prose are implementation details and should
not be persisted or shown to users.
"""

from __future__ import annotations

from backend.apps.ai.tasks.stream_consumer import _strip_successful_app_skill_json_blocks


def test_strip_successful_app_skill_json_blocks_removes_raw_tool_blocks() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}
```

Here are the best matches.
"""

    cleaned = _strip_successful_app_skill_json_blocks(text)

    assert "app_skill_use" not in cleaned
    assert "embed_id" not in cleaned
    assert "Here are the best matches." in cleaned


def test_strip_successful_app_skill_json_blocks_handles_nested_payloads() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"travel","skill_id":"search_connections","providers":[{"id":"google_flights","name":"Google Flights"}]}
```

The afternoon flight is the best option.
"""

    cleaned = _strip_successful_app_skill_json_blocks(text)

    assert "app_skill_use" not in cleaned
    assert "google_flights" not in cleaned
    assert "The afternoon flight is the best option." in cleaned


def test_strip_successful_app_skill_json_blocks_preserves_inline_embed_links() -> None:
    text = "See [the Vueling flight](embed:vueling-2026-abc) for details."

    assert _strip_successful_app_skill_json_blocks(text) == text
