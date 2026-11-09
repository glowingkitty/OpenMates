# contract-test-file: supporting
# Chat Recommendations in post-processing: tool schema, skip rules, aliases, sanitization,
# workflow relevance filter, create->update conversion, caps and stable ids.
# Plan: docs/plans/chat-recommendations/plan.yml
# Run: python3 -m pytest backend/tests/test_postprocessing_recommendations.py -v
import asyncio
import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.ai.processing import postprocessing_recommendations as mod
from backend.apps.ai.processing import postprocessing_workflow_context as wf_ctx
from backend.shared.python_utils.memory_loader import MemoryCatalogEntry

INSTRUCTIONS = Path(__file__).resolve().parents[1] / "apps/ai/base_instructions.yml"


def _entry(entry_id, title, source="personal", when="Anytime"):
    return MemoryCatalogEntry(id=entry_id, title=title, when_to_use=when, load_mode="ask_first", source=source)


MEMORIES = mod.build_memory_aliases([_entry("mem-uuid-1", "Coffee order"), _entry("mem-uuid-2", "Project note", source="project")])
WORKFLOWS = [{"workflow_id": "wf-uuid-1", "title": "Weekly CFP alert", "description": "Alert for new conference CFPs", "updated_at": 5}]


def _build(args, workflows=WORKFLOWS, memories=MEMORIES, task_id="task-1"):
    return mod.build_recommendations(
        args, task_id=task_id, memory_aliases=memories,
        workflow_aliases=mod.build_workflow_aliases(workflows), all_workflows=workflows,
    )


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_tool_schema_has_recommendations_and_no_quick_tip():
    tool = yaml.safe_load(INSTRUCTIONS.read_text())["postprocess_response_tool"]["function"]["parameters"]
    assert "quick_tip_slug" not in tool["properties"] and "quick_tip_slug" not in tool["required"]
    for field in mod.RECOMMENDATION_FIELDS:
        prop = tool["properties"][field]
        assert field in tool["required"]
        assert prop["minItems"] == 1 and prop["maxItems"] == 3
        item = prop["items"]
        assert item["properties"]["action"]["enum"] == ["create", "update"]
        assert item["properties"]["title"]["maxLength"] == 80 and item["properties"]["summary"]["maxLength"] == 200
        assert set(item["required"]) == {"action", "title", "summary"} and "ref" in item["properties"]


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_strip_fields_removes_both_from_tool():
    tool = copy.deepcopy(yaml.safe_load(INSTRUCTIONS.read_text())["postprocess_response_tool"]["function"]["parameters"])
    required = mod.strip_recommendation_fields(tool["properties"], tool["required"])
    assert not set(mod.RECOMMENDATION_FIELDS) & (set(tool["properties"]) | set(required))


@pytest.mark.parametrize("kwargs,reason", [
    ({"recommendations_enabled": False}, "disabled"),
    ({"is_sub_chat": True}, "sub_chat"),
    ({"is_incognito": True}, "incognito"),
    ({"user_message": "hi", "assistant_response": "Hello! How can I help?"}, "small_talk"),
    ({}, None),
])
# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_skip_rules(kwargs, reason):
    base = {"recommendations_enabled": True, "is_sub_chat": False, "is_incognito": False,
            "user_message": "Find open source conferences in Europe for next year",
            "assistant_response": "Here are several conferences. " * 30}
    assert mod.recommendations_skip_reason(**{**base, **kwargs}) == reason


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_aliases_use_personal_memories_only_and_cap_24():
    assert list(MEMORIES) == ["m1"] and MEMORIES["m1"].id == "mem-uuid-1"
    many = mod.build_memory_aliases([_entry(f"id{i}", f"T{i}") for i in range(40)])
    assert len(many) == 24 and "m24" in many and "m25" not in many


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_context_exposes_aliases_not_ids():
    text = mod.build_recommendation_context(MEMORIES, mod.build_workflow_aliases(WORKFLOWS))
    assert "m1: Coffee order" in text and "w1: Weekly CFP alert" in text
    assert "mem-uuid-1" not in text and "wf-uuid-1" not in text


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_update_maps_alias_and_uses_users_own_title():
    out = _build({"memory_recommendations": [{"action": "update", "ref": "m1", "title": "Model invented", "summary": "More detail"}]})
    assert out[0]["target_id"] == "mem-uuid-1" and out[0]["title"] == "Coffee order" and out[0]["action"] == "update"
    assert out[0]["kind"] == "memory"


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_unknown_alias_on_update_is_dropped():
    out = _build({"memory_recommendations": [{"action": "update", "ref": "m9", "title": "x", "summary": "y"},
                                             {"action": "update", "title": "x", "summary": "y"}],
                  "workflow_recommendations": [{"action": "update", "ref": "m1", "title": "x", "summary": "y"}]})
    assert out == []


