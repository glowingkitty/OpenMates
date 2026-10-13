"""Focused checks for clean answer recovery when request content is optional."""

from __future__ import annotations

import copy

import pytest

from backend.apps.ai.utils.answer_recovery import build_answer_recovery_history


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_missing_current_content_uses_latest_user_once_with_tool_evidence() -> None:
    history = [
        {"role": "user", "content": "Older request"},
        {"role": "user", "content": "Latest request"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "search-1", "function": {"name": "web-search"},
        }]},
        {"role": "tool", "tool_call_id": "search-1", "content": "A result"},
    ]
    original = copy.deepcopy(history)

    result = build_answer_recovery_history(history, None, max_tokens=1000)

    assert history == original
    assert result[-1] == {"role": "user", "content": "Latest request"}
    assert sum(item.get("content") == "Latest request" for item in result) == 1
    assert result[0] == {"role": "user", "content": "Older request"}
    assert "A result" in result[1]["content"]
    assert "UNTRUSTED TOOL EVIDENCE" in result[1]["content"]


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_missing_current_content_preserves_latest_multimodal_request() -> None:
    blocks = [
        {"type": "text", "text": "Read this chart", "cache_control": "private"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    history = [{"role": "user", "content": blocks}]
    original = copy.deepcopy(history)

    result = build_answer_recovery_history(history, None, max_tokens=2000)

    assert history == original
    assert result == [{"role": "user", "content": [
        {"type": "text", "text": "Read this chart"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}]


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_missing_current_content_bounds_multimodal_request() -> None:
    images = [{
        "type": "image_url", "image_url": {"url": f"https://image.test/{index}.png"},
    } for index in range(2)]
    history = [{"role": "user", "content": images}]

    with pytest.raises(ValueError, match="exceed"):
        build_answer_recovery_history(history, None, max_tokens=1600)

    result = build_answer_recovery_history(history, None, max_tokens=3300)
    assert result == history


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("history", [
    [],
    [{"role": "assistant", "content": "An answer"}],
    [{"role": "user", "content": None}],
    [{"role": "user", "content": [{"type": "tool_call", "id": "x"}]}],
])
def test_missing_current_content_requires_valid_user_message(history: list[dict]) -> None:
    with pytest.raises(ValueError, match="No valid current user message"):
        build_answer_recovery_history(history, None, max_tokens=1000)


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("invalid", [False, 0, 1.5, {}, ["request"]])
def test_invalid_explicit_current_content_is_rejected(invalid: object) -> None:
    with pytest.raises(ValueError, match="current_user_content"):
        build_answer_recovery_history(
            [{"role": "user", "content": "Authorized request"}],
            invalid,  # type: ignore[arg-type]
            max_tokens=1000,
        )


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_explicit_string_and_published_prefix_stay_bounded() -> None:
    history = [{"role": "user", "content": "A request"}]
    result = build_answer_recovery_history(
        history, "A request", max_tokens=1000, published_prefix="Published."
    )
    assert [item["role"] for item in result] == ["user", "assistant", "user"]
    assert result[0]["content"] == "A request"
    assert "Published." in result[1]["content"]
    with pytest.raises(ValueError, match="exceed"):
        build_answer_recovery_history(
            history, None, max_tokens=1, published_prefix="Published."
        )
