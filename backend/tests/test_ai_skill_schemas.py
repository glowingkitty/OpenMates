"""Core request compatibility for clients that have not adopted chapter requests."""

from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.first-segment-progressive
def test_native_auto_speak_remains_eager_without_web_chapter_capability() -> None:
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="owner-1",
        user_id_hash="hash-1", message_history=[], auto_speak_response=True,
    )

    forwarded = request.model_dump()
    assert forwarded["auto_speak_response"] is True
    assert forwarded["assistant_speech_lazy_dispatch"] is False
