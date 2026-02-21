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

# Language code → Brave search country mapping.
# Maps UI locale codes to the closest Brave country/language pair.
# For unknown locales, falls back to "us"/"en".
_LANGUAGE_TO_SEARCH_PARAMS: Dict[str, Dict[str, str]] = {
    "en": {"country": "us", "search_lang": "en"},
    "de": {"country": "de", "search_lang": "de"},
    "es": {"country": "es", "search_lang": "es"},
    "fr": {"country": "fr", "search_lang": "fr"},
    "it": {"country": "it", "search_lang": "it"},
    "pt": {"country": "br", "search_lang": "pt"},
    "nl": {"country": "nl", "search_lang": "nl"},
    "pl": {"country": "pl", "search_lang": "pl"},
    "ru": {"country": "ru", "search_lang": "ru"},
    "ja": {"country": "jp", "search_lang": "ja"},
    "ko": {"country": "kr", "search_lang": "ko"},
    "zh": {"country": "cn", "search_lang": "zh"},
    "ar": {"country": "sa", "search_lang": "ar"},
    "hi": {"country": "in", "search_lang": "hi"},
    "tr": {"country": "tr", "search_lang": "tr"},
    "sv": {"country": "se", "search_lang": "sv"},
    "da": {"country": "dk", "search_lang": "da"},
    "fi": {"country": "fi", "search_lang": "fi"},
    "no": {"country": "no", "search_lang": "no"},
    "uk": {"country": "ua", "search_lang": "uk"},
    "cs": {"country": "cz", "search_lang": "cs"},
    "ro": {"country": "ro", "search_lang": "ro"},
    "hu": {"country": "hu", "search_lang": "hu"},
    "el": {"country": "gr", "search_lang": "el"},
    "he": {"country": "il", "search_lang": "he"},
    "th": {"country": "th", "search_lang": "th"},
    "vi": {"country": "vn", "search_lang": "vi"},
    "id": {"country": "id", "search_lang": "id"},
}


def get_search_params_for_language(language: str) -> Dict[str, str]:
    """
    Get Brave search country/language params for a given UI locale code.

    Falls back to English defaults for unsupported locales.
    """
    lang_base = (language or "en").lower().split("-")[0].split("_")[0]
    return _LANGUAGE_TO_SEARCH_PARAMS.get(lang_base, {"country": "us", "search_lang": "en"})


def _build_tool_definition(language: str) -> Dict[str, Any]:
    """
    Build the LLM tool definition with a language-specific phrase description.

    The tool schema tells the LLM what language to write the curiosity phrase in.
    English is used when language is "en" or unrecognised.

    Args:
        language: User's UI language code (e.g. "en", "de", "es")
    """
    lang_base = (language or "en").lower().split("-")[0].split("_")[0]

    if lang_base == "en":
        phrase_lang_instruction = "English"
    else:
        # Tell the LLM the target language explicitly
        phrase_lang_instruction = f"the user's language (ISO code: {lang_base})"

    return {
        "type": "function",
        "function": {
            "name": "generate_daily_inspirations",
            "description": (
                "Generate daily inspiration items for the user. For each slot, select the most "
                "engaging YouTube video from the provided candidates and write a short, fascinating "
                f"phrase in {phrase_lang_instruction} (6-12 words) that sparks curiosity. "
                "The phrase should tease what the user will learn or discover — make it sound "
                "exciting and personal. "
                "Example phrases (English): 'Why do cats always land on their feet?', "
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
                                    "description": (
                                        f"Short, fascinating phrase in {phrase_lang_instruction} "
                                        "(6-12 words) that sparks curiosity"
                                    ),
                                },
                                "category": {
                                    "type": "string",
                                    "enum": AVAILABLE_CATEGORIES,
                                    "description": "Chat category that best matches this inspiration",
                                },
                                "selected_video_youtube_id": {
                                    "type": "string",
                                    "description": (
                                        "YouTube video ID selected from the provided candidates "
                                        "for this slot"
                                    ),
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
    language: str = "en",
) -> List[Dict[str, str]]:
    """
    Build the message history for the LLM inspiration generation call.

    Args:
        topic_suggestions: User's recent topic interest phrases (may be empty)
        video_candidates_per_slot: Per-slot list of enriched YouTube candidate dicts
        count: Number of inspirations to generate (1-3)
        language: User's UI language code (e.g. "en", "de"). Used to instruct the
                  LLM to write the phrase in the user's language.

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

    # Determine language instruction for the LLM
    lang_base = (language or "en").lower().split("-")[0].split("_")[0]
    if lang_base == "en":
        lang_instruction = ""
    else:
        lang_instruction = (
            f"\n\nIMPORTANT: Write ALL phrases in the user's language (ISO code: {lang_base}). "
            "Do NOT write in English."
        )

    user_message = (
        f"Generate {count} daily inspiration item(s) for this user.\n\n"
        f"{interests_text}\n\n"
        "Available videos for each slot:\n\n"
        + "\n\n".join(slot_descriptions)
        + "\n\nFor each slot, select the best video and write a curiosity-sparking phrase."
        + lang_instruction
    )

    return [{"role": "user", "content": user_message}]


async def generate_inspirations(
    user_id: str,
    count: int,
    topic_suggestions: List[str],
    secrets_manager: SecretsManager,
    task_id: str = "daily_inspiration",
    language: str = "en",
) -> List[DailyInspiration]:
    """
    Generate 1-3 personalized Daily Inspiration items for a user.

    Args:
        user_id: User UUID (for logging only — no user data sent to LLM)
        count: Number of inspirations to generate (1-3)
        topic_suggestions: User's recent topic interest phrases from cache
        secrets_manager: For API key retrieval
        task_id: Task ID for logging
        language: User's UI language code (e.g. "en", "de"). Controls the language
                  of the generated curiosity phrase and the Brave video search locale.

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

    # Resolve Brave search locale params from the user's UI language
    search_params = get_search_params_for_language(language)

    for phrase in search_phrases[:count]:
        candidates = await find_video_candidates(
            phrase, secrets_manager, language=language,
            country=search_params["country"], search_lang=search_params["search_lang"],
        )
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
    messages = _build_generation_prompt(
        topic_suggestions, video_candidates_per_slot, count, language=language,
    )
    tool_def = _build_tool_definition(language)

    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=INSPIRATION_MODEL_ID,
        message_history=messages,
        tool_definition=tool_def,
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
