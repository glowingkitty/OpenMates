"""Bounded, order-preserving concurrent per-chat reads for Phase 1b sync.

Readers must be read-only: callers merge the returned results afterwards in the
original chat order, so ordering, first-chat-wins deduplication and the phase
message order stay identical to the former sequential loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Collection, Dict, List, Optional, Sequence, Tuple

from backend.core.api.app.routes.handlers.websocket_handlers.sync_delta_hints import select_sync_embeds


async def read_chats_bounded(
    chat_ids: Sequence[str],
    reader: Callable[[str], Awaitable[Any]],
    *,
    concurrency: int,
) -> Tuple[List[Tuple[str, Any]], List[Tuple[str, BaseException]]]:
    """Run ``reader`` per chat with at most ``concurrency`` in flight.

    Returns ``(results, failures)``: successful ``(chat_id, result)`` pairs in
    input order, and ``(chat_id, error)`` pairs for chats whose read raised.
    One failing chat never discards the others. If the caller is cancelled,
    every outstanding read is cancelled and drained before re-raising.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(chat_id: str) -> Any:
        async with semaphore:
            return await reader(chat_id)

    tasks = [asyncio.create_task(run(chat_id)) for chat_id in chat_ids]
    try:
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    results: List[Tuple[str, Any]] = []
    failures: List[Tuple[str, BaseException]] = []
    for chat_id, outcome in zip(chat_ids, outcomes):
        if isinstance(outcome, (Exception, asyncio.CancelledError)):
            failures.append((chat_id, outcome))
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            results.append((chat_id, outcome))
    return results, failures


def merge_phase1b_reads(
    reads: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    sent_embed_ids: set,
    client_embed_ids: Optional[Collection[str]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Merge per-chat Phase 1b reads in chat order into one frame payload.

    Embeds and embed keys shared between chats go to the first chat in order,
    exactly as the former sequential loop did. Returns the payload fields and
    the embed skip-reason counters.
    """
    payload: Dict[str, Any] = {
        "chats": [],
        "embeds": [],
        "embed_windows_by_chat_id": {},
        "embed_keys": [],
        "embed_key_windows_by_chat_id": {},
        "chat_key_wrappers": [],
        "chat_key_wrapper_windows_by_chat_id": {},
        "code_run_outputs": [],
        "code_run_output_windows_by_chat_id": {},
        "notebook_run_outputs": [],
        "notebook_run_output_windows_by_chat_id": {},
    }
    seen_embed_ids: set = set()
    seen_key_ids: set = set()
    embed_skip_reasons: Dict[str, int] = {}
    for chat_id, read in reads:
        payload["chats"].append(read["chat"])
        embeds = read["embeds"]
        if embeds is not None:
            payload["embed_windows_by_chat_id"][chat_id] = embeds["window"]
            payload["embed_key_windows_by_chat_id"][chat_id] = embeds["key_window"]
            payload["embeds"].extend(select_sync_embeds(
                embeds["raw"],
                seen_embed_ids=seen_embed_ids,
                sent_embed_ids=sent_embed_ids,
                client_embed_ids=client_embed_ids,
                skip_reasons=embed_skip_reasons,
            ))
            for key_entry in embeds["keys"]:
                key_id = key_entry.get("id")
                if key_id and key_id not in seen_key_ids:
                    payload["embed_keys"].append(key_entry)
                    seen_key_ids.add(key_id)
        for rows_key, windows_key, read_key in (
            ("code_run_outputs", "code_run_output_windows_by_chat_id", "code_run"),
            ("notebook_run_outputs", "notebook_run_output_windows_by_chat_id", "notebook_run"),
            ("chat_key_wrappers", "chat_key_wrapper_windows_by_chat_id", "key_wrappers"),
        ):
            rows, windows = read[read_key]
            payload[rows_key].extend(rows)
            payload[windows_key].update(windows)
    return payload, embed_skip_reasons
