"""Final composer metadata is independent from postprocessed suggestion chips."""

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing.suggested_followup_stream import may_publish_suggested_followup


def request(**changes):
    values = dict(
        is_sub_chat=False,
        is_sub_chat_continuation=False,
        is_incognito=False,
        is_async_skill_continuation=False,
        awaiting_async_skill_continuation=False,
        is_external=False,
        user_preferences={},
    )
    values.update(changes)
    return SimpleNamespace(**values)


def allowed(data=None, **changes):
    return may_publish_suggested_followup(
        data or request(),
        suggestion=changes.get("suggestion", "Could you give me an example?"),
        response=changes.get("response", "An answer"),
        is_error=changes.get("is_error", False),
        is_server_error=changes.get("is_server_error", False),
        stream_exception=changes.get("stream_exception"),
        terminal_failure_reason=changes.get("terminal_failure_reason"),
        was_revoked=changes.get("was_revoked", False),
        was_soft_limited=changes.get("was_soft_limited", False),
    )


# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_successful_final_response_allows_suggestion():
    assert allowed()


@pytest.mark.parametrize("change", [
    {"suggestion": None},
    {"suggestion": "x" * 401},
    {"response": "  "},
    {"is_error": True},
    {"is_server_error": True},
    {"stream_exception": RuntimeError("failure")},
    {"terminal_failure_reason": "stream_error"},
    {"was_revoked": True},
    {"was_soft_limited": True},
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_failed_or_partial_response_does_not_publish(change):
    assert not allowed(**change)


@pytest.mark.parametrize("change", [
    {"is_sub_chat": True},
    {"is_sub_chat_continuation": True},
    {"is_incognito": True},
    {"is_async_skill_continuation": True},
    {"awaiting_async_skill_continuation": True},
    {"is_external": True},
    {"user_preferences": {"follow_up_suggestions_enabled": False}},
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_private_or_intermediate_turns_do_not_publish(change):
    assert not allowed(request(**change))
