"""Chat workflow authoring receives trusted dispatch context."""

from backend.apps.workflows.skills.chat_authoring_context import (
    is_natural_language_authoring_call,
    with_trusted_timezone,
)


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
def test_only_natural_language_workflow_call_gets_scoped_execution_policy() -> None:
    assert is_natural_language_authoring_call("workflows", "create-or-modify", {"instruction": "Create an alert"})
    assert not is_natural_language_authoring_call("workflows", "create-or-modify", {"graph": {}})
    assert not is_natural_language_authoring_call("weather", "forecast", {"instruction": "Create an alert"})


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.schedule.recurrence
def test_server_timezone_replaces_model_value_without_mutating_arguments() -> None:
    arguments = {"instruction": "Daily in my timezone", "timezone": "Antarctica/Troll"}
    assert with_trusted_timezone(arguments, "Europe/Vienna") == {
        "instruction": "Daily in my timezone", "timezone": "Europe/Vienna",
    }
    assert arguments["timezone"] == "Antarctica/Troll"
    assert with_trusted_timezone(arguments, None)["timezone"] == "UTC"
