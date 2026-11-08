# backend/apps/pdf/services/screenshot_service.py
#
# Screenshot service: renders each PDF page to a PNG image at 150 DPI using
# pymupdf (fitz). The resulting bytes are then encrypted and uploaded to S3
# by the process_task.
#
# Architecture:
#   - Runs synchronously inside asyncio.to_thread() to avoid blocking the
#     Celery worker's async event loop.
#   - 150 DPI is a good balance between quality (readable text/diagrams) and
#     file size (vision AI calls shouldn't receive huge images).
#   - Output format: PNG bytes for each page.

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# DPI for page rendering
SCREENSHOT_DPI = 150


def render_pdf_pages(pdf_bytes: bytes, log_prefix: str = "[Screenshot]") -> Dict[int, bytes]:
    """
    Render all pages of a PDF to PNG images at SCREENSHOT_DPI.

    This function is CPU-bound and should be called via asyncio.to_thread().

    Args:
        pdf_bytes: Raw (decrypted) PDF bytes.
        log_prefix: Logging prefix for traceability.

    Returns:
        Dict mapping 1-indexed page number → PNG bytes.

    Raises:
        ImportError: If pymupdf is not installed.
        RuntimeError: If PDF cannot be opened or rendered.
    """
    try:
        import fitz  # type: ignore[import]  # pymupdf
    except ImportError as e:
        raise ImportError("pymupdf (fitz) is not installed — cannot render PDF pages") from e

    logger.info(f"{log_prefix} Opening PDF for rendering ({len(pdf_bytes)} bytes)")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF for rendering: {e}") from e

    # Zoom factor to achieve the desired DPI (fitz default is 72 DPI)
    zoom = SCREENSHOT_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    pages: Dict[int, bytes] = {}
    page_count = len(doc)
    logger.info(f"{log_prefix} Rendering {page_count} pages at {SCREENSHOT_DPI} DPI")

    for page_index in range(page_count):
        page = doc[page_index]
        page_num = page_index + 1  # 1-indexed

        try:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            pages[page_num] = png_bytes
            logger.debug(f"{log_prefix} Page {page_num} rendered: {len(png_bytes)} bytes")
        except Exception as e:
            logger.error(f"{log_prefix} Failed to render page {page_num}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to render page {page_num}: {e}") from e

    doc.close()
    logger.info(f"{log_prefix} All {page_count} pages rendered successfully")
    return pages


# DPI for on-demand renders that a vision model or a user reads (small print).
ON_DEMAND_DPI = 200
# DPI for pages rendered only to be safety-judged (scanned pages).
SAFETY_JUDGE_DPI = 110


def render_selected_pages(
    pdf_bytes: bytes,
    page_numbers: "list[int]",
    dpi: int = ON_DEMAND_DPI,
    log_prefix: str = "[Screenshot]",
) -> Dict[int, bytes]:
    """Render only ``page_numbers`` (1-based) to PNG. CPU-bound: call via asyncio.to_thread().

    Raises RuntimeError for an unreadable PDF or an out-of-range page.
    """
    import fitz  # type: ignore[import]  # pymupdf

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF for rendering: {e}") from e
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        rendered: Dict[int, bytes] = {}
        for page_number in sorted(set(page_numbers)):
            if not 1 <= page_number <= len(doc):
                raise RuntimeError(f"Page {page_number} is outside the document ({len(doc)} pages)")
            rendered[page_number] = doc[page_number - 1].get_pixmap(matrix=matrix, alpha=False).tobytes("png")
        logger.info(f"{log_prefix} Rendered {len(rendered)} page(s) at {dpi} DPI")
        return rendered
    finally:
        doc.close()
