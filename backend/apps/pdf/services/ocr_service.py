# backend/apps/pdf/services/ocr_service.py
#
# OCR service for extracting structured text from PDF pages.
#
# Architecture — three-provider fallback chain:
#
#   1. Mistral OCR (primary)
#      Uses the Mistral Document AI API (model: mistral-ocr-latest).
#      Returns rich per-page JSON with markdown, images, tables, header/footer,
#      and page dimensions.
#
#   2. Gemini Flash (fallback)
#      Uses Google AI Studio (Gemini API) with the google-genai SDK.
#      Sends the PDF inline as base64, prompts the model to emit markdown with
#      page-break markers, then splits the response into per-page entries.
#      Image extraction is not available via this path (images=[]).
#      Model: gemini-3-flash-preview (same fast Gemini model used by the system).
#
#   3. pymupdf text extraction (last resort)
#      Purely local — no external API call. Uses the fitz (PyMuPDF) library that
#      is already installed in the app-pdf-worker container.
#      Works well for native/digital PDFs; returns empty markdown for scanned
#      PDFs that have no embedded text layer. Never fails.
#
# Entry point:
#   run_ocr_with_fallback(pdf_bytes, secrets_manager, log_prefix)
#   → returns (pages: List[Dict], provider: str)
#   where provider ∈ {"mistral", "gemini_flash", "pymupdf"}
#
# Output schema per page (all providers):
#   {
#     "page_num":  int,           # 1-indexed
#     "markdown":  str,
#     "images":    list,          # non-empty only for Mistral
#     "tables":    list,          # non-empty only for Mistral
#     "header":    str | None,    # non-None only for Mistral
#     "footer":    str | None,    # non-None only for Mistral
#     "width":     float,
#     "height":    float,
#   }
#
# Vault secrets:
#   Mistral API key: kv/data/providers/mistral_ai       →  "api_key"
#   Gemini API key:  kv/data/providers/google_ai_studio →  "api_key"

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Gemini page-break sentinel — unique enough that Gemini is unlikely to emit it
# as part of actual document content.
_GEMINI_PAGE_BREAK = "---PAGE_BREAK---"


# ---------------------------------------------------------------------------
# Vault helpers
# ---------------------------------------------------------------------------


async def _get_mistral_api_key(secrets_manager: Any) -> str:
    """Fetch the Mistral AI API key from Vault."""
    try:
        key = await secrets_manager.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not key:
            raise RuntimeError("Mistral API key is empty in Vault")
        return key
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve Mistral API key from Vault: {e}") from e


async def _get_gemini_api_key(secrets_manager: Any) -> Optional[str]:
    """
    Fetch the Google AI Studio (Gemini API) key from Vault.

    Returns None if the key is unavailable — callers should treat a None key
    as a signal to skip this provider rather than crash.
    """
    try:
        key = await secrets_manager.get_secret(
            "kv/data/providers/google_ai_studio", "api_key"
        )
        return key if key else None
    except Exception as e:
        logger.warning(f"Could not retrieve Google AI Studio API key: {e}")
        return None


# ---------------------------------------------------------------------------
# Provider 1: Mistral OCR
# ---------------------------------------------------------------------------


