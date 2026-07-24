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
        "feature_id": "openmates-intro",
        "icon": "sparkles",
        "title": "OpenMates for Everyone",
        "description": "Ask naturally and let specialized mates and apps help from one workspace.",
        "settings_path": "apps/all/skills",
        "phrase": "Simply ask your AI team mates.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "openmates-actionable-events",
        "icon": "calendar-search",
        "title": "Actionable results",
        "description": "Search for real-world options and inspect useful details from one chat.",
        "settings_path": "apps/events/skill/search",
        "phrase": "Actionable. Not just a wall of text.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "openmates-privacy-safety",
        "icon": "shield-check",
        "title": "Privacy & safety",
        "description": "Encrypted chats and clear controls help you decide what is shared, when, and why.",
        "settings_path": "privacy",
        "phrase": "Privacy & safety by design.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "openmates-mates-focus",
        "icon": "users",
        "title": "Mates & focus modes",
        "description": "Use specialized guidance for different jobs without leaving the chat workspace.",
        "settings_path": "apps/all/focus_modes",
        "phrase": "Specialized team mates and focus modes.",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "openmates-provider-cross-platform",
        "icon": "network",
        "title": "Independent workspace",
        "description": "Avoid locking your work into one model provider or one app surface.",
        "settings_path": "apps/all/skills",
        "phrase": "Provider independent and cross-platform.",
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
    count: int = 5,
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
