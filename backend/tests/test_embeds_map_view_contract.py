"""Contract tests for the virtual embeds_results_view assistant block.

The results view is a rendering instruction over existing embeds. These tests keep
the AI instructions and deterministic guard aligned with the product contract in
docs/specs/embeds-map-view/spec.yml.
"""

from backend.apps.ai.utils.embeds_map_view import (
    ALLOWED_EMBEDS_MAP_VIEW_FIELDS,
    EMBEDS_MAP_VIEW_INSTRUCTION,
    append_missing_embeds_map_view_block,
    content_has_map_view_capable_skill_marker,
    content_has_map_capable_app_skill_use,
    extract_map_capable_source_refs,
    extract_inline_embed_refs,
    is_embeds_map_view_fence_language,
    is_map_view_request,
    is_map_view_suppressed_request,
    normalize_embeds_map_view_blocks,
    should_include_embeds_results_view_instruction,
    should_include_embeds_map_view_hint,
)


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_instruction_limits_fields_and_forbids_paid_enrichment() -> None:
    assert ALLOWED_EMBEDS_MAP_VIEW_FIELDS == {"title", "embeds", "sources", "highlight"}
    assert "```embeds_results_view" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "When location-capable, route-capable, or schedule-capable embed refs are" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "include exactly" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "by default" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "title" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "embeds" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "sources" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "highlight" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "Do not include filters" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "Do not call" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "Prefer adding this block" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "travel.flight_details" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "Flightradar24" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "FlightAware" in EMBEDS_MAP_VIEW_INSTRUCTION


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_map_view_fence_language_is_reserved_for_client_renderer() -> None:
    assert is_embeds_map_view_fence_language("embeds_map_view") is True
    assert is_embeds_map_view_fence_language("embeds_map_view title=Berlin") is True
    assert is_embeds_map_view_fence_language("embeds_results_view") is True
    assert is_embeds_map_view_fence_language("embeds_results_view title=Berlin") is True
    assert is_embeds_map_view_fence_language("") is False
    assert is_embeds_map_view_fence_language("   ") is False
    assert is_embeds_map_view_fence_language("json") is False
    assert is_embeds_map_view_fence_language(None) is False


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_map_view_hint_defaults_to_capable_skills_unless_suppressed() -> None:
    assert is_map_view_request(["Find Berlin AI events and show them on a map."]) is True
    assert is_map_view_request(["Find Berlin AI events."]) is False
    assert is_map_view_suppressed_request(["Find Berlin AI events, but no map."]) is True
    assert is_map_view_suppressed_request(["Find Berlin AI events, but no calendar."]) is True
    assert is_map_view_suppressed_request(["Find Berlin AI events, text only."]) is True
    assert should_include_embeds_map_view_hint(
        "events",
        "search",
        ["Find upcoming AI events in Berlin and show them on a map/list."],
    ) is True
    assert should_include_embeds_map_view_hint(
        "events",
        "search",
        ["Find upcoming AI events in Berlin."],
    ) is True
    assert should_include_embeds_map_view_hint(
        "events",
        "search",
        ["Find upcoming AI events in Berlin, but no map."],
    ) is False
    assert should_include_embeds_map_view_hint(
        "fitness",
        "search_classes",
        ["Find yoga classes near Kreuzberg tomorrow."],
    ) is True
    assert should_include_embeds_map_view_hint(
        "fitness",
        "search_locations",
        ["Find gyms near Friedrichshain."],
    ) is True
    assert should_include_embeds_map_view_hint(
        "home",
        "search",
        ["Find apartments near Kollwitzplatz."],
    ) is True
    assert should_include_embeds_map_view_hint(
        "web",
        "search",
        ["Find AI news and show it on a map."],
    ) is False


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_results_view_instruction_is_gated_to_visual_capable_skills_or_history() -> None:
    assert should_include_embeds_results_view_instruction(
        {"news-search", "web-search"},
        ["Find AI news."],
        ["app_id: news\nskill_id: search\nembed_ref: npr-org-123"],
    ) is False
    assert should_include_embeds_results_view_instruction(
        {"events-search"},
        ["Find Berlin AI events."],
        [],
    ) is True
    assert should_include_embeds_results_view_instruction(
        set(),
        ["Summarize those results."],
        ["app_id: maps\nskill_id: search\nembed_ref: quiet-cafe-123"],
    ) is True
    assert should_include_embeds_results_view_instruction(
        {"events-search"},
        ["Find Berlin AI events, text only."],
        [],
    ) is False


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_history_marker_detector_rejects_news_and_web_search_results() -> None:
    assert content_has_map_view_capable_skill_marker(
        "app_id: news\nskill_id: search\nembed_ref: npr-org-123"
    ) is False
    assert content_has_map_view_capable_skill_marker(
        "app_id: web\nskill_id: search\nembed_ref: example-com-123"
    ) is False
    assert content_has_map_view_capable_skill_marker(
        "app_id: health\nskill_id: search_appointments\nembed_ref: appointment-123"
    ) is True


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_content_detector_finds_map_capable_app_skill_json_fence() -> None:
    content = '''```json
{"type":"app_skill_use","embed_id":"abc","app_id":"events","skill_id":"search"}
```

* [One](embed:event-one-111111)
'''

    assert content_has_map_capable_app_skill_use(content) is True
    assert extract_map_capable_source_refs(content) == ["abc"]


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_content_detector_rejects_non_map_capable_app_skill_json_fence() -> None:
    content = '''```json
{"type":"app_skill_use","embed_id":"abc","app_id":"web","skill_id":"search"}
```
'''

    assert content_has_map_capable_app_skill_use(content) is False


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_append_missing_map_view_uses_existing_inline_refs_only() -> None:
    content = """Here are results:
- [One](embed:event-one-111111)
- [One again](embed:event-one-111111)
- [Two](embed:event-two-222222)
"""

    repaired, changed = append_missing_embeds_map_view_block(content, title="Berlin AI events")

    assert changed is True
    assert extract_inline_embed_refs(content) == ["event-one-111111", "event-two-222222"]
    assert "```embeds_results_view" in repaired
    assert "title: Berlin AI events" in repaired
    assert "embeds: event-one-111111, event-two-222222" in repaired


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_append_missing_map_view_prefers_source_refs_and_highlights_inline_children() -> None:
    content = '''```json
{"type":"app_skill_use","embed_id":"source-abc","app_id":"travel","skill_id":"search_connections"}
```

[!](embed:source-abc)
- [08:27 train](embed:rb-0827-tLB)
- [08:56 train](embed:rb-0856-nAn)
'''

    repaired, changed = append_missing_embeds_map_view_block(content, title="Bonn to Munich routes")

    assert changed is True
    assert "sources: source-abc" in repaired
    assert "highlight: rb-0827-tLB, rb-0856-nAn" in repaired
    assert "embeds: source-abc" not in repaired


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_append_missing_map_view_uses_known_source_refs() -> None:
    repaired, changed = append_missing_embeds_map_view_block(
        "Here are the matching events.",
        source_refs=["events-search-12ab34"],
    )

    assert changed is True
    assert "sources: events-search-12ab34" in repaired
    assert "embeds:" not in repaired


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_append_missing_map_view_is_noop_when_block_exists() -> None:
    content = """[One](embed:event-one-111111)

```embeds_map_view
title: Existing
embeds: event-one-111111
```
"""

    repaired, changed = append_missing_embeds_map_view_block(content)

    assert changed is False
    assert repaired == content


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_append_missing_results_view_is_noop_when_new_block_exists() -> None:
    content = """[One](embed:event-one-111111)

```embeds_results_view
title: Existing
embeds: event-one-111111
```
"""

    repaired, changed = append_missing_embeds_map_view_block(content)

    assert changed is False
    assert repaired == content


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_normalizer_drops_extra_fields_and_deduplicates_refs() -> None:
    content = """Results:

```embeds_results_view
title: Berlin AI events
provider: paid-provider
filters: type=event
embeds: ai-night-111111, ai-night-111111, founders-breakfast-222222
enrichment: travel.flight_details
```
"""

    normalized, changed = normalize_embeds_map_view_blocks(content)

    assert changed is True
    assert "provider" not in normalized
    assert "filters" not in normalized
    assert "enrichment" not in normalized
    assert "embeds: ai-night-111111, founders-breakfast-222222" in normalized


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_normalizer_accepts_source_and_highlight_fields_only() -> None:
    content = """```embeds_results_view
title: Munich to Zurich options
sources: travel-search-connections-12ab34
highlight: nightjet-7abc12, db-ice-9def34
```
"""

    normalized, changed = normalize_embeds_map_view_blocks(content)

    assert changed is False
    assert normalized == content


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_normalizer_promotes_map_capable_parent_embed_refs_to_sources() -> None:
    content = '''```json
{"type":"app_skill_use","embed_id":"events-search-12ab34","app_id":"events","skill_id":"search"}
```

```embeds_results_view
title: Berlin AI events
embeds: events-search-12ab34, ai-founders-meetup-7f3a91
```
'''

    normalized, changed = normalize_embeds_map_view_blocks(content)

    assert changed is True
    assert "sources: events-search-12ab34" in normalized
    assert "highlight: ai-founders-meetup-7f3a91" in normalized
    assert "embeds: events-search-12ab34" not in normalized


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_normalizer_promotes_known_source_refs_without_json_fence() -> None:
    content = """```embeds_results_view
title: Berlin AI events
embeds: events-search-12ab34, ai-founders-meetup-7f3a91
```
"""

    normalized, changed = normalize_embeds_map_view_blocks(
        content,
        source_refs=["events-search-12ab34"],
    )

    assert changed is True
    assert "sources: events-search-12ab34" in normalized
    assert "highlight: ai-founders-meetup-7f3a91" in normalized
    assert "embeds:" not in normalized


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_normalizer_removes_json_like_map_blocks() -> None:
    content = """```embeds_results_view
{"title":"Bad block","provider":"paid","embeds":["one-111111"]}
```
"""

    normalized, changed = normalize_embeds_map_view_blocks(content)

    assert changed is True
    assert "```embeds_results_view" not in normalized
    assert "Bad block" in normalized
    assert "provider" not in normalized
