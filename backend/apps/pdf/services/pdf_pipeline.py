# backend/apps/pdf/services/pdf_pipeline.py
#
# PDF processing v2 pipeline (artefact building). Orchestrated by tasks/process_task.py,
# which owns download, key wrapping, retries, billing refunds and embed delivery.
#
#   1. Triage every page (text layer vs OCR; borderline pages decided by Jev).
#   2. In parallel: text-layer markdown, chunked OCR for scanned pages, unique image extraction.
#   3. In parallel: Jev prompt-injection scores for every page, Jev image decisions for
#      extracted images / scanned pages / the page-1 preview, and the table of contents.
#   4. Encrypt and store allowed artefacts and the page blob.
#
# The embed is only reported "finished" by the caller after this function returns, i.e. after
# every page is final. The assistant is held until then (spec: readiness.complete-before-answer).
# No screenshots are rendered here except the page-1 preview; other pages render on demand.

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.pdf.services.ocr_chunks import run_chunked_ocr
from backend.apps.pdf.services.pdf_extract import extract_text_layer_markdown, extract_unique_images
from backend.apps.pdf.services.pdf_triage import (
    JevDecider,
    TriageResult,
    jev_text_layer_is_complete,
    price_for,
    resolve_borderline_pages,
    triage_pages_sync,
)
from backend.apps.pdf.services.screenshot_service import (
    SAFETY_JUDGE_DPI,
    SCREENSHOT_DPI,
    render_selected_pages,
)
from backend.apps.pdf.services.toc_detector import (
    detect_legend,
    detect_toc,
    find_toc_candidate_pages,
    toc_from_outline,
)

logger = logging.getLogger(__name__)

PDF_S3_BUCKET = "chatfiles"
WHOLE_DOCUMENT_TOKEN_LIMIT = 30_000
TOC_TIMEOUT_SECONDS = 40.0


class PdfRejectedError(RuntimeError):
    """An image was clearly unsafe: the whole PDF is rejected and must not be retried."""


@dataclass
class PipelineOutput:
    embed_fields: Dict[str, Any]
    total_tokens: int
    unreadable_pages: List[int] = field(default_factory=list)
    price_credits: int = 0


def _apply_routes(triage: TriageResult, routes: Optional[List[Dict[str, Any]]]) -> bool:
    """Reuse the routes decided (and priced) at upload time. Returns False if they do not fit."""
    if not routes or len(routes) != triage.page_count:
        return False
    by_number = {r.get("page_number"): r for r in routes}
    if set(by_number) != {p.page_number for p in triage.pages}:
        return False
    for page in triage.pages:
        route = by_number[page.page_number]
        if route.get("route") not in ("text_layer", "ocr"):
            return False
        page.route = route["route"]
        page.decided_by = route.get("decided_by") or "rules"
        # Borderline pages were billed as OCR at upload; the decision model still decides them here.
        page.borderline = bool(route.get("borderline"))
    return True


async def _encrypt_upload(
    s3_service: Any, aesgcm: AESGCM, data: bytes, s3_key: str, created: List[str]
) -> str:
    # A fresh 96-bit nonce per artefact, prepended to the ciphertext (see docs/architecture/pdf-encryption.md).
    nonce = os.urandom(12)
    await s3_service.upload_file(
        bucket_key=PDF_S3_BUCKET,
        file_key=s3_key,
        content=nonce + aesgcm.encrypt(nonce, data, None),
        content_type="application/octet-stream",
    )
    created.append(s3_key)
    return s3_key


