# backend/apps/mail/skills/read_thread_skill.py
#
# Mail read-thread skill: reads one Gmail thread (decoded text bodies) from a
# connected Google account (gmail.readonly). Mailbox text is untrusted and is
# sanitized against prompt injection before reaching the model.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.gmail.client import GmailClient
from backend.shared.python_utils.mail_gmail_support import (
    access_token_for_handle,
    run_mail_request,
    sanitize_mailbox_payload,
    summarize_errors,
)


class ReadThreadItem(BaseModel):
    """Read-thread request."""

    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    access_token_handle: str
    connected_account_id: str | None = None


class ReadThreadResponse(BaseModel):
    """Read-thread response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class ReadThreadSkill(BaseSkill):
    """Read a Gmail thread with a broker-issued access-token handle."""

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        gmail_client_factory: Any | None = None,
        secrets_manager: Any | None = None,
        cache_service: Any | None = None,
        **_: Any,
    ) -> ReadThreadResponse:
        factory = gmail_client_factory or GmailClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            item = ReadThreadItem(**{k: v for k, v in raw.items() if k in ReadThreadItem.model_fields})
            client = factory(access_token=access_token_for_handle(
                item.access_token_handle, connected_account_access_tokens,
            ))
            thread = await client.get_thread(thread_id=item.thread_id)
            messages = await sanitize_mailbox_payload(
                thread["messages"], task_id=f"gmail_thread_{item.thread_id}",
                secrets_manager=secrets_manager, cache_service=cache_service,
            )
            return {"thread_id": thread["thread_id"], "message_count": len(messages), "messages": messages}

        results = [await run_mail_request(r, run) for r in requests]
        return ReadThreadResponse(results=results, error=summarize_errors(results))
