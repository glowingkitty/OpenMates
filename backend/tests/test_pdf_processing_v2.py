# backend/tests/test_pdf_processing_v2.py
#
# PDF processing v2: per-page triage, exact pricing, chunked OCR, and the hold that keeps the
# assistant from answering before a PDF has finished processing.
# Specification: specifications/features/pdf-processing (examples page_routing, borderline_routing,
# readiness, ocr_chunks, pricing).

from __future__ import annotations

import asyncio

import pytest

from backend.apps.pdf.services.ocr_chunks import UNREADABLE_MARKER, _remap, chunk_pages
from backend.apps.pdf.services.pdf_triage import (
    PageTriage,
    TriageResult,
    classify_signals,
    garbled_ratio,
    price_for,
    resolve_borderline_pages,
)
from backend.shared.python_utils.pdf_turn_gate import (
    PdfProcessingFailedForTurn,
    PdfProcessingTimedOutForTurn,
    wait_for_pdfs_final,
)


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_clean_text_page_uses_text_layer():
    assert classify_signals(text_chars=1800, image_coverage=0.1, garbled=0.0, drawings=3) == ("text_layer", "clean_text_layer")


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_scan_without_text_goes_to_ocr_and_blank_page_does_not():
    assert classify_signals(text_chars=0, image_coverage=0.98, garbled=0.0, drawings=0)[0] == "ocr"
    assert classify_signals(text_chars=0, image_coverage=0.0, garbled=0.0, drawings=0)[0] == "text_layer"


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_garbled_layer_goes_to_ocr_and_mild_garble_is_borderline():
    assert classify_signals(text_chars=900, image_coverage=0.0, garbled=0.5, drawings=0)[0] == "ocr"
    assert classify_signals(text_chars=900, image_coverage=0.0, garbled=0.1, drawings=0)[0] is None


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_garbled_ratio_counts_cid_and_replacement_characters():
    assert garbled_ratio("normal text") == 0.0
    assert garbled_ratio("(cid:12)(cid:13)") == 1.0
    assert 0.2 < garbled_ratio("ab��") < 0.6


def _borderline_page(number: int) -> PageTriage:
    return PageTriage(
        page_number=number, route="ocr", decided_by="default_to_ocr", text="caption", text_chars=7,
        image_coverage=0.9, borderline=True, reason="little_text_on_full_page_image",
    )


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.borderline-defaults-to-ocr
def test_borderline_without_decision_model_defaults_to_ocr():
    result = TriageResult(pages=[_borderline_page(1)])
    asyncio.run(resolve_borderline_pages(result, None))
    assert (result.pages[0].route, result.pages[0].decided_by, result.pages[0].borderline) == ("ocr", "default_to_ocr", False)


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.borderline-defaults-to-ocr
def test_borderline_unsure_or_failing_decision_defaults_to_ocr_and_confident_text_is_trusted():
    async def decider(page: PageTriage):
        return {1: True, 2: False, 3: None}[page.page_number]

    result = TriageResult(pages=[_borderline_page(1), _borderline_page(2), _borderline_page(3)])
    asyncio.run(resolve_borderline_pages(result, decider))
    assert [(p.route, p.decided_by) for p in result.pages] == [
        ("text_layer", "decision_model"), ("ocr", "decision_model"), ("ocr", "default_to_ocr"),
    ]


def _two_page_pdf() -> bytes:
    import fitz  # type: ignore[import]  # pymupdf

    doc = fitz.open()
    page = doc.new_page()
    # Written bottom-first so the file order differs from the reading order.
    # Two non-overlapping columns on one baseline, then a line further down.
    page.insert_text((72, 700), "Bottom line: absolute maximum ratings")
    page.insert_text((330, 100), "Top right: features")
    page.insert_text((72, 100), "Top left: quad NAND gate")
    doc.new_page()  # blank page
    data = doc.tobytes()
    doc.close()
    return data


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_triage_text_is_in_reading_order():
    from backend.apps.pdf.services.pdf_triage import triage_pages_sync

    result = triage_pages_sync(_two_page_pdf())
    text = result.pages[0].text
    assert text.index("Top left") < text.index("Top right") < text.index("Bottom line")
    assert result.pages[0].route == "text_layer" and result.pages[1].route == "text_layer"


