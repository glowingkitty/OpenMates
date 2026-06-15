"""Regression tests for full-regeneration embed edit fallback.

Some LLMs ignore the diff-editing instruction and emit a full replacement code
block when the user asks to edit an existing artifact. The stream consumer must
reuse the prior embed in that case instead of creating a duplicate artifact.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.stream_consumer import (
    _select_cached_code_full_replacement_target,
    _select_full_replacement_target,
    _select_history_code_full_replacement_target,
)


def _message(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def _request(last_user_message: str, index: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        embed_file_path_index=index,
        current_user_content=None,
        message_history=[
            _message("assistant", "```toon\ntype: code\nembed_ref: main.py-AbC\n```"),
            _message("user", last_user_message),
        ],
    )


def test_selects_single_prior_embed_for_full_replacement_edit() -> None:
    request = _request(
        "Edit the existing code artifact from the previous turn and preserve the same artifact.",
        {"main.py-AbC": "embed-1"},
    )

    assert _select_full_replacement_target(request, None) == ("main.py-AbC", "embed-1")


def test_selects_first_prior_embed_once_for_full_replacement_edit() -> None:
    request = _request(
        "Update the existing code artifact and preserve the same embed.",
        {"main.py-AbC": "embed-1", "helper.py-DeF": "embed-2"},
    )
    reused_refs: set[str] = set()

    selected = _select_full_replacement_target(request, None, reused_refs)
    assert selected == ("main.py-AbC", "embed-1")

    reused_refs.add(selected[0])
    assert _select_full_replacement_target(request, None, reused_refs) is None


def test_selects_matching_filename_even_after_implicit_reuse() -> None:
    request = _request(
        "Update the existing code artifact and preserve the same embed.",
        {"main.py-AbC": "embed-1", "helper.py-DeF": "embed-2"},
    )

    assert _select_full_replacement_target(request, "helper.py-DeF", {"main.py-AbC"}) == (
        "helper.py-DeF",
        "embed-2",
    )


def test_does_not_reuse_embed_for_new_code_request() -> None:
    request = _request(
        "Create a new Python helper for parsing CSV files.",
        {"main.py-AbC": "embed-1"},
    )

    assert _select_full_replacement_target(request, None) is None


def test_selects_prior_assistant_code_embed_when_ref_index_is_missing() -> None:
    request = SimpleNamespace(
        embed_file_path_index={},
        message_history=[
            _message("user", "Create a Python function."),
            _message("assistant", "```json\n{\"type\": \"code\", \"embed_id\": \"embed-1\"}\n```"),
            _message("user", "Edit the existing code artifact and preserve the same embed."),
        ],
    )

    assert _select_history_code_full_replacement_target(request) == ("history:embed-1", "embed-1")


def test_does_not_select_history_code_embed_for_new_code_request() -> None:
    request = SimpleNamespace(
        embed_file_path_index={},
        message_history=[
            _message("assistant", "```json\n{\"type\": \"code\", \"embed_id\": \"embed-1\"}\n```"),
            _message("user", "Create a new Python helper for parsing CSV files."),
        ],
    )

    assert _select_history_code_full_replacement_target(request) is None


class _FakeCacheService:
    def __init__(self, embeds: dict[str, dict[str, object]]) -> None:
        self.embeds = embeds

    async def get_chat_embed_ids(self, _chat_id: str) -> list[str]:
        return list(self.embeds)

    async def get_embed_from_cache(self, embed_id: str) -> dict[str, object] | None:
        return self.embeds.get(embed_id)


@pytest.mark.anyio
async def test_selects_newest_cached_code_embed_when_ref_index_is_missing() -> None:
    request = SimpleNamespace(
        chat_id="chat-1",
        user_id="user-1",
        embed_file_path_index={},
        message_history=[
            _message("assistant", "```json\n{\"type\": \"code\", \"embed_id\": \"embed-1\"}\n```"),
            _message("user", "Edit the existing code artifact and preserve the same embed."),
        ],
    )
    cache_service = _FakeCacheService({
        "embed-old": {"embed_id": "embed-old", "type": "code", "status": "finished", "updated_at": 10},
        "embed-new": {"embed_id": "embed-new", "type": "code", "status": "finished", "updated_at": 20},
        "embed-mail": {"embed_id": "embed-mail", "type": "mail", "status": "finished", "updated_at": 30},
    })

    assert await _select_cached_code_full_replacement_target(request, cache_service) == (
        "cached:embed-new",
        "embed-new",
    )


@pytest.mark.anyio
async def test_uses_current_user_content_when_history_lacks_current_turn() -> None:
    request = SimpleNamespace(
        chat_id="chat-1",
        user_id="user-1",
        embed_file_path_index={},
        current_user_content="Edit the existing code artifact and preserve the same embed.",
        message_history=[
            _message("user", "Create a code embed with a Python function."),
            _message("assistant", "```json\n{\"type\": \"code\", \"embed_id\": \"embed-old\"}\n```"),
        ],
    )
    cache_service = _FakeCacheService({
        "embed-old": {"embed_id": "embed-old", "type": "code", "status": "finished", "updated_at": 10},
    })

    assert await _select_cached_code_full_replacement_target(request, cache_service) == (
        "cached:embed-old",
        "embed-old",
    )
