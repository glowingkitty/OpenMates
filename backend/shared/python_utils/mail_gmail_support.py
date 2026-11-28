# backend/shared/python_utils/mail_gmail_support.py
#
# Shared helpers for the Gmail-backed Mail skills: per-request error handling
# and prompt-injection hardening of untrusted mailbox content before it can
# reach the model. Mirrors calendar_skill_support.py.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from backend.shared.providers.gmail.errors import GmailProviderError, MailInputError
from backend.shared.python_utils.app_skill_output_safety import (
    is_central_app_skill_dispatch,
    sanitize_long_text_fields_in_payload,
)
from backend.shared.python_utils.calendar_skill_support import access_token_for_handle, summarize_errors

__all__ = ["access_token_for_handle", "run_mail_request", "sanitize_mailbox_payload", "summarize_errors"]


def input_error_result(code: str, message: str) -> dict[str, Any]:
    return {"error": f"mail_{code}", "message": message, "reconnect_required": False, "retryable": False}


async def run_mail_request(
    request: dict[str, Any], operation: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run one request; classified failures become that request's result."""

    try:
        return await operation(request)
    except GmailProviderError as error:
        return error.to_result()
    except MailInputError as error:
        return input_error_result(error.code, str(error))
    except ValidationError as error:
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        return input_error_result("invalid_input", "Invalid or missing fields: " + ", ".join(fields))


async def sanitize_mailbox_payload(
    payload: Any, *, task_id: str, secrets_manager: Any | None, cache_service: Any | None,
) -> Any:
    """Screen standalone reads; trusted dispatch screens the entire result once."""

    if is_central_app_skill_dispatch():
        return payload
    return await sanitize_long_text_fields_in_payload(
        payload=payload, task_id=task_id, secrets_manager=secrets_manager,
        cache_service=cache_service, require_complete_scan=True,
        app_id="mail",
    )
