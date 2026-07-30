"""
Invoice reconciliation script helper tests.

The production reconciliation script talks to Stripe, Directus, Vault, and
Invoice Ninja when executed inside the api container. These tests only cover
the pure matching/date helpers so the incident guardrails remain fast and safe
to run without external services.
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


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
