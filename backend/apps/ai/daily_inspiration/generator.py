# backend/apps/ai/daily_inspiration/generator.py
# LLM-driven generation orchestrator for Daily Inspirations.
#
# For each user, the pipeline is:
# 1. Retrieve the user's recent topic suggestions from cache
# 2. For each inspiration to generate (1-3):
#    a. Pick a topic from the suggestion pool (or use a generic fallback)
#    b. Run find_video_candidates() to get enriched YouTube candidates
#    c. Call the LLM with topic + video candidates → returns selected video + phrase
# 3. Return a list of DailyInspiration objects
#
# The LLM call uses call_preprocessing_llm() (same as post-processing) with
# mistral/mistral-small-latest for cost efficiency.
#
# Architecture note:
# - Each inspiration gets its own video search to avoid re-using the same video.
# - One LLM call is made per user (not per inspiration), passing all inspiration
#   slots at once via an array in the tool schema. This saves tokens and latency.

import logging
import time
import uuid
from typing import Any, Dict, List

from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationVideo
from backend.apps.ai.daily_inspiration.video_processor import find_video_candidates
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Model for inspiration generation — same as post-processing for cost efficiency
INSPIRATION_MODEL_ID = "mistral/mistral-small-latest"

# Available chat categories (must match frontend categoryUtils.ts)
AVAILABLE_CATEGORIES = [
    "software_development",
    "business_development",
    "medical_health",
    "openmates_official",
    "maker_prototyping",
    "marketing_sales",
    "finance",
    "design",
    "electrical_engineering",
    "movies_tv",
    "history",
    "science",
    "life_coach_psychology",
    "cooking_food",
    "activism",
    "general_knowledge",
]

# Tool definition for LLM call (function calling schema)
# The LLM selects one video per inspiration slot and writes a curiosity phrase.
_GENERATE_INSPIRATIONS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_daily_inspirations",
        "description": (
            "Generate daily inspiration items for the user. For each slot, select the most "
            "engaging YouTube video from the provided candidates and write a short, fascinating "
            "English phrase (6-12 words) that sparks curiosity. The phrase should tease what the "
            "user will learn or discover — make it sound exciting and personal. "
            "Example phrases: 'Why do cats always land on their feet?', "
            "'The hidden mathematics behind a perfectly balanced bridge', "
            "'How ancient Romans built roads that lasted 2,000 years'. "
            "IMPORTANT: Each slot must use a different video (no duplicates). "
            "Select videos that are educational, engaging, and family-friendly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "inspirations": {
                    "type": "array",
                    "description": "List of generated inspirations (one per slot requested)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "phrase": {
                                "type": "string",
                                "description": "Short, fascinating English phrase (6-12 words) that sparks curiosity",
                            },
                            "category": {
                                "type": "string",
                                "enum": AVAILABLE_CATEGORIES,
                                "description": "Chat category that best matches this inspiration",
                            },
                            "selected_video_youtube_id": {
                                "type": "string",
                                "description": "YouTube video ID selected from the provided candidates for this slot",
                            },
                        },
                        "required": ["phrase", "category", "selected_video_youtube_id"],
                    },
                },
            },
            "required": ["inspirations"],
        },
    },
}


def _build_generation_prompt(
    topic_suggestions: List[str],
    video_candidates_per_slot: List[List[Dict[str, Any]]],
    count: int,
) -> List[Dict[str, str]]:
    """
    Build the message history for the LLM inspiration generation call.

    Args:
        topic_suggestions: User's recent topic interest phrases (may be empty)
        video_candidates_per_slot: Per-slot list of enriched YouTube candidate dicts
        count: Number of inspirations to generate (1-3)

    Returns:
        Message history list for call_preprocessing_llm()
    """
    # Build a text summary of video candidates for each slot
    slot_descriptions = []
    for slot_idx, candidates in enumerate(video_candidates_per_slot):
        slot_lines = [f"Slot {slot_idx + 1} video candidates:"]
        for i, c in enumerate(candidates):
            view_str = f"{c['view_count']:,}" if c.get("view_count") else "unknown"
            dur = c.get("duration_seconds")
            dur_str = f"{dur // 60}m{dur % 60:02d}s" if dur else "unknown"
            slot_lines.append(
                f"  [{i + 1}] YouTube ID: {c['youtube_id']} | "
                f"Title: {c['title']} | "
                f"Views: {view_str} | "
                f"Duration: {dur_str}"
            )
        slot_descriptions.append("\n".join(slot_lines))

    # Build user interest context
    if topic_suggestions:
        interests_text = (
            "The user's recent conversation topics (use these to personalize the inspirations):\n"
            + "\n".join(f"- {s}" for s in topic_suggestions[:15])
        )
    else:
        interests_text = "No user topic preferences available. Generate broadly interesting inspirations."

    user_message = (
        f"Generate {count} daily inspiration item(s) for this user.\n\n"
        f"{interests_text}\n\n"
        "Available videos for each slot:\n\n"
        + "\n\n".join(slot_descriptions)
        + "\n\nFor each slot, select the best video and write a curiosity-sparking phrase."
    )

    return [{"role": "user", "content": user_message}]


