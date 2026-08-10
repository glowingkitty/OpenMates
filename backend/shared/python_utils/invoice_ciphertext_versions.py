"""Immutable invoice ciphertext version helpers.

Invoice rows remain permanent implicit v1 records. Regeneration uploads a new
AES-GCM object, authenticates a storage read-back, and only then publishes an
append-only version row. Readers overlay the latest verified version without
mutating the original invoice dictionaries.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import os
import uuid
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

INVOICE_CIPHERTEXT_FIELDS = (
    "encrypted_s3_object_key",
    "encrypted_aes_key",
    "encrypted_filename",
    "aes_nonce",
)
INVOICE_VERSION_COLLECTION = "invoice_ciphertext_versions"


async def append_verified_invoice_ciphertext_version(
    *,
    task: Any,
    invoice_id: str,
    user_id_hash: str,
    vault_key_id: str,
    bucket_name: str,
    filename: str,
    pdf_bytes: bytes,
) -> dict[str, Any]:
    """Publish a fresh invoice ciphertext version after authenticated read-back."""
    existing_versions = await task.directus_service.get_items(
        collection=INVOICE_VERSION_COLLECTION,
        params={
            "filter": {"invoice_id": {"_eq": invoice_id}},
            "sort": "-version_number",
            "limit": 1,
        },
    )
    latest_version = max(
        (int(row.get("version_number", 1)) for row in (existing_versions or [])),
        default=1,
    )
    version_number = latest_version + 1

    aes_key = os.urandom(32)
    nonce = os.urandom(12)
    encrypted_pdf = AESGCM(aes_key).encrypt(nonce, pdf_bytes, None)
    object_key = f"invoice-versions/{invoice_id}/{uuid.uuid4().hex}.pdf"

    wrapped_aes_key, _ = await task.encryption_service.encrypt_with_user_key(
        base64.b64encode(aes_key).decode("ascii"),
        vault_key_id,
    )
    encrypted_object_key, _ = await task.encryption_service.encrypt_with_user_key(
        object_key,
        vault_key_id,
    )
    encrypted_filename, _ = await task.encryption_service.encrypt_with_user_key(
        filename,
        vault_key_id,
    )
    if not wrapped_aes_key or not encrypted_object_key or not encrypted_filename:
        raise ValueError("invoice version metadata encryption failed")

    upload_result = await task.s3_service.upload_file(
        bucket_key="invoices",
        file_key=object_key,
        content=encrypted_pdf,
        content_type="application/octet-stream",
    )
    if not upload_result.get("url"):
        raise ValueError("invoice version upload failed")

    try:
        stored_ciphertext = await task.s3_service.get_file(
            bucket_name=bucket_name,
            object_key=object_key,
        )
        if AESGCM(aes_key).decrypt(nonce, stored_ciphertext, None) != pdf_bytes:
            raise ValueError("invoice version read-back verification failed")
    except Exception as exc:
        await task.s3_service.delete_file(bucket_key="invoices", file_key=object_key)
        raise ValueError("invoice version read-back verification failed") from exc

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "version_id": f"{invoice_id}:{version_number}",
        "invoice_id": invoice_id,
        "user_id_hash": user_id_hash,
        "version_number": version_number,
        "encrypted_s3_object_key": encrypted_object_key,
        "encrypted_aes_key": wrapped_aes_key,
        "encrypted_filename": encrypted_filename,
        "aes_nonce": base64.b64encode(nonce).decode("ascii"),
        "created_at": now,
        "verified_at": now,
    }
    try:
        success, _created = await task.directus_service.create_item(
            INVOICE_VERSION_COLLECTION,
            payload,
        )
        if not success:
            raise ValueError("invoice version publication failed")
    except Exception:
        await task.s3_service.delete_file(bucket_key="invoices", file_key=object_key)
        raise
    return payload


def select_latest_invoice_ciphertext(
    invoices: list[dict[str, Any]],
    versions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return invoice copies overlaid with their highest verified ciphertext version."""
    latest_by_invoice: dict[str, dict[str, Any]] = {}
    for version in versions:
        invoice_id = version.get("invoice_id")
        if not invoice_id or not version.get("verified_at"):
            continue
        if any(not version.get(field) for field in INVOICE_CIPHERTEXT_FIELDS):
            continue
        current = latest_by_invoice.get(invoice_id)
        if current is None or int(version.get("version_number", 0)) > int(
            current.get("version_number", 0)
        ):
            latest_by_invoice[invoice_id] = version

    selected = deepcopy(invoices)
    for invoice in selected:
        version = latest_by_invoice.get(invoice.get("id"))
        if version:
            for field in INVOICE_CIPHERTEXT_FIELDS:
                invoice[field] = version[field]
            invoice["ciphertext_version_number"] = int(version["version_number"])
        else:
            invoice["ciphertext_version_number"] = 1
    return selected
