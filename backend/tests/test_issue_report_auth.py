"""Regression coverage for iPad Safari issue-log authentication."""

import pytest

from backend.core.api.app.utils import issue_report_auth


class FakeCache:
    SESSION_KEY_PREFIX = "session:"

    def __init__(self, session_data=None):
        self.session_data = session_data
        self.requested_key = None

    async def get(self, key: str):
        self.requested_key = key
        return self.session_data


# contract-test: direct surface=rest_api assertions=issue-reporting.logs.authenticated-capture
@pytest.mark.asyncio
async def test_cookie_user_takes_precedence_over_ws_token(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(
        issue_report_auth,
        "verify_ws_token",
        lambda _token: (_ for _ in ()).throw(AssertionError("token should not be read")),
    )

    user_id = await issue_report_auth.resolve_issue_report_user_id(
        "cookie-user", "unused-token", cache
    )

    assert user_id == "cookie-user"
    assert cache.requested_key is None


# contract-test: direct surface=rest_api assertions=issue-reporting.logs.authenticated-capture
@pytest.mark.asyncio
async def test_valid_ws_token_recovers_safari_session_user(monkeypatch):
    cache = FakeCache({"user_id": "ipad-user"})
    monkeypatch.setattr(issue_report_auth, "verify_ws_token", lambda token: "token-hash" if token == "ws-token" else None)

    user_id = await issue_report_auth.resolve_issue_report_user_id(
        None, "ws-token", cache
    )

    assert user_id == "ipad-user"
    assert cache.requested_key == "session:token-hash"


# contract-test: direct surface=rest_api assertions=issue-reporting.logs.authenticated-capture
@pytest.mark.asyncio
async def test_invalid_ws_token_is_rejected(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(issue_report_auth, "verify_ws_token", lambda _token: None)

    user_id = await issue_report_auth.resolve_issue_report_user_id(
        None, "invalid-token", cache
    )

    assert user_id is None
    assert cache.requested_key is None
