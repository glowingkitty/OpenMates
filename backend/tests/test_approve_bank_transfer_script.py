"""
Regression tests for the operator-only bank transfer approval script.

These tests keep the manual SEPA flow safe by ensuring the script uses admin
Directus access for pending bank-transfer rows and that support contact lookups
remain explicit, read-only operations.
"""

from __future__ import annotations

import sys

import pytest

from backend.scripts import approve_bank_transfer


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
