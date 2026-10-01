"""Focused accounting check for the opt-in compact authoring benchmark."""
# contract-test-file: infrastructure

from types import SimpleNamespace

import pytest

from backend.scripts.benchmark_workflow_authoring import CASES
from backend.scripts.benchmark_workflow_compact_authoring import run_case, select_cases


def test_case_selection_is_bounded_and_rejects_duplicates():
    assert len(select_cases(["all"])) == 7
    assert [case.id for case in select_cases(["rain_if"])] == ["rain_if"]
    with pytest.raises(ValueError, match="duplicate"):
        select_cases(["rain_if", "rain_if"])


@pytest.mark.asyncio
async def test_complete_component_and_full_request_accounting():
    selection = SimpleNamespace(
        metrics={"input_tokens": 20, "estimated_cost_usd": 0.000001},
        scores={"weather.forecast": 0.9}, capabilities=[SimpleNamespace(id="weather.forecast")],
        operation="create", check_mode="exact", chat_delivery=True,
    )

    class Preselector:
        async def select(self, text, *, timezone):
            assert text == CASES[0].text
            assert timezone == "Europe/Berlin"
            return selection

    class Author:
        model = "gemini-3.8-flash"

        async def generate(self, *, text, selection, timezone, on_component):
            await on_component({"index": 0, "step": {"id": "step1", "kind": "app"}})
            return {"operation": "create", "steps": []}, {
                "input_tokens": 100, "output_tokens": 50, "thinking_tokens": 15,
                "first_component_ms": 1.0, "component_count": 1,
                "estimated_cost_usd": 0.0002,
            }

    def compile_plan(raw, selected, timezone):
        assert raw["operation"] == "create"
        assert selected is selection
        assert timezone == "Europe/Berlin"
        return {"action": "create", "graph": {"version": 2, "trigger_node_id": "trigger",
                "nodes": [
                    {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {
                        "type": "daily", "time": "08:00", "timezone": "Europe/Berlin"}}},
                    {"id": "send", "type": "send_chat_message", "config": {"title": "Test", "message": "Hello"}},
                ], "edges": [{"from": "trigger", "to": "send"}]}}

    row = await run_case(CASES[0], preselector=Preselector(), author=Author(),
                         compile_plan=compile_plan)
    assert row["graph_valid"] is True
    assert row["intent_match"] is False  # Independent oracle still checks intent.
    assert row["observed_components"] == 1
    assert row["first_complete_component_ms"] is not None
    assert row["generation_metrics"]["thinking_tokens"] == 15
    assert row["estimated_cost_usd"] == 0.000201
    assert row["total_ms"] >= row["preselection_ms"]
