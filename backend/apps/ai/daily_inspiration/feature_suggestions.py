# backend/apps/ai/daily_inspiration/feature_suggestions.py
# Static OpenMates feature tips for Daily Inspirations.
#
# These entries are intentionally deterministic and cheap: no LLM calls, no API
# calls, and no user content is inspected. The daily generator shuffles them into
# each user's ordered inspiration list after personalized video/wiki items are
# prepared. Copy lives in shared i18n YAML; settings destinations live here.

import os
import time
import uuid
from collections import Counter
from typing import Any, List, Mapping, Sequence

from backend.apps.ai.daily_inspiration.schemas import (
    DailyInspiration,
    DailyInspirationDirectVideo,
    DailyInspirationFeature,
)

from backend.apps.ai.daily_inspiration.static_localization import localized_static_copy


PRODUCT_VIDEO_BASE_URL_ENV = "OPENMATES_PRODUCT_VIDEOS_BASE_URL"
DEFAULT_PRODUCT_VIDEO_BASE_URL = (
    "https://openmates-product-media.nbg1.your-objectstorage.com/"
    "daily-inspiration/product-videos/v1"
)
TEASER_ASSET_BASE_PATH = "/daily-inspiration-videos"
GUEST_ONBOARDING_FEATURE_IDS = frozenset(
    {
        "openmates-intro",
        "openmates-actionable-events",
        "openmates-privacy-safety",
        "openmates-mates-focus",
        "openmates-provider-cross-platform",
        "openmates-signup-cta",
    }
)
DAILY_INSPIRATION_TYPE_QUOTAS = {"video": 3, "wiki": 3, "feature": 4}


def has_complete_daily_inspiration_set(
    inspirations: Sequence[Mapping[str, Any]],
) -> bool:
    if len(inspirations) != sum(DAILY_INSPIRATION_TYPE_QUOTAS.values()):
        return False
    counts = Counter(item.get("content_type") for item in inspirations)
    return all(
        counts[content_type] == count
        for content_type, count in DAILY_INSPIRATION_TYPE_QUOTAS.items()
    )


FEATURE_TIPS = [
    {
        "feature_id": "export-data",
        "icon": "download",
        "settings_path": "account/export",
        "category": "openmates_official",
        "requires_authentication": True,
    },
    {
        "feature_id": "custom-pii-detection",
        "icon": "shield-check",
        "settings_path": "privacy/hide-personal-data",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "custom-pii-detection.mp4",
    },
    {
        "feature_id": "events-search",
        "icon": "calendar-search",
        "settings_path": "apps/events/skill/search",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "events-search.mp4",
    },
    {
        "feature_id": "web-video-skills",
        "icon": "search",
        "settings_path": "apps/all/skills",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "web-video-skills.mp4",
    },
    {
        "feature_id": "image-detection",
        "icon": "image",
        "settings_path": "apps/all/skills",
        "category": "openmates_official",
        "requires_authentication": False,
        "direct_video_filename": "image-detection.mp4",
    },
    {
        "feature_id": "focus-modes",
        "icon": "target",
        "settings_path": "apps/all/focus_modes",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "memories",
        "icon": "heart",
        "settings_path": "settings_memories",
        "category": "openmates_official",
        "requires_authentication": False,
    },
    {
        "feature_id": "incognito-mode",
        "icon": "mask",
        "settings_path": "incognito/info",
        "category": "openmates_official",
        "requires_authentication": True,
    },
    {
        "feature_id": "privacy-dashboard",
        "icon": "lock",
        "settings_path": "privacy",
        "category": "openmates_official",
        "requires_authentication": False,
    },
]


FEATURE_COPY_KEYS = {
    "export-data": "export",
    "custom-pii-detection": "pii",
    "events-search": "events",
    "web-video-skills": "quotes",
    "image-detection": "image_detection",
    "focus-modes": "focus",
    "memories": "memories",
    "incognito-mode": "incognito",
    "privacy-dashboard": "privacy",
}


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
    language: str = "en",
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
        content_language, copy = localized_static_copy(FEATURE_COPY_KEYS[tip["feature_id"]], language)
        tip = {**tip, **copy}
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
                language=content_language,
                phrase=tip["phrase"],
                title=tip["title"],
                assistant_response=tip["assistant_response"],
                category=tip["category"],
                content_type="feature",
                feature=feature,
                direct_video=_build_direct_video(tip),
                generated_at=now_ts,
                follow_up_suggestions=[],
            )
        )
    return inspirations
