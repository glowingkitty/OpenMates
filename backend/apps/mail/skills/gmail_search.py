# backend/apps/mail/skills/gmail_search.py
#
# Gmail provider path of the Mail search skill (connected Google account,
# gmail.readonly). Results are sanitized against prompt injection and returned
# as normal embeds; nothing is stored server-side.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.shared.providers.gmail.client import GmailClient
from backend.shared.providers.gmail.errors import MailInputError
from backend.shared.python_utils.mail_gmail_support import (
    access_token_for_handle,
    run_mail_request,
    sanitize_mailbox_payload,
    summarize_errors,
)

GOOGLE_PROVIDER = "google"


class GmailSearchRequest(BaseModel):
    """One Gmail search request on a connected Google account."""

    id: Any | None = None
    query: str | None = Field(default=None, max_length=512)
    start_date: str | None = None
    end_date: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    page_token: str | None = Field(default=None, max_length=4096)
    access_token_handle: str
    connected_account_id: str | None = None
    provider: str | None = None


def is_google_request(request: Any) -> bool:
    return isinstance(request, dict) and str(request.get("provider") or "").lower() in {"google", "gmail"}


def build_gmail_query(item: GmailSearchRequest) -> str:
    """Gmail search syntax; dates become after:/before: operators (before is exclusive)."""

    parts = [item.query.strip()] if item.query and item.query.strip() else []
    for operator, value in (("after", item.start_date), ("before", item.end_date)):
        if value:
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                raise MailInputError("invalid_date", f"{operator} date must be YYYY-MM-DD.")
            parts.append(f"{operator}:{value.replace('-', '/')}")
    return " ".join(parts)


async def search_gmail(
    requests: list[dict[str, Any]], *, connected_account_access_tokens: dict[str, str] | None,
    gmail_client_factory: Any | None, secrets_manager: Any | None, cache_service: Any | None,
) -> dict[str, Any]:
    factory = gmail_client_factory or GmailClient

    async def run(raw: dict[str, Any]) -> dict[str, Any]:
        item = GmailSearchRequest(**{k: v for k, v in raw.items() if k in GmailSearchRequest.model_fields})
        client = factory(access_token=access_token_for_handle(
            item.access_token_handle, connected_account_access_tokens,
        ))
        query = build_gmail_query(item)
        page = await client.search_messages(query=query, max_results=item.limit, page_token=item.page_token)
        messages = await sanitize_mailbox_payload(
            page["messages"], task_id=f"gmail_search_{item.id}",
            secrets_manager=secrets_manager, cache_service=cache_service,
        )
        for message in messages:
            message["sender"] = message.get("from", "")
            message["recipient"] = message.get("to", "")
        return {
            "id": item.id, "provider": "Gmail", "query": item.query or "",
            "start_date": item.start_date, "end_date": item.end_date,
            "result_count": len(messages), "results": messages,
            "next_page_token": page.get("next_page_token"),
            "has_more": bool(page.get("next_page_token")), "status": "completed",
        }

    results = [await run_mail_request(r, run) for r in requests]
    return {"results": results, "error": summarize_errors(results)}
