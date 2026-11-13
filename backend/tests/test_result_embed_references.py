# backend/tests/test_result_embed_references.py
"""Continuation replies show the test result embeds of the completed runs."""
import sys
from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks import same_turn_skill_barrier
from backend.apps.ai.tasks.async_skill_continuation import completed_result_embed_ids
from backend.apps.ai.tasks.result_embed_references import append_result_embed_references


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-result-in-reply
def test_unlinked_test_result_is_appended_to_the_reply() -> None:
    text = append_result_embed_references("The test passed, I committed the app.", "test_result", ["result-1"])
    assert text == (
        "The test passed, I committed the app.\n\n"
        '```json\n{"type": "test_result", "embed_id": "result-1"}\n```'
    )


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-result-in-reply
def test_already_linked_result_is_not_repeated() -> None:
    text = "See [the run](embed:result-1)."
    assert append_result_embed_references(text, "test_result", ["result-1", "result-1"]) == text


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-result-in-reply
def test_continuation_carries_each_test_result_once_in_run_order() -> None:
    results = [{"test_result_embed_id": "b"}, {"exit_code": 0}, {"test_result_embed_id": "a"},
               {"test_result_embed_id": "b"}, "not-a-row"]
    assert completed_result_embed_ids(results) == ["b", "a"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.agentic.test-result-in-reply
async def test_same_turn_resume_carries_the_test_results_of_the_batch(monkeypatch):
    results = {"ref-a": [{"test_result_embed_id": "run-1"}], "ref-b": [{"test_result_embed_id": "run-2"}]}

    async def restore(payload):
        return {"async_tool_completion": {"status": "failed", "results": results[payload["agentic_context_ref"]]}}

    monkeypatch.setitem(sys.modules, "backend.shared.python_utils.recent_work_summary_client",
                        SimpleNamespace(restore_private_context_payload=restore))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.text_sanitization",
                        SimpleNamespace(sanitize_text_payload_for_ascii_smuggling=lambda value: (value, {})))
    request = SimpleNamespace(
        user_id="user", chat_id="chat", message_id="turn", completed_result_embed_ids=[],
        same_turn_slots=[{"task_id": "a", "status": "failed", "payload_ref": "ref-a"},
                         {"task_id": "b", "status": "failed", "payload_ref": "ref-b"}],
    )
    checkpoint = {"jobs": [{"task_id": "a", "tool_call_id": "call-1", "app_id": "code", "skill_id": "run"},
                           {"task_id": "b", "tool_call_id": "call-2", "app_id": "code", "skill_id": "run"}],
                  "current_message_history": [
                      {"role": "tool", "tool_call_id": "call-1", "content": "processing"},
                      {"role": "tool", "tool_call_id": "call-2", "content": "processing"},
                  ]}
    await same_turn_skill_barrier.restore_ordered_tool_results(request, checkpoint)
    assert request.completed_result_embed_ids == ["run-1", "run-2"]
