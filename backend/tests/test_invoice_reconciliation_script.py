"""
Invoice reconciliation script helper tests.

The production reconciliation script talks to Stripe, Directus, Vault, and
Invoice Ninja when executed inside the api container. These tests only cover
the pure matching/date helpers so the incident guardrails remain fast and safe
to run without external services.
"""

import base64
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_backfill_missing_stripe_invoices.py"

spec = importlib.util.spec_from_file_location("audit_backfill_missing_stripe_invoices", SCRIPT_PATH)
assert spec and spec.loader
audit_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_script)


def test_parse_datetime_supports_date_only_and_z_suffix():
    assert audit_script._parse_datetime("2026-07-01").isoformat() == "2026-07-01T00:00:00+00:00"
    parsed = audit_script._parse_datetime("2026-07-01T12:34:56Z")
    assert parsed.tzinfo == timezone.utc
    assert parsed.isoformat() == "2026-07-01T12:34:56+00:00"


def test_stripe_invoice_datetime_prefers_charge_created_timestamp():
    payment_intent = SimpleNamespace(
        id="pi_123",
        created=int(datetime(2026, 7, 4, tzinfo=timezone.utc).timestamp()),
        latest_charge=SimpleNamespace(created=int(datetime(2026, 7, 5, tzinfo=timezone.utc).timestamp())),
    )

    assert audit_script._stripe_invoice_datetime(payment_intent).isoformat() == "2026-07-05T00:00:00+00:00"


def test_stripe_invoice_datetime_falls_back_to_payment_intent_created_timestamp():
    payment_intent = SimpleNamespace(
        id="pi_123",
        created=int(datetime(2026, 7, 4, tzinfo=timezone.utc).timestamp()),
        latest_charge="ch_123",
    )

    assert audit_script._stripe_invoice_datetime(payment_intent).isoformat() == "2026-07-04T00:00:00+00:00"


def test_invoice_filename_helpers_preserve_invoice_number_with_original_date():
    filename = audit_script._invoice_filename_for_date("RDGV4VK-2", "2026-06-04")

    assert filename == "openmates_invoice_2026_06_04_RDGV4VK-2.pdf"
    assert audit_script._invoice_number_from_filename(filename) == "RDGV4VK-2"


def test_account_id_from_invoice_number_uses_counter_suffix():
    assert audit_script._account_id_from_invoice_number("RDGV4VK-2") == "RDGV4VK"
    assert audit_script._account_id_from_invoice_number("missing-counter") is None


def test_invoice_s3_object_key_uses_new_original_date_key(monkeypatch):
    monkeypatch.setattr(audit_script.uuid, "uuid4", lambda: SimpleNamespace(hex="fixeduuid"))

    assert audit_script._invoice_s3_object_key_for_date("2026-06-04") == "2026_06_04_fixeduuid.pdf"


def test_stripe_amount_to_display_units_handles_zero_decimal_currencies():
    assert audit_script._stripe_amount_to_display_units(1000, "eur") == 10.0
    assert audit_script._stripe_amount_to_display_units(1000, "jpy") == 1000.0
    assert audit_script._stripe_amount_to_display_units(1000, "xpf") == 1000.0


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext, key_id):
        return f"wrapped:{key_id}:{plaintext}", "v1"


class MapEncryption(FakeEncryption):
    def __init__(self, values):
        self.values = values

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return self.values[ciphertext]


@pytest.mark.asyncio
async def test_repair_pdf_encryption_uses_fresh_key_and_nonce(monkeypatch):
    generated = iter([b"\x01" * 32, b"\x02" * 12])
    monkeypatch.setattr(audit_script.os, "urandom", lambda size: next(generated))

    encrypted_payload, wrapped_key, nonce_b64 = await audit_script._encrypt_repair_pdf_payload(
        FakeEncryption(),
        "vault-key",
        b"pdf bytes",
    )

    aes_key = base64.b64decode(wrapped_key.split(":")[-1])
    nonce = base64.b64decode(nonce_b64)

    assert aes_key == b"\x01" * 32
    assert nonce == b"\x02" * 12
    assert AESGCM(aes_key).decrypt(nonce, encrypted_payload, None) == b"pdf bytes"


