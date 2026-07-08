# backend/apps/ai/daily_inspiration/feature_suggestions.py
# Static OpenMates feature tips for Daily Inspirations.
#
# These entries are intentionally deterministic and cheap: no LLM calls, no API
# calls, and no user content is inspected. The daily generator shuffles them into
# each user's ordered inspiration list after personalized video/wiki items are
# prepared. Edit this file to change feature copy or settings destinations.

import os
import time
import uuid
from typing import List

from backend.apps.ai.daily_inspiration.schemas import (
    DailyInspiration,
    DailyInspirationDirectVideo,
    DailyInspirationFeature,
)


PRODUCT_VIDEO_BASE_URL_ENV = "OPENMATES_PRODUCT_VIDEOS_BASE_URL"
DEFAULT_PRODUCT_VIDEO_BASE_URL = (
    "https://openmates-product-media.nbg1.your-objectstorage.com/"
    "daily-inspiration/product-videos/v1"
)
TEASER_ASSET_BASE_PATH = "/daily-inspiration-videos"


FEATURE_TIPS = [
    {
        "feature_id": "export-data",
        "icon": "download",
        "title": "Export your OpenMates data",
        "description": "Back up chats, settings, memories, and more whenever you need them.",
        "settings_path": "account/export",
        "phrase": "Having a backup matters. OpenMates can export your data from settings.",
        "category": "openmates_official",
        "requires_authentication": True,
    },
    {
        "feature_id": "custom-pii-detection",
        "icon": "shield-check",
        "title": "Custom PII detection",
        "description": "Teach OpenMates which personal details should be hidden before model calls.",
        "settings_path": "privacy/hide-personal-data",
        "phrase": "Want stronger privacy controls? Add custom data to PII detection.",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "custom-pii-detection.mp4",
    },
    {
        "feature_id": "events-search",
        "icon": "calendar-search",
        "title": "Find events",
        "description": "Search Meetup, Luma, Google Events, Resident Advisor, and more.",
        "settings_path": "apps/events/skill/search",
        "phrase": "Looking for something to do? OpenMates can search events across multiple sources.",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "events-search.mp4",
    },
    {
        "feature_id": "web-video-skills",
        "icon": "search",
        "title": "Trusted source quotes",
        "description": "Ask mates to inspect sources and quote the exact lines that support an answer.",
        "settings_path": "apps/all/skills",
        "phrase": "Need an answer you can verify? OpenMates can quote the source it used.",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "web-video-skills.mp4",
    },
    {
        "feature_id": "image-detection",
        "icon": "image",
        "title": "AI image detection",
        "description": "Upload an image and see AI-generation signals directly in the chat.",
        "settings_path": "apps/all/skills",
        "phrase": "Wondering if an image was AI-generated? Upload it and inspect the signals.",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "image-detection.mp4",
    },
    {
        "feature_id": "focus-modes",
        "icon": "target",
        "title": "Focus modes",
        "description": "Temporarily guide a chat toward a specific goal for more useful answers.",
        "settings_path": "apps/all/focus_modes",
        "phrase": "Need a more focused answer? Try an OpenMates focus mode.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "memories",
        "icon": "heart",
        "title": "Memories",
        "description": "Save preferences and memories so mates can help without repeated context.",
        "settings_path": "settings_memories",
        "phrase": "Repeating yourself gets old. Memories help OpenMates remember what matters.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "incognito-mode",
        "icon": "mask",
        "title": "Incognito chats",
        "description": "Start temporary chats when you do not want them saved to history.",
        "settings_path": "incognito/info",
        "phrase": "Need a throwaway conversation? Incognito mode keeps it out of history.",
        "category": "openmates_official",
        "requires_authentication": True,
    },
    {
        "feature_id": "privacy-dashboard",
        "icon": "lock",
        "title": "Privacy controls",
        "description": "Tune encryption, personal-data hiding, and privacy preferences in one place.",
        "settings_path": "privacy",
        "phrase": "OpenMates gives you privacy controls worth reviewing before you need them.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
]


def _build_direct_video(tip: dict) -> DailyInspirationDirectVideo | None:
    filename = tip.get("direct_video_filename")
    if not filename:
        return None

    base_url = os.getenv(PRODUCT_VIDEO_BASE_URL_ENV, DEFAULT_PRODUCT_VIDEO_BASE_URL).strip().rstrip("/")
    if not base_url:
        return None

    feature_id = tip["feature_id"]
    teaser_base = f"{TEASER_ASSET_BASE_PATH}/{feature_id}-teaser"
    return DailyInspirationDirectVideo(
        title=tip["title"],
        mp4_url=f"{base_url}/{filename}",
        thumbnail_url=f"{teaser_base}.webp",
        teaser_url=f"{teaser_base}.webm",
        teaser_mp4_url=f"{teaser_base}.mp4",
        teaser_webp_url=f"{teaser_base}.webp",
    )


def feature_requires_authentication(feature_id: str | None) -> bool:
    """Return whether a feature tip is account-only. Unknown legacy IDs stay private."""
    for tip in FEATURE_TIPS:
        if tip["feature_id"] == feature_id:
            return bool(tip.get("requires_authentication", True))
    return True


def build_feature_inspirations(
    count: int = 4,
    *,
    include_authenticated_only: bool = True,
) -> List[DailyInspiration]:
    """Return up to ``count`` static feature inspiration objects."""
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    linked_tips = [
        tip
        for tip in FEATURE_TIPS
        if tip.get("settings_path")
        and (include_authenticated_only or not tip.get("requires_authentication", True))
    ]
    for tip in linked_tips[:max(0, count)]:
        feature = DailyInspirationFeature(
            feature_id=tip["feature_id"],
            icon=tip["icon"],
            title=tip["title"],
            description=tip["description"],
            settings_path=tip["settings_path"],
            requires_authentication=tip.get("requires_authentication", True),
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
                direct_video=_build_direct_video(tip),
                generated_at=now_ts,
                follow_up_suggestions=[],
            )
        )
    return inspirations
