# backend/apps/mail/skills/create_draft_skill.py
#
# Mail create-draft skill: saves a draft in the connected Gmail account
# (gmail.compose, drafts.create). It NEVER sends: there is no send skill,
# endpoint or scope by owner decision (2026-11-22). Recipients, subject and
# body must be real values; unresolved privacy placeholders are rejected
# before any request to Google.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.gmail.client import GmailClient
from backend.shared.providers.gmail.mime import normalize_recipients, reject_placeholders
from backend.shared.python_utils.mail_gmail_support import (
    access_token_for_handle,
    run_mail_request,
    summarize_errors,
)


class CreateDraftItem(BaseModel):
    """Create-draft request."""

    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=50000)
    thread_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    access_token_handle: str
    connected_account_id: str | None = None


class CreateDraftResponse(BaseModel):
    """Create-draft response."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class CreateDraftSkill(BaseSkill):
    """Create Gmail drafts after connected-account authorization."""

    async def execute(
        self,
        requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        gmail_client_factory: Any | None = None,
        **_: Any,
    ) -> CreateDraftResponse:
        factory = gmail_client_factory or GmailClient

        async def run(raw: dict[str, Any]) -> dict[str, Any]:
            item = CreateDraftItem(**{k: v for k, v in raw.items() if k in CreateDraftItem.model_fields})
            to = normalize_recipients(item.to, "to")
            cc = normalize_recipients(item.cc, "cc")
            bcc = normalize_recipients(item.bcc, "bcc")
            reject_placeholders(item.subject, "subject")
            reject_placeholders(item.body, "body")
            client = factory(access_token=access_token_for_handle(
                item.access_token_handle, connected_account_access_tokens,
            ))
            draft = await client.create_draft(
                to=to, cc=cc, bcc=bcc, subject=item.subject, body=item.body, thread_id=item.thread_id,
            )
            return {
                "status": "draft_created", "sent": False, **draft,
                "to": to, "cc": cc, "bcc": bcc, "subject": item.subject,
            }

        results = [await run_mail_request(r, run) for r in requests]
        return CreateDraftResponse(results=results, error=summarize_errors(results))
