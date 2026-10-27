"""OpenMates Python SDK public exports.

Purpose: expose the ergonomic Python API-key SDK entrypoint.
Architecture: thin package barrel over openmates.sdk.
Security: API keys are passed through at request time and never persisted.
Tests: packages/openmates-python/tests/test_sdk.py.
"""

from .sdk import OpenMates, OpenMatesApiError, OpenMatesConfigError, OpenMatesSignupRequiredError, OpenMatesUnavailableError
from .calendar_event import CalendarEvent, CalendarEventDocument, build_calendar_event_file

__all__ = ["OpenMates", "OpenMatesApiError", "OpenMatesConfigError", "OpenMatesUnavailableError", "OpenMatesSignupRequiredError", "CalendarEvent", "CalendarEventDocument", "build_calendar_event_file"]
