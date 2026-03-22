# backend/tests/test_pdf_ocr_and_toc.py
#
# Integration test for the PDF processing pipeline:
#   1. OCR via Mistral Document AI (mistral-ocr-latest)
#   2. TOC / Legend detection via Groq (gpt-oss-20b) with tool use
#
# PDFs under test:
#   - Prusa MK3.5 assembly manual  (~short, image-heavy)
#   - LCSC component datasheet     (~medium, technical)
#   - USB 1.1 specification        (~300+ pages, large)
#
# OCR results are cached as JSON files under test_results/pdf/ so the
# expensive Mistral call is skipped on subsequent runs.  Delete the cache
# file to force re-OCR.
#
# Run from project root:
#   python backend/tests/test_pdf_ocr_and_toc.py
#
# Or run only the TOC detection step (reads from cache):
#   python backend/tests/test_pdf_ocr_and_toc.py --toc-only
#
# Or run only a specific PDF (by short name):
#   python backend/tests/test_pdf_ocr_and_toc.py --pdf prusa
#   python backend/tests/test_pdf_ocr_and_toc.py --pdf lcsc
#   python backend/tests/test_pdf_ocr_and_toc.py --pdf usb

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Project-root setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PDF test targets
# ---------------------------------------------------------------------------
TEST_PDFS = {
    "prusa": {
        "name": "Prusa MK3.5 Assembly Manual",
        "url": "https://www.prusa3d.com/downloads/manual/prusa3d_manual_MK35_100_en.pdf",
        "expected_has_toc": True,
    },
    "lcsc": {
        "name": "LCSC Component Datasheet (C424093)",
        "url": "https://www.lcsc.com/datasheet/C424093.pdf",
        "expected_has_toc": False,
    },
    "usb": {
        "name": "USB 1.1 Specification (~300 pages)",
        "url": "http://esd.cs.ucr.edu/webres/usb11.pdf",
        "expected_has_toc": True,
    },
}

# Where to cache OCR results
CACHE_DIR = PROJECT_ROOT / "test_results" / "pdf"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# How many pages (batches of 3) to check for TOC, starting from page 1
TOC_SEARCH_MAX_PAGES = 12
TOC_BATCH_SIZE = 3

# How many pages from the END to check for a legend / appendix
LEGEND_SEARCH_LAST_N_PAGES = 5

# Groq model for TOC / legend detection
TOC_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # fast, cheap; fall back to 70b if needed


# ---------------------------------------------------------------------------
# Step 1: Mistral OCR
# ---------------------------------------------------------------------------

async def run_ocr(pdf_key: str, pdf_url: str, mistral_api_key: str) -> dict[str, Any]:
    """
    Run Mistral OCR on a PDF URL.

    Returns the raw OCR response dict with per-page data.
    Caches the result to disk so repeated runs are free.
    """
    cache_file = CACHE_DIR / f"ocr_{pdf_key}.json"

    if cache_file.exists():
        logger.info(f"[{pdf_key}] Loading cached OCR result from {cache_file.name}")
        with cache_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    logger.info(f"[{pdf_key}] Starting Mistral OCR for: {pdf_url}")
    t0 = time.monotonic()

    try:
        from mistralai import Mistral  # type: ignore
    except ImportError:
        raise RuntimeError(
            "mistralai package not installed. Run: pip install mistralai"
        )

    client = Mistral(api_key=mistral_api_key)

    # Mistral OCR only accepts HTTPS URLs directly.
    # For HTTP URLs we download the PDF and send it as base64.
    import urllib.request
    import base64

    if pdf_url.startswith("https://"):
        document_payload = {
            "type": "document_url",
            "document_url": pdf_url,
        }
    else:
        logger.info(f"[{pdf_key}] Non-HTTPS URL — downloading PDF to encode as base64")
        with urllib.request.urlopen(pdf_url, timeout=60) as resp:
            pdf_bytes = resp.read()
        b64_data = base64.b64encode(pdf_bytes).decode("ascii")
        document_payload = {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{b64_data}",
        }

    response = client.ocr.process(
        model="mistral-ocr-latest",
        document=document_payload,
        include_image_base64=False,  # We don't need base64 for this test
        table_format="html",
        extract_header=True,
        extract_footer=True,
    )

    elapsed = time.monotonic() - t0

    # Convert to plain dict for JSON serialisation
    pages = []
    for page in response.pages:
        pages.append({
            "index": page.index,
            "markdown": page.markdown,
            "images": [
                {"id": img.id, "top_left_x": img.top_left_x, "top_left_y": img.top_left_y,
                 "bottom_right_x": img.bottom_right_x, "bottom_right_y": img.bottom_right_y}
                for img in (page.images or [])
            ],
            "tables": [t.html if hasattr(t, "html") else str(t) for t in (page.tables or [])],
            "header": page.header,
            "footer": page.footer,
            "dimensions": {
                "width": page.dimensions.width if page.dimensions else None,
                "height": page.dimensions.height if page.dimensions else None,
                "dpi": page.dimensions.dpi if page.dimensions else None,
            } if page.dimensions else None,
        })

    result = {
        "pdf_key": pdf_key,
        "pdf_url": pdf_url,
        "model": response.model,
        "page_count": len(pages),
        "usage": {
            "pages_processed": response.usage_info.pages_processed if response.usage_info else None,
            "doc_size_bytes": response.usage_info.doc_size_bytes if response.usage_info else None,
        },
        "pages": pages,
        "elapsed_seconds": round(elapsed, 2),
    }

    # Persist to cache
    with cache_file.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    logger.info(
        f"[{pdf_key}] OCR complete: {len(pages)} pages in {elapsed:.1f}s "
        f"(cached → {cache_file.name})"
    )
    return result