# contract-test: supporting surface=rest_api assertions=pdf-processing.triage.per-page-route
def test_text_only_triage_keeps_text_and_leaves_routes_to_the_upload():
    from backend.apps.pdf.services.pdf_pipeline import _apply_routes
    from backend.apps.pdf.services.pdf_triage import triage_pages_sync

    data = _two_page_pdf()
    full = triage_pages_sync(data)
    text_only = triage_pages_sync(data, signals=False)
    assert [p.text for p in text_only.pages] == [p.text for p in full.pages]
    assert all(p.borderline and p.route == "ocr" for p in text_only.pages)  # nothing trusted unrouted
    routes = [p.to_route_dict() for p in full.pages]
    assert _apply_routes(text_only, routes) is True
    assert [p.route for p in text_only.pages] == ["text_layer", "text_layer"]
    assert not any(p.borderline for p in text_only.pages)
    assert _apply_routes(triage_pages_sync(data, signals=False), routes[:1]) is False


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.exact-price
def test_price_is_two_per_file_plus_two_per_ocr_page():
    assert price_for(0).credits == 2
    assert price_for(10).credits == 22
    assert price_for(10).per_ocr_page_credits == 2


# contract-test: supporting surface=rest_api assertions=pdf-processing.ocr.parallel-chunks
def test_ocr_pages_are_chunked_by_twenty():
    chunks = chunk_pages(list(range(1, 101)))
    assert [len(c) for c in chunks] == [20] * 5
    assert chunk_pages([5, 3, 3, 4]) == [[3, 4, 5]]


# contract-test: supporting surface=rest_api assertions=pdf-processing.ocr.parallel-chunks
def test_page_without_ocr_text_gets_unreadable_marker_and_numbers_map_back():
    pages = [{"page_num": 1, "markdown": "first"}, {"page_num": 2, "markdown": "  "}]
    mapped = _remap([30, 35], pages, "mistral")
    assert mapped[0]["page_num"] == 30 and mapped[0]["markdown"] == "first" and not mapped[0]["unreadable"]
    assert mapped[1]["page_num"] == 35 and mapped[1]["markdown"] == UNREADABLE_MARKER and mapped[1]["unreadable"]


class _FakeCache:
    def __init__(self, embeds: dict):
        self.embeds = embeds

    async def get_user_vault_key_id(self, _user_id):
        return "vault-key"

    async def get_embed_from_cache(self, embed_id):
        entry = self.embeds.get(embed_id)
        return entry() if callable(entry) else entry


class _FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext, _key):
        return ciphertext


def _embed(status: str, kind: str = "pdf") -> dict:
    from toon_format import encode

    return {"status": status, "encrypted_content": encode({"type": kind})}


async def _no_sleep(_seconds):
    return None


def _run_gate(embeds: dict, **kwargs):
    ticks = iter(range(10_000))
    return asyncio.run(wait_for_pdfs_final(
        cache_service=_FakeCache(embeds), encryption_service=_FakeEncryption(), user_id="u",
        embed_ids=list(embeds), sleep=_no_sleep, monotonic=lambda: float(next(ticks)), **kwargs,
    ))


# contract-test: supporting surface=rest_api assertions=pdf-processing.readiness.complete-before-answer
def test_turn_is_held_until_pdf_finished_then_released():
    states = iter([_embed("processing"), _embed("processing"), _embed("finished")])
    last = {"value": _embed("processing")}

    def current():
        try:
            last["value"] = next(states)
        except StopIteration:
            pass
        return last["value"]

    waiting_calls = []

    async def on_waiting(ids):
        waiting_calls.append(ids)

    assert _run_gate({"pdf1": current}, on_waiting=on_waiting) == ["pdf1"]
    assert waiting_calls == [["pdf1"]]


# contract-test: supporting surface=rest_api assertions=pdf-processing.readiness.complete-before-answer
def test_failed_pdf_in_current_turn_ends_turn_without_answer_but_old_failure_does_not_block():
    with pytest.raises(PdfProcessingFailedForTurn):
        _run_gate({"pdf1": _embed("error")}, current_turn_embed_ids=["pdf1"])
    assert _run_gate({"pdf1": _embed("error")}) == []


# contract-test: supporting surface=rest_api assertions=pdf-processing.readiness.complete-before-answer
def test_pdf_still_processing_after_maximum_hold_does_not_answer():
    with pytest.raises(PdfProcessingTimedOutForTurn):
        _run_gate({"pdf1": _embed("processing")}, max_wait_seconds=5.0)


# contract-test: supporting surface=rest_api assertions=pdf-processing.readiness.complete-before-answer
def test_non_pdf_embeds_never_hold_the_turn():
    assert _run_gate({"img1": _embed("processing", kind="image")}) == []
