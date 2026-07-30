"""Regression tests for app-skill JSON cleanup in streamed answers.

The frontend receives app-skill embed metadata while streaming, but the final
assistant markdown should not persist raw `app_skill_use` JSON fences. The embed
records and inline embed links remain the renderable source of truth.
"""

from __future__ import annotations

from backend.apps.ai.utils.app_skill_json_cleanup import strip_successful_app_skill_json_blocks


def test_successful_app_skill_json_blocks_are_stripped_from_final_text() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}
```

Here are the best matches.
"""

    cleaned = strip_successful_app_skill_json_blocks(text)

    assert cleaned == "Here are the best matches."


def test_successful_app_skill_json_blocks_strip_nested_payloads() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"travel","skill_id":"search_connections","providers":[{"id":"google_flights","name":"Google Flights"}]}
```

The afternoon flight is the best option.
"""

    cleaned = strip_successful_app_skill_json_blocks(text)

    assert "app_skill_use" not in cleaned
    assert "google_flights" not in cleaned
    assert cleaned == "The afternoon flight is the best option."


def test_non_app_skill_json_fences_are_preserved() -> None:
    text = """```json
{"embed_id":"abc","kind":"example"}
```

This JSON is user-visible output.
"""

    assert strip_successful_app_skill_json_blocks(text) == text


def test_inline_embed_links_remain_supported() -> None:
    text = "See [the Vueling flight](embed:vueling-2026-abc) for details."

    assert strip_successful_app_skill_json_blocks(text) == text
