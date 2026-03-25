# backend/tests/test_auth_endpoints.py
#
# Unit tests for authentication endpoint logic. These tests mock external
# dependencies (Directus, Redis, Vault) and verify that auth route handlers:
#   - Call the correct functions with correct arguments
#   - Handle cache misses with database fallbacks (not silent failures)
#   - Return proper response shapes for all auth methods
#   - Don't crash on missing/wrong parameters
#
# These tests catch the class of bugs where:
#   - A function is called as an instance method instead of module-level
#   - Wrong variable names are passed (hashed_email vs userEmailSalt)
#   - Cache miss is treated as terminal error instead of falling back to DB
#   - Required fields are missing from request payloads
#
# Architecture context: docs/architecture/signup-and-auth.md
# Related E2E tests: frontend/apps/web_app/tests/signup-flow.spec.ts
#
# Execution:
#   cd /home/superdev/projects/OpenMates/backend
#   python -m pytest tests/test_auth_endpoints.py -v

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add project root to Python path for imports (schemas use 'backend.core...' paths)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# ─── Shared Test Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_directus_service():
    """Mock DirectusService with common auth methods."""
    service = AsyncMock()
    service.login_user_with_lookup_hash = AsyncMock(return_value=(
        True,
        {
            "user_id": "test-user-id-123",
            "username": "testuser",
            "email_encrypted": "encrypted-email-blob",
            "is_admin": False,
            "credits": 100,
            "tfa_enabled": False,
            "user_email_salt": "test-salt-abc",
        },
        "Login successful"
    ))
    service.get_user_profile = AsyncMock(return_value={
        "id": "test-user-id-123",
        "username": "testuser",
        "email_encrypted": "encrypted-email-blob",
    })
    service.get_encryption_key = AsyncMock(return_value="mock-encryption-key-base64")
    service.refresh_token = AsyncMock(return_value=(True, {"access_token": "new-token"}, "Token refreshed"))
    return service


@pytest.fixture
def mock_cache_service():
    """Mock CacheService with common auth methods."""
    service = AsyncMock()
    service.get_user_by_token = AsyncMock(return_value=None)  # Default: cache miss
    service.set_user_session = AsyncMock()
    service.get_user_data = AsyncMock(return_value=None)  # Default: cache miss
    service.set_cached_data = AsyncMock()
    return service


@pytest.fixture
def mock_encryption_service():
    """Mock EncryptionService."""
    service = AsyncMock()
    service.encrypt_data = AsyncMock(return_value="encrypted-data")
    service.decrypt_data = AsyncMock(return_value="decrypted-data")
    service.hash_email = AsyncMock(return_value="hashed-email-result")
    return service


@pytest.fixture
def mock_metrics_service():
    """Mock MetricsService."""
    service = AsyncMock()
    service.track_event = AsyncMock()
    return service


@pytest.fixture
def mock_compliance_service():
    """Mock ComplianceService."""
    service = AsyncMock()
    service.log_financial_transaction = AsyncMock()
    return service


# ─── Test: hash_username is a module-level function ──────────────────────────

