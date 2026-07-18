"""
Regression coverage for the public signup quota counter.

The quota must count users with real chat evidence, not users who only reached
the empty composer at /chat/new. This keeps stale no-chat accounts from closing
public signup when SIGNUP_LIMIT is finite.
"""

from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus.user.user_lookup import get_completed_signups_count


class DummyDirectus:
    base_url = "https://directus.example.test"

    def __init__(self, users):
        self.users = users

    async def _make_api_request(self, method, url, params=None):
        assert method == "GET"
        assert url == "https://directus.example.test/users"
        assert params is not None
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": self.users},
        )


@pytest.mark.anyio
async def test_completed_signups_count_excludes_chat_new_and_admins():
    chat_id = "123e4567-e89b-12d3-a456-426614174000"
    users = [
        {"id": "empty-composer", "last_opened": "/chat/new", "is_admin": False},
        {"id": "chat-path", "last_opened": f"/chat/{chat_id}", "is_admin": False},
        {"id": "raw-chat-id", "last_opened": "223e4567-e89b-12d3-a456-426614174001", "is_admin": False},
        {"id": "admin-chat", "last_opened": "/chat/323e4567-e89b-12d3-a456-426614174002", "is_admin": True},
        {"id": "signup-flow", "last_opened": "/signup/one_time_codes", "is_admin": False},
        {"id": "missing", "last_opened": None, "is_admin": False},
    ]

    assert await get_completed_signups_count(DummyDirectus(users)) == 2
