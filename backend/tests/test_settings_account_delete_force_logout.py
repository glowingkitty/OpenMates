"""
Regression tests for account deletion logout fanout.

Purpose: account deletion must notify connected first-party clients before
server sessions disappear so web and CLI can purge local encrypted data.
Security: uses fake services and synthetic user IDs only; no credentials,
cookies, keys, or Directus state are accessed.
"""

from pathlib import Path


def test_delete_account_broadcasts_force_logout_before_session_invalidation():
    settings_source = Path("backend/core/api/app/routes/settings.py").read_text()

    assert "from backend.core.api.app.routes.auth_routes.auth_sessions import _broadcast_force_logout" in settings_source
    assert settings_source.index(
        'await _broadcast_force_logout(cache_service, user_id, "account_deleted")',
    ) < settings_source.index("await directus_service.logout_all_sessions(user_id)")
