# backend/tests/test_result_embed_references.py
"""Continuation replies show the test result embeds of the completed runs."""
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
