"""Team display names are transiently checked against the loaded policy."""

import pytest

from backend.core.api.app.services.team_name_validation import (
    consume_name_approval, issue_name_approval, validate_team_name,
)


class Cache:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ttl):
        assert ttl > 0
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class Policy:
    config_loaded = True
    restricted_domains = {"privatebrand.example"}

    def is_domain_restricted(self, value):
        return value == "blocked.example", None


# contract-test: supporting surface=rest_api assertions=teams.name.transient-policy
@pytest.mark.anyio
async def test_name_approval_is_single_use_user_bound_and_stores_no_plaintext():
    cache = Cache()
    assert validate_team_name("  Friendly  Team  ", Policy())
    assert not validate_team_name("Blocked.Example", Policy())
    assert not validate_team_name("PrivateBrand Support", Policy())
    token, expires_at = await issue_name_approval(cache, "alice")
    assert expires_at > 0
    assert "Friendly Team" not in repr(cache.values)
    assert not await consume_name_approval(cache, "bob", token)
    assert await consume_name_approval(cache, "alice", token)
    assert not await consume_name_approval(cache, "alice", token)
