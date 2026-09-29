"""API key revocation and expiry cannot be bypassed by stale cached records."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.core.api.app.utils.api_key_auth import ApiKeyAuthService, ApiKeyNotFoundError


class Directus:
    def __init__(self):
        self.row = {"id": "key-1", "user_id": "user-1", "credential_version": 2,
                    "full_access": True, "scopes": {}, "expires_at": None}
        self.lookups = 0

    async def get_api_key_by_hash(self, _digest):
        self.lookups += 1
        return self.row

    async def update_api_key_last_used(self, *_args, **_kwargs):
        return True


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_api_key_each_request_reads_authority_and_rejects_legacy_or_bad_expiry():
    async def run():
        directus = Directus()
        service = ApiKeyAuthService(directus, SimpleNamespace())
        await service.authenticate_api_key("sk-api-secret")
        directus.row = None
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        assert directus.lookups == 2

        directus.row = {"id": "legacy", "user_id": "user-1", "expires_at": None}
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        directus.row["credential_version"] = 2
        directus.row["expires_at"] = "unparseable"
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        directus.row["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")

    asyncio.run(run())
