"""Contract checks for the optional Workflow metadata focus hint.

Requests are scope-only and bounded per socket and user. Team membership is
checked before any cached metadata is read. A failed or duplicate hint must
not change the normal authorized cold discovery result.
"""
import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.workflow_metadata_warmup_handler import (
    accept_workflow_warmup_request, warm_workflow_metadata,
)


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
def test_warmup_rejects_text_and_limits_requests_per_socket():
    times = []
    assert accept_workflow_warmup_request(times, {"team_id": "team", "draft": "private"}) == ("invalid", None)
    assert accept_workflow_warmup_request(times, {"_traceparent": "private draft"}) == ("invalid", None)
    assert times == []
    valid_trace = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert accept_workflow_warmup_request(times, {"_traceparent": valid_trace}) == ("accepted", None)
    assert [accept_workflow_warmup_request(times, {}) for _ in range(2)] == [("accepted", None)] * 2
    assert accept_workflow_warmup_request(times, {}) == ("rate_limited", None)


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_warmup_rechecks_team_membership_before_cache_access():
    class Team:
        async def require_team_role(self, team_id, user_id, roles):
            assert (team_id, user_id) == ("other-team", "alice")
            assert "viewer" in roles
            raise PermissionError("Team permission denied")
    class Cache:
        @property
        async def client(self):
            class Redis:
                async def set(self, key, value, **kwargs): return True
            return Redis()
        async def get_user_vault_key_id(self, user_id):
            pytest.fail("cache must not be consulted before Team authorization")
    from types import SimpleNamespace
    with pytest.raises(PermissionError):
        await warm_workflow_metadata(cache_service=Cache(), directus_service=SimpleNamespace(team=Team()),
                                     user_id="alice", team_id="other-team")


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_warmup_shared_rate_limit_precedes_team_lookup():
    class Redis:
        async def set(self, key, value, **kwargs): return False
        async def incr(self, key): return 7
    class Cache:
        @property
        async def client(self): return Redis()
        async def get_user_vault_key_id(self, user_id):
            pytest.fail("rate-limited warmup must not read a Vault key")
    from types import SimpleNamespace
    assert await warm_workflow_metadata(cache_service=Cache(), directus_service=SimpleNamespace(team=None),
                                        user_id="alice", team_id="other-team") == "rate_limited"