async def _table_of_contents(
    pages: List[Dict[str, Any]], outline: List[List[Any]], secrets_manager: Any, log_prefix: str
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    empty_legend = {"detected": False, "source_pages": [], "content": "", "chapters": []}
    outline_toc = toc_from_outline(outline) if outline else None
    legend_coro = (
        detect_legend(pages, secrets_manager, log_prefix) if len(pages) >= 10 else asyncio.sleep(0, empty_legend)
    )
    if outline_toc and outline_toc["detected"]:
        return outline_toc, await legend_coro
    candidates = await find_toc_candidate_pages(pages, secrets_manager, log_prefix)
    toc, legend = await asyncio.gather(
        detect_toc(pages, secrets_manager, log_prefix, candidate_pages=candidates), legend_coro
    )
    return toc, legend


async def run_pipeline(
    *,
    pdf_bytes: bytes,
    secrets_manager: Any,
    s3_service: Any,
    output_aesgcm: AESGCM,
    user_id: str,
    embed_id: str,
    page_routes: Optional[List[Dict[str, Any]]],
    created_s3_keys: List[str],
    log_prefix: str,
) -> PipelineOutput:
    from backend.apps.pdf.services.pdf_safety import judge_images, score_pages_injection

    # 1. Triage (reuse upload-time routes when they fit this document).
    triage = await asyncio.to_thread(triage_pages_sync, pdf_bytes)
    _apply_routes(triage, page_routes)

    async def _decider(page: Any) -> Optional[bool]:
        return await jev_text_layer_is_complete(page, secrets_manager)

    decider: JevDecider = _decider
    await resolve_borderline_pages(triage, decider)
    text_pages, ocr_pages = triage.text_layer_pages, triage.ocr_pages
    price = price_for(len(ocr_pages))
    logger.info("%s Triage: %d text-layer, %d OCR pages (price %d credits)",
                log_prefix, len(text_pages), len(ocr_pages), price.credits)

    # 2. Text, OCR and image extraction in parallel.
    text_task = asyncio.to_thread(extract_text_layer_markdown, pdf_bytes, text_pages)
    images_task = asyncio.to_thread(extract_unique_images, pdf_bytes)
    ocr_task = run_chunked_ocr(pdf_bytes, ocr_pages, secrets_manager, log_prefix)
    text_by_page, extracted_images, (ocr_by_page, ocr_providers) = await asyncio.gather(
        text_task, images_task, ocr_task
    )

    pages: List[Dict[str, Any]] = []
    for info in triage.pages:
        n = info.page_number
        if info.route == "ocr":
            ocr = ocr_by_page[n]
            pages.append({
                "page_num": n, "markdown": ocr["markdown"], "source": "ocr",
                "unreadable": bool(ocr.get("unreadable")), "tables": ocr.get("tables", []),
                "header": ocr.get("header"), "footer": ocr.get("footer"),
                "width": ocr.get("width", 0), "height": ocr.get("height", 0),
            })
        else:
            pages.append({
                "page_num": n, "markdown": text_by_page.get(n) or info.text, "source": "text_layer",
                "unreadable": False, "tables": [], "header": None, "footer": None, "width": 0, "height": 0,
            })

    # 3. Safety decisions and table of contents in parallel.
    judge_inputs: Dict[str, bytes] = {key: data for key, (_page, data) in extracted_images.items()}
    scanned = list(ocr_pages)
    judge_renders = await asyncio.to_thread(
        render_selected_pages, pdf_bytes, scanned, SAFETY_JUDGE_DPI, log_prefix
    ) if scanned else {}
    for n, png in judge_renders.items():
        judge_inputs[f"page_{n}"] = png
    preview_png: Optional[bytes] = None
    if triage.page_count:
        preview = await asyncio.to_thread(render_selected_pages, pdf_bytes, [1], SCREENSHOT_DPI, log_prefix)
        preview_png = preview[1]
        judge_inputs["preview_page_1"] = preview_png

    async def _toc() -> tuple[Dict[str, Any], Dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                _table_of_contents(pages, triage.outline, secrets_manager, log_prefix), TOC_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning("%s Table of contents timed out after %.0fs; continuing without it",
                           log_prefix, TOC_TIMEOUT_SECONDS)
            return ({"detected": False, "source_pages": [], "chapters": []},
                    {"detected": False, "source_pages": [], "content": "", "chapters": []})

    injection, decisions, (toc, legend) = await asyncio.gather(
        score_pages_injection({p["page_num"]: p["markdown"] for p in pages}, secrets_manager, log_prefix=log_prefix),
        judge_images(judge_inputs, secrets_manager, log_prefix=log_prefix),
        _toc(),
    )

    rejected = [k for k, d in decisions.items() if d.outcome == "pdf_rejected"]
    if rejected:
        raise PdfRejectedError(f"PDF contains content that violates community guidelines (item {rejected[0]})")
    withheld = sorted(k for k, d in decisions.items() if d.outcome == "withheld")

    # 4. Store allowed artefacts.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    base = f"chatfiles/{user_id}/{timestamp}_{unique}_pdf_{embed_id[:8]}"

    screenshot_keys: Dict[str, str] = {}
    if preview_png is not None and decisions["preview_page_1"].outcome == "allowed":
        screenshot_keys["1"] = await _encrypt_upload(
            s3_service, output_aesgcm, preview_png, f"{base}_p1.png.bin", created_s3_keys
        )

    image_keys: List[str] = []
    for key, (page_number, data) in extracted_images.items():
        if decisions[key].outcome == "allowed":
            image_keys.append(await _encrypt_upload(
                s3_service, output_aesgcm, data, f"{base}_p{page_number}_{key.split('_', 1)[1]}.bin", created_s3_keys
            ))

    per_page_tokens: Dict[str, int] = {}
    blob_pages: Dict[str, Any] = {}
    unreadable: List[int] = []
    for page in pages:
        n = page["page_num"]
        result = injection[n]
        per_page_tokens[str(n)] = max(1, len(page["markdown"]) // 4)
        if page["unreadable"]:
            unreadable.append(n)
        blob_pages[str(n)] = {
            "markdown": page["markdown"], "source": page["source"], "unreadable": page["unreadable"],
            "injection": {"label": result.label, "score": result.score},
            "header": page["header"], "footer": page["footer"], "tables": page["tables"],
            "image_count": sum(1 for _k, (pn, _d) in extracted_images.items() if pn == n),
            "width": page["width"], "height": page["height"],
            "image_withheld": f"page_{n}" in withheld,
        }
    total_tokens = sum(per_page_tokens.values())
    blob_key = await _encrypt_upload(
        s3_service, output_aesgcm, json.dumps({"pages": blob_pages}, ensure_ascii=False).encode("utf-8"),
        f"{base}_ocr.json.bin", created_s3_keys,
    )

    providers = ",".join(sorted(ocr_providers)) if ocr_providers else "none"
    return PipelineOutput(
        embed_fields={
            "page_count": triage.page_count,
            "total_tokens_estimated": total_tokens,
            "per_page_tokens": per_page_tokens,
            "toc": {"detected": toc["detected"], "source_pages": toc["source_pages"], "chapters": toc["chapters"]},
            "legend": {"detected": legend["detected"], "source_pages": legend["source_pages"],
                       "content": legend["content"]},
            "ocr_data_s3_key": blob_key,
            "screenshot_s3_keys": screenshot_keys,
            "extracted_image_s3_keys": image_keys,
            "withheld_images": withheld,
            "whole_document_readable": total_tokens <= WHOLE_DOCUMENT_TOKEN_LIMIT,
            "page_sources": {"text_layer": len(text_pages), "ocr": len(ocr_pages), "unreadable": len(unreadable)},
            "price": {"credits": price.credits, "ocr_pages": price.ocr_pages},
            "ocr_provider": providers,
            "processing_version": 2,
        },
        total_tokens=total_tokens,
        unreadable_pages=unreadable,
        price_credits=price.credits,
    )
