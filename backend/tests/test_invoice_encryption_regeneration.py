"""Append-only invoice ciphertext regeneration contract tests.

These tests protect immutable invoice v1 rows and objects while allowing a
verified replacement PDF to become the latest selectable ciphertext version.
They intentionally exercise publication ordering and failure behavior without
calling external Vault, Directus, or S3 services.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.shared.python_utils.invoice_ciphertext_versions import (
    append_verified_invoice_ciphertext_version,
    select_latest_invoice_ciphertext,
)


class FakeEncryptionService:
    async def encrypt_with_user_key(self, plaintext: str, _vault_key_id: str):
        return f"wrapped:{plaintext}", None


class FakeS3Service:
    environment = "development"

    def __init__(self, *, corrupt_readback: bool = False):
        self.corrupt_readback = corrupt_readback
        self.objects: dict[str, bytes] = {}
        self.events: list[str] = []
        self.deleted: list[str] = []

    async def upload_file(self, *, bucket_key: str, file_key: str, content: bytes, content_type: str):
        assert bucket_key == "invoices"
        assert content_type == "application/octet-stream"
        self.events.append("upload")
        self.objects[file_key] = content
        return {"url": "https://storage.invalid/invoice"}

    async def get_file(self, *, bucket_name: str, object_key: str):
        assert bucket_name == "development-invoices"
        self.events.append("readback")
        payload = self.objects[object_key]
        return payload[:-1] + bytes([payload[-1] ^ 1]) if self.corrupt_readback else payload

    async def delete_file(self, *, bucket_key: str, file_key: str):
        assert bucket_key == "invoices"
        self.deleted.append(file_key)
        self.objects.pop(file_key, None)


class FakeDirectusService:
    def __init__(self, versions: list[dict] | None = None, *, publish_success: bool = True):
        self.versions = list(versions or [])
        self.publish_success = publish_success
        self.events: list[str] = []
        self.updates: list[tuple] = []
        self.deletes: list[tuple] = []

    async def get_items(self, collection: str, params: dict | None = None):
        assert collection == "invoice_ciphertext_versions"
        return self.versions

    async def create_item(self, collection: str, payload: dict):
        assert collection == "invoice_ciphertext_versions"
        self.events.append("publish")
        if self.publish_success:
            self.versions.append(deepcopy(payload))
        return self.publish_success, {"id": "version-row-1", **payload}

    async def update_item(self, *args, **kwargs):
        self.updates.append((args, kwargs))

    async def delete_item(self, *args, **kwargs):
        self.deletes.append((args, kwargs))


@pytest.mark.asyncio
async def test_regeneration_appends_fresh_verified_ciphertext_before_publication(monkeypatch):
    directus = FakeDirectusService()
    s3 = FakeS3Service()
    task = SimpleNamespace(
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
        s3_service=s3,
    )
    generated = iter((bytes(range(32)), bytes(range(12))))
    monkeypatch.setattr(
        "backend.shared.python_utils.invoice_ciphertext_versions.os.urandom",
        lambda size: next(generated),
    )
    monkeypatch.setattr(
        "backend.shared.python_utils.invoice_ciphertext_versions.uuid.uuid4",
        lambda: SimpleNamespace(hex="fresh-object"),
    )

    version = await append_verified_invoice_ciphertext_version(
        task=task,
        invoice_id="invoice-1",
        user_id_hash="owner-hash",
        vault_key_id="vault-key-1",
        bucket_name="development-invoices",
        filename="invoice.pdf",
        pdf_bytes=b"%PDF-regenerated",
    )

    assert s3.events == ["upload", "readback"]
    assert directus.events == ["publish"]
    assert version["version_number"] == 2
    assert version["verified_at"]
    assert version["encrypted_s3_object_key"] == "wrapped:invoice-versions/invoice-1/fresh-object.pdf"
    assert version["encrypted_aes_key"] == f"wrapped:{base64.b64encode(bytes(range(32))).decode()}"
    assert version["aes_nonce"] == base64.b64encode(bytes(range(12))).decode()
    assert directus.updates == []
    assert directus.deletes == []
    assert s3.deleted == []


@pytest.mark.asyncio
async def test_failed_readback_never_publishes_and_only_cleans_candidate(monkeypatch):
    directus = FakeDirectusService()
    s3 = FakeS3Service(corrupt_readback=True)
    task = SimpleNamespace(
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
        s3_service=s3,
    )
    with pytest.raises(ValueError, match="read-back verification failed"):
        await append_verified_invoice_ciphertext_version(
            task=task,
            invoice_id="invoice-1",
            user_id_hash="owner-hash",
            vault_key_id="vault-key-1",
            bucket_name="development-invoices",
            filename="invoice.pdf",
            pdf_bytes=b"%PDF-regenerated",
        )

    assert directus.events == []
    assert directus.versions == []
    assert directus.updates == []
    assert directus.deletes == []
    assert len(s3.deleted) == 1


@pytest.mark.asyncio
async def test_publication_conflict_cleans_candidate_and_preserves_existing_version():
    existing = {
        "invoice_id": "invoice-1",
        "version_number": 2,
        "verified_at": "2026-08-03T00:00:00+00:00",
    }
    directus = FakeDirectusService([existing], publish_success=False)
    s3 = FakeS3Service()
    task = SimpleNamespace(
        directus_service=directus,
        encryption_service=FakeEncryptionService(),
        s3_service=s3,
    )

    with pytest.raises(ValueError, match="publication failed"):
        await append_verified_invoice_ciphertext_version(
            task=task,
            invoice_id="invoice-1",
            user_id_hash="owner-hash",
            vault_key_id="vault-key-1",
            bucket_name="development-invoices",
            filename="invoice.pdf",
            pdf_bytes=b"%PDF-regenerated",
        )

    assert directus.versions == [existing]
    assert len(s3.deleted) == 1


def test_latest_verified_version_overlays_ciphertext_without_mutating_invoices():
    invoices = [
        {
            "id": "invoice-1",
            "encrypted_s3_object_key": "v1-object",
            "encrypted_aes_key": "v1-key",
            "encrypted_filename": "v1-name",
            "aes_nonce": "v1-nonce",
        },
        {
            "id": "invoice-2",
            "encrypted_s3_object_key": "other-object",
            "encrypted_aes_key": "other-key",
            "encrypted_filename": "other-name",
            "aes_nonce": "other-nonce",
        },
    ]
    original = deepcopy(invoices)
    versions = [
        {
            "invoice_id": "invoice-1",
            "version_number": 2,
            "verified_at": "2026-08-03T00:00:00+00:00",
            "encrypted_s3_object_key": "v2-object",
            "encrypted_aes_key": "v2-key",
            "encrypted_filename": "v2-name",
            "aes_nonce": "v2-nonce",
        },
        {
            "invoice_id": "invoice-1",
            "version_number": 3,
            "verified_at": None,
            "encrypted_s3_object_key": "unverified-object",
            "encrypted_aes_key": "unverified-key",
            "encrypted_filename": "unverified-name",
            "aes_nonce": "unverified-nonce",
        },
    ]

    selected = select_latest_invoice_ciphertext(invoices, versions)

    assert selected[0]["id"] == "invoice-1"
    assert selected[0]["encrypted_s3_object_key"] == "v2-object"
    assert selected[0]["encrypted_aes_key"] == "v2-key"
    assert selected[0]["aes_nonce"] == "v2-nonce"
    assert selected[0]["ciphertext_version_number"] == 2
    assert selected[1] == {**invoices[1], "ciphertext_version_number": 1}
    assert invoices == original


def test_refund_link_regeneration_uses_append_only_version_helper():
    source = (
        Path(__file__).parents[1]
        / "core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py"
    ).read_text(encoding="utf-8")
    regeneration = source.split("# 11. Now that we have the invoice UUID", 1)[1].split(
        "email_context =",
        1,
    )[0]

    assert "append_verified_invoice_ciphertext_version(" in regeneration
    assert "AESGCM(aes_key)" not in regeneration
    assert "file_key=s3_object_key" not in regeneration


def test_invoice_version_lifecycle_covers_account_export_and_deletion():
    backend_root = Path(__file__).parents[1]
    deletion_source = (
        backend_root / "core/api/app/tasks/user_cache_tasks.py"
    ).read_text(encoding="utf-8")
    export_source = (
        backend_root / "core/api/app/routes/settings.py"
    ).read_text(encoding="utf-8")
    account_export_source = (
        backend_root / "core/api/app/services/account_export_service.py"
    ).read_text(encoding="utf-8")

    assert '"invoice_ciphertext_versions"' in deletion_source
    assert 'bulk_delete_items(\n                    "invoice_ciphertext_versions"' in deletion_source
    assert 'collection="invoice_ciphertext_versions"' in export_source
    assert "select_latest_invoice_ciphertext(" in export_source
    assert '"invoice_ciphertext_versions"' in account_export_source
    assert "select_latest_invoice_ciphertext(invoices, versions)" in account_export_source
