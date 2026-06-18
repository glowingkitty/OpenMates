"""Regression tests for full-regeneration embed edit fallback.

Some LLMs ignore the diff-editing instruction and emit a full replacement code
block when the user asks to edit an existing artifact. The stream consumer must
reuse the prior embed in that case instead of creating a duplicate artifact.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.stream_consumer import (
    _apply_requested_symbol_rename,
    _apply_diff_block_to_existing_embed,
    _is_diff_edit_fence,
    _is_edit_existing_artifact_request,
    _should_skip_code_block_for_embed,
    _select_cached_code_full_replacement_target,
    _select_full_replacement_target,
    _select_history_code_full_replacement_target,
    _should_keep_regenerated_code_inline_for_edit_request,
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


def test_detects_e2e_rename_prompt_as_existing_artifact_edit() -> None:
    request = SimpleNamespace(
        current_user_content=None,
        message_history=[
            _message(
                "user",
                "Rename the function from calculate_average to compute_mean and add a type hint for the return value (-> float).",
            ),
        ],
    )

    assert _is_edit_existing_artifact_request(request) is True


def test_detects_enum_style_user_role_as_existing_artifact_edit() -> None:
    request = SimpleNamespace(
        current_user_content=None,
        message_history=[
            SimpleNamespace(
                role=SimpleNamespace(value="user"),
                content="Rename the function from calculate_average to compute_mean.",
            ),
        ],
    )

    assert _is_edit_existing_artifact_request(request) is True


def test_skips_example_usage_snippet_code_embed() -> None:
    assert _should_skip_code_block_for_embed(
        "# Example usage:\nprint(calculate_average([10, 20, 30, 40]))  # Output: 25.0"
    ) is True


def test_keeps_function_code_as_embed() -> None:
    assert _should_skip_code_block_for_embed(
        "def calculate_average(numbers):\n"
        "    if not numbers:\n"
        "        return 0\n"
        "    return sum(numbers) / len(numbers)"
    ) is False


def test_applies_requested_symbol_rename_to_regenerated_code() -> None:
    request = SimpleNamespace(
        current_user_content="Rename the function from calculate_average to compute_mean and add a type hint.",
        message_history=[],
    )

    updated = _apply_requested_symbol_rename(
        request,
        "def calculate_average(numbers: list[float]) -> float:\n"
        "    return sum(numbers) / len(numbers)\n"
        "# print(calculate_average([1, 2, 3]))",
    )

    assert "def compute_mean" in updated
    assert "calculate_average" not in updated


def test_does_not_rename_when_model_already_used_new_symbol() -> None:
    request = SimpleNamespace(
        current_user_content="Rename the function from calculate_average to compute_mean.",
        message_history=[],
    )
    code = "def compute_mean(numbers):\n    return sum(numbers) / len(numbers)"

    assert _apply_requested_symbol_rename(request, code) == code


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


def test_keeps_regenerated_code_inline_when_edit_target_is_missing() -> None:
    request = _request(
        "Edit the existing code artifact from the previous turn and preserve the same artifact.",
        {},
    )

    assert _should_keep_regenerated_code_inline_for_edit_request(request) is True


def test_allows_new_code_embed_for_new_code_request() -> None:
    request = _request(
        "Create a new Python helper for parsing CSV files.",
        {},
    )

    assert _should_keep_regenerated_code_inline_for_edit_request(request) is False


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

    async def set_embed_in_cache(
        self,
        embed_id: str,
        embed_data: dict[str, object],
        chat_id: str,
    ) -> bool:
        assert chat_id
        self.embeds[embed_id] = embed_data
        return True


class _FakeDirectusEmbedService:
    async def get_embed_by_id(self, _embed_id: str) -> None:
        return None


class _FakeDirectusService:
    def __init__(self) -> None:
        self.embed = _FakeDirectusEmbedService()


class _FakeEncryptionService:
    def __init__(self, plaintext: str) -> None:
        self.plaintext = plaintext

    async def decrypt_with_user_key(self, _encrypted_content: str, _vault_key_id: str) -> str:
        return self.plaintext


class _FakeEmbedService:
    def __init__(self) -> None:
        self.updated_code: str | None = None
        self.version_number: int | None = None

    async def update_code_embed_content(self, **kwargs: object) -> None:
        self.updated_code = str(kwargs["code_content"])
        self.version_number = int(kwargs["version_number"])


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


def test_identifies_bare_diff_fence_when_single_edit_target_exists() -> None:
    assert _is_diff_edit_fence("diff", None, {"main.py-AbC": "embed-1"}) is True
    assert _is_diff_edit_fence("diff", None, {}) is False


@pytest.mark.anyio
async def test_applies_bare_diff_fence_to_existing_code_embed() -> None:
    from toon_format import encode

    original_code = (
        "def calculate_average(numbers):\n"
        "    if not numbers:\n"
        "        return 0\n"
        "    return sum(numbers) / len(numbers)"
    )
    diff_content = (
        "@@ -1,4 +1,4 @@\n"
        "-def calculate_average(numbers):\n"
        "+def compute_mean(numbers) -> float:\n"
        "     if not numbers:\n"
        "         return 0\n"
        "     return sum(numbers) / len(numbers)"
    )
    request = SimpleNamespace(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        embed_file_path_index={"main.py-AbC": "embed-1"},
    )
    cache_service = _FakeCacheService({
        "embed-1": {
            "embed_id": "embed-1",
            "type": "code",
            "status": "finished",
            "version_number": 1,
            "encrypted_content": "encrypted",
        },
    })
    embed_service = _FakeEmbedService()

    response_chunk = await _apply_diff_block_to_existing_embed(
        diff_content=diff_content,
        diff_embed_ref=None,
        request_data=request,
        cache_service=cache_service,
        directus_service=_FakeDirectusService(),
        encryption_service=_FakeEncryptionService(encode({
            "type": "code",
            "code": original_code,
            "language": "python",
            "filename": "main.py",
        })),
        embed_service=embed_service,
        user_vault_key_id="vault-1",
        log_prefix="[test]",
    )

    assert '"embed_id": "embed-1"' in response_chunk
    assert embed_service.updated_code is not None
    assert "def compute_mean(numbers) -> float" in embed_service.updated_code
    assert "def calculate_average" not in embed_service.updated_code
    assert "@@" not in embed_service.updated_code
    assert embed_service.version_number == 2
    assert isinstance(cache_service.embeds["embed-1"], dict)
    assert cache_service.embeds["embed-1"]["version_number"] == 2
