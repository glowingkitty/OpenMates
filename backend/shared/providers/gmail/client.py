# backend/shared/providers/gmail/client.py
#
# Minimal async client for Google's official Gmail REST API: search/list
# messages, read messages and threads, create drafts. No send call exists in
# this module by owner decision (2026-11-22). Scopes: gmail.readonly for reads,
# gmail.compose for drafts.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .errors import GmailProviderError, classify_status_error
from .mime import attachment_names, build_draft_raw, extract_body, header_map

logger = logging.getLogger(__name__)

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_PAGE_SIZE = 50
_METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]


class GmailClient:
    """Gmail API client for authorized mailbox reads and draft creation."""

    def __init__(
        self, *, access_token: str, timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.timeout = timeout
        self._transport = transport

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, mutation: bool = False,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.request(
                    method, f"{GMAIL_API_BASE_URL}{path}", params=params, json=json, headers=headers,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise GmailProviderError("gmail_unavailable") from exc
        except httpx.TransportError as exc:
            code = "gmail_outcome_uncertain" if mutation else "gmail_unavailable"
            raise GmailProviderError(code) from exc
        if response.is_error:
            error = classify_status_error(response)
            logger.info("Gmail %s %s failed: %s", method, path.split("/")[1], error.code)
            raise error
        return response

    async def search_messages(
        self, *, query: str | None = None, max_results: int = 10, page_token: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """One page of message summaries for a Gmail search query (same syntax as the Gmail UI)."""

        params: dict[str, Any] = {"maxResults": max(1, min(max_results, MAX_PAGE_SIZE))}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        if label_ids:
            params["labelIds"] = label_ids
        payload = (await self._request("GET", "/messages", params=params)).json()
        messages = []
        for item in payload.get("messages", []):
            raw = (await self._request(
                "GET", f"/messages/{_path(str(item['id']))}",
                params={"format": "metadata", "metadataHeaders": _METADATA_HEADERS},
            )).json()
            messages.append(normalize_message(raw, with_body=False))
        return {
            "messages": messages,
            "next_page_token": payload.get("nextPageToken"),
            "result_size_estimate": payload.get("resultSizeEstimate"),
        }

    async def get_thread(self, *, thread_id: str) -> dict[str, Any]:
        """A whole thread with decoded bodies, oldest message first."""

        raw = (await self._request(
            "GET", f"/threads/{_path(thread_id)}", params={"format": "full"},
        )).json()
        return {
            "thread_id": str(raw.get("id", thread_id)),
            "messages": [normalize_message(item, with_body=True) for item in raw.get("messages", [])],
        }

    async def create_draft(
        self, *, to: list[str], cc: list[str], bcc: list[str], subject: str, body: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft (drafts.create). For a reply, threading headers come from the thread's last message."""

        in_reply_to: str | None = None
        references: str | None = None
        if thread_id:
            thread = (await self._request(
                "GET", f"/threads/{_path(thread_id)}",
                params={"format": "metadata", "metadataHeaders": ["Message-ID", "References"]},
            )).json()
            last = (thread.get("messages") or [None])[-1]
            if last:
                headers = header_map(last.get("payload") or {})
                in_reply_to = headers.get("message-id")
                references = headers.get("references")
        raw = build_draft_raw(
            to=to, cc=cc, bcc=bcc, subject=subject, body=body,
            in_reply_to=in_reply_to, references=references,
        )
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        created = (await self._request(
            "POST", "/drafts", json={"message": message}, mutation=True,
        )).json()
        return {
            "draft_id": str(created.get("id", "")),
            "message_id": str((created.get("message") or {}).get("id", "")),
            "thread_id": (created.get("message") or {}).get("threadId"),
        }


def normalize_message(item: dict[str, Any], *, with_body: bool) -> dict[str, Any]:
    payload = item.get("payload") or {}
    headers = header_map(payload)
    result: dict[str, Any] = {
        "id": str(item.get("id", "")),
        "thread_id": item.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": item.get("snippet", ""),
        "labels": list(item.get("labelIds") or []),
    }
    if with_body:
        result["body"] = extract_body(payload)
        result["attachments"] = attachment_names(payload)
    return result


def _path(value: str) -> str:
    return quote(value, safe="")
