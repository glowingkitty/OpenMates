"""Regression tests for canonical app-skill metadata in streamed answers.

Final assistant Markdown retains only the hidden fields needed to reconstruct
the permanent execution group with the same order after completion and reload.
"""

from __future__ import annotations

from backend.apps.ai.utils.app_skill_json_cleanup import (
    canonicalize_app_skill_json_blocks,
    strip_failed_app_skill_json_blocks,
)


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_app_skill_json_blocks_retain_canonical_execution_identity() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}
```

Here are the best matches.
"""

    cleaned = canonicalize_app_skill_json_blocks(text)
    assert cleaned == (
        '```json\n{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}\n```\n\n'
        "Here are the best matches."
    )


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_app_skill_json_blocks_strip_noncanonical_nested_payloads() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","app_id":"travel","skill_id":"search_connections","providers":[{"id":"google_flights","name":"Google Flights"}]}
```

The afternoon flight is the best option.
"""

    cleaned = canonicalize_app_skill_json_blocks(text)
    assert '"type":"app_skill_use"' in cleaned
    assert "google_flights" not in cleaned
    assert "The afternoon flight is the best option." in cleaned


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_parent_and_inline_child_embed_links_remain_renderable() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"parent","app_id":"travel","skill_id":"search_connections"}
```

See [the afternoon train](embed:train-abc123) for details.
"""

    cleaned = canonicalize_app_skill_json_blocks(text)
    assert cleaned == (
        '```json\n{"type":"app_skill_use","embed_id":"parent","app_id":"travel","skill_id":"search_connections"}\n```\n\n'
        "See [the afternoon train](embed:train-abc123) for details."
    )


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_app_skill_payloads_with_backticks_are_canonicalized() -> None:
    text = """```json
{"type":"app_skill_use","embed_id":"abc","query":"find `quoted` text"}
```
"""
    assert canonicalize_app_skill_json_blocks(text) == (
        '```json\n{"type":"app_skill_use","embed_id":"abc"}\n```'
    )


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_app_skill_payloads_with_typographic_quotes_are_canonicalized() -> None:
    text = (
        "```json\n"
        "{\u201ctype\u201d:\u201capp_skill_use\u201d,\u201cembed_id\u201d:\u201cabc\u201d,"
        "\u201capp_id\u201d:\u201cimages\u201d,\u201cskill_id\u201d:\u201cgenerate\u201d}"
        "\n```\n"
    )
    assert canonicalize_app_skill_json_blocks(text) == (
        '```json\n{"type":"app_skill_use","embed_id":"abc",'
        '"app_id":"images","skill_id":"generate"}\n```'
    )


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_failed_app_skill_payloads_with_typographic_quotes_are_stripped() -> None:
    text = (
        "Intro\n\n"
        "```json\n"
        "{\u201ctype\u201d:\u201capp_skill_use\u201d,"
        "\u201cembed_id\u201d:\u201cfailed-embed\u201d,"
        "\u201capp_id\u201d:\u201cimages\u201d,\u201cskill_id\u201d:\u201cgenerate\u201d}"
        "\n```\n\n"
        "Visible answer text\n"
    )

    cleaned, stripped_count = strip_failed_app_skill_json_blocks(
        text,
        {"failed-embed"},
    )
    assert stripped_count == 1
    assert "app_skill_use" not in cleaned
    assert "failed-embed" not in cleaned
    assert cleaned == "Intro\n\nVisible answer text"


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_non_app_skill_json_fences_are_preserved() -> None:
    text = """```json
{"embed_id":"abc","kind":"example"}
```

This JSON is user-visible output.
"""
    assert canonicalize_app_skill_json_blocks(text) == text


# contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
def test_inline_embed_links_remain_supported() -> None:
    text = "See [the Vueling flight](embed:vueling-2026-abc) for details."
    assert canonicalize_app_skill_json_blocks(text) == text
