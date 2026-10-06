"""Billing addresses and invoice snapshots stay isolated by billing owner."""

import pytest
import base64

from backend.core.api.app.services.billing_profile_service import BillingProfileService


class FakeDirectus:
    def __init__(self):
        self.rows = {"billing_profiles": [], "billing_order_contexts": []}

    async def get_items(self, collection, params, **_kwargs):
        rows = self.rows[collection]
        for field, condition in params.get("filter", {}).items():
            rows = [row for row in rows if row.get(field) == condition["_eq"]]
        return rows[:params.get("limit", len(rows))]

    async def create_item(self, collection, payload, **_kwargs):
        row = {"id": f"{collection}-{len(self.rows[collection]) + 1}", **payload}
        self.rows[collection].append(row)
        return True, row

    async def update_item(self, collection, item_id, payload, **_kwargs):
        row = next(row for row in self.rows[collection] if row["id"] == item_id)
        row.update(payload)
        return row


class FakeEncryption:
    def __init__(self):
        self.created = 0

    async def create_user_key(self):
        self.created += 1
        return f"team-billing-key-{self.created}"

    async def encrypt_with_user_key(self, plaintext, key_id):
        return f"vault:{key_id}:{base64.b64encode(plaintext.encode()).decode()}", key_id

    async def decrypt_with_user_key(self, ciphertext, key_id):
        prefix = f"vault:{key_id}:"
        assert ciphertext.startswith(prefix)
        return base64.b64decode(ciphertext.removeprefix(prefix)).decode()


ADDRESS = {
    "name": "Example GmbH", "street_line_1": "Main Street 1", "postal_code": "10115",
    "city": "Berlin", "country": "DE",
}


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity,teams.chat-billing.team-credit-boundary
@pytest.mark.anyio
async def test_billing_addresses_and_order_snapshots_are_context_scoped():
    directus = FakeDirectus()
    encryption = FakeEncryption()
    service = BillingProfileService(directus, encryption)
    await service.save_address("team", "team-1", ADDRESS, "personal-key")
    await service.save_address("personal", "alice", {**ADDRESS, "name": "Alice"}, "personal-key")

    await service.save_order_context(
        order_id="order-1", owner_kind="team", owner_id="team-1", actor_user_id="alice",
        credits_amount=50, currency="eur", provider="bank_transfer", vault_key_id="personal-key",
        email_encryption_key="temporary", buyer_address=None, payer_email="alice@example.com",
    )
    context = await service.get_order_context("order-1")
    assert await service.get_order_address(context) == ADDRESS
    assert await service.get_address("personal", "alice") == {**ADDRESS, "name": "Alice"}
    team_profile = await service.get_profile("team", "team-1")
    assert team_profile["billing_vault_key_id"] == "team-billing-key-1"
    assert team_profile["address_vault_key_id"] == "team-billing-key-1"
    assert context["address_vault_key_id"] == "team-billing-key-1"
    assert context["email_key_vault_key_id"] == "team-billing-key-1"
    assert context["payer_email_vault_key_id"] == "team-billing-key-1"
    assert await service.get_order_payer_email(context) == "alice@example.com"
    assert (await service.get_profile("personal", "alice"))["address_vault_key_id"] == "personal-key"
    assert encryption.created == 1
    assert "Example GmbH" not in str(directus.rows["billing_profiles"])

    await service.save_address("team", "team-1", {**ADDRESS, "name": "Changed GmbH"}, "personal-key")
    assert (await service.get_order_address(context))["name"] == "Example GmbH"
    assert context["encrypted_email_encryption_key"] != "temporary"
    assert await service.get_order_email_key(context) == "temporary"
    assert encryption.created == 1
    await service.mark_invoice_dispatched(context)
    assert context["encrypted_email_encryption_key"] is None


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity,teams.chat-billing.team-credit-boundary
@pytest.mark.anyio
async def test_explicit_missing_address_can_skip_saved_profile():
    directus = FakeDirectus()
    service = BillingProfileService(directus, FakeEncryption())
    await service.save_address("team", "team-1", ADDRESS, "key-1")
    await service.save_order_context(
        order_id="order-2", owner_kind="team", owner_id="team-1", actor_user_id="alice",
        credits_amount=50, currency="eur", provider="stripe", vault_key_id="key-1",
        email_encryption_key="temporary", buyer_address=None, use_saved_address=False,
    )
    assert await service.get_order_address(await service.get_order_context("order-2")) is None


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity,teams.chat-billing.team-credit-boundary
@pytest.mark.anyio
async def test_canceled_subscription_invoice_uses_original_team_checkout_after_replacement():
    directus = FakeDirectus()
    service = BillingProfileService(directus, FakeEncryption())
    await service.save_order_context(
        order_id="checkout-old", owner_kind="team", owner_id="team-1", actor_user_id="alice",
        credits_amount=50, currency="eur", provider="team_subscription_setup", vault_key_id="key-1",
        email_encryption_key="temporary", buyer_address=ADDRESS, bonus_credits=10,
        payer_email="alice@example.com",
    )
    old_context = await service.get_order_context("checkout-old")
    await directus.update_item("billing_order_contexts", old_context["id"], {"provider_subscription_id": "sub-old"})
    await service.update_profile("team", "team-1", {
        "monthly_subscription_id": "sub-new", "monthly_subscription_credits": 100,
        "monthly_subscription_bonus_credits": 25, "monthly_payer_user_id": "bob",
    })

    historical = await service.get_team_subscription_profile("sub-old")
    assert historical["monthly_subscription_credits"] == 50
    assert historical["monthly_subscription_bonus_credits"] == 10
    assert historical["monthly_payer_user_id"] == "alice"
    assert await service.get_order_payer_email(historical["_subscription_setup_context"]) == "alice@example.com"
    assert (await service.get_order_address(historical["_subscription_setup_context"]))["name"] == "Example GmbH"


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity
@pytest.mark.anyio
async def test_legacy_ciphertext_keeps_original_key_metadata_after_team_key_creation():
    directus = FakeDirectus()
    encryption = FakeEncryption()
    service = BillingProfileService(directus, encryption)
    legacy_ciphertext, _ = await encryption.encrypt_with_user_key(
        __import__("json").dumps(ADDRESS), "payer-key"
    )
    await service.update_profile("team", "team-1", {
        "encrypted_buyer_address": legacy_ciphertext,
        "address_vault_key_id": "payer-key",
    })
    assert await service.get_address("team", "team-1") == ADDRESS
    assert await service.get_or_create_team_billing_key("team-1") == "team-billing-key-1"
    assert (await service.get_profile("team", "team-1"))["address_vault_key_id"] == "payer-key"
    await service.save_address("team", "team-1", ADDRESS, "payer-key")
    assert (await service.get_profile("team", "team-1"))["address_vault_key_id"] == "team-billing-key-1"
