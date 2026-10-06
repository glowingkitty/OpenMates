"""Team warning recipients must be current owners/admins at the delivery gate."""

from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.tasks import team_storage_billing_tasks as billing


# contract-test: supporting surface=rest_api assertions=billing.storage.team-warning-expiry
@pytest.mark.asyncio
async def test_team_warning_resolves_owner_and_admin_including_nonpasskey() -> None:
    owner_id, admin_id = "6c90eaf5-9f91-4d68-afb4-21a87c762479", "fa81e93d-eed0-4876-b642-dfb7087e621e"
    addresses = {owner_id: "Owner@example.com", admin_id: "admin@example.com"}
    hashes = {user_id: hashlib.sha256(user_id.encode()).hexdigest() for user_id in addresses}
    async def execute(operation: str, _body: dict) -> dict:
        assert operation == "list_team_storage_recipients"
        return {"recipients": [{"user_id": user_id, "user_hash": hashes[user_id]} for user_id in sorted(addresses, key=lambda item: hashes[item])]}
    async def get_items(collection: str, *, params: dict, **_kwargs) -> list[dict]:
        user_id = params["filter[id][_eq]"]
        digest = hashlib.sha256(addresses[user_id].strip().lower().encode()).digest()
        assert collection == "directus_users"
        return [{"id": user_id, "hashed_email": base64.b64encode(digest).decode(),
                 "language": "en"}]
    async def contact_items(collection: str, *, params: dict, **_kwargs) -> list[dict]:
        assert collection == "account_contact_emails"
        user_id = params["filter[user_id][_eq]"]
        digest = hashlib.sha256(addresses[user_id].strip().lower().encode()).digest()
        assert params["filter[purpose][_eq]"] == "account_lifecycle"
        return [{"user_id": user_id, "hashed_email": base64.b64encode(digest).decode(),
                 "encrypted_email_address": f"vault:v1:{user_id}",
                 "purpose": "account_lifecycle", "verified_at": "2026-10-01T00:00:00Z"}]
    async def rows(collection: str, *, params: dict, **kwargs) -> list[dict]:
        if collection == "directus_users":
            return await get_items(collection, params=params, **kwargs)
        return await contact_items(collection, params=params, **kwargs)
    async def decrypt(cipher: str) -> str:
        assert cipher.startswith("vault:v1:")
        return addresses[cipher.removeprefix("vault:v1:")]
    encryption = SimpleNamespace(decrypt_account_contact_email=AsyncMock(side_effect=decrypt),
                                 decrypt_with_user_key=AsyncMock(side_effect=AssertionError("client secretbox must not use Vault user key")))
    recipients = await billing._recipients(SimpleNamespace(execute=execute),
        SimpleNamespace(get_items=rows), encryption, "a" * 64, sorted(hashes.values()))
    encryption.decrypt_with_user_key.assert_not_awaited()
    assert [row["user_hash"] for row in recipients] == sorted(hashes.values())
    assert all(len(row["email_hash"]) == 64 for row in recipients)

    # A changed address with a stale canonical hash holds every send.
    addresses[admin_id] = "changed@example.com"
    async def stale_rows(collection: str, *, params: dict, **kwargs) -> list[dict]:
        data = await rows(collection, params=params, **kwargs)
        if ((collection == "directus_users" and params["filter[id][_eq]"] == admin_id)
                or (collection == "account_contact_emails" and params["filter[user_id][_eq]"] == admin_id)):
            data[0]["hashed_email"] = base64.b64encode(hashlib.sha256(b"admin@example.com").digest()).decode()
        return data
    with pytest.raises(RuntimeError, match="email identity changed"):
        await billing._recipients(SimpleNamespace(execute=execute),
            SimpleNamespace(get_items=stale_rows), encryption, "a" * 64, sorted(hashes.values()))


# contract-test: supporting surface=rest_api assertions=billing.storage.team-warning-expiry
@pytest.mark.asyncio
async def test_team_warning_holds_when_one_admin_has_no_verified_contact() -> None:
    user_id = "fa81e93d-eed0-4876-b642-dfb7087e621e"
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    async def execute(_operation: str, _body: dict) -> dict:
        return {"recipients": [{"user_id": user_id, "user_hash": user_hash}]}
    async def get_items(collection: str, **_kwargs) -> list[dict]:
        if collection == "directus_users":
            return [{"id": user_id, "hashed_email": "ci-hash", "language": "en"}]
        assert collection == "account_contact_emails"
        return []
    encryption = SimpleNamespace(decrypt_account_contact_email=AsyncMock())
    with pytest.raises(RuntimeError, match="Verified Team warning contact email is unavailable"):
        await billing._recipients(SimpleNamespace(execute=execute),
            SimpleNamespace(get_items=get_items), encryption, "a" * 64, [user_hash])
    encryption.decrypt_account_contact_email.assert_not_awaited()
