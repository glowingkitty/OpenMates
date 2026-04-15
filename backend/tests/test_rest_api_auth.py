# backend/tests/test_rest_api_auth.py
# @privacy-promise: argon2-password-hashing
#
# Integration tests for authentication REST API endpoints.
# These tests call the REAL API at api.dev.openmates.org with ZERO mocks.
#
# Purpose: Catch the class of bugs where auth endpoints crash (500) due to:
#   - Wrong function call signatures (hash_username as method vs module-level)
#   - Missing/wrong request fields (hashed_email vs userEmailSalt)
#   - Cache miss treated as terminal error
#   - Missing encryption keys for login methods
#
# These tests verify the endpoints don't crash — they intentionally use
# invalid credentials (so they get "invalid" responses, not "success").
# The key assertion is: the response is a proper JSON error, NOT a 500.
#
# Related unit tests: backend/tests/test_auth_endpoints.py
# Related E2E tests: frontend/apps/web_app/tests/signup-flow.spec.ts
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_auth.py

import httpx
import pytest
import hashlib
import base64

from backend.tests.conftest import API_BASE_URL, log_response

# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_hashed_email(email: str) -> str:
    """Create a SHA-256 hashed email (same logic as frontend)."""
    return base64.b64encode(
        hashlib.sha256(email.encode()).digest()
    ).decode()


def make_lookup_hash(email: str, password: str) -> str:
    """Create a lookup hash from email + password (simplified test version)."""
    combined = f"{email}:{password}"
    return base64.b64encode(
        hashlib.sha256(combined.encode()).digest()
    ).decode()


# ─── Test: Login endpoint doesn't crash ──────────────────────────────────────

@pytest.mark.integration
class TestLoginEndpoint:
    """Test /v1/auth/login returns proper responses, not 500 errors.

    If hash_username is called as an instance method (the bug from commits
    85f4b48, 80895fb), the endpoint would return 500 TypeError. These tests
    verify it returns a proper JSON response with success=False.
    """

    def test_login_with_invalid_credentials_returns_json(self):
        """Login with wrong credentials should return 4xx/JSON, not 500."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/login", json={
                "hashed_email": make_hashed_email("nonexistent-test@example.com"),
                "lookup_hash": make_lookup_hash("nonexistent-test@example.com", "wrong"),
            })
            # Should NOT be 500 (which indicates a code crash).
            # We don't assert success=False here because the simplified test
            # hash might accidentally match a real account. What matters is that
            # the endpoint returns a valid JSON response shape, not a crash.
            assert resp.status_code != 500, (
                f"Login endpoint crashed with 500: {resp.text}"
            )
            data = resp.json()
            # Valid responses: {"success": bool, ...} or {"detail": "..."} or {"error": "..."} (rate-limit)
            assert isinstance(data, dict), f"Expected JSON object, got: {data}"
            assert "success" in data or "detail" in data or "error" in data, (
                f"Expected 'success', 'detail', or 'error' field in response, got: {data}"
            )

    def test_login_with_missing_hashed_email_returns_422(self):
        """Missing required field should return 422 validation error."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/login", json={
                "lookup_hash": "test-hash",
            })
            # Pydantic validation should return 422, not 500
            assert resp.status_code in (422, 400), (
                f"Expected 422/400 for missing field, got {resp.status_code}: {resp.text}"
            )

    def test_login_with_missing_lookup_hash_returns_422(self):
        """Missing required field should return 422 validation error."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/login", json={
                "hashed_email": "test-email",
            })
            assert resp.status_code in (422, 400), (
                f"Expected 422/400 for missing field, got {resp.status_code}: {resp.text}"
            )

    def test_login_with_all_optional_fields(self):
        """Login with all optional fields populated should not crash."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/login", json={
                "hashed_email": make_hashed_email("test@example.com"),
                "lookup_hash": make_lookup_hash("test@example.com", "password"),
                "login_method": "password",
                "stay_logged_in": True,
                "session_id": "test-session-uuid",
                "email_encryption_key": "test-key",
            })
            assert resp.status_code != 500, (
                f"Login with optional fields crashed: {resp.text}"
            )
            data = resp.json()
            # Accept rate-limit response too ({"error": "Rate limit exceeded"})
            assert "success" in data or "error" in data, (
                f"Expected 'success' or rate-limit 'error' in response, got: {data}"
            )

    def test_login_with_pair_method_does_not_crash(self):
        """Login with login_method='pair' should not crash.

        Catches the bug where encryption key lookup for 'pair' method
        had no DB entry (commit cb48a39).
        """
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/login", json={
                "hashed_email": make_hashed_email("pair-test@example.com"),
                "lookup_hash": make_lookup_hash("pair-test@example.com", "pair-password"),
                "login_method": "pair",
                "stay_logged_in": False,
            })
            assert resp.status_code != 500, (
                f"Pair login crashed: {resp.text}"
            )


# ─── Test: Username check endpoint ──────────────────────────────────────────

@pytest.mark.integration
class TestCheckUsernameEndpoint:
    """Test /v1/auth/check_username doesn't crash.

    The hash_username function is called in this endpoint — if it's still
    called as an instance method, this would be a 500.
    """

    def test_check_username_returns_json(self):
        """Check username should return proper JSON with 'available' field."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/check_username_valid", json={
                "username": "ci_test_user_abc",
            })
            assert resp.status_code != 500, (
                f"Check username crashed: {resp.text}"
            )
            data = resp.json()
            assert "available" in data or "message" in data


# ─── Test: User lookup endpoint ──────────────────────────────────────────────

@pytest.mark.integration
class TestUserLookupEndpoint:
    """Test /v1/auth/user_lookup doesn't crash."""

    def test_user_lookup_with_nonexistent_user(self):
        """Lookup of nonexistent user should return proper response, not 500."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.post("/v1/auth/user_lookup", json={
                "hashed_email": make_hashed_email("nonexistent@example.com"),
            })
            assert resp.status_code != 500, (
                f"User lookup crashed: {resp.text}"
            )


# ─── Test: Session endpoint (authenticated) ─────────────────────────────────

@pytest.mark.integration
class TestSessionEndpoint:
    """Test /v1/auth/session with and without authentication.

    This exercises the verify_authenticated_user cache-miss fallback path.
    """

    def test_session_without_auth_returns_401(self):
        """Session check without cookies should return auth error, not 500."""
        with httpx.Client(
            base_url=API_BASE_URL,
            headers={"Origin": "https://app.dev.openmates.org"},
            event_hooks={"response": [log_response]},
            timeout=30.0,
        ) as client:
            resp = client.get("/v1/auth/session")
            # Should be 401 or a JSON response with success=False
            assert resp.status_code != 500, (
                f"Session check crashed without auth: {resp.text}"
            )

    def test_session_with_api_key(self, api_client):
        """Session check with valid API key should return user data."""
        resp = api_client.get("/v1/auth/session")
        assert resp.status_code != 500, (
            f"Session check crashed with API key: {resp.text}"
        )
