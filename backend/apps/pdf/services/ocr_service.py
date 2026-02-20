# backend/apps/pdf/services/ocr_service.py
#
# Mistral OCR service for extracting structured text from PDF pages.
#
# Architecture:
#   Uses the Mistral Document AI API (model: mistral-ocr-latest) to extract
#   per-page markdown content, embedded images, tables, headers, and footers.
#
#   Key behaviour:
#   - Requires HTTPS URLs. For HTTP or local S3 URLs the PDF bytes are downloaded
#     and submitted as a base64 data URI.
#   - include_image_base64=True so extracted images are returned inline.
#   - table_format="html" so table structure is preserved in markdown.
#
# Vault secrets:
#   API key is stored at kv/data/providers/mistral_ai with key "api_key".

import base64
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


async def _get_mistral_api_key(secrets_manager: Any) -> str:
    """
    Fetch the Mistral AI API key from Vault via SecretsManager.

    Args:
        secrets_manager: An initialised SecretsManager instance.

    Returns:
        Mistral API key string.

    Raises:
        RuntimeError: If the key cannot be retrieved.
    """
    try:
        key = await secrets_manager.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not key:
            raise RuntimeError("Mistral API key is empty in Vault")
        return key
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve Mistral API key from Vault: {e}") from e


async def run_mistral_ocr(
    pdf_bytes: bytes,
    secrets_manager: Any,
    log_prefix: str = "[OCR]",
) -> List[Dict[str, Any]]:
    """
    Run Mistral OCR on raw PDF bytes and return per-page results.

    The PDF is submitted as a base64 data URI so no external URL is needed —
    this works regardless of whether the S3 bucket is publicly accessible.

    Args:
        pdf_bytes: Raw (decrypted) PDF bytes.
        secrets_manager: Initialised SecretsManager for Vault access.
        log_prefix: Logging prefix for traceability.

    Returns:
        List of page dicts with keys:
          - page_num (int, 1-indexed)
          - markdown (str)
          - images (list of {id, base64, bbox})
          - tables (list)
          - header (str or None)
          - footer (str or None)
          - width (float)
          - height (float)

    Raises:
        RuntimeError: On API error or unexpected response format.
    """
    api_key = await _get_mistral_api_key(secrets_manager)

    # Encode PDF as base64 data URI (works for HTTP and HTTPS endpoints)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    document_url = f"data:application/pdf;base64,{pdf_b64}"

    logger.info(f"{log_prefix} Submitting {len(pdf_bytes)} bytes to Mistral OCR")

    payload = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": document_url,
        },
        "include_image_base64": True,
        "table_format": "html",
        "extract_header": True,
        "extract_footer": True,
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/ocr",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Mistral OCR API error: HTTP {resp.status_code} — {resp.text[:400]}"
        )

    data = resp.json()
    raw_pages = data.get("pages", [])
    logger.info(f"{log_prefix} Mistral OCR returned {len(raw_pages)} pages")

    pages: List[Dict[str, Any]] = []
    for page in raw_pages:
        page_index = page.get("index", 0)  # 0-indexed from Mistral
        page_num = page_index + 1           # convert to 1-indexed

        # Extract embedded images (with base64 if include_image_base64=True)
        images = []
        for img in page.get("images", []):
            images.append(
                {
                    "id": img.get("id", ""),
                    "base64": img.get("image_base64", ""),
                    "bbox": img.get("bbox", {}),
                }
            )

        # Dimensions from the page object
        dims = page.get("dimensions", {})

        pages.append(
            {
                "page_num": page_num,
                "markdown": page.get("markdown", ""),
                "images": images,
                "tables": page.get("tables", []),
                "header": (page.get("header") or {}).get("markdown") if page.get("header") else None,
                "footer": (page.get("footer") or {}).get("markdown") if page.get("footer") else None,
                "width": dims.get("width", 0.0),
                "height": dims.get("height", 0.0),
            }
        )

    logger.info(f"{log_prefix} OCR complete: {len(pages)} pages extracted")
    return pages
