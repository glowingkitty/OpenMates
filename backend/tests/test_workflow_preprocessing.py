"""Workflow Ask AI steps skip the classifier but must still carry required routing fields."""

# contract-test-file: infrastructure

from __future__ import annotations

from backend.apps.ai.processing import preprocessor
from backend.apps.ai.processing.model_routing import LOW_TIER
from backend.apps.ai.processing.workflow_preprocessing import workflow_deterministic_preprocessing_arguments


def test_workflow_arguments_set_china_sensitivity_explicitly_to_the_conservative_default():
    arguments = workflow_deterministic_preprocessing_arguments("de")

    # A missing value made every Workflow AI step log a production ERROR before
    # falling back to True; the explicit value keeps the same model exclusion.
    assert arguments["china_model_sensitive"] is True
    assert arguments["output_language"] == "de"
    assert arguments["complexity"] == LOW_TIER
    assert arguments["harmful_or_illegal"] == 0 and arguments["misuse_risk"] == 0
    assert arguments["relevant_app_skills"] == [] and arguments["relevant_focus_modes"] == []


def test_workflow_arguments_are_fresh_per_request():
    first = workflow_deterministic_preprocessing_arguments("en")
    first["relevant_app_skills"].append("web-search")
    first.pop("china_model_sensitive")

    second = workflow_deterministic_preprocessing_arguments("en")
    assert second["relevant_app_skills"] == []
    assert second["china_model_sensitive"] is True


def test_preprocessor_uses_the_shared_workflow_arguments():
    assert preprocessor.workflow_deterministic_preprocessing_arguments is workflow_deterministic_preprocessing_arguments