# ---------------------------------------------------------------------------
# Step 2: TOC / Legend detection via Groq with tool use
# ---------------------------------------------------------------------------

def _build_toc_tool() -> dict[str, Any]:
    """
    JSON-schema tool definition for structured TOC / Legend extraction.
    The LLM must call this tool when it detects a table of contents or legend.
    """
    return {
        "type": "function",
        "function": {
            "name": "report_document_structure",
            "description": (
                "Report the detected table of contents and/or legend from the document pages "
                "provided. Call this tool once you have enough information. "
                "If a section is not found, set its 'detected' field to false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "toc": {
                        "type": "object",
                        "description": "Table of contents / chapter overview",
                        "properties": {
                            "detected": {
                                "type": "boolean",
                                "description": "True if a TOC was found in these pages",
                            },
                            "is_complete": {
                                "type": "boolean",
                                "description": (
                                    "True if the TOC appears to be complete (not cut off). "
                                    "False if more pages should be checked."
                                ),
                            },
                            "source_pages": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "1-indexed page numbers where TOC content was found",
                            },
                            "chapters": {
                                "type": "array",
                                "description": "List of top-level chapters / sections extracted from the TOC",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "page": {
                                            "type": "integer",
                                            "description": "Page number referenced in TOC (if available)",
                                        },
                                    },
                                    "required": ["title"],
                                },
                            },
                        },
                        "required": ["detected", "is_complete", "source_pages", "chapters"],
                    },
                    "legend": {
                        "type": "object",
                        "description": "Figure/table legend or glossary (typically near the end of a document)",
                        "properties": {
                            "detected": {
                                "type": "boolean",
                                "description": "True if a legend / glossary / appendix was found",
                            },
                            "source_pages": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "1-indexed page numbers where legend content was found",
                            },
                            "content": {
                                "type": "string",
                                "description": "Extracted legend / glossary text (concise, max 2000 chars)",
                            },
                        },
                        "required": ["detected", "source_pages", "content"],
                    },
                },
                "required": ["toc", "legend"],
            },
        },
    }


