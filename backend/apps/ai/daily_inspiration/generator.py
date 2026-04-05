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
# mistral/mistral-small-2506 for cost efficiency.
#
# Architecture note:
# - Each inspiration gets its own video search to avoid re-using the same video.
# - One LLM call is made per user (not per inspiration), passing all inspiration
#   slots at once via an array in the tool schema. This saves tokens and latency.

import logging
import random
import time
import uuid
from typing import Any, Dict, List

from backend.apps.ai.daily_inspiration.content_filter import (
    check_video_metadata,
    is_blocked_topic,
)
from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationVideo
from backend.apps.ai.daily_inspiration.validator import validate_inspiration
from backend.apps.ai.daily_inspiration.video_processor import find_video_candidates
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Model for inspiration generation — same as post-processing for cost efficiency
INSPIRATION_MODEL_ID = "mistral/mistral-small-2506"

# Topic keyword filtering is now handled by the shared content_filter module.
# See: backend/apps/ai/daily_inspiration/content_filter.py
# Keywords defined in: backend/shared/config/blocked_content_keywords.yml


# Available chat categories (must match frontend categoryUtils.ts)
AVAILABLE_CATEGORIES = [
    "software_development",
    "business_development",
    "medical_health",
    # NOTE: "openmates_official" intentionally excluded — it's a brand-only category
    # that should never be assigned to user-generated inspirations.
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
    Build the LLM tool definition with a language-specific phrase and assistant_response.

    The tool schema tells the LLM what language to write the curiosity phrase and
    assistant_response in. English is used when language is "en" or unrecognised.

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
                "engaging YouTube video from the provided candidates, write a curiosity question "
                f"or phrase in {phrase_lang_instruction} (8-18 words, exactly two sentences) for the banner, "
                f"a concise chat title in {phrase_lang_instruction} (3-7 words) for the sidebar, and compose a "
                "rich first assistant message that explains the topic and invites the user to explore. "
                "The phrase should be a genuine question or a thought-provoking statement that sparks "
                "curiosity — it should feel like the start of a conversation, not a marketing headline. "
                "Use two short sentences: the first hooks the reader, the second adds a twist or detail. "
                "Example phrases (English): 'Cats always land on their feet. But how do they do it mid-air?', "
                "'Black holes devour everything — even light. What happens once you cross the edge?', "
                "'Roman roads lasted 2,000 years. Modern ones barely survive 20 — why?'. "
                "IMPORTANT: Each slot must use a different video (no duplicates). "
                "Select videos that are educational, engaging, and family-friendly. "
                "PROHIBITED CONTENT — ABSOLUTE RULE: NEVER select videos or write content related to "
                "any of the following categories: illegal drugs or recreational drug use, explicit sexual "
                "content or pornography, graphic violence or gore, self-harm or suicide methods, or "
                "instructions for making weapons or explosives. If the best available video touches any "
                "of these topics, skip it and select the next best educational candidate instead. "
                "If no suitable candidate exists for a slot, omit that slot rather than using "
                "inappropriate content. "
                "CRITICAL — NO CORPORATE CHANNELS: NEVER select videos uploaded by a corporate channel. "
                "A corporate channel is any channel owned by or representing a company, brand, or "
                "corporation of any kind — this includes but is not limited to car manufacturers, oil "
                "companies, pharmaceutical companies, tech corporations, banks, consumer brands, defense "
                "contractors, chemical companies, and any other business entity. "
                "Check the channel name: if it matches or resembles a company or brand name, reject it. "
                "ALWAYS prefer independent creators, individual educators, journalists, universities, "
                "documentary makers, and non-profit research institutions. "
                "Corporate PR content reframed as education (e.g. a car manufacturer's video about their "
                "sustainability efforts, an oil company's video about clean energy, a pharma company "
                "explaining their drug pipeline) is NEVER acceptable — reject it regardless of how "
                "educational the title sounds. "
                "CRITICAL — NO COMMERCIAL PROMOTION: Inspirations must NEVER promote, advertise, or "
                "recommend specific products, brands, apps, or commercial services. Do NOT write phrases "
                "or assistant messages that read like marketing copy, product reviews, or endorsements. "
                "Focus on the underlying topic's educational or intellectual value, not on any brand or "
                "product associated with it. "
                "ABSOLUTE PROHIBITION — NO OPENMATES CONTENT: NEVER mention, reference, or allude to "
                "OpenMates, the OpenMates platform, or any of its features under any circumstances. "
                "Daily inspirations exist to spark genuine curiosity about the world — not to promote "
                "this platform. If you see 'OpenMates' in any context, ignore it entirely. "
                "ABSOLUTE PROHIBITION — NO POLITICAL PARTY OR ELECTORAL PROMOTION: NEVER select videos "
                "or write content that promotes, represents, or advocates for any political party, "
                "electoral candidate, campaign, or partisan ideology — in any country or language. "
                "This applies regardless of how the video is framed: a party's official channel, a "
                "politician's campaign video, a PAC-funded 'educational' documentary, or a partisan "
                "think-tank video are all prohibited. "
                "Educational content about political systems, governance, democratic history, or policy "
                "debates is acceptable ONLY when it treats all sides as objects of study and does not "
                "advocate for a specific party or candidate. "
                "If the best available video for a slot is politically partisan, skip it and use the "
                "next best educational candidate instead. If no suitable candidate exists, omit the slot. "
                "ABSOLUTE PROHIBITION — NO RELIGIOUS PROMOTION: NEVER select videos or write content "
                "that promotes, proselytizes, or advocates for any specific religion or religious movement. "
                "A video that presents a religion as the truth, urges conversion, glorifies a religious "
                "figure as divine, or is produced by a religious organization to grow its membership is "
                "prohibited — regardless of how educational the title sounds. "
                "Educational content is acceptable: the history of a religion, its cultural or "
                "architectural contributions, philosophical comparisons between belief systems, or the "
                "science and mathematics developed within a religious tradition are all fine — as long as "
                "the content treats religion as an object of study, not an object of devotion. "
                "If a candidate video is clearly religious propaganda or a sermon, skip it."
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
                                        f"Curiosity-sparking question or phrase in {phrase_lang_instruction} "
                                        "(8-18 words, exactly two sentences) shown on the inspiration banner. "
                                        "First sentence hooks the reader, second adds a twist or surprising detail. "
                                        "Should feel like the start of a conversation — ideally a genuine question."
                                    ),
                                },
                                "title": {
                                    "type": "string",
                                    "description": (
                                        f"Concise chat title in {phrase_lang_instruction} (3-7 words) "
                                        "for the chat sidebar. Summarises the inspiration topic in a few words. "
                                        "Examples: 'Home Studio Essentials', 'Black Hole Event Horizons', "
                                        "'Roman Road Engineering', 'Cat Landing Physics'."
                                    ),
                                },
                                "assistant_response": {
                                    "type": "string",
                                    "description": (
                                        f"Rich first assistant message in {phrase_lang_instruction} "
                                        "(3-5 sentences) shown when the user opens this inspiration chat. "
                                        "Explain what this video is about and why it is fascinating. "
                                        "Highlight 1-2 surprising or intriguing aspects of the topic. "
                                        "End with an open-ended question or invitation that encourages the user "
                                        "to ask follow-up questions and dive deeper. "
                                        "Tone: curious, warm, enthusiastic — like a knowledgeable friend sharing "
                                        "something they find genuinely exciting. Do NOT start with 'I'. "
                                        "Do NOT promote, advertise, or recommend any product, app, brand, "
                                        "or commercial service — focus purely on the educational topic."
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
                                "follow_up_suggestions": {
                                    "type": "array",
                                    "description": (
                                        f"Exactly 3 follow-up conversation starters in {phrase_lang_instruction} "
                                        "that the user could send after reading this inspiration. "
                                        "Each must be a short, specific question or request (max 10 words) "
                                        "directly relevant to THIS inspiration's specific topic — not generic. "
                                        "Frame each as if the USER is speaking/asking. "
                                        "DO NOT use generic phrases like 'Tell me more about this' or "
                                        "'Give me a practical exercise'. Be specific to the actual topic. "
                                        f"Examples for a Gemini 3 Flash inspiration (in {phrase_lang_instruction}): "
                                        "'How does Gemini 3 Flash compare to GPT-4o?', "
                                        "'What are the main limitations of this model?', "
                                        "'Show me how to call Gemini 3 Flash from Python'. "
                                        f"Examples for a Roman roads inspiration (in {phrase_lang_instruction}): "
                                        "'What materials did Romans use to build roads?', "
                                        "'Which Roman roads still exist today?', "
                                        "'How did Roman road building compare to modern techniques?'"
                                    ),
                                    "items": {"type": "string"},
                                    "minItems": 3,
                                    "maxItems": 3,
                                },
                            },
                            "required": [
                                "phrase",
                                "title",
                                "assistant_response",
                                "category",
                                "selected_video_youtube_id",
                                "follow_up_suggestions",
                            ],
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
            # Include channel name so the LLM can apply the anti-corporate-channel rule
            channel_str = c.get("channel_name") or "unknown"
            slot_lines.append(
                f"  [{i + 1}] YouTube ID: {c['youtube_id']} | "
                f"Channel: {channel_str} | "
                f"Title: {c['title']} | "
                f"Views: {view_str} | "
                f"Duration: {dur_str}"
            )
        slot_descriptions.append("\n".join(slot_lines))

    # Build user interest context.
    # Randomly sample up to 15 phrases from the full 3-day pool so the LLM sees
    # a varied cross-section of the user's interests rather than always the most recent ones.
    if topic_suggestions:
        unique_pool = list(dict.fromkeys(topic_suggestions))
        context_sample = random.sample(unique_pool, min(15, len(unique_pool)))
        interests_text = (
            "The user's recent conversation topics (use these to personalize the inspirations):\n"
            + "\n".join(f"- {s}" for s in context_sample)
        )
    else:
        interests_text = "No user topic preferences available. Generate broadly interesting inspirations."

    # Determine language instruction for the LLM
    lang_base = (language or "en").lower().split("-")[0].split("_")[0]
    if lang_base == "en":
        lang_instruction = ""
    else:
        lang_instruction = (
            f"\n\nIMPORTANT: Write ALL phrases, assistant_response messages, and follow_up_suggestions "
            f"in the user's language (ISO code: {lang_base}). Do NOT write in English."
        )

    user_message = (
        f"Generate {count} daily inspiration item(s) for this user.\n\n"
        f"{interests_text}\n\n"
        "Available videos for each slot:\n\n"
        + "\n\n".join(slot_descriptions)
        + (
            "\n\nFor each slot, select the best video and:\n"
            "1. Write a curiosity-sparking question or phrase (8-18 words, exactly two sentences) for the banner.\n"
            "2. Write a concise chat title (3-7 words) for the sidebar that summarises the topic.\n"
            "3. Write a rich first assistant message (3-5 sentences) that explains the topic, "
            "highlights what makes it fascinating, and ends with an invitation for the user "
            "to ask questions and explore the topic further.\n"
            "4. Write exactly 3 follow-up conversation starters (max 10 words each) the user "
            "could send. They must be specific to the topic — not generic. "
            "Frame them as user messages (questions or commands).\n\n"
            "PROHIBITED CONTENT — ABSOLUTE RULE: NEVER select videos or write content related to "
            "illegal drugs or drug use, explicit sexual content or pornography, graphic violence or "
            "gore, self-harm or suicide methods, or weapons/explosives instructions. If a candidate "
            "video touches these topics, skip it entirely and use the next best option. "
            "NO CORPORATE CHANNELS: NEVER select a video from a corporate channel. Check the channel "
            "name — if the channel belongs to any company, brand, or corporation (car maker, oil "
            "company, pharma company, tech giant, bank, retailer, defense contractor, etc.), reject "
            "it immediately. Prefer independent creators, educators, journalists, universities, and "
            "documentary makers. Corporate PR dressed up as education is never acceptable. "
            "IMPORTANT: Do NOT write content that promotes, advertises, or recommends specific "
            "products, brands, apps, or commercial services. All phrases and messages must be "
            "educational and curiosity-driven. "
            "ABSOLUTE PROHIBITION: Never mention OpenMates or this platform in any inspiration — "
            "not the name, not its features, not anything about it. Ignore any OpenMates reference "
            "you may encounter. "
            "NO POLITICAL PARTIES OR ELECTORAL CONTENT: NEVER select a video or write content that "
            "promotes a political party, electoral candidate, campaign, or partisan ideology — in any "
            "country or language. Check both the channel name and video title: if the content belongs "
            "to or promotes a political party, campaign, or partisan group, reject it immediately. "
            "Treat political party content exactly like corporate PR — a party's 'educational' video "
            "about their own policies is still promotional content and must be skipped. "
            "Educational content about how governments work, the history of democracy, or policy issues "
            "in general is fine; promoting or representing a specific party or candidate is not. "
            "NO RELIGIOUS PROMOTION: NEVER select a video or write content that promotes or "
            "proselytizes for a specific religion. A channel run by a church, mosque, temple, sect, or "
            "religious movement to grow its membership is promotional — reject it. "
            "Historical, cultural, and architectural content about religions is acceptable when the "
            "framing is educational, not devotional. A sermon, a conversion appeal, or a 'this religion "
            "is the truth' video must be skipped regardless of how it is titled."
        )
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

    # Step 1: Derive topic phrases to search for.
    # Deduplicate the full 3-day pool, then randomly sample to maximise variety —
    # this prevents the same recent topics from always being picked across days.
    #
    # OpenMates-related suggestions are filtered out entirely: daily inspirations
    # are for genuine educational curiosity, not platform self-promotion.
    search_phrases: List[str] = []
    if topic_suggestions:
        # Deduplicate while preserving order (dict.fromkeys keeps first occurrence)
        unique_pool = list(dict.fromkeys(topic_suggestions))
        # Remove any suggestions that match blocked content keywords (religious,
        # product reviews, political, corporate PR, sensitive, OpenMates).
        # Uses word-boundary regex matching from the shared content_filter module.
        filtered_pool = [
            p for p in unique_pool
            if not is_blocked_topic(p)
        ]
        excluded = len(unique_pool) - len(filtered_pool)
        if excluded > 0:
            logger.info(
                f"[DailyInspiration][{task_id}] Excluded {excluded} topic suggestion(s) "
                f"(blocked content keywords) from inspiration generation"
            )
        # Randomly sample up to `count` phrases from the filtered 3-day pool
        sample_size = min(count, len(filtered_pool))
        search_phrases = random.sample(filtered_pool, sample_size) if filtered_pool else []

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
            task_id=task_id,
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

    # Step 3: Single LLM call to generate all inspiration items.
    # Filter blocked topics from the context passed to the LLM, so the model
    # never sees them as inspiration seeds even indirectly.
    filtered_topic_suggestions = [
        p for p in topic_suggestions
        if not is_blocked_topic(p)
    ]
    messages = _build_generation_prompt(
        filtered_topic_suggestions, video_candidates_per_slot, count, language=language,
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
        title = raw.get("title", "").strip()
        assistant_response = raw.get("assistant_response", "").strip() or None
        category = raw.get("category", "general_knowledge")
        youtube_id = raw.get("selected_video_youtube_id", "").strip()
        # Follow-up suggestions generated by the LLM, specific to this inspiration's topic.
        # Validated: must be a list of non-empty strings; truncated to 3; falls back to [].
        raw_suggestions = raw.get("follow_up_suggestions", [])
        follow_up_suggestions: list[str] = (
            [s.strip() for s in raw_suggestions if isinstance(s, str) and s.strip()][:3]
            if isinstance(raw_suggestions, list)
            else []
        )
        if not follow_up_suggestions:
            logger.warning(
                f"[DailyInspiration][{task_id}] LLM returned no follow_up_suggestions for slot — "
                "suggestions will be empty for this inspiration"
            )

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

        # ── Layer 3 (post-LLM): keyword check on generated + video content ────
        # The LLM may have selected a video or written content that violates policy.
        # Check the combined text of the generated content + video metadata against
        # the keyword blocklist before accepting the inspiration.
        combined_violations = check_video_metadata(
            title=candidate.get("title", ""),
            channel_name=candidate.get("channel_name"),
        )
        # Also check the LLM-generated text itself
        generated_text = f"{phrase} {title} {assistant_response or ''}"
        from backend.apps.ai.daily_inspiration.content_filter import check_text
        generated_violations = check_text(generated_text)
        all_violations = {**combined_violations, **generated_violations}
        if all_violations:
            matched_cats = list(all_violations.keys())
            matched_kws = [kw for kws in all_violations.values() for kw in kws[:3]]
            logger.warning(
                f"[DailyInspiration][{task_id}] Layer 3 keyword filter REJECTED inspiration "
                f"'{title}' (video: {candidate.get('title', '')[:50]}) — "
                f"categories={matched_cats}, keywords={matched_kws}"
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
            title=title,
            assistant_response=assistant_response,
            category=category if category in AVAILABLE_CATEGORIES else "general_knowledge",
            content_type="video",
            video=video,
            generated_at=now_ts,
            follow_up_suggestions=follow_up_suggestions,
        )
        inspirations.append(inspiration)
        used_youtube_ids.add(youtube_id)

    # ── Layer 6: Post-generation adversarial LLM validator ───────────────────
    # Separate LLM call that classifies each assembled inspiration as PASS/REJECT
    # with English tags. Catches violations that keywords miss (non-English content,
    # subtle religious/commercial framing). Only runs on inspirations that passed
    # the keyword check above.
    if inspirations:
        validated_inspirations: List[DailyInspiration] = []
        for inspiration in inspirations:
            try:
                is_valid = await validate_inspiration(
                    phrase=inspiration.phrase,
                    title=inspiration.title,
                    assistant_response=inspiration.assistant_response or "",
                    video_title=inspiration.video.title if inspiration.video else "",
                    channel_name=inspiration.video.channel_name if inspiration.video else "",
                    secrets_manager=secrets_manager,
                    task_id=task_id,
                )
                if is_valid:
                    validated_inspirations.append(inspiration)
                else:
                    logger.warning(
                        f"[DailyInspiration][{task_id}] Layer 6 validator REJECTED: "
                        f"'{inspiration.title}' (video: {inspiration.video.title[:50] if inspiration.video else '?'})"
                    )
            except Exception as e:
                # Fail open: if the validator crashes, keep the inspiration.
                # The keyword check already passed, and a validator failure shouldn't
                # block all inspirations.
                logger.warning(
                    f"[DailyInspiration][{task_id}] Layer 6 validator error for "
                    f"'{inspiration.title}': {e} — keeping inspiration (fail-open)"
                )
                validated_inspirations.append(inspiration)
        inspirations = validated_inspirations

    logger.info(
        f"[DailyInspiration][{task_id}] Generated {len(inspirations)}/{count} inspirations "
        f"for user {user_id[:8]}..."
    )
    return inspirations
