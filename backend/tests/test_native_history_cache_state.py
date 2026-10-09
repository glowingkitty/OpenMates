"""Focused contracts for temporary native provider replay state."""

# contract-test-file: infrastructure

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.native_history_cache import (
    add_dispatch_event, append_provider_output, append_tool_results,
    collect_server_embed_provenance,
    finalize_native_cache_state, matched_visible_prefix, new_native_segment,
    native_replay_fits_budget, replay_byte_estimate, resume_native_segment,
    seal_native_embed_fingerprints, selected_tool_delta, validate_native_embed_fingerprints,
)
from backend.apps.ai.processing.chat_compressor import (
    model_history_token_budget, model_total_input_token_budget,
)
from backend.apps.ai.llm_providers.native_cache_context import (
    openai_function_tool, validate_native_cache_context,
)
from backend.apps.ai.llm_providers.openai_responses import native_responses_input
from backend.shared.python_utils.native_cache_history import canonical_content_sha256
from backend.apps.ai.utils.app_skill_json_cleanup import canonicalize_app_skill_json_blocks
from backend.apps.ai.utils.embeds_map_view import (
    append_missing_embeds_map_view_block, extract_map_capable_source_refs,
)


def _tool(name, description="first"):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {}},
    }}


def _message(role, message_id, content):
    return {"role": role, "message_id": message_id, "content": content}


def _segment():
    visible = [_message("user", "u1", "Find the weather")]
    state = new_native_segment(
        model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
        provider_prefix="openai", cacheable_system_prefix="Stable policy",
        selected_tools=[_tool("weather")],
        messages=[{"role": "system", "content": "Stable policy"},
                  {"role": "user", "content": "Find the weather"}],
        visible_history=visible,
    )
    return state, visible


def test_same_second_user_before_prior_assistant_cannot_start_native_segment():
    """Timestamp sorting can move a rapid successor before its prior answer."""
    visible = [
        {**_message("user", "u1", "first"), "created_at": 100},
        {**_message("assistant", "a1", "answer"), "created_at": 101},
        {**_message("user", "u2", "follow up"), "created_at": 100},
    ]
    ordered = sorted(visible, key=lambda message: message["created_at"])
    assert [message["message_id"] for message in ordered] == ["u1", "u2", "a1"]
    assert ordered[-1]["role"] == "assistant"
    with pytest.raises(ValueError, match="current user message"):
        new_native_segment(
            model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
            provider_prefix="openai", cacheable_system_prefix="Stable policy",
            selected_tools=[],
            messages=[{"role": "system", "content": "Stable policy"}, *ordered],
            visible_history=ordered,
        )


def test_tool_timeline_keeps_old_output_and_selected_deltas():
    state, visible = _segment()
    add_dispatch_event(state, system_prompt="Stable policy\nCurrent date: today",
                       selected_tools=[_tool("weather")], openai=True)
    first_event = copy.deepcopy(state["events"][0])
    output = [{"type": "function_call", "call_id": "call-1", "name": "weather", "arguments": "{}"}]
    append_provider_output(state, output, "")
    append_tool_results(state, [{"role": "tool", "tool_call_id": "call-1", "content": "sunny"}])
    add_dispatch_event(state, system_prompt="Stable policy\nCurrent date: today",
                       selected_tools=[_tool("weather"), _tool("time")], openai=True)
    assert len(state["events"]) == 2
    assert state["events"][0] == first_event
    assert state["events"][1]["after_message_index"] == 3
    assert [tool["function"]["name"] for tool in state["events"][1]["add_tools"]] == ["time"]
    assert "system_suffix" not in state["events"][1]  # unchanged instruction is not duplicated
    assert state["messages"][2]["provider_transport_state"] == output
    assert replay_byte_estimate(state) > len(str(output))


def test_changed_or_cleared_dynamic_instructions_explicitly_replace_old_context():
    state, _ = _segment()
    add_dispatch_event(state, system_prompt="Stable policy\nBudget: 10",
                       selected_tools=[_tool("weather")], openai=True)
    add_dispatch_event(state, system_prompt="Stable policy\nBudget: 5",
                       selected_tools=[_tool("weather")], openai=True)
    add_dispatch_event(state, system_prompt="Stable policy",
                       selected_tools=[_tool("weather")], openai=True)
    assert len(state["events"]) == 3
    assert "replaces earlier current turn context" in state["events"][1]["system_suffix"]
    assert "Budget: 5" in state["events"][1]["system_suffix"]
    assert state["events"][2]["system_suffix"].endswith("(none)")


