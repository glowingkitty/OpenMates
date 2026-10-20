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
def test_wr7tn_copied_example_source_is_repaired_to_real_short_parent() -> None:
    from backend.apps.ai.utils.embeds_map_view import (
        collect_results_view_sources, map_view_source_bindings_from_tool_calls,
        preferred_map_view_source_refs, validate_embeds_map_view_sources,
    )

    parent_id = "11111111-1111-4111-8111-111111111111"
    parent_ref = "events-search-111111"
    sources = collect_results_view_sources([{
        "embed_id": parent_id, "embed_ref": parent_ref, "status": "finished",
        "child_embed_ids": [f"child-{i}" for i in range(15)],
    }], app_id="events", skill_id="search")
    assert sources == {parent_ref: parent_id}
    bindings = map_view_source_bindings_from_tool_calls([{
        "app_id": "events", "skill_id": "search", "embed_id": parent_id,
        "source_ref_bindings": sources,
    }])
    content = "```embeds_results_view\ntitle: Berlin AI events\nsources: events-search-12ab34\n```"
    repaired, changed = validate_embeds_map_view_sources(
        content, available_sources=bindings, repair_source_refs=preferred_map_view_source_refs(bindings),
    )
    assert changed is True
    assert f"sources: {parent_ref}" in repaired
    assert "events-search-12ab34" not in repaired
    assert parent_id not in repaired
    assert validate_embeds_map_view_sources(
        repaired, available_sources=bindings, repair_source_refs=[parent_ref],
    ) == (repaired, False)


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_source_validation_keeps_history_and_does_not_guess_between_searches() -> None:
    from backend.apps.ai.utils.embeds_map_view import (
        extract_results_view_source_refs, validate_embeds_map_view_sources,
    )

    bindings = {"events-search-old": "old-id", "events-search-new": "new-id"}
    previous = "```embeds_results_view\ntitle: Earlier results\nsources: events-search-old\n```"
    assert validate_embeds_map_view_sources(
        previous, available_sources=bindings, repair_source_refs=["events-search-new"],
    ) == (previous, False)
    mixed_case = previous.replace("sources:", "Sources:")
    assert extract_results_view_source_refs(mixed_case) == ["events-search-old"]
    normalized, _ = validate_embeds_map_view_sources(
        mixed_case, available_sources=bindings, repair_source_refs=["events-search-new"],
    )
    assert "sources: events-search-old" in normalized
    assert "events-search-new" not in normalized
    bad = previous.replace("events-search-old", "events-search-12ab34")
    repaired, changed = validate_embeds_map_view_sources(
        bad, available_sources=bindings, repair_source_refs=bindings,
    )
    assert changed is True
    assert "```" not in repaired
    assert "events-search-new" not in repaired
    assert "events-search-old" not in repaired


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_source_validation_preserves_selected_children_and_valid_sources() -> None:
    from backend.apps.ai.utils.embeds_map_view import validate_embeds_map_view_sources

    content = "```embeds_results_view\ntitle: Selected events\nembeds: event-one-abc\nsources: invented-source\n```"
    repaired, _ = validate_embeds_map_view_sources(
        content, available_sources={"events-search-real": "parent"}, repair_source_refs=["events-search-real"],
    )
    assert "embeds: event-one-abc" in repaired
    assert "sources:" not in repaired
    mixed = "```embeds_results_view\ntitle: Events\nsources: events-search-real, invented-source\n```"
    repaired, _ = validate_embeds_map_view_sources(
        mixed, available_sources={"events-search-real": "parent"}, repair_source_refs=[],
    )
    assert "sources: events-search-real" in repaired
    assert "invented-source" not in repaired


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_source_provenance_handles_batches_and_rejects_unregistered_aliases() -> None:
    from backend.apps.ai.utils.embeds_map_view import (
        collect_results_view_sources, map_view_source_bindings_from_tool_calls, preferred_map_view_source_refs,
    )

    bindings = map_view_source_bindings_from_tool_calls([{
        "app_id": "events", "skill_id": "search", "embed_id": "parent-one",
        "embed_ids": ["parent-one", "parent-two"],
        "source_ref_bindings": {"events-search-one": "parent-one", "events-search-two": "parent-two",
                                "invented": "not-authored"},
    }])
    assert preferred_map_view_source_refs(bindings) == ["events-search-one", "events-search-two"]
    assert "invented" not in bindings
    assert collect_results_view_sources([
        {"embed_id": "failed", "embed_ref": "failed-ref", "status": "error", "child_embed_ids": ["a"]},
        {"embed_id": "empty", "embed_ref": "empty-ref", "child_embed_ids": []},
    ], app_id="events", skill_id="search") == {}
    assert "events-search-12ab34" not in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "source_ref" in EMBEDS_MAP_VIEW_INSTRUCTION
    assert "Instruction examples and placeholder text are never usable references" in EMBEDS_MAP_VIEW_INSTRUCTION


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
