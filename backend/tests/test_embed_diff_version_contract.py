"""Backend contract tests for encrypted embed diff version history.

These tests cover the product contract from
docs/specs/embed-diff-editing-parity/spec.yml: version history rows are
encrypted client-side with the embed key, so the server must not persist,
reconstruct, or restore plaintext diff history.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.core.api.app.services.embed_diff_service import EmbedDiffService


STREAM_CONSUMER_PATH = Path(__file__).resolve().parents[1] / "apps/ai/tasks/stream_consumer.py"
DIFF_INSTRUCTION_PATH = Path(__file__).resolve().parents[1] / "apps/ai/instructions/base_diff_editing_instruction.md"


@pytest.mark.anyio
async def test_server_side_diff_persistence_reconstruction_and_restore_are_disabled() -> None:
    service = EmbedDiffService(
        cache_service=None,
        directus_service=None,
        encryption_service=None,
    )

    with pytest.raises(RuntimeError, match="stored by the client"):
        await service.store_initial_snapshot("embed-1", "content", "vault-key", "user-hash")

    with pytest.raises(RuntimeError, match="stored by the client"):
        await service.store_diff_version("embed-1", 2, "@@ diff", "vault-key", "user-hash")

    with pytest.raises(RuntimeError, match="reconstructed by the client"):
        await service.reconstruct_version("embed-1", 2, "user-hash", "vault-key")

    with pytest.raises(RuntimeError, match="performed by the client"):
        await service.restore_version(
            embed_id="embed-1",
            target_version=1,
            new_version=4,
            hashed_user_id="user-hash",
            user_vault_key_id="vault-key",
        )


def test_final_stream_marker_is_published_after_ai_cache_context_save() -> None:
    source = STREAM_CONSUMER_PATH.read_text(encoding="utf-8")

    cache_save = source.index("# Save assistant response to cache for follow-up message context")
    final_publish = source.index("# Publish final marker only after the AI cache write has been attempted")

    assert cache_save < final_publish


def test_diff_instruction_forbids_new_embed_json_for_small_edits() -> None:
    instruction = DIFF_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "Do **not** create a new `json` / `json_embed` embed reference" in instruction
    assert "never respond with a new embed JSON block" in instruction
    assert "diff:<embed_ref>" in instruction


def test_stream_consumer_uses_cache_embed_lookup_signature() -> None:
    source = STREAM_CONSUMER_PATH.read_text(encoding="utf-8")

    assert not re.search(r"get_embed_from_cache\(\s*[^,)]+,", source)
