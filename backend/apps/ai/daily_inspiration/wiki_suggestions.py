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


WIKI_TIPS = [
    {
        "title": "The Antikythera mechanism",
        "wiki_title": "Antikythera_mechanism",
        "description": "An ancient Greek hand-powered model of the cosmos.",
        "phrase": "An ancient shipwreck held a machine that predicted the sky.",
        "assistant_response": "The Antikythera mechanism is often described as the oldest known analog computer. It used bronze gears to model astronomical cycles, eclipses, and calendar timing. Open it to explore how much engineering knowledge existed more than 2,000 years ago.",
        "category": "history",
    },
    {
        "title": "Bioluminescence",
        "wiki_title": "Bioluminescence",
        "description": "Living organisms producing light through chemistry.",
        "phrase": "Some animals make their own light. The chemistry is surprisingly elegant.",
        "assistant_response": "Bioluminescence lets organisms glow for hunting, camouflage, communication, and defense. It appears across deep-sea animals, fungi, bacteria, and insects. Open it to learn how chemistry becomes light without heat.",
        "category": "science",
    },
    {
        "title": "Murmuration",
        "wiki_title": "Murmuration",
        "description": "Coordinated flock movement that creates living patterns in the sky.",
        "phrase": "Thousands of birds turn as one. No conductor is in charge.",
        "assistant_response": "A murmuration is a flock movement pattern where simple local reactions create large coordinated waves. Each bird responds to nearby neighbors, yet the whole group looks choreographed. Open it to explore how complex behavior can emerge from simple rules.",
        "category": "nature",
    },
    {
        "title": "Library of Alexandria",
        "wiki_title": "Library_of_Alexandria",
        "description": "One of the ancient world's most famous centers of knowledge.",
        "phrase": "The ancient world's most famous library was also a research institution.",
        "assistant_response": "The Library of Alexandria was part of a larger scholarly ecosystem attached to the Mouseion. It gathered texts, hosted scholars, and became a symbol of ambitious knowledge preservation. Open it to separate the legend from what historians actually know.",
        "category": "history",
    },
    {
        "title": "Tensegrity",
        "wiki_title": "Tensegrity",
        "description": "Structures stabilized by a balance of tension and compression.",
        "phrase": "Some structures seem to float because tension does the hidden work.",
        "assistant_response": "Tensegrity structures use isolated compression elements held together by continuous tension. The result can look impossibly light while remaining stable. Open it to see why artists, architects, and biologists all care about this principle.",
        "category": "design",
    },
    {
        "title": "Fermi paradox",
        "wiki_title": "Fermi_paradox",
        "description": "The tension between likely extraterrestrial life and no clear evidence.",
        "phrase": "If the universe is so large, why does it seem so quiet?",
        "assistant_response": "The Fermi paradox asks why we have not seen convincing evidence of extraterrestrial civilizations despite the scale and age of the universe. Possible answers range from rare life to communication limits to self-destruction risks. Open it to explore one of science's biggest open questions.",
        "category": "space",
    },
]


def build_wiki_inspirations(count: int = 3) -> List[DailyInspiration]:
    """Return up to ``count`` static public wiki inspiration objects."""
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    for tip in WIKI_TIPS[:max(0, count)]:
        wiki = DailyInspirationWiki(
            title=tip["title"],
            wiki_title=tip["wiki_title"],
            description=tip["description"],
            extract=tip["assistant_response"],
        )
        inspirations.append(
            DailyInspiration(
                inspiration_id=str(uuid.uuid4()),
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