def test_finalized_visible_boundary_replays_only_an_exact_followup():
    state, visible = _segment()
    add_dispatch_event(state, system_prompt="Stable policy\nCurrent date: today",
                       selected_tools=[_tool("weather")], openai=True)
    state["expected_visible_response"] = "It is sunny."
    state["raw_final_text"] = "It is sunny."
    output = [{"type": "message", "content": [{"type": "output_text", "text": "It is sunny."}]}]
    final = finalize_native_cache_state(
        state, raw_final_output=output, content_markdown="It is sunny.", assistant_message_id="a1",
    )
    assert final is not None
    followup = [*visible, _message("assistant", "a1", "It is sunny."),
                _message("user", "u2", "How about tomorrow?")]
    assert matched_visible_prefix(final, followup) == 2
    resumed = resume_native_segment(
        final, model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
        provider_prefix="openai", cacheable_system_prefix="Stable policy",
        visible_history=followup,
        new_user_message={"role": "user", "content": "How about tomorrow?"},
    )
    assert resumed is not None
    assert resumed["messages"][:-1] == final["messages"]
    assert resumed["events"] == final["events"]
    assert final["messages"][-1]["provider_transport_state"] == output
    assert resume_native_segment(
        final, model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
        provider_prefix="openai", cacheable_system_prefix="Changed policy",
        visible_history=followup,
        new_user_message={"role": "user", "content": "How about tomorrow?"},
    ) is None
    changed = copy.deepcopy(followup)
    changed[1]["content"] = "Different answer"
    assert matched_visible_prefix(final, changed) is None


def test_visible_boundary_binds_sender_category_and_timestamp():
    state, visible = _segment()
    state["expected_visible_response"] = "Done"
    output = [{"type": "message"}]
    final = finalize_native_cache_state(
        state, raw_final_output=output, content_markdown="Done",
        assistant_message_id="a1", assistant_category="general_knowledge",
        assistant_created_at=123,
    )
    assert final is not None
    followup = [*visible, {**_message("assistant", "a1", "Done"),
                           "sender_name": "assistant", "category": "general_knowledge",
                           "created_at": 123}, _message("user", "u2", "Next")]
    assert matched_visible_prefix(final, followup) == 2
    for key, changed_value in (("sender_name", "other"), ("category", "other"),
                               ("created_at", 124)):
        changed = copy.deepcopy(followup)
        changed[1][key] = changed_value
        assert matched_visible_prefix(final, changed) is None


def test_schema_changes_and_removed_tools_never_reenter_allowed_set():
    first = [_tool("weather"), _tool("time")]
    next_tools = [_tool("time")]
    added, removed = selected_tool_delta(first, next_tools, openai=True)
    assert added == [] and removed == ["weather"]
    with pytest.raises(ValueError, match="schema changed"):
        selected_tool_delta(first, [_tool("weather", "new schema"), _tool("time")], openai=True)
    added, removed = selected_tool_delta(first, [_tool("weather", "new schema")], openai=False)
    assert [tool["function"]["name"] for tool in added] == ["weather"]
    assert removed == ["time"]


def test_substantive_final_edit_cold_resets_private_replay():
    state, _ = _segment()
    state["expected_visible_response"] = "The source said sunny."
    state["raw_final_text"] = "The source said sunny."
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown="The corrected source said rainy.", assistant_message_id="a1",
    ) is None


def test_server_app_skill_reference_is_presentation_only_and_resolved_followup_matches():
    state, visible = _segment()
    state["expected_visible_response"] = "Sunny."
    ref = {"type": "app_skill_use", "embed_id": "embed-1",
           "app_id": "weather", "skill_id": "search"}
    rendered = f"```json\n{json.dumps(ref)}\n```\n\nSunny."
    info = [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-1",
             "embed_reference": json.dumps(ref)}]
    final = finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}], content_markdown=rendered,
        assistant_message_id="a1", tool_calls_info=info,
    )
    assert final is not None
    followup = [*visible, {**_message("assistant", "a1", "TOON: resolved immutable weather result"),
                           "native_cache_canonical_content_sha256": canonical_content_sha256(rendered)},
                _message("user", "u2", "Tomorrow?")]
    assert matched_visible_prefix(final, followup) == 2
    edited = copy.deepcopy(followup)
    edited[1]["native_cache_canonical_content_sha256"] = canonical_content_sha256("edited original")
    assert matched_visible_prefix(final, edited) is None


