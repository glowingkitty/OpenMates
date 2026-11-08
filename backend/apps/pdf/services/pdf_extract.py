# backend/apps/pdf/services/pdf_extract.py
#
# pymupdf extraction helpers for PDF processing v2: the embedded text layer as
# markdown and the unique embedded images. Synchronous and CPU-bound; call via
# asyncio.to_thread().

from __future__ import annotations

import hashlib
import logging
from typing import Dict, Sequence, Tuple

logger = logging.getLogger(__name__)

MIN_IMAGE_SIDE_PX = 80
MIN_IMAGE_BYTES = 2048
MAX_UNIQUE_IMAGES = 60


def extract_text_layer_markdown(pdf_bytes: bytes, page_numbers: Sequence[int]) -> Dict[int, str]:
    """Embedded text layer (reading order) for the given 1-based pages; pymupdf has no markdown mode."""
    import fitz  # type: ignore[import]  # pymupdf

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        texts: Dict[int, str] = {}
        for number in page_numbers:
            page = doc[number - 1]
            texts[number] = (page.get_text("text", sort=True) or "").strip()
        return texts
    finally:
        doc.close()


def extract_unique_images(pdf_bytes: bytes, max_images: int = MAX_UNIQUE_IMAGES) -> Dict[str, Tuple[int, bytes]]:
    """Unique embedded images, keyed ``p<page>_img<n>`` -> (page_number, bytes).

    Identical images (logos repeated on every page) are returned once, tiny images are skipped
    and the largest ``max_images`` are kept.
    """
    import fitz  # type: ignore[import]  # pymupdf

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        seen: Dict[str, Tuple[int, int, bytes]] = {}
        for index in range(len(doc)):
            for img in doc[index].get_images(full=True):
                xref = img[0]
                try:
                    extracted = doc.extract_image(xref)
                except (RuntimeError, ValueError) as exc:
                    logger.info("[pdf.extract] image xref %s on page %d unreadable: %s", xref, index + 1, exc)
                    continue
                data = extracted.get("image") or b""
                if (
                    len(data) < MIN_IMAGE_BYTES
                    or extracted.get("width", 0) < MIN_IMAGE_SIDE_PX
                    or extracted.get("height", 0) < MIN_IMAGE_SIDE_PX
                ):
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if digest not in seen:
                    seen[digest] = (index + 1, extracted["width"] * extracted["height"], data)
        largest = sorted(seen.values(), key=lambda item: item[1], reverse=True)[:max_images]
        per_page: Dict[int, int] = {}
        result: Dict[str, Tuple[int, bytes]] = {}
        for page_number, _area, data in sorted(largest, key=lambda item: item[0]):
            n = per_page.get(page_number, 0)
            per_page[page_number] = n + 1
            result[f"p{page_number}_img{n}"] = (page_number, data)
        return result
    finally:
        doc.close()