@pytest.mark.parametrize("text", ["api_key: abcdef123456", "token = abcdefghijkl", "-----BEGIN PRIVATE KEY-----"])
# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_secret_items_are_dropped_without_fallback(text):
    out = _build({"memory_recommendations": [{"action": "create", "title": "Fine", "summary": text}],
                  "workflow_recommendations": [{"action": "create", "title": text, "summary": "Fine"}]})
    assert out == []


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_workflow_create_converted_to_update_against_all_workflows():
    # The prompt subset is empty; the match comes from the full list.
    out = mod.build_recommendations(
        {"workflow_recommendations": [{"action": "create", "title": "weekly cfp alert", "summary": "s"},
                                      {"action": "create", "title": "Weekly alert for CFP", "summary": "s"},
                                      {"action": "create", "title": "Brand new idea", "summary": "s"}]},
        task_id="t", memory_aliases={}, workflow_aliases={}, all_workflows=WORKFLOWS,
    )
    assert [(i["action"], i["target_id"]) for i in out] == [("update", "wf-uuid-1"), ("create", None)]
    assert out[0]["title"] == "Weekly CFP alert"


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_titles_match_rules():
    assert mod.titles_match("Open-source conferences", "open source conferences")
    assert mod.titles_match("alpha beta gamma delta epsilon", "alpha beta gamma zeta eta") is False
    assert mod.titles_match("alpha beta gamma delta", "alpha beta gamma")


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_normalisation_is_unicode_aware():
    # Non-Latin titles must keep their letters: "" would make all of them match each other.
    assert mod.normalise_text("Kaffee-Bestellung für Büro") == "kaffee bestellung für büro"
    assert mod.normalise_text("咖啡订单") == "咖啡订单"
    assert mod.titles_match("咖啡订单", "咖啡订单！") and not mod.titles_match("咖啡订单", "会议提醒")
    assert not mod.titles_match("???", "!!!")  # empty normalised titles never match


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.no-duplicates
def test_caps_three_per_kind_and_dedup():
    items = [{"action": "create", "title": f"Topic number {chr(97 + i)}", "summary": "s"} for i in range(6)]
    out = _build({"memory_recommendations": items + [items[0]], "workflow_recommendations": items}, workflows=[])
    assert len([i for i in out if i["kind"] == "memory"]) == 3 and len([i for i in out if i["kind"] == "workflow"]) == 3


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_stable_ids_are_deterministic_uuids():
    args = {"memory_recommendations": [{"action": "create", "title": "A first", "summary": "s"},
                                       {"action": "create", "title": "B second", "summary": "s"}]}
    first, second = _build(args), _build(args)
    assert [i["id"] for i in first] == [i["id"] for i in second]
    assert len({i["id"] for i in first}) == 2 and uuid.UUID(first[0]["id"])
    assert first[0]["id"] == mod.recommendation_id("task-1", "memory", 0)
    assert mod.recommendation_id("task-2", "memory", 0) != first[0]["id"]
    assert set(first[0]) == {"id", "kind", "action", "target_id", "title", "summary"}


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_title_and_summary_limits_enforced():
    out = _build({"memory_recommendations": [{"action": "create", "title": "T" * 200, "summary": "S" * 500}]})
    assert len(out[0]["title"]) == 80 and len(out[0]["summary"]) == 200