@pytest.mark.asyncio
async def test_live_shape_canonical_reference_and_map_repair_keep_encrypted_multiturn_replay():
    state, visible = _segment()
    state["expected_visible_response"] = "The Berlin results are ready."
    full = {"type": "app_skill_use", "embed_id": "embed-1", "app_id": "events",
            "skill_id": "search", "query": "Berlin AI events", "provider": "fixture"}
    canonical = {key: full[key] for key in ("type", "embed_id", "app_id", "skill_id")}
    info = [{"app_id": "events", "skill_id": "search", "embed_id": "embed-1",
             "embed_reference": json.dumps(full)}]
    streamed = f"```json\n{json.dumps(full)}\n```\n\nThe Berlin results are ready."
    auto_map, repaired = append_missing_embeds_map_view_block(streamed, source_refs=[])
    assert repaired and extract_map_capable_source_refs(streamed) == ["embed-1"]
    rendered = canonicalize_app_skill_json_blocks(auto_map)
    assert f"```json\n{json.dumps(canonical, separators=(',', ':'))}\n```" in rendered
    assert "sources: embed-1" in rendered and '"query"' not in rendered
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}], content_markdown=rendered,
        assistant_message_id="a1", tool_calls_info=info,
    ) is None
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}], content_markdown=rendered,
        assistant_message_id="a1", tool_calls_info=info,
        presentation_steps=[{"kind": "append_map_view", "refs": ["untrusted-id"]}],
    ) is None
    final = finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}], content_markdown=rendered,
        assistant_message_id="a1", tool_calls_info=info,
        # Actual source_refs was empty; the stream records only the derived
        # executed source identity, not a user-supplied map reference.
        presentation_steps=[{"kind": "append_map_view", "refs": ["embed-1"]}],
    )
    assert final is not None
    row = {"embed_id": "embed-1", "type": "app_skill_use", "status": "finished",
           "hashed_user_id": "owner", "encrypted_content": "vault:result",
           "version_number": 1, "updated_at": 123}
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=row))
    sealed = await seal_native_embed_fingerprints(final, info, cache, "owner")
    assert sealed is not None and set(sealed["embed_fingerprints"]) == {"embed-1"}
    retained = json.loads(json.dumps(sealed))  # encrypted-context plaintext after vault decrypt
    followup = [*visible, _message("assistant", "a1", rendered), _message("user", "u2", "More?")]
    resumed = resume_native_segment(
        retained, model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
        provider_prefix="openai", cacheable_system_prefix="Stable policy",
        visible_history=followup, new_user_message={"role": "user", "content": "More?"},
    )
    assert resumed is not None
    resumed["expected_visible_response"] = "Here is another result."
    second = finalize_native_cache_state(
        resumed, raw_final_output=[{"type": "message", "content": "Here is another result."}],
        content_markdown="Here is another result.", assistant_message_id="a2",
    )
    assert second is not None
    second = await seal_native_embed_fingerprints(second, [], cache, "owner")
    assert second is not None and second["embed_fingerprints"] == sealed["embed_fingerprints"]
    cache.get_embed_from_cache.return_value = {**row, "hashed_user_id": "other"}
    assert await seal_native_embed_fingerprints(final, info, cache, "owner") is None