async def _run_mistral_ocr(
    pdf_bytes: bytes,
    secrets_manager: Any,
    log_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Call the Mistral OCR API and return per-page results.

    Raises RuntimeError on any API-level or network failure — the caller
    (run_ocr_with_fallback) catches this and moves on to the next provider.
    """
    api_key = await _get_mistral_api_key(secrets_manager)

    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    document_url = f"data:application/pdf;base64,{pdf_b64}"

    logger.info(f"{log_prefix} [Mistral] Submitting {len(pdf_bytes)} bytes to Mistral OCR")

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
    logger.info(f"{log_prefix} [Mistral] Returned {len(raw_pages)} pages")

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

        # Mistral OCR returns header/footer as plain strings (str|null).
        # Earlier API versions returned dicts with a "markdown" key — handle
        # both formats defensively so the code survives future API changes.
        raw_header = page.get("header")
        if isinstance(raw_header, dict):
            header_text = raw_header.get("markdown")
        elif isinstance(raw_header, str):
            header_text = raw_header
        else:
            header_text = None

        raw_footer = page.get("footer")
        if isinstance(raw_footer, dict):
            footer_text = raw_footer.get("markdown")
        elif isinstance(raw_footer, str):
            footer_text = raw_footer
        else:
            footer_text = None

        pages.append(
            {
                "page_num": page_num,
                "markdown": page.get("markdown", ""),
                "images": images,
                "tables": page.get("tables", []),
                "header": header_text,
                "footer": footer_text,
                "width": dims.get("width", 0.0),
                "height": dims.get("height", 0.0),
            }
        )

    return pages


# ---------------------------------------------------------------------------
# Provider 2: Gemini Flash (Google AI Studio)
# ---------------------------------------------------------------------------


async def _run_gemini_ocr(
    pdf_bytes: bytes,
    secrets_manager: Any,
    log_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Call Gemini Flash via the Google AI Studio API and return per-page results.

    The PDF is sent as inline base64 bytes. Gemini is prompted to emit markdown
    with a page-break sentinel between pages; the response is then split into
    per-page entries with the same schema as Mistral output (images=[], tables=[]).

    The google-genai SDK is synchronous, so the API call is offloaded to a thread
    via asyncio.to_thread() to avoid blocking the event loop.

    Raises RuntimeError on any API-level or network failure.
    """
    # google-genai SDK is already installed in app-pdf-worker via
    # backend/core/api/requirements.txt (google-genai==1.58.0).
    try:
        from google import genai  # type: ignore[import]
        from google.genai import types as genai_types  # type: ignore[import]
    except ImportError as e:
        raise RuntimeError(
            f"google-genai package not available in this environment: {e}"
        ) from e

    api_key = await _get_gemini_api_key(secrets_manager)
    if not api_key:
        raise RuntimeError(
            "Google AI Studio API key is not configured — cannot use Gemini OCR fallback"
        )

    logger.info(
        f"{log_prefix} [Gemini] Submitting {len(pdf_bytes)} bytes to gemini-3-flash-preview"
    )

    prompt = (
        "You are an OCR engine. Extract all text from this PDF document and return it "
        "as markdown. Preserve structure: use # for headings, ** for bold, tables in "
        "markdown format, and code blocks where appropriate.\n\n"
        f"IMPORTANT: You MUST separate each page with exactly this marker on its own line:\n"
        f"{_GEMINI_PAGE_BREAK}\n\n"
        "Start directly with the content of page 1 (no preamble). "
        "Do not include any commentary — only the document content with the page markers."
    )

    # Run the synchronous Gemini SDK call in a thread so we don't block the
    # async Celery event loop. Timeout is enforced via asyncio.wait_for.
    def _call_gemini() -> str:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                genai_types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                ),
                prompt,
            ],
        )
        return response.text or ""

    try:
        raw_text: str = await asyncio.wait_for(
            asyncio.to_thread(_call_gemini),
            timeout=300.0,
        )
    except asyncio.TimeoutError as e:
        raise RuntimeError("Gemini OCR timed out after 300 s") from e

    # Split on the page-break sentinel
    page_chunks = raw_text.split(_GEMINI_PAGE_BREAK)

    pages: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(page_chunks):
        stripped = chunk.strip()
        if not stripped and idx == 0:
            # Gemini sometimes emits a blank section before the first page — skip it
            continue
        pages.append(
            {
                "page_num": len(pages) + 1,  # 1-indexed, sequential
                "markdown": stripped,
                "images": [],
                "tables": [],
                "header": None,
                "footer": None,
                "width": 0.0,
                "height": 0.0,
            }
        )

    if not pages:
        # Fallback: Gemini returned text but no page markers — treat as single page
        if raw_text.strip():
            pages.append(
                {
                    "page_num": 1,
                    "markdown": raw_text.strip(),
                    "images": [],
                    "tables": [],
                    "header": None,
                    "footer": None,
                    "width": 0.0,
                    "height": 0.0,
                }
            )
        else:
            raise RuntimeError("Gemini OCR returned empty text")

    logger.info(f"{log_prefix} [Gemini] Extracted {len(pages)} pages")
    return pages


# ---------------------------------------------------------------------------
# Provider 3: pymupdf text extraction (last resort — never fails)
# ---------------------------------------------------------------------------


