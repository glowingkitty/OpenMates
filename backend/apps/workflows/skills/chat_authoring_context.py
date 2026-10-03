"""Small chat-side policy for natural-language Workflow authoring calls."""

from __future__ import annotations

from typing import Any


WORKFLOW_AUTHORING_TOOL_INSTRUCTION = (
    "When saving workflows through workflows-create-or-modify, pass one complete "
    "natural-language instruction containing every requested workflow and all "
    "details settled in this conversation. Use the instruction field, not title "
    "or graph. For one immediate execution, set execution_mode=run_once and pass "
    "explicit input, Send-node destination overrides, or typed return outputs only "
    "when requested; the chat-owned definition stays in the encrypted chat embed. "
    "Saved mode validates and saves new workflows disabled, preserves the "
    "enabled state of complete edits, and may ask for clarification. A partial "
    "edit updates the original workflow and disables it; relay its recovery "
    "message and do not describe it as complete. Remind users to activate new "
    "workflows themselves. Report only workflow "
    "IDs confirmed saved by the tool; if it asks for clarification or reports a "
    "pending save, do not claim the workflows were saved."
)


def is_natural_language_authoring_call(app_id: str, skill_id: str, arguments: dict[str, Any]) -> bool:
    return (
        app_id == "workflows" and skill_id == "create-or-modify"
        and isinstance(arguments.get("instruction"), str)
    )


def with_trusted_timezone(arguments: dict[str, Any], timezone: str | None) -> dict[str, Any]:
    """Use server-known user timezone instead of a model-supplied value."""
    return {**arguments, "timezone": timezone or "UTC"}
