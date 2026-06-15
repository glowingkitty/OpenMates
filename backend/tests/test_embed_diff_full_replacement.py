"""Regression tests for full-regeneration embed edit fallback.

Some LLMs ignore the diff-editing instruction and emit a full replacement code
block when the user asks to edit an existing artifact. The stream consumer must
reuse the prior embed in that case instead of creating a duplicate artifact.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.apps.ai.tasks.stream_consumer import _select_full_replacement_target


def _message(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def _request(last_user_message: str, index: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        embed_file_path_index=index,
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


def test_does_not_reuse_embed_for_new_code_request() -> None:
    request = _request(
        "Create a new Python helper for parsing CSV files.",
        {"main.py-AbC": "embed-1"},
    )

    assert _select_full_replacement_target(request, None) is None