def test_canonical_app_reference_remains_cardinality_and_identity_bounded():
    state, _ = _segment()
    state["expected_visible_response"] = "Sunny."
    full = {"type": "app_skill_use", "embed_id": "embed-1", "app_id": "weather",
            "skill_id": "search", "query": "weather"}
    canonical = {key: full[key] for key in ("type", "embed_id", "app_id", "skill_id")}
    info = [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-1",
             "embed_reference": json.dumps(full)}]

    def accepted(payloads, answer="Sunny."):
        rendered = "\n\n".join(f"```json\n{json.dumps(payload)}\n```" for payload in payloads)
        return finalize_native_cache_state(
            state, raw_final_output=[{"type": "message"}],
            content_markdown=f"{rendered}\n\n{answer}", assistant_message_id="a1",
            tool_calls_info=info,
        ) is not None

    assert accepted([full])
    assert accepted([canonical])
    assert not accepted([full, canonical])
    alternate_info = [{**info[0], "embed_references": [json.dumps({**full, "query": "changed"})]}]
    duplicate = "\n\n".join(f"```json\n{json.dumps(canonical)}\n```" for _ in range(2))
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown=f"{duplicate}\n\nSunny.", assistant_message_id="a1",
        tool_calls_info=alternate_info,
    ) is None
    assert not accepted([{**canonical, "query": "changed"}])
    assert not accepted([{**canonical, "embed_id": "other"}])
    assert not accepted([canonical], answer="Rainy.")


def test_invalid_inline_link_replay_requires_the_exact_trusted_rewrite():
    state, _ = _segment()
    state["expected_visible_response"] = "Read [the result](embed:missing-ref) next."
    approved = [{"kind": "strip_invalid_links", "refs": ["trusted-ref"]}]
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown="Read the result next.", assistant_message_id="a1",
        presentation_steps=approved,
    ) is not None
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown="Read a different result next.", assistant_message_id="a1",
        presentation_steps=approved,
    ) is None
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown="Read the result next.", assistant_message_id="a1",
        presentation_steps=[{"kind": "strip_invalid_links", "refs": ["missing-ref"]}],
    ) is None


def test_finished_single_embed_keeps_same_id_placeholder_provenance_for_replay():
    state, _ = _segment()
    state["expected_visible_response"] = "Sunny."
    ref = {"type": "app_skill_use", "embed_id": "embed-1",
           "app_id": "weather", "skill_id": "search"}
    placeholder = {"embed_id": "embed-1", "embed_reference": json.dumps(ref)}
    updated = [{"embed_id": "embed-1", "status": "finished", "child_embed_ids": []}]
    references, embed_ids = collect_server_embed_provenance(
        updated, placeholder, app_id="weather", skill_id="search",
    )
    assert references == [placeholder["embed_reference"]]
    assert embed_ids == ["embed-1"]
    info = [{"app_id": "weather", "skill_id": "search",
             "embed_id": embed_ids[0], "embed_reference": references[0]}]
    visible = f"```json\n{json.dumps(ref, separators=(',', ':'))}\n```\n\nSunny."
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown=visible, assistant_message_id="a1", tool_calls_info=info,
    ) is not None

    for bad_placeholder in (
        {"embed_id": "other", "embed_reference": json.dumps(ref)},
        {"embed_id": "embed-1", "embed_reference": json.dumps({**ref, "app_id": "other"})},
    ):
        bad_refs, ids = collect_server_embed_provenance(
            updated, bad_placeholder, app_id="weather", skill_id="search",
        )
        assert not bad_refs and ids == ["embed-1"]
        assert finalize_native_cache_state(
            state, raw_final_output=[{"type": "message"}],
            content_markdown=visible, assistant_message_id="a1",
            tool_calls_info=[{"app_id": "weather", "skill_id": "search", "embed_id": ids[0]}],
        ) is None


def test_presentation_tolerance_rejects_unapproved_or_mutated_embed_and_answer():
    state, _ = _segment()
    state["expected_visible_response"] = "Sunny."
    ref = {"type": "app_skill_use", "embed_id": "embed-1",
           "app_id": "weather", "skill_id": "search"}
    info = [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-1",
             "embed_reference": json.dumps(ref)}]
    variants = [
        {**ref, "embed_id": "invented"},
        {**ref, "type": "code"},
        {**ref, "app_id": "other"},
    ]
    for variant in variants:
        assert finalize_native_cache_state(
            state, raw_final_output=[{"type": "message"}],
            content_markdown=f"```json\n{json.dumps(variant)}\n```\n\nSunny.",
            assistant_message_id="a1", tool_calls_info=info,
        ) is None
    duplicated = f"```json\n{json.dumps(ref)}\n```\n\n```json\n{json.dumps(ref)}\n```\n\nSunny."
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown=duplicated, assistant_message_id="a1",
        tool_calls_info=[{**info[0], "embed_references": [json.dumps(ref)]}],
    ) is None
    assert finalize_native_cache_state(
        state, raw_final_output=[{"type": "message"}],
        content_markdown=f"```json\n{json.dumps(ref)}\n```\n\nActually rainy.",
        assistant_message_id="a1", tool_calls_info=info,
    ) is None


