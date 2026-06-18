# backend/shared/providers/google_calendar/__init__.py
#
# Pure Google Calendar provider wrapper exports.
# Provider code has no dependency on Calendar app skills or permission policy;
# callers supply short-lived access tokens after authorization.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from .client import GoogleCalendarClient
from .models import (
    CalendarEvent,
    CalendarEventDeleteRequest,
    CalendarEventMutationRequest,
    CalendarEventsRequest,
)

__all__ = [
    "CalendarEvent",
    "CalendarEventDeleteRequest",
    "CalendarEventMutationRequest",
    "CalendarEventsRequest",
    "GoogleCalendarClient",
]
