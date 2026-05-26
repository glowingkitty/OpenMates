# backend/apps/ai/daily_inspiration/wiki_generator.py
# Personalized Wikipedia article generation for Daily Inspirations.
#
# This is the low-cost companion to the video pipeline: one small LLM call turns
# recent topic suggestions into candidate article titles, then the existing
# Wikimedia provider validates titles and fetches public summaries. No user IDs
# are sent to Wikimedia and no live browser requests are made from the client.

import logging
import random
import time
import uuid
from typing import Any, Dict, List

from backend.apps.ai.daily_inspiration.content_filter import is_blocked_topic
from backend.apps.ai.daily_inspiration.generator import AVAILABLE_CATEGORIES, INSPIRATION_MODEL_ID
from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationWiki
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.wikipedia.wikipedia_api import batch_validate_topics, fetch_page_summary

logger = logging.getLogger(__name__)


def _language_base(language: str) -> str:
    return (language or "en").lower().split("-")[0].split("_")[0]


def _build_wiki_tool_definition(language: str) -> Dict[str, Any]:
    lang_base = _language_base(language)
    phrase_lang = "English" if lang_base == "en" else f"the user's language (ISO code: {lang_base})"
    return {
        "type": "function",
        "function": {
            "name": "generate_wiki_inspirations",
            "description": "Suggest Wikipedia article inspirations based on recent user topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "articles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "wiki_title": {
                                    "type": "string",
                                    "description": "Canonical Wikipedia article title/slug, e.g. Albert_Einstein.",
                                },
                                "phrase": {
                                    "type": "string",
                                    "description": f"Curiosity phrase in {phrase_lang}, 8-18 words, two short sentences.",
                                },
                                "title": {
                                    "type": "string",
                                    "description": f"Concise chat title in {phrase_lang}, 3-7 words.",
                                },
                                "assistant_response": {
                                    "type": "string",
                                    "description": f"3-5 sentence intro in {phrase_lang} inviting exploration of the article topic.",
                                },
                                "category": {
                                    "type": "string",
                                    "enum": AVAILABLE_CATEGORIES,
                                },
                                "follow_up_suggestions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 3,
                                    "maxItems": 3,
                                },
                            },
                            "required": [
                                "wiki_title",
                                "phrase",
                                "title",
                                "assistant_response",
                                "category",
                                "follow_up_suggestions",
                            ],
                        },
                    }
                },
                "required": ["articles"],
            },
        },
    }


async def generate_wiki_inspirations(
    topic_suggestions: List[str],
    secrets_manager: SecretsManager,
    *,
    count: int = 3,
    language: str = "en",
    task_id: str = "daily_inspiration_wiki",
) -> List[DailyInspiration]:
    """Generate personalized Wikipedia-based daily inspirations."""
    count = max(0, min(3, count))
    if count == 0:
        return []

    filtered_topics = [t for t in dict.fromkeys(topic_suggestions) if not is_blocked_topic(t)]
    if filtered_topics:
        sampled_topics = random.sample(filtered_topics, min(15, len(filtered_topics)))
        topic_context = "Recent user topics:\n" + "\n".join(f"- {topic}" for topic in sampled_topics)
    else:
        topic_context = "No recent topics are available. Pick broadly interesting educational articles."

    lang_base = _language_base(language)
    lang_instruction = "" if lang_base == "en" else f"\nWrite all user-facing text in ISO language {lang_base}."
    messages = [
        {
            "role": "user",
            "content": (
                f"Generate {count} Wikipedia article daily inspirations.\n\n"
                f"{topic_context}\n\n"
                "Choose notable, specific, non-promotional Wikipedia articles that match the user's interests. "
                "Avoid brands, product promotion, party politics, religious promotion, explicit/sensitive content, "
                "and OpenMates-related topics. Prefer concepts, people, places, scientific ideas, history, culture, "
                "or technology topics with broad educational value. Use canonical Wikipedia titles with underscores."
                f"{lang_instruction}"
            ),
        }
    ]

    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=INSPIRATION_MODEL_ID,
        message_history=messages,
        tool_definition=_build_wiki_tool_definition(language),
        secrets_manager=secrets_manager,
    )
    if result.error_message or not result.arguments:
        logger.warning("[DailyInspiration][%s] Wiki LLM failed: %s", task_id, result.error_message)
        return []

    raw_articles = result.arguments.get("articles", [])
    if not isinstance(raw_articles, list):
        return []

    candidate_titles = [
        str(item.get("wiki_title", "")).strip()
        for item in raw_articles
        if isinstance(item, dict) and item.get("wiki_title")
    ]
    validated = await batch_validate_topics(candidate_titles, language=lang_base)
    valid_by_title = {topic.wiki_title.lower(): topic for topic in validated}
    valid_by_original = {topic.topic.lower(): topic for topic in validated}

    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    for raw in raw_articles:
        if len(inspirations) >= count or not isinstance(raw, dict):
            break
        raw_title = str(raw.get("wiki_title", "")).strip()
        valid = valid_by_title.get(raw_title.lower()) or valid_by_original.get(raw_title.lower())
        if not valid:
            continue

        summary = await fetch_page_summary(valid.wiki_title.replace(" ", "_"), language=lang_base)
        phrase = str(raw.get("phrase", "")).strip()
        title = str(raw.get("title", "")).strip() or valid.wiki_title
        assistant_response = str(raw.get("assistant_response", "")).strip() or None
        category = str(raw.get("category", "general_knowledge")).strip()
        raw_suggestions = raw.get("follow_up_suggestions", [])
        follow_up_suggestions = (
            [s.strip() for s in raw_suggestions if isinstance(s, str) and s.strip()][:3]
            if isinstance(raw_suggestions, list)
            else []
        )
        if not phrase:
            continue

        wiki = DailyInspirationWiki(
            title=summary.get("title") if summary else valid.wiki_title,
            wiki_title=valid.wiki_title.replace(" ", "_"),
            description=(summary or {}).get("description") or valid.description,
            thumbnail_url=((summary or {}).get("thumbnail") or {}).get("source") or valid.thumbnail_url,
            wikidata_id=valid.wikidata_id,
            extract=(summary or {}).get("extract"),
        )
        inspirations.append(
            DailyInspiration(
                inspiration_id=str(uuid.uuid4()),
                phrase=phrase,
                title=title,
                assistant_response=assistant_response,
                category=category if category in AVAILABLE_CATEGORIES else "general_knowledge",
                content_type="wiki",
                wiki=wiki,
                generated_at=now_ts,
                follow_up_suggestions=follow_up_suggestions,
            )
        )

    logger.info("[DailyInspiration][%s] Generated %d/%d wiki inspirations", task_id, len(inspirations), count)
    return inspirations