def test_ninja_invoice_matches_custom_field_or_private_notes():
    assert audit_script._ninja_invoice_matches({"custom_value2": "pi_123"}, "pi_123")
    assert audit_script._ninja_invoice_matches({"private_notes": "stripe Order ID: pi_123"}, "pi_123")
    assert not audit_script._ninja_invoice_matches({"custom_value2": "pi_other"}, "pi_123")


class FakeNinja:
    def __init__(self):
        self.calls = []

    async def make_api_request(self, method, endpoint, params=None, data=None):
        self.calls.append((method, endpoint, params, data))
        if params == {"custom_value2": "bt_123"}:
            return {"data": [{"id": "1", "custom_value2": "unrelated"}]}
        if params == {"filter": "bt_123", "status": "active"}:
            return {"data": [{"id": "2", "private_notes": "bank_transfer Order ID: bt_123"}]}
        return {"data": []}


class EmptyNinja:
    def __init__(self):
        self.calls = []

    async def make_api_request(self, method, endpoint, params=None, data=None):
        self.calls.append((method, endpoint, params, data))
        return {"data": []}


class FakeDirectusUsers:
    def __init__(self, users_by_collection):
        self.users_by_collection = users_by_collection
        self.calls = []

    async def get_items(self, collection, params=None, admin_required=False):
        self.calls.append((collection, params, admin_required))
        return self.users_by_collection.get(collection, [])


@pytest.mark.asyncio
async def test_ninja_invoice_exists_falls_back_to_filtered_private_notes():
    ninja = FakeNinja()

    assert await audit_script._ninja_invoice_exists(ninja, "bt_123")

    assert len(ninja.calls) == 3


class FailingNinja:
    async def make_api_request(self, method, endpoint, params=None, data=None):
        return None


@pytest.mark.asyncio
async def test_ninja_invoice_exists_returns_unknown_on_lookup_errors():
    assert await audit_script._ninja_invoice_exists(FailingNinja(), "pi_123") is None


@pytest.mark.asyncio
async def test_directus_users_by_hash_prefers_users_collection():
    user = {"id": "user-1", "account_id": "ACCT001", "vault_key_id": "vault-key"}
    user_hash = audit_script.hashlib.sha256(b"user-1").hexdigest()
    directus = FakeDirectusUsers({"users": [user], "directus_users": []})

    assert await audit_script._directus_users_by_hash(directus, {user_hash}) == {user_hash: user}
    assert [call[0] for call in directus.calls] == ["users"]


@pytest.mark.asyncio
async def test_directus_users_by_hash_falls_back_to_directus_users_collection():
    user = {"id": "user-1", "account_id": "ACCT001", "vault_key_id": "vault-key"}
    user_hash = audit_script.hashlib.sha256(b"user-1").hexdigest()
    directus = FakeDirectusUsers({"users": [], "directus_users": [user]})

    assert await audit_script._directus_users_by_hash(directus, {user_hash}) == {user_hash: user}
    assert [call[0] for call in directus.calls] == ["users", "directus_users"]


@pytest.mark.asyncio
async def test_invoice_ninja_backfill_dry_run_uses_directus_invoice_metadata():
    result = await audit_script._backfill_invoice_ninja_from_directus_invoice(
        ninja=EmptyNinja(),
        s3=None,
        encryption=MapEncryption({
            "enc-filename": "openmates_invoice_2026_07_01_RDGV4VK-2.pdf",
            "enc-amount": "1000",
            "enc-credits": "10000",
            "enc-currency": "eur",
        }),
        invoice={
            "id": "invoice-1",
            "provider": "bank_transfer",
            "order_id": "bt_123",
            "date": "2026-07-01T09:00:00+00:00",
            "user_id_hash": "hash-1",
            "encrypted_filename": "enc-filename",
            "encrypted_amount": "enc-amount",
            "encrypted_credits_purchased": "enc-credits",
            "encrypted_currency": "enc-currency",
        },
        user={"vault_key_id": "vault-key", "account_id": "RDGV4VK"},
        apply=False,
    )

    assert result["status"] == "would_create"
    assert result["invoice_number"] == "RDGV4VK-2"
    assert result["invoice_date"] == "2026-07-01"
    assert result["amount"] == 1000
    assert result["credits"] == 10000
    assert result["currency"] == "eur"


