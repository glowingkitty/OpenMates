"""Bounded copy recovery; every attempt must pass the same source review."""
import asyncio
import logging

from backend.apps.ai.daily_inspiration.config import FALLBACK_WRITER, writer_model

logger = logging.getLogger(__name__)
ATTEMPT_TIMEOUT_SECONDS = 30
RETRY_DELAY_SECONDS = .5


def _complete_arguments(arguments, collection, count):
    """Reject malformed/empty copy before assembly, without English word rules."""
    rows = arguments.get(collection) if isinstance(arguments, dict) else None
    # The source-aware assembler may discard extra unselected identities. The
    # admitted set must still have exactly count cards, all from its catalogue.
    if not isinstance(rows, list) or not count <= len(rows) <= 10:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        identity = "wiki_title" if collection == "articles" else "selected_video_youtube_id"
        if any(not isinstance(row.get(key), str) or not row[key].strip()
               for key in (identity, "phrase", "title", "assistant_response")):
            return False
        suggestions = row.get("follow_up_suggestions")
        if (not isinstance(suggestions, list) or len(suggestions) != 3
                or any(not isinstance(value, str) or not value.strip() for value in suggestions)):
            return False
    return True


async def write_reviewed_cards(*, writer_call, accept, count, collection, **request):
    """Mercury twice, then Flash Lite once; errors and rejected copy both recover.

    Discovery/evidence stay fixed. No rejected draft becomes source evidence, no
    facade fallback multiplies these three logical attempts. The Mercury adapter
    also disables SDK retries. If every attempt
    fails review, callers retain their existing incomplete-set/static recovery.
    """
    primary = writer_model()
    best = []
    for index, model in enumerate((primary, primary, FALLBACK_WRITER)):
        if index == 1:
            await asyncio.sleep(RETRY_DELAY_SECONDS)
        try:
            result = await asyncio.wait_for(writer_call(
                **request, model_id=model, fallback_models=[], allow_retries=False,
                reasoning_effort="low", temperature=.5, max_output_tokens=4096,
                observability_purpose="inspiration",
                single_attempt_timeout_seconds=ATTEMPT_TIMEOUT_SECONDS,
            ), timeout=ATTEMPT_TIMEOUT_SECONDS)
            if result.error_message or not _complete_arguments(result.arguments, collection, count):
                reason = "provider_or_shape_failure"
            else:
                cards = await accept(result.arguments)
                if len(cards) == count:
                    logger.info("Daily writer accepted: model=%s attempt=%d cards=%d", model, index + 1, count)
                    return cards
                if len(cards) > len(best):
                    best = cards
                reason = "editorial_or_source_rejection"
        except Exception as error:
            reason = type(error).__name__
        logger.warning("Daily writer attempt withheld: model=%s attempt=%d reason=%s", model, index + 1, reason)
    return best
