# backend/apps/pdf/services/ocr_chunks.py
#
# Parallel, chunked OCR for the pages that triage routed to OCR (PDF processing v2).
#
# Pages needing OCR are cut into sub-PDFs of at most OCR_CHUNK_PAGES pages and
# processed concurrently. A failed chunk is retried and then falls back to the
# secondary OCR provider on its own; other chunks are never repeated. A page
# that still has no text gets an explicit unreadable marker, never an empty string.
#
# See specifications/features/pdf-processing (assertion ocr.parallel-chunks).

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Sequence, Tuple

from backend.apps.pdf.services.ocr_service import (
    _run_gemini_ocr,
    _run_mistral_ocr,
    sanitize_ocr_pages_for_ascii_smuggling,
)

logger = logging.getLogger(__name__)

OCR_CHUNK_PAGES = 20
OCR_CHUNK_CONCURRENCY = 6
MISTRAL_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 2.0

UNREADABLE_MARKER = "[This page could not be read: text recognition returned no text for it.]"


def chunk_pages(pages: Sequence[int], size: int = OCR_CHUNK_PAGES) -> List[List[int]]:
    """Split sorted page numbers into consecutive chunks of at most ``size`` pages."""
    ordered = sorted(set(pages))
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


def _extract_sub_pdf(pdf_bytes: bytes, page_numbers: Sequence[int]) -> bytes:
    import fitz  # type: ignore[import]  # pymupdf

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    target = fitz.open()
    try:
        for page_number in page_numbers:
            target.insert_pdf(source, from_page=page_number - 1, to_page=page_number - 1)
        return target.tobytes(garbage=3, deflate=True)
    finally:
        target.close()
        source.close()


def _unreadable_page(page_number: int) -> Dict[str, Any]:
    return {
        "page_num": page_number,
        "markdown": UNREADABLE_MARKER,
        "images": [],
        "tables": [],
        "header": None,
        "footer": None,
        "width": 0.0,
        "height": 0.0,
        "ocr_provider": None,
        "unreadable": True,
    }


def _remap(chunk_pages_in_order: Sequence[int], ocr_pages: List[Dict[str, Any]], provider: str) -> List[Dict[str, Any]]:
    """Map sub-PDF page numbers (1..n) back to the original page numbers."""
    by_index = {p["page_num"]: p for p in ocr_pages}
    remapped: List[Dict[str, Any]] = []
    for position, original in enumerate(chunk_pages_in_order, start=1):
        page = by_index.get(position)
        if page is None or not (page.get("markdown") or "").strip():
            remapped.append(_unreadable_page(original))
            continue
        page = dict(page)
        page["page_num"] = original
        page["ocr_provider"] = provider
        page["unreadable"] = False
        remapped.append(page)
    return remapped


async def _ocr_chunk(
    pdf_bytes: bytes,
    page_numbers: List[int],
    secrets_manager: Any,
    log_prefix: str,
) -> Tuple[List[Dict[str, Any]], str]:
    sub_pdf = await asyncio.to_thread(_extract_sub_pdf, pdf_bytes, page_numbers)
    label = f"{log_prefix} [chunk {page_numbers[0]}-{page_numbers[-1]}]"
    for attempt in range(1, MISTRAL_ATTEMPTS + 1):
        try:
            pages = await _run_mistral_ocr(sub_pdf, secrets_manager, label, include_image_base64=False)
            return _remap(page_numbers, pages, "mistral"), "mistral"
        except RuntimeError as exc:
            logger.warning("%s Mistral attempt %d/%d failed: %s", label, attempt, MISTRAL_ATTEMPTS, exc)
            if attempt < MISTRAL_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
    try:
        pages = await _run_gemini_ocr(sub_pdf, secrets_manager, label)
        return _remap(page_numbers, pages, "gemini_flash"), "gemini_flash"
    except RuntimeError as exc:
        logger.error("%s Gemini fallback failed too: %s", label, exc)
    return [_unreadable_page(n) for n in page_numbers], "none"


async def run_chunked_ocr(
    pdf_bytes: bytes,
    page_numbers: Sequence[int],
    secrets_manager: Any,
    log_prefix: str = "[pdf.ocr]",
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, int]]:
    """OCR ``page_numbers`` (1-based, original document) in parallel chunks.

    Returns ``(pages_by_number, provider_page_counts)``. Every requested page is present;
    pages OCR could not read carry the unreadable marker (``unreadable=True``).
    """
    chunks = chunk_pages(page_numbers)
    if not chunks:
        return {}, {}
    semaphore = asyncio.Semaphore(OCR_CHUNK_CONCURRENCY)

    async def _run(chunk: List[int]) -> Tuple[List[Dict[str, Any]], str]:
        async with semaphore:
            return await _ocr_chunk(pdf_bytes, chunk, secrets_manager, log_prefix)

    outcomes = await asyncio.gather(*(_run(c) for c in chunks))
    pages: Dict[int, Dict[str, Any]] = {}
    providers: Dict[str, int] = {}
    for chunk_pages_out, provider in outcomes:
        sanitized = sanitize_ocr_pages_for_ascii_smuggling(chunk_pages_out, log_prefix=f"{log_prefix} [post-ocr] ")
        for page in sanitized:
            pages[page["page_num"]] = page
            providers[provider] = providers.get(provider, 0) + 1
    logger.info("%s OCR finished: %d pages in %d chunks via %s", log_prefix, len(pages), len(chunks), providers)
    return pages, providers
