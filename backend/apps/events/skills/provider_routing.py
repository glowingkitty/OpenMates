"""Deterministic routing to the retained official conference source."""
from typing import Sequence
from backend.apps.events.providers.pretalx import is_conference_query

def deterministic_auto_providers(*, query: str, eligible_ids: Sequence[str]) -> tuple[list[str], list[str]]:
    return (["pretalx"] if "pretalx" in eligible_ids and is_conference_query(query) else []), []

async def select_ambiguous_specialists(**kwargs) -> list[str]:
    """No discovery specialists are configured."""
    return []
