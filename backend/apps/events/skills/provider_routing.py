"""Bounded, auto-only specialist routing for public event searches."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from typing import Any, Mapping, Optional, Sequence

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.shared.providers.typesafe.models import NoulAnswer

logger = logging.getLogger(__name__)

GENERAL_PROVIDERS = frozenset({"meetup", "luma", "eventbrite"})
SPECIALIST_PROVIDERS = frozenset({"resident_advisor", "siegessaeule", "berlin_philharmonic"})
_JEV_ROUTING_BUDGET_SECONDS = 0.9
_JEV_INCLUDE_THRESHOLD = 0.70

_CLEAR_SPECIALIST_TERMS: dict[str, frozenset[str]] = {
    "resident_advisor": frozenset({
        "techno", "rave", "raves", "dj", "djs", "edm", "electronic", "elektronisch",
        "club", "clubbing", "nightclub", "nightlife", "nachtleben", "house music",
    }),
    "siegessaeule": frozenset({
        "lgbtq", "lgbt", "queer", "pride", "lesbian", "lesbisch", "gay", "schwul",
        "transgender", "nonbinary", "non binary",
    }),
    "berlin_philharmonic": frozenset({
        "classical", "klassik", "klassische", "philharmonic", "philharmonie",
        "orchestra", "orchester", "symphony", "sinfonie", "chamber music",
        "kammermusik", "piano", "klavier",
    }),
}
_AMBIGUOUS_SPECIALIST_TERMS = frozenset({
    "dance", "tanz", "music", "musik", "concert", "konzert", "live performance",
    "underground", "festival", "night out", "party", "parties", "social gathering",
})
_CROSS_SPECIALIST_TERMS = frozenset({"dance", "tanz", "party", "parties", "night out"})


def _normalized_query(query: str) -> str:
    value = unicodedata.normalize("NFKD", query.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(
        char for char in value if not unicodedata.combining(char)
    )))


def _has_term(query: str, terms: frozenset[str]) -> bool:
    return any(f" {term} " in f" {query} " for term in terms)


def deterministic_auto_providers(
    *,
    query: str,
    eligible_ids: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Return immediate providers and eligible ambiguous specialists, in registry order."""
    normalized = _normalized_query(query)
    immediate = [pid for pid in eligible_ids if pid in GENERAL_PROVIDERS]
    explicit_specialists = {
        pid for pid in eligible_ids
        if pid in SPECIALIST_PROVIDERS
        and _has_term(normalized, _CLEAR_SPECIALIST_TERMS.get(pid, frozenset()))
    }
    immediate.extend(pid for pid in eligible_ids if pid in explicit_specialists)
    needs_semantic_decision = _has_term(normalized, _AMBIGUOUS_SPECIALIST_TERMS) and (
        not explicit_specialists or _has_term(normalized, _CROSS_SPECIALIST_TERMS)
    )
    ambiguous = (
        [pid for pid in eligible_ids if pid in SPECIALIST_PROVIDERS and pid not in explicit_specialists]
        if needs_semantic_decision
        else []
    )
    return immediate, ambiguous


async def select_ambiguous_specialists(
    *,
    query: str,
    location: str,
    event_type: Optional[str],
    candidates: Sequence[str],
    provider_metadata: Sequence[Mapping[str, Any]],
    secrets_manager: Optional[SecretsManager],
) -> list[str]:
    """Select useful eligible specialists; a failed decision safely selects none."""
    if not candidates:
        return []
    descriptions = {
        str(meta.get("id")): str(meta.get("routing_description") or "")[:200]
        for meta in provider_metadata
    }
    questions = {
        pid: {
            "type": "noul",
            "instructions": {
                "question": "Would this specialist materially improve coverage for this event search?",
                "provider": pid,
                "provider_capability": descriptions.get(pid, ""),
            },
            "criteria": {
                "true": "The request is clearly related to this provider's specialty.",
                "false": "The provider is only tangential or unrelated to the request.",
            },
        }
        for pid in candidates
    }
    started = time.monotonic()
    try:
        client = JevDecisionClient(
            secrets_manager=secrets_manager,
            timeout_seconds=_JEV_ROUTING_BUDGET_SECONDS,
            max_retries=0,
        )
        response = await asyncio.wait_for(
            client.evaluate(
                state={
                    "task": "select_event_specialists",
                    "query": query[:200],
                    "location": location[:120],
                    "event_type": event_type,
                    "eligible_specialists": list(candidates),
                },
                questions=questions,
            ),
            timeout=_JEV_ROUTING_BUDGET_SECONDS,
        )
        selected = [
            pid for pid in candidates
            if isinstance(response.answers.get(pid), NoulAnswer)
            and response.answers[pid].noul >= _JEV_INCLUDE_THRESHOLD
        ]
        logger.info(
            "Event specialist decision selected=%s candidates=%s latency_ms=%.1f",
            selected, list(candidates), (time.monotonic() - started) * 1000,
        )
        return selected
    except Exception as exc:
        logger.info(
            "Event specialist decision fell back reason=%s latency_ms=%.1f",
            type(exc).__name__, (time.monotonic() - started) * 1000,
        )
        return []
