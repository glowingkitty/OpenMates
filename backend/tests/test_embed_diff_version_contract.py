"""Backend contract tests for encrypted embed diff version history.

These tests cover the product contract from
docs/specs/embed-diff-editing-parity/spec.yml: version history rows are
encrypted client-side with the embed key, so the server must not persist,
reconstruct, or restore plaintext diff history.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.services.embed_diff_service import EmbedDiffService


@pytest.mark.asyncio
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