def _run_pymupdf_ocr_sync(
    pdf_bytes: bytes,
    log_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Extract text from PDF using PyMuPDF (fitz) — runs synchronously.

    This is the last-resort provider. It works well for native/digital PDFs
    (those with an embedded text layer). For scanned PDFs without a text layer,
    pages will have empty or minimal markdown — better than failing completely.

    PyMuPDF (pymupdf) is already installed in the app-pdf-worker container.
    This function is designed to never raise: any per-page error results in
    an empty markdown entry so the pipeline can continue.
    """
    import fitz  # type: ignore[import]  # pymupdf

    logger.info(
        f"{log_prefix} [pymupdf] Extracting text from {len(pdf_bytes)} bytes via PyMuPDF"
    )

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"{log_prefix} [pymupdf] Failed to open PDF: {e}")
        # Return a single empty page so the pipeline has something to work with
        return [
            {
                "page_num": 1,
                "markdown": "",
                "images": [],
                "tables": [],
                "header": None,
                "footer": None,
                "width": 0.0,
                "height": 0.0,
            }
        ]

    pages: List[Dict[str, Any]] = []
    for page_idx in range(len(doc)):
        try:
            page = doc[page_idx]
            # get_text("markdown") returns text with basic formatting hints.
            # Falls back to plain text for pages without layout information.
            markdown_text = page.get_text("markdown") or ""
            rect = page.rect
            pages.append(
                {
                    "page_num": page_idx + 1,
                    "markdown": markdown_text.strip(),
                    "images": [],
                    "tables": [],
                    "header": None,
                    "footer": None,
                    "width": float(rect.width),
                    "height": float(rect.height),
                }
            )
        except Exception as e:
            logger.warning(
                f"{log_prefix} [pymupdf] Error extracting page {page_idx + 1}: {e}"
            )
            pages.append(
                {
                    "page_num": page_idx + 1,
                    "markdown": "",
                    "images": [],
                    "tables": [],
                    "header": None,
                    "footer": None,
                    "width": 0.0,
                    "height": 0.0,
                }
            )

    doc.close()

    if not pages:
        # Edge case: empty PDF
        pages = [
            {
                "page_num": 1,
                "markdown": "",
                "images": [],
                "tables": [],
                "header": None,
                "footer": None,
                "width": 0.0,
                "height": 0.0,
            }
        ]

    logger.info(f"{log_prefix} [pymupdf] Extracted {len(pages)} pages")
    return pages


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_ocr_with_fallback(
    pdf_bytes: bytes,
    secrets_manager: Any,
    log_prefix: str = "[OCR]",
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Run OCR on raw PDF bytes using a three-provider fallback chain.

    Tries providers in order: Mistral → Gemini Flash → pymupdf.
    Each failed provider is logged as a warning and skipped; the pymupdf
    provider is the final safety net and will always produce a result.

    Args:
        pdf_bytes:       Raw (decrypted) PDF bytes.
        secrets_manager: Initialised SecretsManager for Vault access.
        log_prefix:      Logging prefix for traceability.

    Returns:
        A tuple of (pages, provider_name) where:
          - pages: List of per-page dicts (see module docstring for schema)
          - provider_name: one of "mistral", "gemini_flash", "pymupdf"

    The function never raises: if all external providers fail, pymupdf is
    always used as the last resort.
    """
    # ------------------------------------------------------------------
    # Provider 1: Mistral OCR
    # ------------------------------------------------------------------
    try:
        pages = await _run_mistral_ocr(pdf_bytes, secrets_manager, log_prefix)
        logger.info(f"{log_prefix} OCR succeeded via Mistral ({len(pages)} pages)")
        return pages, "mistral"
    except Exception as exc:
        logger.warning(
            f"{log_prefix} Mistral OCR failed — falling back to Gemini Flash. "
            f"Error: {exc}"
        )

    # ------------------------------------------------------------------
    # Provider 2: Gemini Flash (Google AI Studio)
    # ------------------------------------------------------------------
    try:
        pages = await _run_gemini_ocr(pdf_bytes, secrets_manager, log_prefix)
        logger.info(
            f"{log_prefix} OCR succeeded via Gemini Flash ({len(pages)} pages)"
        )
        return pages, "gemini_flash"
    except Exception as exc:
        logger.warning(
            f"{log_prefix} Gemini Flash OCR failed — falling back to pymupdf. "
            f"Error: {exc}"
        )

    # ------------------------------------------------------------------
    # Provider 3: pymupdf (last resort — never raises)
    # ------------------------------------------------------------------
    pages = await asyncio.to_thread(_run_pymupdf_ocr_sync, pdf_bytes, log_prefix)
    logger.info(
        f"{log_prefix} OCR completed via pymupdf text extraction ({len(pages)} pages)"
    )
    return pages, "pymupdf"


# ---------------------------------------------------------------------------
# Legacy compatibility shim
# ---------------------------------------------------------------------------


async def run_mistral_ocr(
    pdf_bytes: bytes,
    secrets_manager: Any,
    log_prefix: str = "[OCR]",
) -> List[Dict[str, Any]]:
    """
    Deprecated shim: calls _run_mistral_ocr directly (no fallback).

    Kept for backward compatibility in case any other module imports this
    function by name. New code should use run_ocr_with_fallback() instead.
    """
    return await _run_mistral_ocr(pdf_bytes, secrets_manager, log_prefix)
