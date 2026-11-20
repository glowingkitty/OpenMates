"""Deterministic preprocessing arguments for isolated Workflow "Ask AI" steps.

A Workflow graph already chose the source app and the input values, so its AI
steps skip the classification LLM. The preprocessor still runs credit, safety,
model-selection and language handling on these arguments, so they must carry
every field those stages read as required.
"""

from typing import Any, Dict

from backend.apps.ai.processing.model_routing import LOW_TIER


def workflow_deterministic_preprocessing_arguments(output_language: str) -> Dict[str, Any]:
    """Return the fixed preprocessing decision used for a Workflow AI request.

    ``china_model_sensitive`` stays True, the documented conservative default:
    no classifier ran, so China-origin models are excluded as before.
    """
    return {
        "harmful_or_illegal": 0,
        "misuse_risk": 0,
        "category": "general_knowledge",
        "topic_area": "general",
        "complexity": LOW_TIER,
        "china_model_sensitive": True,
        "relevant_app_skills": [],
        "relevant_focus_modes": [],
        "relevant_embedded_previews": [],
        "load_app_settings_and_memories": [],
        "output_language": output_language,
        "llm_response_temp": 0.4,
    }
