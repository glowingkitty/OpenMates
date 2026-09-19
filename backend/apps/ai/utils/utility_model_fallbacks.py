"""Bound utility-model recovery while keeping Google outages independently recoverable."""

from typing import List


MISTRAL_UTILITY_MODEL = "mistral/mistral-small-2506"
DEEPSEEK_UTILITY_MODEL = "deepseek/deepseek-v4-flash"


def utility_model_fallbacks(model_id: str, server_fallbacks: List[str]) -> List[str]:
    """Prefer independent Mistral recovery before a second Google server path.

    Gemini's configured Vertex fallback remains available, but it cannot provide
    vendor independence during a Google outage. Replace the previous DeepSeek
    recovery slot with Mistral instead of adding a fourth attempt that would
    shrink every provider's share of the existing interactive deadline.
    Non-Google utility models retain their established server/DeepSeek recovery.
    """
    independent_model = (
        MISTRAL_UTILITY_MODEL
        if model_id.startswith(("google/", "google_ai_studio/"))
        else DEEPSEEK_UTILITY_MODEL
    )
    excluded = {independent_model, DEEPSEEK_UTILITY_MODEL}
    # google/model may identify Vertex while the identical logical primary
    # resolves to AI Studio. Its concrete fallback must remain available.
    if independent_model != MISTRAL_UTILITY_MODEL:
        excluded.add(model_id)
    servers = list(dict.fromkeys(
        fallback for fallback in server_fallbacks if fallback not in excluded
    ))
    if independent_model == MISTRAL_UTILITY_MODEL:
        return [independent_model, *servers]
    return [*servers, independent_model] if independent_model != model_id else servers