def _workflows(n):
    return [{"workflow_id": f"w{i}", "title": f"Workflow {i} topic{i}", "description": f"desc {i}", "updated_at": i} for i in range(n)]


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_relevance_filter_all_when_at_most_15():
    assert len(mod.select_prompt_workflows(_workflows(15), "anything")) == 15


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_relevance_filter_top8_plus_two_recent_when_more_than_15():
    workflows = _workflows(30)
    workflows[3]["description"] = "conference cfp alert europe"
    selected = mod.select_prompt_workflows(workflows, "open source conference cfp europe")
    ids = {w["workflow_id"] for w in selected}
    assert "w3" in ids and {"w29", "w28"} <= ids and 8 <= len(selected) <= 10


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_workflow_description_truncated_in_prompt():
    aliases = mod.build_workflow_aliases([{"workflow_id": "x", "title": "T", "description": "D" * 500}])
    line = mod.build_recommendation_context({}, aliases).split("w1: ")[1].splitlines()[0]
    assert line.count("D") == 160


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_small_talk_heuristic_short_greeting_only():
    assert mod.is_small_talk("Hello there", "Hi!") and mod.is_small_talk("", "x")
    assert mod.is_small_talk("Find FOSDEM talks", "Short")  # <= 3 words and short answer
    # long answer to a short question is substantive
    assert not mod.is_small_talk("Kyoto trip plan", "x" * 500)
    # Scripts without spaces: one token, but a long message is not small talk.
    assert not mod.is_small_talk("请帮我找到明年在欧洲举办的开源软件会议和征稿截止日期", "短")
    assert mod.is_small_talk("你好", "你好！")


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_workflow_fetch_failure_logs_type_only_and_returns_empty(monkeypatch, caplog):
    from backend.apps.ai.processing import context_preselection as cp

    async def boom(_request, _cache):
        raise RuntimeError("SECRET-WORKFLOW-TITLE")

    monkeypatch.setattr(cp, "_authorize_workflow_team", boom)
    request = SimpleNamespace(user_id="u", team_id=None)
    with caplog.at_level("WARNING"):
        assert asyncio.run(wf_ctx.fetch_user_workflow_metadata(request, object())) == []
    assert "RuntimeError" in caplog.text and "SECRET-WORKFLOW-TITLE" not in caplog.text


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_workflow_fetch_skips_incognito_and_sub_chat():
    assert asyncio.run(wf_ctx.fetch_user_workflow_metadata(SimpleNamespace(user_id="u", is_incognito=True), object())) == []
    assert asyncio.run(wf_ctx.fetch_user_workflow_metadata(SimpleNamespace(user_id="u", is_sub_chat=True), object())) == []


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_settings_request_accepts_recommendations_enabled_and_rejects_nothing_else():
    from backend.core.api.app.schemas.settings import AiModelDefaultsRequest
    assert AiModelDefaultsRequest().recommendations_enabled is None
    assert AiModelDefaultsRequest(recommendations_enabled=False).recommendations_enabled is False
    assert "quick_tips_enabled" not in AiModelDefaultsRequest.model_fields


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_ask_preference_defaults_true_and_directus_schema_columns():
    root = Path(__file__).resolve().parents[1] / "core/directus/schemas"
    users = yaml.safe_load((root / "users.yml").read_text())["directus_users"]["fields"]
    assert users["recommendations_enabled"]["default"] is True and "quick_tips_enabled" not in users
    chats = yaml.safe_load((root / "chats.yml").read_text())["chats"]["fields"]
    assert chats["encrypted_recommendations"]["type"] == "text" and "encrypted_quick_tip_slugs" not in chats
