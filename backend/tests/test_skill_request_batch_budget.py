# contract-test-file: infrastructure
"""Oversized multi-request skill calls run up to the research budget (issue 4VXWM).

Before the fix, any non-news call whose request batch exceeded the remaining
budget was skipped wholesale: no embed, no usage, and the model told the user
the tool was unavailable "because of a limit".
"""
import copy
import json

import pytest

from backend.tests.test_delegated_primary_read import batch_schema_fixture, run
from backend.tests.test_main_processor_invalid_tool_calls import main_processor


@pytest.mark.asyncio
@pytest.mark.parametrize("request_count", [6, 10])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_oversized_batch_executes_budgeted_requests_and_reports_omitted(monkeypatch, request_count):
    batch_schema_fixture(monkeypatch)
    executed = []

    async def execute(**kwargs):
        requests = copy.deepcopy(kwargs["arguments"]["requests"])
        executed.append((kwargs["skill_id"], requests))
        return [{"results": [{"id": r["id"], "results": [{"url": f"https://example.org/{r['id']}",
                            "title": "Result"}]} for r in requests]}]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", execute)
    searches = [{"id": i, "query": f"vegetarian idea {i}"} for i in range(request_count)]
    _, calls = await run(monkeypatch, [
        [{"fake_google_tool_call": "web-search", "arguments": {"requests": searches}, "tool_call_id": "batch"}],
        ["Here are the recipes I found."],
    ])

    limit = main_processor.HARD_LIMIT_SKILL_CALLS
    assert executed == [("search", searches[:limit])]
    tool_results = [m for m in calls[-1]["message_history"] if m.get("tool_call_id") == "batch"]
    assert len(tool_results) == 1
    content = tool_results[0]["content"]
    assert '"status": "skipped"' not in content
    budget = json.loads(content[content.index('{"research_budget"'):])["research_budget"]
    assert budget["omitted_queries"] == [s["query"] for s in searches[limit:]]
    assert [r["query"] for r in budget["omitted_requests"]] == budget["omitted_queries"]
