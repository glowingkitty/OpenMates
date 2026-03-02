# backend/apps/pdf/services/toc_detector.py
#
# Table-of-contents and legend detector using Groq's gpt-oss-20b with tool use.
#
# Architecture:
#   - Processes pages in batches of 3 starting from page 1, up to 12 pages max.
#   - Each batch asks the model: "Is TOC found? Is it complete?"
#   - Stops when is_complete=True OR 12 pages have been checked.
#   - Legend: checks the last 5 pages in a single call.
#   - Uses OpenAI-compatible tool use (function calling) via Groq.
#
# Vault secrets:
#   API key at kv/data/providers/groq with key "api_key".

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Groq API endpoint and model
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

# Tuning constants
TOC_BATCH_SIZE = 3     # pages per TOC detection call
TOC_MAX_PAGES = 12     # maximum pages to inspect for TOC
LEGEND_LAST_N = 5      # pages from end to inspect for legend


async def _get_groq_api_key(secrets_manager: Any) -> str:
    """Retrieve Groq API key from Vault."""
    try:
        key = await secrets_manager.get_secret("kv/data/providers/groq", "api_key")
        if not key:
            raise RuntimeError("Groq API key is empty in Vault")
        return key
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve Groq API key from Vault: {e}") from e


def _build_toc_tool() -> Dict[str, Any]:
    """Build the Groq tool schema for TOC detection."""
    return {
        "type": "function",
        "function": {
            "name": "report_toc_status",
            "description": (
                "Report whether a table of contents (TOC) was found in the provided pages "
                "and whether the TOC is complete (all entries visible)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "toc_found": {
                        "type": "boolean",
                        "description": "True if a table of contents is present in these pages.",
                    },
                    "is_complete": {
                        "type": "boolean",
                        "description": (
                            "True if the TOC is complete (all entries are visible). "
                            "False if it continues on the next page or is only partial."
                        ),
                    },
                    "source_pages": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "1-indexed page numbers that contain TOC content.",
                    },
                    "chapters": {
                        "type": "array",
                        "description": "List of TOC chapters/sections found so far.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Chapter or section title.",
                                },
                                "page": {
                                    "type": "integer",
                                    "description": "1-indexed page number where this chapter starts.",
                                },
                            },
                            "required": ["title", "page"],
                        },
                    },
                },
                "required": ["toc_found", "is_complete", "source_pages", "chapters"],
            },
        },
    }


def _build_legend_tool() -> Dict[str, Any]:
    """Build the Groq tool schema for legend detection."""
    return {
        "type": "function",
        "function": {
            "name": "report_legend_status",
            "description": (
                "Report whether a legend, glossary, or list of abbreviations/symbols "
                "was found in the provided pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "legend_found": {
                        "type": "boolean",
                        "description": "True if a legend or glossary is present in these pages.",
                    },
                    "source_pages": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "1-indexed page numbers containing the legend.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Concise summary of the legend contents "
                            "(abbreviations, symbols, figure captions, etc.). "
                            "Empty string if no legend found."
                        ),
                    },
                },
                "required": ["legend_found", "source_pages", "content"],
            },
        },
    }


async def _call_groq_with_tool(
    api_key: str,
    system_prompt: str,
    user_message: str,
    tool: Dict[str, Any],
    tool_name: str,
    log_prefix: str,
) -> Optional[Dict[str, Any]]:
    """
    Call Groq API with a single tool and return the parsed tool arguments.

    Returns:
        Parsed tool call arguments dict, or None on failure.
    """
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "temperature": 0,
        "max_tokens": 2048,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            GROQ_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code != 200:
        logger.error(
            f"{log_prefix} Groq API error: HTTP {resp.status_code} — {resp.text[:300]}"
        )
        return None

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        logger.error(f"{log_prefix} Groq returned no choices")
        return None

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    if not tool_calls:
        logger.error(f"{log_prefix} Groq returned no tool calls")
        return None

    try:
        args_str = tool_calls[0]["function"]["arguments"]
        return json.loads(args_str)
    except Exception as e:
        logger.error(f"{log_prefix} Failed to parse Groq tool call arguments: {e}", exc_info=True)
        return None


def _pages_to_text(pages: List[Dict[str, Any]], page_nums: List[int]) -> str:
    """
    Build a text block containing the markdown of the specified pages.

    Args:
        pages: Full list of page dicts (from OCR).
        page_nums: 1-indexed page numbers to include.

    Returns:
        Concatenated markdown string with page number headers.
    """
    page_map = {p["page_num"]: p for p in pages}
    parts = []
    for num in page_nums:
        page = page_map.get(num)
        if not page:
            continue
        md = page.get("markdown", "").strip()
        parts.append(f"=== Page {num} ===\n{md}")
    return "\n\n".join(parts)


