# backend/shared/testing/mock_context.py
# Per-request context variables and marker detection for live mock testing.
#
# The live mock system runs the full processing pipeline but intercepts external
# API calls (LLM providers, skill HTTP requests) with cached responses. Activation
# is per-request via markers in the user message, so real users on the same server
# are never affected.
#
# Markers:
#   <<<TEST_LIVE_MOCK:group_id>>>    — replay cached API responses (error if cache miss)
#   <<<TEST_LIVE_RECORD:group_id>>>  — call real APIs and record responses for replay
#
# Security: Disabled in production. Requires MOCK_EXTERNAL_APIS=true env var.
#
# Architecture context: See docs/architecture/live-mock-testing.md

import contextvars
import logging
import os
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Per-task context variables — only set when a TEST_LIVE_MOCK/RECORD marker is detected.
# These use contextvars so each Celery task has its own isolated mock state.
# Default is "off" — all API calls pass through to real providers unchanged.
mock_mode_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "live_mock_mode", default="off"
)
# Values: "off" (real APIs), "mock" (replay from cache), "record" (call real + save)

mock_group_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "live_mock_group", default=""
)
# Namespaces cached responses (e.g., "web_search_flow", "travel_search_flow")

# Regex to detect live mock/record markers in message text.
# Format: <<<TEST_LIVE_MOCK:group_id>>> or <<<TEST_LIVE_RECORD:group_id>>>
_LIVE_MARKER_PATTERN = re.compile(
    r"<<<TEST_LIVE_(MOCK|RECORD):([a-zA-Z0-9_-]+)\s*>>>"
)


def detect_live_marker(content: str) -> Optional[Tuple[str, str]]:
    """
    Detect a TEST_LIVE_MOCK or TEST_LIVE_RECORD marker in message content.

    Returns:
        Tuple of (mode, group_id) where:
            mode: "mock" or "record"
            group_id: identifier for namespacing cached responses
        Returns None if no marker found, or if in production, or if feature flag not set.
    """
    # SECURITY: Never honor markers in production
    if os.getenv("SERVER_ENVIRONMENT", "production") == "production":
        return None

    # Feature flag: MOCK_EXTERNAL_APIS must be explicitly enabled
    if os.getenv("MOCK_EXTERNAL_APIS") != "true":
        return None

    match = _LIVE_MARKER_PATTERN.search(content)
    if not match:
        return None

    mode = match.group(1).lower()  # "mock" or "record"
    group_id = match.group(2)

    return (mode, group_id)


def strip_live_marker(content: str) -> str:
    """Remove the TEST_LIVE_MOCK/TEST_LIVE_RECORD marker from message content."""
    return _LIVE_MARKER_PATTERN.sub("", content).rstrip()


def activate_mock_mode(mode: str, group_id: str) -> None:
    """
    Set context vars for current task. Call from ask_skill_task.py after marker detection.

    Args:
        mode: "mock" (replay) or "record" (real API + save)
        group_id: Namespace for cached responses
    """
    mock_mode_var.set(mode)
    mock_group_var.set(group_id)
    logger.info(
        f"[LiveMock] Activated: mode={mode}, group={group_id}"
    )


def deactivate_mock_mode() -> None:
    """Reset context vars. Call at end of task to clean up."""
    mock_mode_var.set("off")
    mock_group_var.set("")


def is_mock_active() -> bool:
    """Check if live mock mode is active for the current task."""
    return mock_mode_var.get() != "off"


def is_record_mode() -> bool:
    """Check if we're in record mode (call real APIs and save responses)."""
    return mock_mode_var.get() == "record"


def get_mock_group() -> str:
    """Get the current mock group ID for cache namespacing."""
    return mock_group_var.get()
