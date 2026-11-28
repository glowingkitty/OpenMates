# backend/tests/fake_gmail.py
#
# Stateful in-memory stand-in for the Gmail v1 REST API, served via
# httpx.MockTransport. It implements only what the OpenMates client calls:
# messages.list (q, pageToken, maxResults), messages.get (metadata), threads.get
# (full/metadata) and drafts.create. There is intentionally no send endpoint:
# any call to a *send path is recorded in `forbidden_calls` so tests can prove
# the client never reaches one. Synthetic data only.
#
# Reference: https://developers.google.com/gmail/api/reference/rest

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_PATH = "/gmail/v1/users/me"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def text_message(msg_id: str, thread_id: str, subject: str, body: str, *, sender: str = "Alex <alex@example.org>",
                 message_id_header: str | None = None, html: str | None = None) -> dict[str, Any]:
    headers = [
        {"name": "From", "value": sender}, {"name": "To", "value": "me@example.org"},
        {"name": "Subject", "value": subject}, {"name": "Date", "value": "Sun, 22 Nov 2026 09:00:00 +0000"},
        {"name": "Message-ID", "value": message_id_header or f"<{msg_id}@example.org>"},
    ]
    parts = [{"mimeType": "text/plain", "body": {"data": b64(body)}}] if body else []
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": b64(html)}})
    return {"id": msg_id, "threadId": thread_id, "snippet": body[:40], "labelIds": ["INBOX"],
            "payload": {"mimeType": "multipart/alternative", "headers": headers, "parts": parts}}


@dataclass
class FakeGmail:
    access_token: str = "synthetic-access-token"
    messages: list[dict[str, Any]] = field(default_factory=list)
    granted_scopes: set[str] = field(default_factory=lambda: {"gmail.readonly", "gmail.compose"})
    page_size: int = 2
    requests: list[httpx.Request] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    forbidden_calls: list[str] = field(default_factory=list)
    fail_next: list[httpx.Response | Exception] = field(default_factory=list)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client_factory(self):
        from backend.shared.providers.gmail.client import GmailClient

        def build(*, access_token: str) -> GmailClient:
            return GmailClient(access_token=access_token, transport=self.transport)

        return build

    @staticmethod
    def _error(status: int, reason: str, message: str = "error") -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": status, "message": message,
                                                      "errors": [{"reason": reason, "message": message}]}})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            item = self.fail_next.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if request.headers.get("authorization") != f"Bearer {self.access_token}":
            return self._error(401, "authError", "Invalid Credentials")
        path = request.url.path.removeprefix(BASE_PATH)
        params = request.url.params
        if path.endswith("/send") or path == "/messages/send":
            self.forbidden_calls.append(path)
            return self._error(403, "insufficientPermissions")
        if request.method == "GET" and path == "/messages":
            if "gmail.readonly" not in self.granted_scopes:
                return self._error(403, "insufficientPermissions", "Request had insufficient authentication scopes.")
            query = params.get("q", "")
            self.queries.append(query)
            matches = [m for m in self.messages if _matches(m, query)]
            start = int(params.get("pageToken") or 0)
            size = min(int(params.get("maxResults", 100)), self.page_size)
            page = matches[start:start + size]
            body: dict[str, Any] = {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in page],
                                    "resultSizeEstimate": len(matches)}
            if start + size < len(matches):
                body["nextPageToken"] = str(start + size)
            return httpx.Response(200, json=body)
        if request.method == "GET" and path.startswith("/messages/"):
            message = next((m for m in self.messages if m["id"] == path.split("/")[2]), None)
            return httpx.Response(200, json=message) if message else self._error(404, "notFound")
        if request.method == "GET" and path.startswith("/threads/"):
            if "gmail.readonly" not in self.granted_scopes:
                return self._error(403, "insufficientPermissions")
            thread = [m for m in self.messages if m["threadId"] == path.split("/")[2]]
            return httpx.Response(200, json={"id": path.split("/")[2], "messages": thread}) if thread \
                else self._error(404, "notFound")
        if request.method == "POST" and path == "/drafts":
            if "gmail.compose" not in self.granted_scopes:
                return self._error(403, "insufficientPermissions")
            payload = json.loads(request.content)
            draft = {"id": f"draft-{len(self.drafts) + 1}",
                     "message": {"id": f"dm-{len(self.drafts) + 1}", "threadId": payload["message"].get("threadId", "new-thread")},
                     "_request": payload}
            self.drafts.append(draft)
            return httpx.Response(200, json={"id": draft["id"], "message": draft["message"]})
        return self._error(404, "notFound")


def _matches(message: dict[str, Any], query: str) -> bool:
    haystack = (message["snippet"] + " " + " ".join(h["value"] for h in message["payload"]["headers"])).lower()
    return all(term.lower() in haystack for term in query.split() if ":" not in term)
