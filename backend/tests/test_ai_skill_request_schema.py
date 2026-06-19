# backend/tests/test_ai_skill_request_schema.py
#
# Regression tests for the core API AskSkillRequest schema used by WebSocket
# handlers before dispatching to the AI app. If this schema omits fields that
# the AI app schema expects, Pydantic silently drops them and changes runtime
# behavior such as incognito persistence and benchmark usage tagging.

from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest


def test_core_ask_skill_request_preserves_runtime_flags() -> None:
    request = AskSkillRequest(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        message_history=[],
        is_incognito=True,
        benchmark_metadata={
            "source": "benchmark",
            "benchmark_run_id": "run-1",
        },
        connected_account_directory=[{"provider": "calendar"}],
        connected_account_token_refs=[{"turn_token_ref": "ref-1"}],
    )

    dumped = request.model_dump()
    assert dumped["is_incognito"] is True
    assert dumped["benchmark_metadata"]["source"] == "benchmark"
    assert dumped["connected_account_directory"] == [{"provider": "calendar"}]
    assert dumped["connected_account_token_refs"] == [{"turn_token_ref": "ref-1"}]
