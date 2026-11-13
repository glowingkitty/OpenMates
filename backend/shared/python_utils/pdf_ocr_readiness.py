# backend/shared/python_utils/pdf_ocr_readiness.py
#
# Shared by the pdf.read, pdf.search and pdf.view skills.
#
# A PDF embed is created at upload time, but its OCR text, page screenshots and
# wrapped artefact keys are only written once the Celery task apps.pdf.tasks.
# process_pdf finishes. The assistant starts answering as soon as the message is
# sent, so its first PDF skill call regularly runs while OCR is still working.
# Without a wait the skill fails with "PDF embed cache missing ocr_data_s3_key"
# and the user gets no answer about their document. This module polls the same
# cached embed until it is ready, reports a processing failure straight away and
# gives up with an actionable message when OCR outlasts the skill budget.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

# Leaves headroom under the skill timeout (see get_skill_timeout for pdf skills).
PDF_OCR_MAX_WAIT_SECONDS = 150.0
PDF_OCR_POLL_INTERVAL_SECONDS = 2.0


class PdfNotReadyError(RuntimeError):
    """The PDF is still being processed; the user can ask again shortly."""


class PdfProcessingFailedError(RuntimeError):
    """The PDF processing task ended in an error state."""


def _is_ready(content: Dict[str, Any], required_fields: Sequence[str]) -> bool:
    return all(bool(content.get(field)) for field in required_fields)


async def wait_for_pdf_artefacts(
    lookup: Callable[[], Awaitable[Dict[str, Any]]],
    required_fields: Sequence[str],
    *,
    initial: Optional[Dict[str, Any]] = None,
    log_prefix: str = "[pdf]",
    max_wait_seconds: float = PDF_OCR_MAX_WAIT_SECONDS,
    poll_interval_seconds: float = PDF_OCR_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Return the cached PDF embed content once every required field is present.

    ``lookup`` re-reads and decrypts the embed. ``initial`` is content the caller
    already read, so a PDF that is ready costs no extra lookup.

    Raises:
        PdfProcessingFailedError: the embed carries status "error".
        PdfNotReadyError: the fields are still missing after ``max_wait_seconds``.
    """
    started = monotonic()
    content = initial if initial is not None else await lookup()
    announced = False
    while True:
        if content.get("status") == "error":
            raise PdfProcessingFailedError(
                content.get("error") or "PDF processing failed. Please upload the PDF again."
            )
        if _is_ready(content, required_fields):
            if announced:
                logger.info("%s PDF processing finished after %.1fs", log_prefix, monotonic() - started)
            return content
        waited = monotonic() - started
        if waited >= max_wait_seconds:
            page_count = content.get("page_count")
            pages = f" ({page_count} pages)" if page_count else ""
            raise PdfNotReadyError(
                f"The PDF{pages} is still being processed (text recognition takes longer for "
                "large documents). Tell the user it is not ready yet and to ask again in a minute."
            )
        if not announced:
            logger.info("%s PDF still processing, waiting up to %.0fs", log_prefix, max_wait_seconds)
            announced = True
        await sleep(min(poll_interval_seconds, max_wait_seconds - waited))
        content = await lookup()