def test_missing_invoice_ninja_replacement_parts_requires_complete_surfaces():
    assert audit_script._missing_invoice_ninja_replacement_parts(None) == ["replacement transaction"]
    assert audit_script._missing_invoice_ninja_replacement_parts({
        "invoice_id": "inv-new",
        "payment_id": None,
        "bank_transaction_id": "bank-new",
        "pdf_upload_success": True,
        "transaction_match_success": False,
    }) == ["replacement payment", "replacement bank transaction match"]


@pytest.mark.asyncio
async def test_cleanup_incomplete_invoice_ninja_replacement_deletes_new_rows_in_safe_order():
    ninja = ReplacementNinja(replacement={})

    assert await audit_script._cleanup_incomplete_invoice_ninja_replacement(ninja, {
        "invoice_id": "inv-new",
        "payment_id": "pay-new",
        "bank_transaction_id": "bank-new",
    }) == []
    assert ninja.events == [
        ("DELETE", "/bank_transactions/bank-new"),
        ("DELETE", "/payments/pay-new"),
        ("DELETE", "/invoices/inv-new"),
    ]


class ReplacementNinja:
    def __init__(self, replacement):
        self.replacement = replacement
        self.events = []

    async def process_income_transaction(self, **kwargs):
        self.events.append(("PROCESS", kwargs["external_order_id"]))
        return self.replacement

    async def make_api_request(self, method, endpoint, params=None, data=None):
        self.events.append((method, endpoint))
        return {}


class OldDeleteFailsReplacementNinja(ReplacementNinja):
    async def make_api_request(self, method, endpoint, params=None, data=None):
        self.events.append((method, endpoint))
        if endpoint == "/bank_transactions/bank-old":
            return None
        return {}


async def fake_payment_rows(ninja, external_order_id):
    return [{"id": "pay-old"}]


async def fake_bank_transaction_rows(ninja, external_order_id, invoice_number):
    return [{"id": "bank-old"}]


@pytest.mark.asyncio
async def test_recreate_locked_ninja_surfaces_keeps_old_rows_when_replacement_fails(monkeypatch):
    monkeypatch.setattr(audit_script, "_ninja_payment_rows", fake_payment_rows)
    monkeypatch.setattr(audit_script, "_ninja_bank_transaction_rows", fake_bank_transaction_rows)
    ninja = ReplacementNinja(replacement=None)

    result = await audit_script._recreate_locked_invoice_ninja_surfaces(
        ninja=ninja,
        external_order_id="pi_123",
        invoice_rows=[{"id": "inv-old"}],
        invoice_number="ACCT-1",
        invoice_date="2026-07-01",
        pdf_bytes=b"pdf",
        user_hash="user-hash",
        user={"account_id": "acct"},
        credits=1000,
        amount_paid=1000,
        currency_code="eur",
        card_details={},
        is_gift_card=False,
        apply=True,
    )

    assert result["recreated"] is False
    assert result["errors"] == ["failed to create complete replacement: replacement transaction"]
    assert ninja.events == [("PROCESS", "pi_123")]


@pytest.mark.asyncio
async def test_recreate_locked_ninja_surfaces_cleans_incomplete_replacement(monkeypatch):
    monkeypatch.setattr(audit_script, "_ninja_payment_rows", fake_payment_rows)
    monkeypatch.setattr(audit_script, "_ninja_bank_transaction_rows", fake_bank_transaction_rows)
    ninja = ReplacementNinja(
        replacement={
            "invoice_id": "inv-new",
            "invoice_number": "ACCT-1",
            "payment_id": None,
            "bank_transaction_id": None,
            "pdf_upload_success": True,
            "transaction_match_success": False,
        }
    )

    result = await audit_script._recreate_locked_invoice_ninja_surfaces(
        ninja=ninja,
        external_order_id="pi_123",
        invoice_rows=[{"id": "inv-old"}],
        invoice_number="ACCT-1",
        invoice_date="2026-07-01",
        pdf_bytes=b"pdf",
        user_hash="user-hash",
        user={"account_id": "acct"},
        credits=1000,
        amount_paid=1000,
        currency_code="eur",
        card_details={},
        is_gift_card=False,
        apply=True,
    )

    assert result["recreated"] is False
    assert result["errors"] == ["failed to create complete replacement: replacement payment"]
    assert ninja.events == [("PROCESS", "pi_123"), ("DELETE", "/invoices/inv-new")]


