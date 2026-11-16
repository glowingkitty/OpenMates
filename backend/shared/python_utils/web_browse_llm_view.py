"""What the assistant model sees of a saved Browse result.

A Browse embed keeps the full result for the client: the page screenshot
(base64, tens of thousands of characters), timing metrics and the runtime
observations. Resolved into chat history as is, two form turns already put
~90k tokens of base64 into the next prompt, and the model began copying the
embed back as a text tool call. The model needs the answer, status, sources
and the safety-scanned form view (`observations.form`, flattened to
`observations_form` in the saved TOON), never the image bytes or metrics.
Specification: feature.app-skill.web-browse (form-with-user, session-and-run).
"""

from __future__ import annotations

from typing import Any

_DROPPED_KEYS = frozenset({"screenshot_base64", "metrics", "observations"})
_DROPPED_PREFIXES = ("screenshot_ref", "metrics_", "observations_")
_KEPT_OBSERVATIONS = frozenset({"observations_form"})


def _model_field(key: str) -> bool:
    if key in _KEPT_OBSERVATIONS:
        return True
    return key not in _DROPPED_KEYS and not key.startswith(_DROPPED_PREFIXES)


def browse_result_for_model(result: dict[str, Any]) -> dict[str, Any]:
    """Drop screenshot bytes, metrics and observations except the form view."""
    kept = {key: value for key, value in result.items() if _model_field(key)}
    observations = result.get("observations")
    if isinstance(observations, dict) and observations.get("form"):
        kept["observations"] = {"form": observations["form"]}
    return kept


def browse_embed_for_model(decoded: dict[str, Any]) -> dict[str, Any]:
    """Apply browse_result_for_model to a saved web/browse embed and its results."""
    filtered = browse_result_for_model(decoded)
    results = decoded.get("results")
    if isinstance(results, list):
        filtered["results"] = [
            browse_result_for_model(item) if isinstance(item, dict) else item
            for item in results
        ]
    return filtered