async def detect_toc(
    pages: List[Dict[str, Any]],
    secrets_manager: Any,
    log_prefix: str = "[TOC]",
) -> Dict[str, Any]:
    """
    Detect the table of contents across the first N pages of the PDF.

    Processes pages in batches of TOC_BATCH_SIZE. Stops when:
    - is_complete=True (full TOC found), or
    - TOC_MAX_PAGES pages have been inspected.

    Accumulates chapters across batches to handle multi-page TOCs.

    Args:
        pages: OCR page list (1-indexed page_num).
        secrets_manager: Initialised SecretsManager.
        log_prefix: Log prefix for traceability.

    Returns:
        Dict with keys: detected (bool), source_pages (list[int]), chapters (list[dict]).
    """
    api_key = await _get_groq_api_key(secrets_manager)
    tool = _build_toc_tool()
    total_pages = len(pages)
    pages_to_check = min(total_pages, TOC_MAX_PAGES)

    accumulated_chapters: List[Dict[str, Any]] = []
    accumulated_source_pages: List[int] = []
    toc_detected = False

    system_prompt = (
        "You are a document analyst. You will be given text extracted from PDF pages. "
        "Your task is to identify if a table of contents (TOC) is present. "
        "Extract all chapter and section titles with their page numbers. "
        "Call report_toc_status with your findings."
    )

    for batch_start in range(1, pages_to_check + 1, TOC_BATCH_SIZE):
        batch_end = min(batch_start + TOC_BATCH_SIZE - 1, pages_to_check)
        batch_page_nums = list(range(batch_start, batch_end + 1))

        text_block = _pages_to_text(pages, batch_page_nums)
        if not text_block.strip():
            continue

        user_message = (
            f"Analyse these PDF pages (pages {batch_start}–{batch_end}) "
            f"and report whether a table of contents is present:\n\n{text_block}"
        )

        logger.info(
            f"{log_prefix} TOC check: pages {batch_start}–{batch_end}"
        )

        result = await _call_groq_with_tool(
            api_key=api_key,
            system_prompt=system_prompt,
            user_message=user_message,
            tool=tool,
            tool_name="report_toc_status",
            log_prefix=log_prefix,
        )

        if result is None:
            logger.warning(f"{log_prefix} TOC detection failed for batch {batch_start}–{batch_end}")
            continue

        if result.get("toc_found"):
            toc_detected = True
            new_source_pages = result.get("source_pages", [])
            new_chapters = result.get("chapters", [])

            # Merge: add only pages/chapters not already accumulated
            for sp in new_source_pages:
                if sp not in accumulated_source_pages:
                    accumulated_source_pages.append(sp)

            # Deduplicate chapters by (title, page) tuple
            existing_keys = {(c["title"], c["page"]) for c in accumulated_chapters}
            for ch in new_chapters:
                key = (ch.get("title", ""), ch.get("page", 0))
                if key not in existing_keys:
                    accumulated_chapters.append(ch)
                    existing_keys.add(key)

            if result.get("is_complete"):
                logger.info(
                    f"{log_prefix} TOC complete at pages {batch_start}–{batch_end}. "
                    f"{len(accumulated_chapters)} chapters found."
                )
                break
        else:
            # No TOC found in this batch. If we already found one earlier, it ended here.
            if toc_detected:
                break

    logger.info(
        f"{log_prefix} TOC detection done: detected={toc_detected}, "
        f"chapters={len(accumulated_chapters)}, source_pages={accumulated_source_pages}"
    )

    return {
        "detected": toc_detected,
        "source_pages": sorted(accumulated_source_pages),
        "chapters": accumulated_chapters,
    }


async def detect_legend(
    pages: List[Dict[str, Any]],
    secrets_manager: Any,
    log_prefix: str = "[Legend]",
) -> Dict[str, Any]:
    """
    Detect a legend, glossary, or list of abbreviations in the last N pages.

    Args:
        pages: OCR page list (1-indexed page_num).
        secrets_manager: Initialised SecretsManager.
        log_prefix: Log prefix for traceability.

    Returns:
        Dict with keys: detected (bool), source_pages (list[int]), content (str).
    """
    api_key = await _get_groq_api_key(secrets_manager)
    tool = _build_legend_tool()
    total_pages = len(pages)

    # Inspect the last LEGEND_LAST_N pages
    last_page_nums = list(range(max(1, total_pages - LEGEND_LAST_N + 1), total_pages + 1))
    text_block = _pages_to_text(pages, last_page_nums)

    if not text_block.strip():
        return {"detected": False, "source_pages": [], "content": ""}

    system_prompt = (
        "You are a document analyst. You will be given text extracted from the last pages "
        "of a PDF. Identify if a legend, glossary, or list of abbreviations/symbols is "
        "present. Call report_legend_status with your findings."
    )

    user_message = (
        f"Analyse these PDF pages (pages {last_page_nums[0]}–{last_page_nums[-1]}) "
        f"and report whether a legend or glossary is present:\n\n{text_block}"
    )

    logger.info(f"{log_prefix} Legend check: pages {last_page_nums}")

    result = await _call_groq_with_tool(
        api_key=api_key,
        system_prompt=system_prompt,
        user_message=user_message,
        tool=tool,
        tool_name="report_legend_status",
        log_prefix=log_prefix,
    )

    if result is None:
        logger.warning(f"{log_prefix} Legend detection failed")
        return {"detected": False, "source_pages": [], "content": ""}

    detected = bool(result.get("legend_found"))
    logger.info(
        f"{log_prefix} Legend detection done: detected={detected}, "
        f"source_pages={result.get('source_pages', [])}"
    )

    return {
        "detected": detected,
        "source_pages": result.get("source_pages", []),
        "content": result.get("content", ""),
    }