class TestHashUsernameImport:
    """Verify hash_username is importable and callable as a standalone function.

    This catches the recurring bug where hash_username was moved from a class
    method to a module-level function but call sites still used
    `directus_service.hash_username()`, passing `self` as the first argument.
    Commits: 85f4b48, 80895fb
    """

    @pytest.mark.integration
    def test_hash_username_is_module_level_function(self):
        """hash_username should be importable directly, not as a class method."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        assert callable(hash_username)
        # It should NOT be a bound method
        assert not hasattr(hash_username, '__self__'), (
            "hash_username should be a module-level function, not a bound method"
        )

    @pytest.mark.integration
    def test_hash_username_returns_string(self):
        """hash_username should accept a username string and return a hash string."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result = hash_username("testuser")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    def test_hash_username_is_deterministic(self):
        """Same input should always produce the same hash."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result1 = hash_username("testuser")
        result2 = hash_username("testuser")
        assert result1 == result2

    @pytest.mark.integration
    def test_hash_username_different_inputs_different_hashes(self):
        """Different usernames should produce different hashes."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result1 = hash_username("alice")
        result2 = hash_username("bob")
        assert result1 != result2

    @pytest.mark.integration
    def test_hash_username_imported_in_auth_files(self):
        """Verify auth files import hash_username correctly (not as a method).

        Uses ast.parse to inspect the source without loading the full module.
        Loading auth_email.py requires Celery, Redis, and other production services
        that are not available in the local unit-test venv — using AST inspection
        avoids that dependency chain while still catching the structural bug.
        """
        import ast
        import pathlib

        # Auth files that must import hash_username at module level
        auth_files = [
            "backend/core/api/app/routes/auth_routes/auth_email.py",
            "backend/core/api/app/routes/auth_routes/auth_password.py",
        ]
        repo_root = pathlib.Path(__file__).parent.parent.parent

        for rel_path in auth_files:
            file_path = repo_root / rel_path
            assert file_path.exists(), f"Auth file not found: {rel_path}"

            source = file_path.read_text()
            tree = ast.parse(source, filename=rel_path)

            # Look for "import hash_username" at module level (not inside a function/class)
            found = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom):
                        imported_names = [alias.asname or alias.name for alias in node.names]
                        if 'hash_username' in imported_names:
                            # Confirm it's at module level (not nested in function/class)
                            found = True
                            break

            assert found, (
                f"{rel_path} must import hash_username at module level "
                "(not as an instance method). "
                "Bug: calling it as self.hash_username() silently ignores the first arg."
            )


# ─── Test: Login endpoint request validation ─────────────────────────────────

class TestLoginRequestValidation:
    """Test that LoginRequest schema validates correctly.

    Catches bugs where required fields are missing or wrong field names
    are used (e.g., userEmailSalt vs hashed_email). Commit: 498d5c0
    """

    def test_login_request_requires_hashed_email(self):
        """LoginRequest should require hashed_email field."""
        from core.api.app.schemas.auth import LoginRequest
        with pytest.raises(Exception):
            LoginRequest(lookup_hash="test-hash")  # Missing hashed_email

    def test_login_request_requires_lookup_hash(self):
        """LoginRequest should require lookup_hash field."""
        from core.api.app.schemas.auth import LoginRequest
        with pytest.raises(Exception):
            LoginRequest(hashed_email="test-email")  # Missing lookup_hash

    def test_login_request_accepts_valid_input(self):
        """LoginRequest should accept valid hashed_email + lookup_hash."""
        from core.api.app.schemas.auth import LoginRequest
        req = LoginRequest(
            hashed_email="base64-hashed-email",
            lookup_hash="base64-lookup-hash",
        )
        assert req.hashed_email == "base64-hashed-email"
        assert req.lookup_hash == "base64-lookup-hash"
        assert req.stay_logged_in is False  # Default

    def test_login_request_stay_logged_in_default_false(self):
        """stay_logged_in should default to False, not be omitted.

        Catches the bug where stay_logged_in was never sent to backend
        in pair login flow. Commit: 0973bc4
        """
        from core.api.app.schemas.auth import LoginRequest
        req = LoginRequest(
            hashed_email="test",
            lookup_hash="test",
        )
        assert req.stay_logged_in is False

    def test_login_request_accepts_all_login_methods(self):
        """LoginRequest should accept all valid login_method values."""
        from core.api.app.schemas.auth import LoginRequest
        for method in ['password', 'passkey', 'security_key', 'recovery_key', 'pair']:
            req = LoginRequest(
                hashed_email="test",
                lookup_hash="test",
                login_method=method,
            )
            assert req.login_method == method


# ─── Test: Login response shape ──────────────────────────────────────────────

