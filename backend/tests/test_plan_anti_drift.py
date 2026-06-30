"""Tests for Plans V1 anti-drift and AI evaluation steering contracts."""

from types import SimpleNamespace

from backend.core.api.app.services.user_plan_service import UserPlanService


def test_drift_scores_map_to_actions() -> None:
    service = UserPlanService(SimpleNamespace())

    assert service.drift_decision(10)["recommended_action"] == "continue"
    assert service.drift_decision(45)["recommended_action"] == "steer_back"
    assert service.drift_decision(75)["recommended_action"] == "ask_user"
    assert service.drift_decision(95)["recommended_action"] == "stop"


def test_correction_message_is_system_display_but_user_role_for_llm() -> None:
    service = UserPlanService(SimpleNamespace())

    message = service.build_correction_message(
        "plan-1",
        72,
        "Return to AC-2 before starting new social media ideas.",
        task_id="task-1",
    )

    assert message["display_role"] == "system"
    assert message["llm_role"] == "user"
    assert message["origin"] == "system_generated"
    assert message["recommended_action"] == "ask_user"


def test_failed_ai_evaluation_message_keeps_plan_active() -> None:
    service = UserPlanService(SimpleNamespace())
    message = service.build_ai_evaluation_correction(
        plan_id="plan-1",
        task_id="task-1",
        score=78,
        threshold=85,
        required_fixes=["Add licensing comparison", "Cite current sources"],
    )

    assert message["display_role"] == "system"
    assert message["llm_role"] == "user"
    assert message["score"] == 78
    assert message["threshold"] == 85
    assert message["plan_status"] == "active"
    assert "Add licensing comparison" in message["content"]
