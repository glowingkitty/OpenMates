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
