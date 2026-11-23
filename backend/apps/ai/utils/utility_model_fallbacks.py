"""Bound utility-model recovery while keeping Google outages independently recoverable."""

from typing import List


# Utility work that has no configured primary (chat title/summary translation) uses the
# same low-latency Gemini model as preprocessing. Mistral models are never an automatic
# choice (owner decision, 21 Nov); they stay selectable by users.
UTILITY_TRANSLATION_MODEL = "google/gemini-3.5-flash-lite"
INDEPENDENT_UTILITY_MODEL = "inception/mercury-3"
DEEPSEEK_UTILITY_MODEL = "deepseek/deepseek-v4-flash"


def utility_model_fallbacks(model_id: str, server_fallbacks: List[str]) -> List[str]:
    """Prefer independent Mercury recovery before a second Google server path.

    Gemini's configured Vertex fallback remains available, but it cannot provide
    vendor independence during a Google outage. Replace the previous DeepSeek
    recovery slot with Mercury 3 instead of adding a fourth attempt that would
    shrink every provider's share of the existing interactive deadline.
    Non-Google utility models retain their established server/DeepSeek recovery.
    """
    google_primary = model_id.startswith(("google/", "google_ai_studio/"))
    independent_model = INDEPENDENT_UTILITY_MODEL if google_primary else DEEPSEEK_UTILITY_MODEL
    excluded = {independent_model, DEEPSEEK_UTILITY_MODEL}
    # google/model may identify Vertex while the identical logical primary
    # resolves to AI Studio. Its concrete fallback must remain available.
    if not google_primary:
        excluded.add(model_id)
    servers = list(dict.fromkeys(
        fallback for fallback in server_fallbacks if fallback not in excluded
    ))
    if google_primary:
        return [independent_model, *servers]
    return [*servers, independent_model] if independent_model != model_id else servers