@pytest.mark.asyncio
async def test_recreate_locked_ninja_surfaces_deletes_old_rows_after_replacement_success(monkeypatch):
    monkeypatch.setattr(audit_script, "_ninja_payment_rows", fake_payment_rows)
    monkeypatch.setattr(audit_script, "_ninja_bank_transaction_rows", fake_bank_transaction_rows)
    ninja = ReplacementNinja(
        replacement={
            "invoice_id": "inv-new",
            "invoice_number": "ACCT-1",
            "payment_id": "pay-new",
            "bank_transaction_id": "bank-new",
            "pdf_upload_success": True,
            "transaction_match_success": True,
        }
    )

    result = await audit_script._recreate_locked_invoice_ninja_surfaces(
        ninja=ninja,
        external_order_id="pi_123",
        invoice_rows=[{"id": "inv-old"}],
        invoice_number="ACCT-1",
        invoice_date="2026-07-01",
        pdf_bytes=b"pdf",
        user_hash="user-hash",
        user={"account_id": "acct"},
        credits=1000,
        amount_paid=1000,
        currency_code="eur",
        card_details={},
        is_gift_card=False,
        apply=True,
    )

    assert result["recreated"] is True
    assert result["errors"] == []
    assert ninja.events == [
        ("PROCESS", "pi_123"),
        ("DELETE", "/bank_transactions/bank-old"),
        ("DELETE", "/payments/pay-old"),
        ("DELETE", "/invoices/inv-old"),
    ]


@pytest.mark.asyncio
async def test_recreate_locked_ninja_surfaces_cleans_replacement_when_old_delete_fails(monkeypatch):
    monkeypatch.setattr(audit_script, "_ninja_payment_rows", fake_payment_rows)
    monkeypatch.setattr(audit_script, "_ninja_bank_transaction_rows", fake_bank_transaction_rows)
    ninja = OldDeleteFailsReplacementNinja(
        replacement={
            "invoice_id": "inv-new",
            "invoice_number": "ACCT-1",
            "payment_id": "pay-new",
            "bank_transaction_id": "bank-new",
            "pdf_upload_success": True,
            "transaction_match_success": True,
        }
    )

    result = await audit_script._recreate_locked_invoice_ninja_surfaces(
        ninja=ninja,
        external_order_id="pi_123",
        invoice_rows=[{"id": "inv-old"}],
        invoice_number="ACCT-1",
        invoice_date="2026-07-01",
        pdf_bytes=b"pdf",
        user_hash="user-hash",
        user={"account_id": "acct"},
        credits=1000,
        amount_paid=1000,
        currency_code="eur",
        card_details={},
        is_gift_card=False,
        apply=True,
    )

    assert result["recreated"] is False
    assert result["errors"] == ["failed to delete old bank transaction bank-old"]
    assert ninja.events == [
        ("PROCESS", "pi_123"),
        ("DELETE", "/bank_transactions/bank-old"),
    ]


@pytest.mark.parametrize(
    ("directus_present", "invoice_ninja_present", "expected"),
    [
        (False, False, "dispatch_no_email_invoice_task"),
        (False, True, "none_invoice_ninja_present"),
        (False, None, "none_invoice_ninja_unknown"),
        (True, False, "none_requires_invoice_ninja_backfill"),
        (True, True, "none_directus_present"),
    ],
)
def test_apply_action_for_stripe_record_fails_closed(directus_present, invoice_ninja_present, expected):
    assert audit_script._apply_action_for_stripe_record(
        directus_present=directus_present,
        invoice_ninja_present=invoice_ninja_present,
        checked_invoice_ninja=True,
    ) == expected


def test_apply_preflight_blocks_unmapped_or_non_dispatchable_findings():
    findings = [
        {"apply_action": "dispatch_no_email_invoice_task", "user_id": "user-1"},
        {"apply_action": "dispatch_no_email_invoice_task", "user_id": None},
        {"apply_action": "none_requires_invoice_ninja_backfill", "user_id": "user-2"},
    ]

    blocked, unmapped = audit_script._apply_preflight_blockers(findings)

    assert blocked == [findings[2]]
    assert unmapped == [findings[1]]
