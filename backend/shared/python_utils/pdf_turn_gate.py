# backend/shared/python_utils/pdf_turn_gate.py
#
# Hold an AI turn until every PDF it can refer to has finished processing.
#
# Spec: feature.pdf-processing, assertion readiness.complete-before-answer. The
# assistant must never answer about a PDF from general knowledge or from a partly
# processed document. The AI worker calls wait_for_pdfs_final() before it builds the
# request; a PDF that failed ends the turn with PdfProcessingFailedForTurn (the PDF
# embed shows the failure and the refund, the assistant gives no answer).

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

# The AI task has a 300 s soft time limit; the hold must end before it so the turn fails cleanly.
PDF_TURN_MAX_WAIT_SECONDS = 240.0
PDF_TURN_POLL_SECONDS = 2.0

_FINAL_STATUSES = {"finished", "error", "cancelled"}


class PdfProcessingFailedForTurn(RuntimeError):
    """A PDF attached to this chat failed or was cancelled; the turn must not be answered."""


class PdfProcessingTimedOutForTurn(RuntimeError):
    """A PDF was still processing after the maximum hold; the turn must not be answered."""


async def _is_pdf(embed_data: dict, encryption_service: Any, vault_key_id: str) -> bool:
    from toon_format import decode as toon_decode  # type: ignore[import]

    encrypted = embed_data.get("encrypted_content")
    if not encrypted or not vault_key_id:
        return False
    plaintext = await encryption_service.decrypt_with_user_key(encrypted, vault_key_id)
    if not plaintext:
        return False
    try:
        decoded = toon_decode(plaintext)
    except ValueError:
        return False
    return isinstance(decoded, dict) and decoded.get("type") == "pdf"


async def wait_for_pdfs_final(
    *,
    cache_service: Any,
    encryption_service: Any,
    user_id: str,
    embed_ids: Iterable[str],
    current_turn_embed_ids: Iterable[str] = (),
    log_prefix: str = "[pdf.gate]",
    max_wait_seconds: float = PDF_TURN_MAX_WAIT_SECONDS,
    poll_seconds: float = PDF_TURN_POLL_SECONDS,
    on_waiting: Optional[Callable[[List[str]], Awaitable[None]]] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> List[str]:
    """Wait until every PDF among ``embed_ids`` is final. Returns the PDF embed ids that were checked.

    Raises PdfProcessingFailedForTurn / PdfProcessingTimedOutForTurn; never returns while a PDF is
    still processing.
    """
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    pdf_ids: List[str] = []
    non_pdf: set[str] = set()
    started = monotonic()
    announced = False
    pending = list(dict.fromkeys(embed_ids))
    current_turn = set(current_turn_embed_ids)
    while True:
        waiting: List[str] = []
        for embed_id in pending:
            if embed_id in non_pdf:
                continue
            embed_data = await cache_service.get_embed_from_cache(embed_id)
            if not embed_data:
                non_pdf.add(embed_id)  # not cached → nothing to hold on (resolved elsewhere)
                continue
            status = embed_data.get("status")
            if status == "finished":
                non_pdf.add(embed_id)  # nothing to hold on, whatever the embed type
                continue
            if status in ("error", "cancelled") and embed_id not in current_turn:
                non_pdf.add(embed_id)  # an earlier failed PDF must not block unrelated turns
                continue
            if embed_id not in pdf_ids:
                if not await _is_pdf(embed_data, encryption_service, vault_key_id):
                    non_pdf.add(embed_id)
                    continue
                pdf_ids.append(embed_id)
            if status in ("error", "cancelled"):
                raise PdfProcessingFailedForTurn(f"PDF embed {embed_id} ended with status {status}")
            if status not in _FINAL_STATUSES:
                waiting.append(embed_id)
        if not waiting:
            if announced:
                logger.info("%s PDFs final after %.1fs", log_prefix, monotonic() - started)
            return pdf_ids
        waited = monotonic() - started
        if waited >= max_wait_seconds:
            raise PdfProcessingTimedOutForTurn(f"{len(waiting)} PDF(s) still processing after {waited:.0f}s")
        if not announced:
            logger.info("%s Holding turn: %d PDF(s) still processing", log_prefix, len(waiting))
            announced = True
            if on_waiting is not None:
                await on_waiting(waiting)
        await sleep(min(poll_seconds, max_wait_seconds - waited))
        pending = waiting
