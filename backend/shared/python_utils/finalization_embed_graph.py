# backend/shared/python_utils/finalization_embed_graph.py
"""Request-scoped decoded embed reuse for AI finalization validators.

The graph coalesces concurrent reads only within one request and never stores
nodes globally. Callers must invalidate an embed after any in-request mutation
so the next validator reloads the current encrypted cache version.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class FinalizationEmbedNode:
    toon: str
    decoded: dict[str, Any]


class FinalizationEmbedGraph:
    """Load and decode each unchanged embed at most once per request."""

    def __init__(
        self,
        embed_service: Any,
        user_vault_key_id: str,
        log_prefix: str = "",
        *,
        decoder: Callable[[str], Any] | None = None,
    ) -> None:
        self._embed_service = embed_service
        self._user_vault_key_id = user_vault_key_id
        self._log_prefix = log_prefix
        self._decoder = decoder
        self._loads: dict[str, asyncio.Task[FinalizationEmbedNode | None]] = {}

    async def get(self, embed_id: str) -> FinalizationEmbedNode | None:
        task = self._loads.get(embed_id)
        if task is None:
            task = asyncio.create_task(self._load(embed_id))
            self._loads[embed_id] = task
        try:
            return await task
        except BaseException:
            if self._loads.get(embed_id) is task:
                self._loads.pop(embed_id, None)
            raise

    def invalidate(self, embed_id: str) -> None:
        # Existing readers finish against their immutable snapshot; subsequent
        # readers create a fresh load without cancelling unrelated validators.
        self._loads.pop(embed_id, None)

    async def verify_quote(self, embed_id: str, quoted_text: str) -> bool:
        node = await self.get(embed_id)
        if node is None or not quoted_text:
            return False
        normalized_quote = self._embed_service._normalize_for_quote_comparison(quoted_text)
        searchable = self._embed_service._extract_searchable_text(node.decoded)
        normalized_content = self._embed_service._normalize_for_quote_comparison(searchable)
        return bool(normalized_quote and normalized_quote in normalized_content)

    async def _load(self, embed_id: str) -> FinalizationEmbedNode | None:
        toon = await self._embed_service._get_cached_embed_toon(
            embed_id,
            self._user_vault_key_id,
            self._log_prefix,
        )
        if not toon:
            return None
        if self._decoder is None:
            from toon_format import decode

            decoded = decode(toon)
        else:
            decoded = self._decoder(toon)
        if not isinstance(decoded, dict):
            return None
        return FinalizationEmbedNode(toon=toon, decoded=decoded)
