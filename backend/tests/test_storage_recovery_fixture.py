"""Provider-free scenario bodies used by isolated sealed-output replay."""

# contract-test-file: infrastructure

import pytest

from backend.apps.ai.testing.capacity_fixtures import generate_fixture, should_fail_child_prompt_save
from backend.shared.testing.mock_context import sign_live_marker


def _response(scenario: str) -> dict:
    result = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [{"role": "user", "content":
            f"STORAGE_CAPACITY_SCENARIO:{scenario}"}], "tools": [],
    })
    assert result is not None
    return result["response"]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_recovery_fixture_has_code_and_versioned_diff_artifacts() -> None:
    embed = _response("recovery_embed")["body"]
    diff = _response("recovery_diff")["body"]
    assert embed.startswith("```python:recovery_demo.py\n")
    assert "stable_value = 7" in embed
    assert diff.startswith("```diff\n--- a/recovery_demo.py\n")
    assert "-    stable_value = 7\n+    stable_value = 8" in diff


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_recovery_fixture_checkpoint_and_failure_paths_remain_synthetic() -> None:
    assert "Synthetic post-checkpoint answer" in _response("recovery_checkpoint")["body"]
    failure = generate_fixture("llm/gemini", {
        "model": "gemini-test",
        "messages": [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:recovery_save_failure"}],
        "tools": [{"function": {"name": "start_sub_chats"}}],
    })
    assert failure is not None
    assert failure["response"]["chunks"][0]["value"]["function_name"] == "start_sub_chats"


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_detached_docs_fixture_generates_a_local_document_without_provider_tools() -> None:
    body = _response("recovery_detached_doc")["body"]
    assert body.startswith("```docx_model\n")
    assert body.endswith("\n```\n")
    import json

    document = json.loads(body.split("\n", 1)[1].rsplit("\n```", 1)[0])
    assert document == {
        "title": "Synthetic detached document",
        "filename": "Recovery_Detached_Document.docx",
        "blocks": [
            {"type": "heading", "text": "Synthetic detached document"},
            {"type": "paragraph", "text": "Durable worker output after disconnect."},
        ],
    }


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_child_prompt_save_failure_requires_current_signed_replay_marker(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "synthetic-unit-secret")
    user_id = "44444444-4444-4444-8444-444444444444"
    prompt = "STORAGE_CAPACITY_SCENARIO:recovery_save_failure"
    marker = sign_live_marker(
        "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>", user_id,
        is_allowlisted_test_account=True,
    )
    assert marker
    assert should_fail_child_prompt_save(f"{prompt} {marker}", user_id)
    assert not should_fail_child_prompt_save(prompt, user_id)
    assert not should_fail_child_prompt_save(f"STORAGE_CAPACITY_SCENARIO:child {marker}", user_id)
    with pytest.raises(RuntimeError, match="Invalid or unauthorized TEST_LIVE marker"):
        should_fail_child_prompt_save(f"{prompt} {marker}", "different-user")
    with pytest.raises(RuntimeError, match="Invalid or unauthorized TEST_LIVE marker"):
        should_fail_child_prompt_save(f"{prompt} <<<TEST_LIVE_MOCK:storage_capacity_v1>>>", user_id)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert not should_fail_child_prompt_save(f"{prompt} {marker}", user_id)
