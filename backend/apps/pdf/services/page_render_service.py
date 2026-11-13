# backend/apps/pdf/services/page_render_service.py
#
# On-demand page renders for PDF processing v2 (assertion view.on-demand-render).
#
# Only the page-1 preview is rendered during processing. Any other page is rendered when
# pdf.view (or a user opening the page) needs it: render from the original PDF at a
# resolution suitable for small print, judge the render with the Jev image decision, encrypt it
# with the embed's output key, store it and remember the S3 key in the embed so the next request
# reuses it. Pages nobody views are never rendered or scanned.
#
# Storage and key handling are injected as callables so the pdf.view skill and the first-party
# page route share one implementation.

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Literal, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.pdf.services.screenshot_service import ON_DEMAND_DPI, render_selected_pages

logger = logging.getLogger(__name__)

PageStatus = Literal["ok", "withheld", "rejected", "unavailable"]


@dataclass
class PageRender:
    page_number: int
    status: PageStatus
    png: Optional[bytes] = None
    s3_key: Optional[str] = None


UnwrapKey = Callable[[str], Awaitable[bytes]]
Download = Callable[[str], Awaitable[bytes]]
Upload = Callable[[str, bytes], Awaitable[None]]
RecordKey = Callable[[int, str], Awaitable[None]]


def _decrypt_blob(aesgcm: AESGCM, blob: bytes) -> bytes:
    return aesgcm.decrypt(blob[:12], blob[12:], None)


async def get_page_render(
    *,
    embed_content: Dict[str, Any],
    page_number: int,
    unwrap_key: UnwrapKey,
    download: Download,
    upload: Upload,
    record_key: RecordKey,
    secrets_manager: Any,
    user_id: str,
    embed_id: str,
    log_prefix: str = "[pdf.render]",
) -> PageRender:
    """Return the decrypted PNG for one page, rendering and judging it first if needed."""
    from backend.apps.pdf.services.pdf_safety import judge_images

    output_key = await unwrap_key(embed_content["vault_wrapped_aes_key"])
    output_aesgcm = AESGCM(output_key)
    existing: Dict[str, str] = embed_content.get("screenshot_s3_keys") or {}
    if str(page_number) in existing:
        png = _decrypt_blob(output_aesgcm, await download(existing[str(page_number)]))
        return PageRender(page_number, "ok", png, existing[str(page_number)])

    original_key = embed_content.get("original_s3_key")
    original_wrapped = embed_content.get("original_vault_wrapped_aes_key")
    original_nonce = embed_content.get("original_aes_nonce")
    if not (original_key and original_wrapped and original_nonce):
        logger.warning("%s page %d has no stored render and the original PDF is not recorded", log_prefix, page_number)
        return PageRender(page_number, "unavailable")

    import base64

    original_aes = AESGCM(await unwrap_key(original_wrapped))
    pdf_bytes = original_aes.decrypt(base64.b64decode(original_nonce), await download(original_key), None)
    rendered = await asyncio.to_thread(render_selected_pages, pdf_bytes, [page_number], ON_DEMAND_DPI, log_prefix)
    png = rendered[page_number]

    decisions = await judge_images({f"page_{page_number}": png}, secrets_manager, log_prefix=log_prefix)
    decision = decisions[f"page_{page_number}"]
    if decision.outcome == "pdf_rejected":
        return PageRender(page_number, "rejected")
    if decision.outcome != "allowed":
        return PageRender(page_number, "withheld")

    nonce = os.urandom(12)
    s3_key = f"chatfiles/{user_id}/{uuid.uuid4().hex[:8]}_pdf_{embed_id[:8]}_p{page_number}.png.bin"
    await upload(s3_key, nonce + output_aesgcm.encrypt(nonce, png, None))
    await record_key(page_number, s3_key)
    return PageRender(page_number, "ok", png, s3_key)
