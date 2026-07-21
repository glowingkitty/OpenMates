"""
Regression tests for the operator-only bank transfer approval script.

These tests keep the manual SEPA flow safe by ensuring the script uses admin
Directus access for pending bank-transfer rows and that support contact lookups
remain explicit, read-only operations.
"""

from __future__ import annotations

from collections import defaultdict
import sys
import types
from types import SimpleNamespace

import pytest

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")

    class FakeClientSession:
        pass

    aiohttp_module.ClientSession = FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module

from backend.scripts import approve_bank_transfer
from backend.core.api.app.services.directus.team_methods import TeamMethods, hash_id


class FakeDirectus:
    def __init__(self) -> None:
        self.get_items_calls: list[dict] = []
        self.update_item_calls: list[dict] = []
        self.user_fields_calls: list[tuple[str, list[str]]] = []

    async def get_items(self, collection, params=None, no_cache=False, admin_required=False):
        self.get_items_calls.append(
            {
                "collection": collection,
                "params": params,
                "no_cache": no_cache,
                "admin_required": admin_required,
            }
        )
        return [{"id": "row-id", "reference": "OM-TEST"}]

    async def update_item(self, collection, item_id, data, admin_required=False):
        self.update_item_calls.append(
            {
                "collection": collection,
                "item_id": item_id,
                "data": data,
                "admin_required": admin_required,
            }
        )
        return {"id": item_id, **data}

    async def get_user_fields_direct(self, user_id: str, fields: list[str]):
        self.user_fields_calls.append((user_id, fields))
        return {"encrypted_email_address": "encrypted-email"}


class FakeEncryption:
    def __init__(self) -> None:
        self.decrypt_calls: list[tuple[str, str]] = []

    async def decrypt_with_email_key(self, encrypted_email: str, email_encryption_key: str):
        self.decrypt_calls.append((encrypted_email, email_encryption_key))
        return "buyer@example.com"


class FakeSecrets:
    async def initialize(self) -> None:
        return None

    async def get_secret(self, secret_path: str, secret_key: str) -> str:
        return f"secret-{secret_key}"


class FakeCache:
    def __init__(self) -> None:
        self.status_updates: list[dict] = []
        self.stats: list[tuple] = []
        self.closed = False

    async def get_user_by_id(self, user_id: str):
        return {"id": user_id, "vault_key_id": "vault-key", "credits": 10}

    async def update_bank_transfer_status(self, **kwargs):
        self.status_updates.append(kwargs)
        return True

    async def increment_stat(self, name: str, value: int | None = None):
        self.stats.append(("increment_stat", name, value))

    async def increment_json_stat(self, name: str, key: str):
        self.stats.append(("increment_json_stat", name, key))

    async def update_liability(self, amount: int):
        self.stats.append(("update_liability", amount))

    async def set_user(self, data: dict, user_id: str):
        return True

    async def close(self) -> None:
        self.closed = True


class FakeApprovalEncryption:
    def __init__(self, cache_service=None) -> None:
        self.cache_service = cache_service

    async def encrypt_with_user_key(self, plaintext: str, key_id: str):
        return f"encrypted:{plaintext}", "v1"


class FakeApprovalDirectus:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.team = TeamMethods(self)
        self.updated_items: list[tuple[str, str, dict, bool]] = []
        self.closed = False

    async def create_item(self, collection: str, record: dict, admin_required: bool = False):
        row = {"id": f"{collection}-{len(self.rows[collection]) + 1}", **record}
        self.rows[collection].append(row)
        return True, row

    async def update_item(self, collection: str, item_id: str, patch: dict, admin_required: bool = False):
        self.updated_items.append((collection, item_id, dict(patch), admin_required))
        for row in self.rows[collection]:
            if row.get("id") == item_id:
                row.update(patch)
                return row
        return None

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        rows = list(self.rows[collection])
        for key, expected in (params or {}).items():
            if key.startswith("filter[") and "][_eq]" in key:
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) == expected]
        limit = (params or {}).get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]

    async def get_user_profile(self, user_id: str):
        return True, {"id": user_id, "vault_key_id": "vault-key", "credits": 10}, "ok"

    async def update_user(self, user_id: str, payload: dict):
        return True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_order_uses_admin_access_for_pending_bank_transfers():
    directus = FakeDirectus()

    order = await approve_bank_transfer._fetch_order(directus, "OM-TEST")

    assert order["reference"] == "OM-TEST"
    assert directus.get_items_calls == [
        {
            "collection": "pending_bank_transfers",
            "params": {"filter[reference][_eq]": "OM-TEST", "limit": 1},
            "no_cache": True,
            "admin_required": True,
        }
    ]