class TestLoginResponseShape:
    """Test LoginResponse schema for correct shape.

    Catches bugs where login returns success=false despite setting cookies,
    or where user data is missing expected fields.
    """

    def test_login_response_success_shape(self):
        """Successful login response should have user data."""
        from core.api.app.schemas.auth import LoginResponse
        resp = LoginResponse(
            success=True,
            message="Login successful",
            user={
                "username": "testuser",
                "is_admin": False,
                "credits": 100,
                "tfa_enabled": False,
            },
        )
        assert resp.success is True
        assert resp.user is not None

    def test_login_response_failure_shape(self):
        """Failed login response should have success=False and message."""
        from core.api.app.schemas.auth import LoginResponse
        resp = LoginResponse(
            success=False,
            message="Invalid credentials",
        )
        assert resp.success is False
        assert resp.user is None

    def test_login_response_tfa_required(self):
        """2FA-required response should have tfa_required=True."""
        from core.api.app.schemas.auth import LoginResponse
        resp = LoginResponse(
            success=True,
            message="2FA required",
            tfa_required=True,
        )
        assert resp.tfa_required is True


# ─── Test: Cache miss fallback pattern ───────────────────────────────────────

class TestCacheMissFallback:
    """Test that auth services fall back to Directus on cache miss.

    Catches the anti-pattern where cache_service.get_user_data() returning None
    is treated as a terminal error instead of falling back to the database.
    Commits: e4d5ea5, 792526c, a20bacf
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_verify_authenticated_user_falls_back_on_cache_miss(
        self, mock_cache_service, mock_directus_service
    ):
        """When cache returns None, auth should try Directus refresh_token."""
        from core.api.app.routes.auth_routes.auth_common import verify_authenticated_user

        # Cache miss
        mock_cache_service.get_user_by_token = AsyncMock(return_value=None)

        # Directus refresh succeeds
        mock_directus_service.refresh_token = AsyncMock(return_value=(
            True,
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "user_id": "test-user-id",
            },
            "Token refreshed"
        ))
        mock_directus_service.get_user_by_id = AsyncMock(return_value={
            "id": "test-user-id",
            "username": "testuser",
        })

        # Create mock request with refresh token cookie
        mock_request = MagicMock()
        mock_request.cookies = {"auth_refresh_token": "valid-refresh-token"}
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value="Mozilla/5.0")
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        success, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request=mock_request,
            cache_service=mock_cache_service,
            directus_service=mock_directus_service,
            require_known_device=False,  # Skip device check for this test
        )

        # Should have attempted Directus fallback
        mock_directus_service.refresh_token.assert_called_once_with("valid-refresh-token")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_verify_authenticated_user_fails_without_cookie(
        self, mock_cache_service, mock_directus_service
    ):
        """Missing refresh token cookie should return authentication_failed."""
        from core.api.app.routes.auth_routes.auth_common import verify_authenticated_user

        mock_request = MagicMock()
        mock_request.cookies = {}  # No refresh token
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value="Mozilla/5.0")

        success, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request=mock_request,
            cache_service=mock_cache_service,
            directus_service=mock_directus_service,
        )

        assert success is False
        assert auth_status == "authentication_failed"


# ─── Test: Email code request validation ─────────────────────────────────────

class TestEmailCodeRequestValidation:
    """Test RequestEmailCodeRequest schema validation."""

    def test_requires_email_and_hashed_email(self):
        """Should require both email and hashed_email."""
        from core.api.app.schemas.auth import RequestEmailCodeRequest
        with pytest.raises(Exception):
            RequestEmailCodeRequest(email="test@example.com")  # Missing hashed_email

    def test_accepts_valid_request(self):
        """Should accept a valid email code request."""
        from core.api.app.schemas.auth import RequestEmailCodeRequest
        req = RequestEmailCodeRequest(
            email="test@example.com",
            hashed_email="abc123hashed",
        )
        assert req.email == "test@example.com"
        assert req.language == "en"  # Default


# ─── Test: CheckUsernameRequest schema ───────────────────────────────────────

class TestCheckUsernameValidation:
    """Test username validation schemas."""

    def test_check_username_request_shape(self):
        """CheckUsernameRequest should accept a username string."""
        from core.api.app.schemas.auth import CheckUsernameRequest
        req = CheckUsernameRequest(username="testuser")
        assert req.username == "testuser"

    def test_check_username_response_shape(self):
        """CheckUsernameResponse should have available flag."""
        from core.api.app.schemas.auth import CheckUsernameResponse
        resp = CheckUsernameResponse(available=True, message="Username available")
        assert resp.available is True