def _page_excerpt(page: dict[str, Any], max_chars: int = 1500) -> str:
    """
    Return a truncated excerpt of a page's markdown content for LLM input.
    Preserves as much structure as possible while respecting the char budget.
    """
    md = page.get("markdown", "") or ""
    if len(md) <= max_chars:
        return md
    # Try to cut at a paragraph boundary
    cut = md.rfind("\n\n", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return md[:cut] + "\n[…truncated]"


async def detect_toc_and_legend(
    pdf_key: str,
    ocr_result: dict[str, Any],
    groq_api_key: str,
) -> dict[str, Any]:
    """
    Detect TOC and legend using Groq (gpt-oss-20b) with tool use.

    TOC detection:
      - Processes pages in batches of TOC_BATCH_SIZE (default 3)
      - Starts from the beginning
      - Stops early when the tool signals is_complete=True
      - Checks up to TOC_SEARCH_MAX_PAGES pages total

    Legend detection:
      - Checks the last LEGEND_SEARCH_LAST_N_PAGES pages
      - Single call

    Returns a combined structure dict that will go into the TOON embed content.
    """
    from groq import AsyncGroq  # type: ignore

    client = AsyncGroq(api_key=groq_api_key)
    pages = ocr_result["pages"]
    total_pages = len(pages)

    tool = _build_toc_tool()
    toc_result: Optional[dict] = None

    # -----------------------------------------------------------------------
    # Phase A: TOC detection (iterative batches from the front)
    # -----------------------------------------------------------------------
    logger.info(f"[{pdf_key}] TOC detection — checking up to {TOC_SEARCH_MAX_PAGES} pages in batches of {TOC_BATCH_SIZE}")

    pages_to_check = min(TOC_SEARCH_MAX_PAGES, total_pages)
    batch_start = 0  # 0-indexed into pages list

    accumulated_toc_chapters: list[dict] = []
    accumulated_toc_source_pages: list[int] = []
    toc_detected = False

    while batch_start < pages_to_check:
        batch_end = min(batch_start + TOC_BATCH_SIZE, pages_to_check)
        batch_pages = pages[batch_start:batch_end]

        # Build user message content
        page_texts = []
        for p in batch_pages:
            page_num = p["index"] + 1  # 1-indexed for human readability
            page_texts.append(f"--- Page {page_num} ---\n{_page_excerpt(p)}")
        batch_content = "\n\n".join(page_texts)

        already_found_summary = ""
        if accumulated_toc_chapters:
            already_found_summary = (
                f"\n\nPrevious batches already found {len(accumulated_toc_chapters)} "
                f"chapter entries on pages {accumulated_toc_source_pages}. "
                "Continue extracting where the TOC left off."
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a document analysis assistant. "
                    "Your task is to detect and extract the table of contents and legends from PDF pages. "
                    "You MUST call the report_document_structure tool with your findings. "
                    "Be precise: only report a TOC if you actually see chapter/section listings with page numbers or clear headings. "
                    "Set is_complete=false if the TOC appears to continue beyond the pages shown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze these PDF pages and extract the table of contents (if present). "
                    f"Document has {total_pages} pages total. "
                    f"You are currently looking at pages {batch_pages[0]['index']+1}–{batch_pages[-1]['index']+1}."
                    f"{already_found_summary}\n\n"
                    f"For the legend field: set detected=false and leave content empty (we'll check the end of the document separately).\n\n"
                    f"{batch_content}"
                ),
            },
        ]

        t0 = time.monotonic()
        response = await client.chat.completions.create(
            model=TOC_MODEL,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "report_document_structure"}},
            temperature=0.1,
            max_tokens=2048,
        )
        elapsed = time.monotonic() - t0
        logger.info(f"[{pdf_key}] TOC batch pages {batch_pages[0]['index']+1}–{batch_pages[-1]['index']+1}: {elapsed:.1f}s")

        # Parse tool call response
        tool_call = None
        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            try:
                tool_call = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                logger.warning(f"[{pdf_key}] Failed to parse tool call JSON: {exc}")

        if tool_call:
            toc_data = tool_call.get("toc", {})
            if toc_data.get("detected"):
                toc_detected = True
                # Accumulate chapters across batches
                new_chapters = toc_data.get("chapters", [])
                accumulated_toc_chapters.extend(new_chapters)
                accumulated_toc_source_pages.extend(toc_data.get("source_pages", []))
                accumulated_toc_source_pages = sorted(set(accumulated_toc_source_pages))

                logger.info(
                    f"[{pdf_key}] TOC found: {len(new_chapters)} new chapters "
                    f"(total {len(accumulated_toc_chapters)}), "
                    f"complete={toc_data.get('is_complete')}"
                )

                if toc_data.get("is_complete"):
                    logger.info(f"[{pdf_key}] TOC is complete — stopping early.")
                    break
            else:
                logger.info(f"[{pdf_key}] No TOC detected in this batch.")
                # If we already found chapters, the TOC doesn't continue — stop
                if toc_detected:
                    break

        batch_start = batch_end

    toc_result = {
        "detected": toc_detected,
        "source_pages": accumulated_toc_source_pages,
        "chapters": accumulated_toc_chapters,
    }

    # -----------------------------------------------------------------------
    # Phase B: Legend detection (last N pages, single call)
    # -----------------------------------------------------------------------
    legend_result: dict[str, Any] = {"detected": False, "source_pages": [], "content": ""}

    if total_pages > 0:
        legend_page_count = min(LEGEND_SEARCH_LAST_N_PAGES, total_pages)
        legend_pages = pages[total_pages - legend_page_count:]

        logger.info(
            f"[{pdf_key}] Legend detection — checking last {legend_page_count} pages "
            f"(pages {total_pages - legend_page_count + 1}–{total_pages})"
        )

        page_texts = []
        for p in legend_pages:
            page_num = p["index"] + 1
            page_texts.append(f"--- Page {page_num} ---\n{_page_excerpt(p, max_chars=2000)}")
        legend_content = "\n\n".join(page_texts)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a document analysis assistant. "
                    "Your task is to detect legends, glossaries, or figure/table indices at the end of documents. "
                    "You MUST call the report_document_structure tool with your findings."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze these final pages of a PDF document. "
                    f"Document has {total_pages} pages total. "
                    f"Check if there is a legend, glossary, figure index, or appendix.\n\n"
                    f"For the toc field: set detected=false (we've already handled TOC separately).\n\n"
                    f"{legend_content}"
                ),
            },
        ]

        t0 = time.monotonic()
        response = await client.chat.completions.create(
            model=TOC_MODEL,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "report_document_structure"}},
            temperature=0.1,
            max_tokens=2048,
        )
        elapsed = time.monotonic() - t0
        logger.info(f"[{pdf_key}] Legend detection: {elapsed:.1f}s")

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            try:
                tool_call = json.loads(tc.function.arguments)
                legend_data = tool_call.get("legend", {})
                legend_result = {
                    "detected": legend_data.get("detected", False),
                    "source_pages": legend_data.get("source_pages", []),
                    "content": (legend_data.get("content", "") or "")[:2000],
                }
                logger.info(
                    f"[{pdf_key}] Legend detected={legend_result['detected']}, "
                    f"pages={legend_result['source_pages']}"
                )
            except json.JSONDecodeError as exc:
                logger.warning(f"[{pdf_key}] Failed to parse legend tool call: {exc}")

    # -----------------------------------------------------------------------
    # Compute per-page token estimates
    # -----------------------------------------------------------------------
    per_page_tokens: dict[str, int] = {}
    total_tokens = 0
    for p in pages:
        md = p.get("markdown", "") or ""
        est = max(1, len(md) // 4)
        per_page_tokens[str(p["index"] + 1)] = est  # 1-indexed, string key for JSON
        total_tokens += est

    # -----------------------------------------------------------------------
    # Assemble final embed-ready structure
    # -----------------------------------------------------------------------
    result = {
        "pdf_key": pdf_key,
        "page_count": total_pages,
        "total_tokens_estimated": total_tokens,
        "per_page_tokens": per_page_tokens,  # {"1": 420, "2": 380, ...}
        "toc": toc_result,
        "legend": legend_result,
    }

    # Persist to disk for inspection
    out_file = CACHE_DIR / f"toc_legend_{pdf_key}.json"
    with out_file.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    logger.info(f"[{pdf_key}] TOC/legend result saved → {out_file.name}")

    return result


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _print_separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print('=' * 70)


def _print_ocr_summary(pdf_key: str, ocr: dict[str, Any]) -> None:
    _print_separator(f"OCR RESULT — {TEST_PDFS[pdf_key]['name']}")
    print(f"  Pages : {ocr['page_count']}")
    print(f"  Model : {ocr.get('model', 'n/a')}")
    print(f"  Usage : {ocr.get('usage', {})}")
    print(f"  Time  : {ocr.get('elapsed_seconds', '(cached)')}s")

    # Show first page excerpt
    if ocr["pages"]:
        first_md = (ocr["pages"][0].get("markdown") or "")[:500]
        print(f"\n  --- First 500 chars of page 1 ---\n{first_md}\n  [...]")


def _print_toc_legend_summary(pdf_key: str, result: dict[str, Any]) -> None:
    _print_separator(f"TOC / LEGEND — {TEST_PDFS[pdf_key]['name']}")
    print(f"  Pages         : {result['page_count']}")
    print(f"  Total tokens~ : {result['total_tokens_estimated']:,}")

    toc = result.get("toc", {})
    print(f"\n  TOC detected  : {toc.get('detected')}")
    if toc.get("detected"):
        print(f"  TOC pages     : {toc.get('source_pages')}")
        chapters = toc.get("chapters", [])
        print(f"  TOC chapters  : {len(chapters)}")
        for ch in chapters[:10]:
            page_ref = f" → p.{ch['page']}" if ch.get("page") else ""
            print(f"    • {ch['title']}{page_ref}")
        if len(chapters) > 10:
            print(f"    ... and {len(chapters) - 10} more")

    legend = result.get("legend", {})
    print(f"\n  Legend detected: {legend.get('detected')}")
    if legend.get("detected"):
        print(f"  Legend pages   : {legend.get('source_pages')}")
        content_preview = (legend.get("content") or "")[:300]
        print(f"  Legend preview : {content_preview}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(pdf_filter: Optional[str] = None, toc_only: bool = False) -> None:
    # Fetch API keys from Vault
    logger.info("Initialising SecretsManager …")
    sm = SecretsManager()
    await sm.initialize()

    mistral_key = await sm.get_secret("kv/data/providers/mistral_ai", "api_key")
    groq_key = await sm.get_secret("kv/data/providers/groq", "api_key")

    if not mistral_key:
        raise RuntimeError("Mistral API key not found in Vault at kv/data/providers/mistral_ai")
    if not groq_key:
        raise RuntimeError("Groq API key not found in Vault at kv/data/providers/groq")

    logger.info(f"Mistral key: {mistral_key[:8]}…   Groq key: {groq_key[:8]}…")

    # Select which PDFs to process
    targets = {k: v for k, v in TEST_PDFS.items() if pdf_filter is None or k == pdf_filter}
    if not targets:
        print(f"No PDFs matched filter '{pdf_filter}'. Valid keys: {list(TEST_PDFS.keys())}")
        return

    all_results: dict[str, dict] = {}

    for pdf_key, pdf_info in targets.items():
        logger.info(f"\n{'─' * 60}")
        logger.info(f"Processing: {pdf_info['name']}")
        logger.info(f"URL: {pdf_info['url']}")
        logger.info(f"{'─' * 60}")

        # ── Step 1: OCR ────────────────────────────────────────────────────
        if not toc_only:
            ocr = await run_ocr(pdf_key, pdf_info["url"], mistral_key)
        else:
            cache_file = CACHE_DIR / f"ocr_{pdf_key}.json"
            if not cache_file.exists():
                logger.error(
                    f"[{pdf_key}] --toc-only requires a cached OCR file at {cache_file}. "
                    "Run without --toc-only first."
                )
                continue
            logger.info(f"[{pdf_key}] --toc-only: loading cached OCR from {cache_file.name}")
            with cache_file.open("r", encoding="utf-8") as fh:
                ocr = json.load(fh)

        _print_ocr_summary(pdf_key, ocr)

        # ── Step 2: TOC / Legend detection ─────────────────────────────────
        toc_legend = await detect_toc_and_legend(pdf_key, ocr, groq_key)
        _print_toc_legend_summary(pdf_key, toc_legend)

        all_results[pdf_key] = {
            "ocr_pages": ocr["page_count"],
            "toc_detected": toc_legend["toc"]["detected"],
            "toc_chapters": len(toc_legend["toc"].get("chapters", [])),
            "legend_detected": toc_legend["legend"]["detected"],
            "total_tokens": toc_legend["total_tokens_estimated"],
        }

    # ── Final summary table ─────────────────────────────────────────────────
    if all_results:
        _print_separator("SUMMARY")
        print(f"  {'PDF':<8} {'Pages':>6} {'TOC':>5} {'Chapters':>9} {'Legend':>7} {'~Tokens':>10}")
        print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*9} {'-'*7} {'-'*10}")
        for key, r in all_results.items():
            print(
                f"  {key:<8} {r['ocr_pages']:>6} "
                f"{'YES' if r['toc_detected'] else 'no':>5} "
                f"{r['toc_chapters']:>9} "
                f"{'YES' if r['legend_detected'] else 'no':>7} "
                f"{r['total_tokens']:>10,}"
            )
        print()

    logger.info("All done. Results cached under test_results/pdf/")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF OCR + TOC/Legend detection test")
    parser.add_argument(
        "--pdf",
        choices=list(TEST_PDFS.keys()),
        default=None,
        help="Only process a specific PDF (default: all three)",
    )
    parser.add_argument(
        "--toc-only",
        action="store_true",
        help="Skip OCR step (use cached results) and only run TOC/legend detection",
    )
    args = parser.parse_args()
    asyncio.run(main(pdf_filter=args.pdf, toc_only=args.toc_only))
