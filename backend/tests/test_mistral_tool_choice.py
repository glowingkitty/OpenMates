# contract-test-file: infrastructure
"""Focused contracts for Mistral tool-choice translation."""

from backend.apps.ai.llm_providers.mistral_client import _resolve_mistral_tool_choice


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_single_required_tool_is_pinned_by_name() -> None:
    assert _resolve_mistral_tool_choice("required", [_tool("analyze_request_properties")]) == {
        "type": "function",
        "function": {"name": "analyze_request_properties"},
    }


def test_multiple_required_tools_keep_model_choice() -> None:
    assert _resolve_mistral_tool_choice("required", [_tool("weather"), _tool("search")]) == "any"


def test_auto_and_named_choices_are_preserved() -> None:
    tools = [_tool("weather")]
    named = {"type": "function", "function": {"name": "weather"}}
    assert _resolve_mistral_tool_choice(None, tools) == "auto"
    assert _resolve_mistral_tool_choice("auto", tools) == "auto"
    assert _resolve_mistral_tool_choice(named, tools) == named