@pytest.mark.asyncio
async def test_finished_app_embed_row_must_remain_identical_for_followup():
    state, _ = _segment()
    reference = {"type": "app_skill_use", "embed_id": "embed-1",
                 "app_id": "weather", "skill_id": "search"}
    info = [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-1",
             "embed_reference": json.dumps(reference)}]
    row = {"embed_id": "embed-1", "type": "app_skill_use", "status": "finished",
           "hashed_user_id": "owner", "encrypted_content": "vault:original",
           "version_number": 1, "updated_at": 123}
    reader = AsyncMock(return_value=row)
    cache = SimpleNamespace(get_embed_from_cache=reader)
    sealed = await seal_native_embed_fingerprints(state, info, cache, "owner")
    assert sealed is not None and set(sealed["embed_fingerprints"]) == {"embed-1"}
    assert await validate_native_embed_fingerprints(sealed, cache, "owner")
    reader.return_value = {**row, "encrypted_content": "vault:changed"}
    assert not await validate_native_embed_fingerprints(sealed, cache, "owner")
    assert await seal_native_embed_fingerprints(sealed, [], cache, "owner") is None
    reader.return_value = {**row, "status": "processing"}
    assert not await validate_native_embed_fingerprints(sealed, cache, "owner")
    reader.return_value = {**row, "version_number": 2}
    assert not await validate_native_embed_fingerprints(sealed, cache, "owner")
    reader.return_value = None
    assert not await validate_native_embed_fingerprints(sealed, cache, "owner")
    reader.return_value = {**row, "hashed_user_id": "other"}
    assert not await validate_native_embed_fingerprints(sealed, cache, "owner")


@pytest.mark.asyncio
async def test_embed_fingerprints_merge_across_turns_without_reads_for_no_embed_state():
    state, _ = _segment()
    reader = AsyncMock()
    cache = SimpleNamespace(get_embed_from_cache=reader)
    empty = await seal_native_embed_fingerprints(state, [], cache, "owner")
    assert empty is not None and empty["embed_fingerprints"] == {}
    assert await validate_native_embed_fingerprints(empty, cache, "owner")
    reader.assert_not_awaited()
    rows = {
        embed_id: {"embed_id": embed_id, "type": "app_skill_use", "status": "finished",
                   "hashed_user_id": "owner", "encrypted_content": f"vault:{embed_id}"}
        for embed_id in ("embed-1", "embed-2")
    }
    reader.side_effect = lambda embed_id: rows.get(embed_id)
    first = await seal_native_embed_fingerprints(
        empty, [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-1",
                 "embed_reference": json.dumps({"type": "app_skill_use", "embed_id": "embed-1",
                                                "app_id": "weather", "skill_id": "search"})}],
        cache, "owner",
    )
    assert first is not None
    second = await seal_native_embed_fingerprints(
        first, [{"app_id": "weather", "skill_id": "search", "embed_id": "embed-2",
                 "embed_reference": json.dumps({"type": "app_skill_use", "embed_id": "embed-2",
                                                "app_id": "weather", "skill_id": "search"})}],
        cache, "owner",
    )
    assert second is not None and set(second["embed_fingerprints"]) == {"embed-1", "embed-2"}


def test_replay_budget_counts_opaque_output_and_new_tool_definitions():
    state, _ = _segment()
    quote_history = copy.deepcopy(state["messages"])
    quote_tools = copy.deepcopy(state["baseline_tools"])
    assert native_replay_fits_budget(
        state, quote_system="", quote_history=quote_history,
        quote_tools=quote_tools, input_token_budget=10_000,
    )
    quote_history.append({"role": "assistant", "provider_transport_state": [{
        "type": "reasoning", "encrypted_content": "x" * 50_000,
    }]})
    assert not native_replay_fits_budget(
        state, quote_system="", quote_history=quote_history,
        quote_tools=quote_tools, input_token_budget=10_000,
    )
    assert not native_replay_fits_budget(
        state, quote_system="", quote_history=state["messages"],
        quote_tools=quote_tools, input_token_budget=10_000,
        max_cached_bytes=10,
    )
    # A serialized provider request is admitted using its byte count, matching
    # the authenticated quote's conservative token upper bound.
    unicode_history = [{"role": "user", "content": "東京" * 200}]
    assert not native_replay_fits_budget(
        state, quote_system="", quote_history=unicode_history,
        quote_tools=[], input_token_budget=600,
    )