async def generate_inspirations(
    user_id: str,
    count: int,
    topic_suggestions: List[str],
    secrets_manager: SecretsManager,
    task_id: str = "daily_inspiration",
) -> List[DailyInspiration]:
    """
    Generate 1-3 personalized Daily Inspiration items for a user.

    Args:
        user_id: User UUID (for logging only — no user data sent to LLM)
        count: Number of inspirations to generate (1-3)
        topic_suggestions: User's recent topic interest phrases from cache
        secrets_manager: For API key retrieval
        task_id: Task ID for logging

    Returns:
        List of DailyInspiration objects (may be shorter than `count` on errors)
    """
    count = max(1, min(3, count))  # Clamp to 1-3
    logger.info(
        f"[DailyInspiration][{task_id}] Generating {count} inspiration(s) for user {user_id[:8]}..."
    )

    # Step 1: Derive topic phrases to search for
    # Use user's suggestions for diversity; fall back to generic topics
    search_phrases: List[str] = []
    if topic_suggestions:
        # Use distinct suggestions for each slot to avoid duplicates
        used: set = set()
        for suggestion in topic_suggestions:
            if suggestion not in used:
                search_phrases.append(suggestion)
                used.add(suggestion)
            if len(search_phrases) >= count:
                break

    # Fill remaining slots with generic phrases if not enough suggestions
    generic_fallbacks = [
        "fascinating science discoveries",
        "mind-blowing history facts",
        "incredible engineering feats",
        "mysterious natural phenomena",
        "surprising psychology experiments",
    ]
    while len(search_phrases) < count:
        search_phrases.append(generic_fallbacks[len(search_phrases) % len(generic_fallbacks)])

    # Step 2: Search for videos for each slot (in parallel would be ideal but sequential is safer
    # for rate limits — Brave has low quotas)
    video_candidates_per_slot: List[List[Dict[str, Any]]] = []
    all_candidate_map: Dict[str, Dict[str, Any]] = {}  # youtube_id → candidate dict

    for phrase in search_phrases[:count]:
        candidates = await find_video_candidates(phrase, secrets_manager)
        if not candidates:
            logger.warning(
                f"[DailyInspiration][{task_id}] No candidates for phrase '{phrase}' — using empty slot"
            )
        video_candidates_per_slot.append(candidates)
        for c in candidates:
            all_candidate_map[c["youtube_id"]] = c

    # If all slots have no candidates, abort
    if not any(video_candidates_per_slot):
        logger.error(
            f"[DailyInspiration][{task_id}] All video searches returned empty — cannot generate inspirations"
        )
        return []

    # Step 3: Single LLM call to generate all inspiration items
    messages = _build_generation_prompt(topic_suggestions, video_candidates_per_slot, count)

    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=INSPIRATION_MODEL_ID,
        message_history=messages,
        tool_definition=_GENERATE_INSPIRATIONS_TOOL,
        secrets_manager=secrets_manager,
    )

    if result.error_message or not result.arguments:
        logger.error(
            f"[DailyInspiration][{task_id}] LLM call failed: {result.error_message}"
        )
        return []

    raw_inspirations = result.arguments.get("inspirations", [])
    if not raw_inspirations:
        logger.error(
            f"[DailyInspiration][{task_id}] LLM returned no inspirations in tool arguments"
        )
        return []

    # Step 4: Assemble DailyInspiration objects
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    used_youtube_ids: set = set()

    for raw in raw_inspirations[:count]:
        phrase = raw.get("phrase", "").strip()
        category = raw.get("category", "general_knowledge")
        youtube_id = raw.get("selected_video_youtube_id", "").strip()

        if not phrase or not youtube_id:
            logger.warning(
                f"[DailyInspiration][{task_id}] Skipping inspiration with missing phrase or video"
            )
            continue

        if youtube_id in used_youtube_ids:
            logger.warning(
                f"[DailyInspiration][{task_id}] Duplicate youtube_id {youtube_id} — skipping"
            )
            continue

        candidate = all_candidate_map.get(youtube_id)
        if not candidate:
            logger.warning(
                f"[DailyInspiration][{task_id}] LLM selected unknown youtube_id '{youtube_id}' — skipping"
            )
            continue

        video = DailyInspirationVideo(
            youtube_id=youtube_id,
            title=candidate.get("title", ""),
            thumbnail_url=candidate.get("thumbnail_url") or f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg",
            channel_name=candidate.get("channel_name"),
            view_count=candidate.get("view_count"),
            duration_seconds=candidate.get("duration_seconds"),
            published_at=candidate.get("published_at"),
        )

        inspiration = DailyInspiration(
            inspiration_id=str(uuid.uuid4()),
            phrase=phrase,
            category=category if category in AVAILABLE_CATEGORIES else "general_knowledge",
            content_type="video",
            video=video,
            generated_at=now_ts,
        )
        inspirations.append(inspiration)
        used_youtube_ids.add(youtube_id)

    logger.info(
        f"[DailyInspiration][{task_id}] Generated {len(inspirations)}/{count} inspirations "
        f"for user {user_id[:8]}..."
    )
    return inspirations
