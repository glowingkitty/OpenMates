"""Encrypted, context-scoped buyer details for invoice generation.

This is a first-party billing surface. The server decrypts an address only while
serving an authorized billing owner or rendering a purchased invoice.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id


class BillingProfileService:
    def __init__(self, directus: Any, encryption: Any) -> None:
        self.directus = directus
        self.encryption = encryption

    async def get_profile(self, owner_kind: str, owner_id: str) -> dict[str, Any]:
        rows = await self.directus.get_items(
            "billing_profiles",
            params={"filter": {"owner_kind": {"_eq": owner_kind}, "owner_hash": {"_eq": hash_id(owner_id)}}, "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else {}

    async def get_or_create_team_billing_key(self, team_id: str) -> str:
        """Keep Team billing ciphertext readable after a payer account is removed."""
        profile = await self.get_profile("team", team_id)
        if profile.get("billing_vault_key_id"):
            return profile["billing_vault_key_id"]
        key_id = await self.encryption.create_user_key()
        if not key_id:
            raise RuntimeError("Team billing encryption key unavailable")
        # A legacy profile has field-specific key metadata for its older ciphertext.
        # Preserve those IDs so reads continue to use the key that wrote each field.
        await self.update_profile("team", team_id, {"billing_vault_key_id": key_id})
        return (await self.get_profile("team", team_id))["billing_vault_key_id"]

    async def get_team_subscription_profile(self, subscription_id: str) -> dict[str, Any]:
        rows = await self.directus.get_items(
            "billing_profiles",
            params={"filter": {"owner_kind": {"_eq": "team"}, "monthly_subscription_id": {"_eq": subscription_id}}, "limit": 1},
            no_cache=True, admin_required=True,
        )
        if rows:
            return rows[0]
        setup_rows = await self.directus.get_items(
            "billing_order_contexts",
            params={"filter": {"provider_subscription_id": {"_eq": subscription_id}, "owner_kind": {"_eq": "team"}}, "limit": 1},
            no_cache=True, admin_required=True,
        )
        if not setup_rows:
            return {}
        setup = setup_rows[0]
        profile = await self.get_profile("team", setup["owner_id"])
        if not profile or profile.get("owner_hash") != setup.get("owner_hash"):
            return {}
        return {
            **profile,
            "monthly_subscription_credits": setup["credits_amount"],
            "monthly_subscription_bonus_credits": setup.get("bonus_credits") or 0,
            "monthly_subscription_currency": setup["currency"],
            "monthly_payer_user_id": setup["actor_user_id"],
            "monthly_email_vault_key_id": setup.get("payer_email_vault_key_id"),
            "_subscription_setup_context": setup,
        }

    async def get_address(self, owner_kind: str, owner_id: str) -> dict[str, str] | None:
        profile = await self.get_profile(owner_kind, owner_id)
        encrypted = profile.get("encrypted_buyer_address")
        key_id = profile.get("address_vault_key_id")
        if not encrypted or not key_id:
            return None
        plaintext = await self.encryption.decrypt_with_user_key(encrypted, key_id)
        if not plaintext:
            raise RuntimeError("Billing address unavailable")
        return json.loads(plaintext)

    async def save_address(
        self, owner_kind: str, owner_id: str, address: dict[str, str] | None, vault_key_id: str
    ) -> dict[str, str] | None:
        if owner_kind == "team" and address is not None:
            vault_key_id = await self.get_or_create_team_billing_key(owner_id)
        ciphertext = None
        if address is not None:
            ciphertext, _ = await self.encryption.encrypt_with_user_key(
                json.dumps(address, sort_keys=True), vault_key_id
            )
            if not ciphertext:
                raise RuntimeError("Billing address encryption failed")
        await self.update_profile(
            owner_kind,
            owner_id,
            {
                "encrypted_buyer_address": ciphertext,
                "address_vault_key_id": vault_key_id if ciphertext else None,
            },
        )
        return address

    async def update_profile(self, owner_kind: str, owner_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if owner_kind not in {"personal", "team"}:
            raise ValueError("Invalid billing owner")
        profile = await self.get_profile(owner_kind, owner_id)
        now = datetime.now(timezone.utc).isoformat()
        if profile:
            updated = await self.directus.update_item(
                "billing_profiles", profile["id"], {**changes, "owner_id": owner_id, "updated_at": now}, admin_required=True
            )
            if not updated:
                raise RuntimeError("Billing profile update failed")
            return updated
        created, item = await self.directus.create_item(
            "billing_profiles",
            {"owner_kind": owner_kind, "owner_hash": hash_id(owner_id), "owner_id": owner_id, **changes, "updated_at": now},
            admin_required=True,
        )
        if not created:
            # A simultaneous purchase may have inserted this owner first.
            profile = await self.get_profile(owner_kind, owner_id)
            if not profile:
                raise RuntimeError("Billing profile creation failed")
            updated = await self.directus.update_item(
                "billing_profiles", profile["id"],
                {**changes, "owner_id": owner_id, "updated_at": now}, admin_required=True,
            )
            if not updated:
                raise RuntimeError("Billing profile update after concurrent creation failed")
            return updated
        return item

    async def save_order_context(
        self,
        *,
        order_id: str,
        owner_kind: str,
        owner_id: str,
        actor_user_id: str,
        credits_amount: int,
        currency: str,
        provider: str,
        vault_key_id: str,
        email_encryption_key: str | None,
        buyer_address: dict[str, str] | None,
        use_saved_address: bool = True,
        is_gift_card: bool = False,
        bonus_credits: int = 0,
        payer_email: str | None = None,
    ) -> None:
        if owner_kind == "team":
            vault_key_id = await self.get_or_create_team_billing_key(owner_id)
        address = buyer_address if buyer_address is not None else (
            await self.get_address(owner_kind, owner_id) if use_saved_address else None
        )
        ciphertext = None
        if address:
            ciphertext, _ = await self.encryption.encrypt_with_user_key(json.dumps(address, sort_keys=True), vault_key_id)
            if not ciphertext:
                raise RuntimeError("Billing order address encryption failed")
        encrypted_email_key = None
        if email_encryption_key:
            encrypted_email_key, _ = await self.encryption.encrypt_with_user_key(email_encryption_key, vault_key_id)
            if not encrypted_email_key:
                raise RuntimeError("Billing order email key encryption failed")
        encrypted_payer_email = None
        if payer_email:
            encrypted_payer_email, _ = await self.encryption.encrypt_with_user_key(payer_email, vault_key_id)
            if not encrypted_payer_email:
                raise RuntimeError("Billing payer email encryption failed")
        created, _ = await self.directus.create_item(
            "billing_order_contexts",
            {
                "order_id": order_id,
                "owner_kind": owner_kind,
                "owner_hash": hash_id(owner_id),
                "owner_id": owner_id,
                "actor_user_id": actor_user_id,
                "encrypted_buyer_address": ciphertext,
                "address_vault_key_id": vault_key_id if ciphertext else None,
                "encrypted_email_encryption_key": encrypted_email_key,
                "email_key_vault_key_id": vault_key_id if encrypted_email_key else None,
                "credits_amount": credits_amount,
                "currency": currency.lower(),
                "provider": provider,
                "bonus_credits": bonus_credits,
                "encrypted_payer_email": encrypted_payer_email,
                "payer_email_vault_key_id": vault_key_id if encrypted_payer_email else None,
                "is_gift_card": is_gift_card,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            admin_required=True,
        )
        if not created:
            existing = await self.get_order_context(order_id)
            if not existing or existing.get("owner_kind") != owner_kind or existing.get("owner_hash") != hash_id(owner_id) or existing.get("actor_user_id") != actor_user_id:
                raise RuntimeError("Billing order context creation failed")

    async def get_order_context(self, order_id: str) -> dict[str, Any]:
        rows = await self.directus.get_items(
            "billing_order_contexts",
            params={"filter": {"order_id": {"_eq": order_id}}, "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else {}

    async def get_order_address(self, context: dict[str, Any]) -> dict[str, str] | None:
        encrypted = context.get("encrypted_buyer_address")
        key_id = context.get("address_vault_key_id")
        if not encrypted or not key_id:
            return None
        value = await self.encryption.decrypt_with_user_key(encrypted, key_id)
        if not value:
            raise RuntimeError("Order billing address unavailable")
        return json.loads(value)

    async def get_order_email_key(self, context: dict[str, Any]) -> str | None:
        encrypted = context.get("encrypted_email_encryption_key")
        key_id = context.get("email_key_vault_key_id")
        if not encrypted or not key_id:
            return None
        value = await self.encryption.decrypt_with_user_key(encrypted, key_id)
        if not value:
            raise RuntimeError("Order email key unavailable")
        return value

    async def get_order_payer_email(self, context: dict[str, Any]) -> str | None:
        encrypted = context.get("encrypted_payer_email")
        key_id = context.get("payer_email_vault_key_id")
        if not encrypted or not key_id:
            return None
        value = await self.encryption.decrypt_with_user_key(encrypted, key_id)
        if not value:
            raise RuntimeError("Order payer email unavailable")
        return value

    async def mark_invoice_dispatched(self, context: dict[str, Any]) -> None:
        await self.directus.update_item(
            "billing_order_contexts",
            context["id"],
            {"invoice_dispatched_at": datetime.now(timezone.utc).isoformat(), "encrypted_email_encryption_key": None, "email_key_vault_key_id": None},
            admin_required=True,
        )

    async def mark_invoice_dispatch_requested(self, context: dict[str, Any]) -> None:
        await self.directus.update_item(
            "billing_order_contexts", context["id"],
            {"invoice_dispatch_requested_at": datetime.now(timezone.utc).isoformat()},
            admin_required=True,
        )