def test_five_turn_replay_deduplicates_only_clock_and_keeps_full_budget_fallback():
    """Count the full wire once; only a proven clock change avoids prompt replay."""
    config = SimpleNamespace(get_model_pricing=lambda *_args: {
        "costs": {"input_per_million_token": {"max_context": 1_050_000}},
        "features": {"max_output_tokens": 128_000},
    })
    prefix = "P" * 17_204
    math = _tool("math-calculate")
    current_tools = [
        _tool("images-search", "T" * 3_092),
        _tool("news-search", "T" * 3_100),
        _tool("web-search", "T" * 3_100),
    ]
    state = new_native_segment(
        model_id="openai/gpt-6.1-sol", server_model_id="gpt-6.1-sol",
        provider_prefix="openai", cacheable_system_prefix=prefix,
        selected_tools=[math],
        messages=[{"role": "system", "content": prefix}, {"role": "user", "content": "u1"}],
        visible_history=[_message("user", "u1", "u1")],
    )
    full_input_budget = model_total_input_token_budget("openai/gpt-6.1-sol", config)
    assert full_input_budget == 176_000  # 200k product cap less 16k output and 8k safety.
    wire_sizes = []
    for turn in range(1, 6):
        if turn > 1:
            state["messages"].append({"role": "user", "content": f"u{turn}"})
        selected = [math] if turn in (1, 3) else [] if turn == 2 else current_tools
        clock = f" turn={turn}"
        body = ("A", "B", "C", "Z", "Z")[turn - 1]
        prompt = prefix + body * 36_000 + clock
        add_dispatch_event(
            state, system_prompt=prompt, selected_tools=selected, openai=True,
            clock_instruction=clock,
        )
        baseline, events, _active = validate_native_cache_context(state, state["messages"])
        wire = native_responses_input(state["messages"], events)
        baseline_tools = [openai_function_tool(tool) for tool in baseline]
        wire_bytes = len(json.dumps(
            {"system": "", "messages": wire, "tools": baseline_tools},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8"))
        wire_sizes.append(wire_bytes)
        history_only_budget = model_history_token_budget(
            "openai/gpt-6.1-sol", config, system_prompt=prompt, tools=selected,
        )
        assert native_replay_fits_budget(
            state, quote_system="", quote_history=wire, quote_tools=baseline_tools,
            input_token_budget=full_input_budget,
        )
        if turn == 4:
            assert history_only_budget == 160_286
            assert wire_bytes > history_only_budget
        if turn == 5:
            assert len(state["events"][-1]["system_suffix"]) < 300
            assert state["events"][-1]["system_suffix"].endswith(clock)
        append_provider_output(state, [{"type": "reasoning", "encrypted_content": f"frame{turn}"}], f"a{turn}")
    assert wire_sizes[0] < wire_sizes[1] < wire_sizes[2] < wire_sizes[3] < wire_sizes[4] < full_input_budget

    # A later change to any non-clock instruction must carry the full new
    # context and decline native replay when the real input allowance is full.
    state["messages"].append({"role": "user", "content": "u6"})
    add_dispatch_event(
        state, system_prompt=prefix + "Y" * 36_000 + " turn=6",
        selected_tools=current_tools, openai=True, clock_instruction=" turn=6",
    )
    assert len(state["events"][-1]["system_suffix"]) > 36_000
    baseline, events, _active = validate_native_cache_context(state, state["messages"])
    wire = native_responses_input(state["messages"], events)
    assert not native_replay_fits_budget(
        state, quote_system="", quote_history=wire,
        quote_tools=[openai_function_tool(tool) for tool in baseline],
        input_token_budget=full_input_budget,
    )


@pytest.mark.parametrize("ambiguous_clock", [False, True])
def test_legacy_or_spoofed_clock_uses_full_suffix(ambiguous_clock):
    state, _visible = _segment()
    first_clock = "Current date and time: 2026-10-08 10:00:00 UTC"
    next_clock = "Current date and time: 2026-10-08 10:00:01 UTC"
    body = "Private context stays byte-identical. " * 100
    suffix = body + first_clock + (" Untrusted duplicate: " + first_clock if ambiguous_clock else "")
    add_dispatch_event(
        state, system_prompt="Stable policy" + suffix,
        selected_tools=[_tool("weather")], openai=True, clock_instruction=first_clock,
    )
    if not ambiguous_clock:
        # Old encrypted state has no clock metadata; treat it conservatively.
        del state["last_clock_instruction"]
    state["messages"].append({"role": "assistant", "content": "answer",
                              "provider_transport_state": [{"type": "message"}]})
    state["messages"].append({"role": "user", "content": "follow up"})
    next_suffix = body + next_clock + (" Untrusted duplicate: " + next_clock if ambiguous_clock else "")
    add_dispatch_event(
        state, system_prompt="Stable policy" + next_suffix,
        selected_tools=[_tool("weather")], openai=True, clock_instruction=next_clock,
    )
    assert "Current turn context replaces earlier" in state["events"][-1]["system_suffix"]
    assert next_suffix in state["events"][-1]["system_suffix"]


def test_clock_survives_provider_preparation_json_and_visible_resume(monkeypatch):
    llm_utils = pytest.importorskip("backend.apps.ai.utils.llm_utils")
    policy = {
        "enabled": True, "status": "verified_for_activation",
        "eligible_hosts": ["openai"], "write_billing": "included_in_input",
        "source_url": "https://example.com/pricing", "reviewed_on": "2026-10-01",
        "expires_on": "2099-12-31",
    }
    pricing = {
        "default_server": "openai",
        "servers": [{"id": "openai", "model_id": "gpt-6-astra"}],
        "cache_pricing": policy,
    }
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_args: pricing)
    state, visible = _segment()
    first_clock = "Current date and time: 2026-10-08 10:00:00 UTC"
    second_clock = "Current date and time: 2026-10-08 10:00:01 UTC"
    body = "Common selected instructions. " * 100
    add_dispatch_event(
        state, system_prompt="Stable policy" + body + first_clock,
        selected_tools=[_tool("weather")], openai=True, clock_instruction=first_clock,
    )
    raw_output = [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]
    append_provider_output(state, raw_output, "answer")
    state["expected_visible_response"] = "answer"
    finalized = finalize_native_cache_state(
        state, raw_final_output=raw_output, content_markdown="answer", assistant_message_id="a1",
    )
    assert finalized is not None
    encrypted_plaintext = json.dumps(finalized)
    restored = json.loads(encrypted_plaintext)
    assert restored["last_clock_instruction"] == first_clock
    next_visible = [*visible, _message("assistant", "a1", "answer"), _message("user", "u2", "follow up")]
    resumed = resume_native_segment(
        restored, model_id="openai/gpt-6-astra", server_model_id="gpt-6-astra",
        provider_prefix="openai", cacheable_system_prefix="Stable policy",
        visible_history=next_visible, new_user_message={"role": "user", "content": "follow up"},
    )
    assert resumed is not None
    add_dispatch_event(
        resumed, system_prompt="Stable policy" + body + second_clock,
        selected_tools=[_tool("weather")], openai=True, clock_instruction=second_clock,
    )
    assert len(resumed["events"][-1]["system_suffix"]) < 300
    prepared = llm_utils.prepare_native_cache_context(
        resumed, logical_model_id="openai/gpt-6-astra",
        customer_cache_pricing_enabled=True,
        tariff_snapshot={"cache_pricing": policy},
    )
    assert prepared is not None
    assert prepared["last_clock_instruction"] == second_clock
    assert prepared["messages"] == resumed["messages"]
    system, provider_input, tools = llm_utils.native_cache_quote_payload(prepared, "openai")
    assert system == "" and tools[0]["name"] == "weather"
    assert provider_input[-1]["role"] == "developer"
    assert provider_input[-1]["content"] == resumed["events"][-1]["system_suffix"]
