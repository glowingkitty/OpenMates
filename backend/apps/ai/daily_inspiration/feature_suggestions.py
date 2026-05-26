# backend/apps/ai/daily_inspiration/feature_suggestions.py
# Static OpenMates feature tips for Daily Inspirations.
#
# These entries are intentionally deterministic and cheap: no LLM calls, no API
# calls, and no user content is inspected. The daily generator shuffles them into
# each user's ordered inspiration list after personalized video/wiki items are
# prepared. Edit this file to change feature copy or settings destinations.

import time
import uuid
from typing import List

from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationFeature


FEATURE_TIPS = [
    {
        "feature_id": "export-data",
        "icon": "download",
        "title": "Export your OpenMates data",
        "description": "Back up chats, settings, memories, and more whenever you need them.",
        "settings_path": "account/export",
        "phrase": "Having a backup matters. OpenMates can export your data from settings.",
        "category": "openmates_official",
    },
    {
        "feature_id": "custom-pii-detection",
        "icon": "shield-check",
        "title": "Custom PII detection",
        "description": "Teach OpenMates which personal details should be hidden before model calls.",
        "settings_path": "privacy/hide-personal-data",
        "phrase": "Want stronger privacy controls? Add custom data to PII detection.",
        "category": "openmates_official",
    },
    {
        "feature_id": "focus-modes",
        "icon": "target",
        "title": "Focus modes",
        "description": "Temporarily guide a chat toward a specific goal for more useful answers.",
        "settings_path": "app_store/all/focus_modes",
        "phrase": "Need a more focused answer? Try an OpenMates focus mode.",
        "category": "openmates_official",
    },
    {
        "feature_id": "settings-memories",
        "icon": "heart",
        "title": "Settings and memories",
        "description": "Save preferences and memories so mates can help without repeated context.",
        "settings_path": "settings_memories",
        "phrase": "Repeating yourself gets old. Memories help OpenMates remember what matters.",
        "category": "openmates_official",
    },
    {
        "feature_id": "events-search",
        "icon": "calendar-search",
        "title": "Find events",
        "description": "Search Meetup, Luma, Google Events, Resident Advisor, and more.",
        "settings_path": "app_store/events/skill/search",
        "phrase": "Looking for something to do? OpenMates can search events across multiple sources.",
        "category": "openmates_official",
    },
    {
        "feature_id": "web-video-skills",
        "icon": "search",
        "title": "Search and videos",
        "description": "Use app skills to search the web, inspect pages, and find useful videos.",
        "settings_path": "app_store/all/skills",
        "phrase": "OpenMates can do more than chat. App skills connect mates to useful sources.",
        "category": "openmates_official",
    },
    {
        "feature_id": "incognito-mode",
        "icon": "mask",
        "title": "Incognito chats",
        "description": "Start temporary chats when you do not want them saved to history.",
        "settings_path": "privacy/incognito",
        "phrase": "Need a throwaway conversation? Incognito mode keeps it out of history.",
        "category": "openmates_official",
    },
    {
        "feature_id": "connected-apps",
        "icon": "plug",
        "title": "Connected apps",
        "description": "Review which app skills your mates can use and adjust them anytime.",
        "settings_path": "app_store/all/apps",
        "phrase": "Your mates can use apps for real tasks. Check which ones are available.",
        "category": "openmates_official",
    },
    {
        "feature_id": "privacy-dashboard",
        "icon": "lock",
        "title": "Privacy controls",
        "description": "Tune encryption, personal-data hiding, and privacy preferences in one place.",
        "settings_path": "privacy",
        "phrase": "OpenMates gives you privacy controls worth reviewing before you need them.",
        "category": "openmates_official",
    },
    {
        "feature_id": "keyboard-shortcuts",
        "icon": "keyboard",
        "title": "Faster navigation",
        "description": "Use shortcuts and focused navigation to move through chats more quickly.",
        "settings_path": "settings/shortcuts",
        "phrase": "A few shortcuts can make OpenMates feel much faster.",
        "category": "openmates_official",
    },
]


def build_feature_inspirations(count: int = 4) -> List[DailyInspiration]:
    """Return up to ``count`` static feature inspiration objects."""
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    for tip in FEATURE_TIPS[:max(0, count)]:
        feature = DailyInspirationFeature(
            feature_id=tip["feature_id"],
            icon=tip["icon"],
            title=tip["title"],
            description=tip["description"],
            settings_path=tip["settings_path"],
        )
        inspirations.append(
            DailyInspiration(
                inspiration_id=str(uuid.uuid4()),
                phrase=tip["phrase"],
                title=tip["title"],
                assistant_response=tip["description"],
                category=tip["category"],
                content_type="feature",
                feature=feature,
                generated_at=now_ts,
                follow_up_suggestions=[],
            )
        )
    return inspirations
