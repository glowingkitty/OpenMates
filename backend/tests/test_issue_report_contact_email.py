"""
Regression coverage for issue-report contact email resolution.

Authenticated issue reports must be able to resolve a contact email when the
server has a server-decryptable account contact email. This protects follow-up
support and thank-you credit workflows from client-side races where the browser
submits before the decrypted email has loaded into the form.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.utils.issue_report_contact_email import resolve_account_contact_email
from backend.core.api.app.utils.issue_report_text import (
    normalize_issue_report_error_sentinels,
    normalize_issue_report_trace_ids,
)


class FakeDirectus:
    def __init__(self):
        self.created_payloads: list[dict] = []

    async def get_items(self, collection: str, params: dict, **_kwargs):
        if collection == "account_contact_emails":
            assert params["filter"] == {"user_id": {"_eq": "user-123"}}
            return [{"encrypted_email_address": "encrypted-contact-email"}]
        raise AssertionError(f"unexpected collection: {collection}")


class FakeEncryption:
    async def decrypt_account_contact_email(self, encrypted_email: str) -> str:
        assert encrypted_email == "encrypted-contact-email"
        return "user@example.com"

    async def encrypt_issue_report_email(self, email: str) -> str:
        assert email == "user@example.com"
        return "encrypted-issue-email"

    async def encrypt_issue_report_data(self, value: str) -> str:
        return f"encrypted:{value}"


@pytest.mark.anyio
async def test_authenticated_issue_report_can_resolve_server_contact_email():
    directus = FakeDirectus()

    contact_email = await resolve_account_contact_email(
        directus,
        FakeEncryption(),
        "user-123",
    )

    assert contact_email == "user@example.com"


def test_issue_report_normalizes_raw_chat_error_sentinel() -> None:
    assert (
        normalize_issue_report_error_sentinels("Schlechte Antwortqualität:\n\nchat.an_error_occured")
        == "Schlechte Antwortqualität:\n\nAI processing error"
    )
    assert normalize_issue_report_error_sentinels("chat.an_error_occurred") == "AI processing error"
    assert normalize_issue_report_error_sentinels(None) is None


def test_issue_report_trace_ids_are_bounded_for_yaml() -> None:
    long_trace_id = "a" * 100

    assert normalize_issue_report_trace_ids([long_trace_id, "trace-2", ""]) == ["a" * 64, "trace-2"]
    assert normalize_issue_report_trace_ids(None) == []
