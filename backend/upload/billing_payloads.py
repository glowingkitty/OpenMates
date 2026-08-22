# backend/upload/billing_payloads.py
#
# Pure billing payload builders for the upload service.
# Keep these helpers free of FastAPI route imports so focused unit tests can run
# in lightweight environments that do not install upload-server form parsing or
# worker dependencies.

from typing import Any


PDF_BILLING_IDEMPOTENCY_PREFIX = "pdf:upload"


def build_pdf_billing_payload(
    *,
    user_id: str,
    user_id_hash: str,
    embed_id: str,
    credits_to_charge: int,
    page_count: int,
    credits_per_page: int,
    filename: str,
    deduplicated: bool = False,
) -> dict[str, Any]:
    usage_details: dict[str, Any] = {
        "page_count": page_count,
        "credits_per_page": credits_per_page,
        "filename": filename,
        "embed_id": embed_id,
    }
    if deduplicated:
        usage_details["deduplicated"] = True

    return {
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "credits": credits_to_charge,
        "skill_id": "process",
        "app_id": "pdf",
        "idempotency_key": f"{PDF_BILLING_IDEMPOTENCY_PREFIX}:{embed_id}",
        "usage_details": usage_details,
    }