@pytest.mark.asyncio
async def test_update_order_uses_admin_access_for_pending_bank_transfers():
    directus = FakeDirectus()

    await approve_bank_transfer._update_order(directus, "row-id", {"status": "completed"})

    assert directus.update_item_calls == [
        {
            "collection": "pending_bank_transfers",
            "item_id": "row-id",
            "data": {"status": "completed"},
            "admin_required": True,
        }
    ]


@pytest.mark.asyncio
async def test_decrypt_contact_email_uses_order_email_key():
    directus = FakeDirectus()
    encryption = FakeEncryption()

    email = await approve_bank_transfer._decrypt_contact_email(
        directus,
        encryption,
        {"user_id": "user-id", "email_encryption_key": "email-key"},
    )

    assert email == "buyer@example.com"
    assert directus.user_fields_calls == [("user-id", ["encrypted_email_address"])]
    assert encryption.decrypt_calls == [("encrypted-email", "email-key")]


def test_parse_args_allows_contact_lookup_without_received_cents(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["approve_bank_transfer.py", "--reference", "OM-TEST", "--show-contact-email"],
    )

    args = approve_bank_transfer.parse_args()

    assert args.reference == "OM-TEST"
    assert args.show_contact_email is True
    assert args.received_cents is None


def test_parse_args_requires_received_cents_for_approval(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["approve_bank_transfer.py", "--reference", "OM-TEST"])

    with pytest.raises(SystemExit):
        approve_bank_transfer.parse_args()


def test_parse_args_rejects_contact_lookup_with_apply(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "approve_bank_transfer.py",
            "--reference",
            "OM-TEST",
            "--show-contact-email",
            "--apply",
        ],
    )

    with pytest.raises(SystemExit):
        approve_bank_transfer.parse_args()


@pytest.mark.asyncio
async def test_approve_team_bank_transfer_grants_team_credits_and_completes_order(monkeypatch):
    cache = FakeCache()
    directus = FakeApprovalDirectus()
    compliance_events: list[dict] = []
    await directus.team.create_team(
        "alice",
        {
            "team_id": "team-1",
            "encrypted_name": "cipher-name",
            "encrypted_team_key": "cipher-team-key",
            "encrypted_zero_balance": "cipher-zero",
            "created_at": 100,
            "updated_at": 100,
        },
    )
    success, order = await directus.create_item(
        "pending_bank_transfers",
        {
            "order_id": "bt_team01",
            "user_id": "alice",
            "team_id": "team-1",
            "hashed_team_id": hash_id("team-1"),
            "credits_amount": 110000,
            "amount_expected_cents": 10000,
            "currency": "eur",
            "reference": "OMT-team01-bt01",
            "status": "pending",
            "order_type": "team_credit_purchase",
            "created_at": "2026-07-18T00:00:00+00:00",
            "expires_at": "2026-07-25T00:00:00+00:00",
            "email_encryption_key": "email-key",
        },
        admin_required=True,
    )
    assert success is True
    assert order["id"] == "pending_bank_transfers-1"

    monkeypatch.setattr(approve_bank_transfer, "SecretsManager", lambda: FakeSecrets())
    monkeypatch.setattr(approve_bank_transfer, "CacheService", lambda: cache)
    monkeypatch.setattr(approve_bank_transfer, "EncryptionService", lambda cache_service=None: FakeApprovalEncryption(cache_service))
    monkeypatch.setattr(approve_bank_transfer, "DirectusService", lambda cache_service=None, encryption_service=None: directus)
    monkeypatch.setattr(
        approve_bank_transfer.ComplianceService,
        "log_financial_transaction",
        lambda **kwargs: compliance_events.append(kwargs),
    )

    result = await approve_bank_transfer.approve(
        SimpleNamespace(
            reference="OMT-team01-bt01",
            received_cents=10000,
            bank_transaction_id="txn-team-1",
            allow_amount_mismatch=False,
            no_email=True,
            show_contact_email=False,
            apply=True,
            verbose=False,
        )
    )

    assert result == 0
    account = directus.rows["team_credit_accounts"][0]
    assert account["balance_credits"] == 110000
    assert account["encrypted_balance"] == "cipher-zero"
    credit_event = directus.rows["team_credit_events"][0]
    assert credit_event["event_id"] == "bank-transfer:bt_team01"
    assert credit_event["event_type"] == "purchase"
    assert credit_event["amount"] == 110000
    completed_order = directus.rows["pending_bank_transfers"][0]
    assert completed_order["status"] == "completed"
    assert completed_order["received_amount_cents"] == 10000
    assert cache.status_updates[0]["order_id"] == "bt_team01"
    assert ("increment_json_stat", "purchases_by_provider", "team_bank_transfer_manual") in cache.stats
    assert compliance_events[0]["transaction_type"] == "team_credit_purchase"
    assert compliance_events[0]["details"]["team_id"] == "team-1"
    assert cache.closed is True
    assert directus.closed is True
