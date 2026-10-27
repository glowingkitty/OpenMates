# backend/apps/ai/daily_inspiration/wiki_suggestions.py
# Static public Wikipedia inspirations for unauthenticated/default Daily Inspirations.
#
# Personalized users get wiki cards from wiki_generator.py. Public defaults can be
# incomplete when the daily pool has only video rows, so this module provides a
# deterministic, privacy-safe fallback with no LLM or network dependency.

import time
import uuid
from typing import List

from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationWiki

from backend.apps.ai.daily_inspiration.static_localization import localized_static_copy


WIKI_TIPS = [
    {
        "wiki_title": "Antikythera_mechanism",
        "category": "history",
    },
    {
        "wiki_title": "Bioluminescence",
        "category": "science",
    },
    {
        "wiki_title": "Collective_animal_behavior",
        "category": "science",
    },
    {
        "wiki_title": "Library_of_Alexandria",
        "category": "history",
    },
    {
        "wiki_title": "Tensegrity",
        "category": "design",
    },
    {
        "wiki_title": "Fermi_paradox",
        "category": "science",
    },
]


WIKI_COPY_KEYS = ("antikythera", "bioluminescence", "collective", "alexandria", "tensegrity", "fermi")


def build_wiki_inspirations(count: int = 3, *, language: str = "en") -> List[DailyInspiration]:
    """Return up to ``count`` static public wiki inspiration objects."""
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    for index, tip in enumerate(WIKI_TIPS[:max(0, count)]):
        content_language, copy = localized_static_copy(WIKI_COPY_KEYS[index], language)
        tip = {**tip, **copy}
        wiki = DailyInspirationWiki(
            source_language="en",
            title=tip["title"],
            wiki_title=tip["wiki_title"],
            description=tip["description"],
            extract=tip["assistant_response"],
        )
        inspirations.append(
            DailyInspiration(
                inspiration_id=str(uuid.uuid4()),
                language=content_language,
                phrase=tip["phrase"],
                title=tip["title"],
                assistant_response=tip["assistant_response"],
                category=tip["category"],
                content_type="wiki",
                wiki=wiki,
                generated_at=now_ts,
                follow_up_suggestions=[],
            )
        )
    return inspirations
