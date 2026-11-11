# backend/tests/test_draft_deletion_record.py
# Durable draft delete record (positive delete evidence for the reconnect
# stale-draft probe): written with the deleted version and a 180-day TTL by the
# delete paths, never on a failed delete, and cleared by any later draft save.

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.draft_shell_deletion import (
    DraftShellDeletionError,
    delete_draft_shell_drafts,
)
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.core.api.app.services.draft_deletion_record import (
    DRAFT_DELETION_RECORD_TTL,
    clear_draft_deletion_record,
    draft_deletion_record_key,
    record_draft_deletion,
)

CHAT = "00000000-0000-4000-8000-000000000001"
RECORD_KEY = f"user:user-1:chat:{CHAT}:draft_deleted"


class _Client:
    def __init__(self, write_result=1, fail=False):
        self.evals, self.deleted, self.write_result, self.fail = [], [], write_result, fail

    async def eval(self, script, key_count, *args):
        if self.fail:
            raise ConnectionError("redis down")
        if "draft_deleted" in str(args[0]):
            self.evals.append(args)
            return 1
        return self.write_result  # versioned draft write script

    async def delete(self, key):
        self.deleted.append(key)


class _Cache:
    def __init__(self, client):
        self._client = client

    @property
    async def client(self):
        return self._client


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_record_stores_version_with_long_ttl_and_reports_failures() -> None:
    client = _Client()
    assert draft_deletion_record_key("user-1", CHAT) == RECORD_KEY
    assert await record_draft_deletion(_Cache(client), "user-1", CHAT, 7) is True
    key, version, _deleted_at, ttl = client.evals[0]
    assert (key, version, ttl) == (RECORD_KEY, 7, DRAFT_DELETION_RECORD_TTL)
    assert DRAFT_DELETION_RECORD_TTL == 180 * 24 * 3600
    assert await record_draft_deletion(_Cache(None), "user-1", CHAT, 7) is False
    assert await record_draft_deletion(_Cache(_Client(fail=True)), "user-1", CHAT, 7) is False

    await clear_draft_deletion_record(_Cache(client), "user-1", CHAT)
    assert client.deleted == [RECORD_KEY]


class _ShellCache(_Cache):
    async def increment_and_tombstone_user_draft(self, user_id, chat_id):
        return 4


class _ShellDirectus:
    def __init__(self, delete_ok=True):
        self.delete_ok = delete_ok

    async def get_items(self, collection, params, **kwargs):
        return [{"id": "draft-row-1"}]

    async def bulk_delete_items(self, collection, item_ids):
        return self.delete_ok


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_draft_only_chat_delete_records_only_after_rows_are_gone() -> None:
    client = _Client()
    assert await delete_draft_shell_drafts(_ShellCache(client), _ShellDirectus(), "user-1", CHAT) == 1
    assert [(args[0], args[1]) for args in client.evals] == [(RECORD_KEY, 4)]

    failed = _Client()
    with pytest.raises(DraftShellDeletionError):
        await delete_draft_shell_drafts(_ShellCache(failed), _ShellDirectus(delete_ok=False), "user-1", CHAT)
    assert failed.evals == []


class _MixinCache(ChatCacheMixin):
    USER_DRAFT_TTL = 2700
    CHAT_VERSIONS_TTL = 86400

    def __init__(self, client):
        self._client = client

    @property
    async def client(self):
        return self._client


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_new_draft_save_clears_the_delete_record() -> None:
    written = _Client(write_result=1)
    assert await _MixinCache(written).update_user_draft_in_cache("user-1", CHAT, "cipher", 5) is True
    assert written.deleted == [RECORD_KEY]

    superseded = _Client(write_result=0)
    assert await _MixinCache(superseded).update_user_draft_in_cache("user-1", CHAT, "cipher", 5) is False
    assert superseded.deleted == []
