"""A Team invoice survives deletion of the payer's Personal account."""

import base64
import importlib.util
import io
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

class _FakeCeleryApp:
    def task(self, *args, **_kwargs):
        return lambda func: func


@contextmanager
def _temporary_task_imports():
    task_package = types.ModuleType("backend.core.api.app.tasks")
    task_package.__path__ = [str(Path(__file__).parents[1] / "core/api/app/tasks")]
    celery_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_module.app = _FakeCeleryApp()
    base_task_module = types.ModuleType("backend.core.api.app.tasks.base_task")
    base_task_module.BaseServiceTask = type("BaseServiceTask", (), {})
    s3_service_module = types.ModuleType("backend.core.api.app.services.s3.service")
    s3_service_module.HetznerObjectStorageError = type("HetznerObjectStorageError", (RuntimeError,), {})
    cache_module = types.ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = type("CacheService", (), {})
    replacements = {
        "backend.core.api.app.tasks": task_package,
        "backend.core.api.app.tasks.celery_config": celery_module,
        "backend.core.api.app.tasks.base_task": base_task_module,
        "backend.core.api.app.services.s3.service": s3_service_module,
        "backend.core.api.app.services.cache": cache_module,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in replacements}
    sys.modules.update(replacements)
    try:
        yield
    finally:
        for name, original in previous.items():
            if original is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


TASK_PATH = Path(__file__).parents[1] / "core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py"
with _temporary_task_imports():
    spec = importlib.util.spec_from_file_location("backend.tests._team_invoice_task_under_test", TASK_PATH)
    assert spec and spec.loader
    billing_task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(billing_task)

from backend.core.api.app.services.billing_profile_service import BillingProfileService  # noqa: E402
from backend.core.api.app.services.directus.team_methods import hash_id  # noqa: E402


class FakeDirectus:
    def __init__(self):
        self.rows = {"billing_profiles": [], "billing_order_contexts": [], "invoices": []}
        self.user_field_reads = 0

    async def get_items(self, collection, params=None, **_kwargs):
        rows = self.rows[collection]
        for field, condition in (params or {}).get("filter", {}).items():
            rows = [row for row in rows if row.get(field) == condition["_eq"]]
        return rows[:(params or {}).get("limit", len(rows))]

    async def create_item(self, collection, payload, **_kwargs):
        row = {"id": f"{collection}-{len(self.rows[collection]) + 1}", **payload}
        self.rows[collection].append(row)
        return True, row

    async def update_item(self, collection, item_id, payload, **_kwargs):
        row = next(row for row in self.rows[collection] if row["id"] == item_id)
        row.update(payload)
        return row

    async def get_user_fields_direct(self, *_args):
        self.user_field_reads += 1
        return None  # The payer's Personal account has been deleted.


class FakeEncryption:
    def __init__(self):
        self.encryption_keys = []

    async def create_user_key(self):
        return "team-independent-key"

    async def encrypt_with_user_key(self, plaintext, key_id):
        self.encryption_keys.append(key_id)
        return f"wrapped:{key_id}:{base64.b64encode(str(plaintext).encode()).decode()}", key_id

    async def decrypt_with_user_key(self, ciphertext, key_id):
        prefix = f"wrapped:{key_id}:"
        assert ciphertext.startswith(prefix)
        return base64.b64decode(ciphertext.removeprefix(prefix)).decode()

    async def decrypt_with_email_key(self, *_args):
        raise AssertionError("Team invoices must not use a Personal email fallback")


class FakeCache:
    async def get_user_by_id(self, _user_id):
        return None

    async def close(self):
        pass


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_recipient", [True, False])
async def test_deleted_payer_team_invoice_uses_team_key_and_snapshot(monkeypatch, snapshot_recipient):
    directus = FakeDirectus()
    encryption = FakeEncryption()
    profiles = BillingProfileService(directus, encryption)
    await profiles.save_order_context(
        order_id="order-team-1", owner_kind="team", owner_id="team-1", actor_user_id="deleted-payer",
        credits_amount=50, currency="eur", provider="stripe_managed", vault_key_id="personal-key",
        email_encryption_key="client-key", buyer_address={
            "name": "Example GmbH", "street_line_1": "Main 1", "postal_code": "10115",
            "city": "Berlin", "country": "DE",
        },
        payer_email="payer@example.com" if snapshot_recipient else None,
    )
    pdf_calls = []
    sent_email = []
    stored_objects = {}

    def render_pdf(data, **kwargs):
        pdf_calls.append((data.copy(), kwargs))
        return io.BytesIO(b"%PDF-team-invoice")

    async def get_order(_order_id):
        return {"amount": 500, "currency": "eur", "payments": [], "created": "2026-10-06T00:00:00Z"}

    async def upload_file(**kwargs):
        stored_objects[kwargs["file_key"]] = kwargs["content"]
        return {"url": "https://storage.invalid/team-invoice"}

    async def send_email(**kwargs):
        sent_email.append(kwargs)
        return True

    class FakeTask:
        async def initialize_services(self):
            pass

        async def cleanup_services(self):
            pass

    task = FakeTask()
    task.directus_service = directus
    task.encryption_service = encryption
    task.payment_service = SimpleNamespace(get_order=get_order, provider_name="stripe_managed")
    task.invoice_template_service = SimpleNamespace(generate_invoice=render_pdf)
    task.email_template_service = SimpleNamespace(send_email=send_email)
    task.s3_service = SimpleNamespace(upload_file=upload_file, environment="development")
    monkeypatch.setattr(billing_task, "CacheService", FakeCache)

    result = await billing_task._async_process_invoice_and_send_email(
        task, "order-team-1", "deleted-payer", 50,
        "Sender street", "", "", "DE", "billing@example.com", "", provider="stripe_managed",
    )

    assert result is True
    assert directus.user_field_reads == 1
    invoice = directus.rows["invoices"][0]
    assert invoice["user_id_hash"] == hash_id("team-1")
    assert invoice["hashed_team_id"] == hash_id("team-1")
    assert invoice["invoice_vault_key_id"] == "team-independent-key"
    assert invoice["encrypted_aes_key"].startswith("wrapped:team-independent-key:")
    assert invoice["encrypted_s3_object_key"].startswith("wrapped:team-independent-key:")
    assert invoice["encrypted_filename"].startswith("wrapped:team-independent-key:")
    assert invoice["aes_nonce"] and stored_objects
    assert all(key == "team-independent-key" for key in encryption.encryption_keys)
    assert pdf_calls[0][0]["receiver_name"] == "Example GmbH"
    assert pdf_calls[0][0]["receiver_account_id"].startswith("TEAM-")
    assert [mail["recipient_email"] for mail in sent_email] == (
        ["payer@example.com"] if snapshot_recipient else []
    )
