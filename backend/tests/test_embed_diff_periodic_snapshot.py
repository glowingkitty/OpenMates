"""Client-sealed diff checkpoints use the exact final artifact text."""

from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.stream_consumer import _apply_diff_block_to_existing_embed
from backend.tests.test_embed_diff_full_replacement import (
    _FakeCacheService,
    _FakeDirectusService,
    _FakeEncryptionService,
)


class CapturingEmbedService:
    def __init__(self) -> None:
        self.content = None
        self.history_rows = None

    async def update_code_embed_content(self, **kwargs):
        self.content = kwargs["code_content"]
        self.history_rows = kwargs["version_history_rows"]


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.anyio
@pytest.mark.parametrize("prior_version", [30, 31])
async def test_diff_edit_supplies_exact_client_snapshot_at_revision_32(prior_version: int) -> None:
    from toon_format import encode

    original = "first line\nsecond line"
    patch = "@@ -1,2 +1,2 @@\n first line\n-second line\n+updated line"
    request = SimpleNamespace(
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", embed_file_path_index={"main.py-AbC": "embed-1"},
    )
    cache = _FakeCacheService({
        "embed-1": {
            "embed_id": "embed-1", "type": "code", "status": "finished",
            "version_number": prior_version, "encrypted_content": "encrypted",
        },
    })
    embed_service = CapturingEmbedService()
    await _apply_diff_block_to_existing_embed(
        diff_content=patch, diff_embed_ref=None, request_data=request,
        cache_service=cache, directus_service=_FakeDirectusService(),
        encryption_service=_FakeEncryptionService(encode({
            "type": "code", "code": original, "language": "python", "filename": "main.py",
        })),
        embed_service=embed_service, user_vault_key_id="vault-1", log_prefix="[test]",
    )
    assert embed_service.content == "first line\nupdated line"
    newest = embed_service.history_rows[-1]
    assert newest["version_number"] == prior_version + 1
    assert newest["patch"] == patch
    assert (newest.get("snapshot") == embed_service.content) is (prior_version == 31)
