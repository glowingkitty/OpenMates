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
# Architecture context: docs/architecture/core/signup-and-auth.md
# Related E2E tests: frontend/apps/web_app/tests/signup-flow.spec.ts
#
# Execution:
#   cd /home/superdev/projects/OpenMates/backend
#   python -m pytest tests/test_auth_endpoints.py -v

# contract-test-file: tooling

import pytest
import base64
import json
import sys
import hashlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import BackgroundTasks, HTTPException, Response
from starlette.requests import Request
from starlette.datastructures import Headers

# Add project root to Python path for imports (schemas use 'backend.core...' paths)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import argon2  # noqa: F401
except ModuleNotFoundError:
    fake_argon2 = ModuleType("argon2")
    fake_argon2_exceptions = ModuleType("argon2.exceptions")

    class VerifyMismatchError(Exception):
        pass

    class PasswordHasher:
        def hash(self, value: str) -> str:
            return f"test-argon2:{value}"

        def verify(self, hashed_value: str, value: str) -> bool:
            if hashed_value != self.hash(value):
                raise VerifyMismatchError()
            return True

    fake_argon2.PasswordHasher = PasswordHasher
    fake_argon2_exceptions.VerifyMismatchError = VerifyMismatchError
    sys.modules["argon2"] = fake_argon2
    sys.modules["argon2.exceptions"] = fake_argon2_exceptions

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    fake_tasks_package = ModuleType("backend.core.api.app.tasks")
    fake_tasks_package.__path__ = []
    fake_celery_config = ModuleType("backend.core.api.app.tasks.celery_config")
    fake_celery_config.app = SimpleNamespace(
        conf=SimpleNamespace(task_always_eager=False),
        send_task=MagicMock(),
    )
    fake_tasks_package.celery_config = fake_celery_config
    sys.modules["backend.core.api.app.tasks"] = fake_tasks_package
    sys.modules["backend.core.api.app.tasks.celery_config"] = fake_celery_config


# ─── Shared Test Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_directus_service():
    """Mock DirectusService with common auth methods."""
    service = AsyncMock()
    service.get_items = AsyncMock(return_value=[])
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


class TestDevSignupCleanup:
    """Verify failed-signup cleanup is dev-only and secret-gated."""

    @staticmethod
    def _request(api_key: str | None = "cleanup-key") -> Request:
        headers = []
        if api_key is not None:
            headers.append((b"authorization", f"Bearer {api_key}".encode()))
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/v1/auth/cleanup_failed_signup",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
        })

    @pytest.mark.anyio
    async def test_cleanup_rejects_production_environment(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes.auth_invite import cleanup_failed_signup
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest

        monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
        directus_service = AsyncMock()
        cache_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_failed_signup(
                request=self._request(),
                cleanup_request=DevSignupCleanupRequest(hashed_email="hash"),
                directus_service=directus_service,
                cache_service=cache_service,
            )

        assert exc_info.value.status_code == 404
        directus_service.get_user_by_hashed_email.assert_not_called()

    @pytest.mark.anyio
    async def test_cleanup_requires_matching_dev_secret(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes.auth_invite import cleanup_failed_signup
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "cleanup-key")
        directus_service = AsyncMock()
        cache_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_failed_signup(
                request=self._request("wrong-key"),
                cleanup_request=DevSignupCleanupRequest(hashed_email="hash"),
                directus_service=directus_service,
                cache_service=cache_service,
            )

        assert exc_info.value.status_code == 403
        directus_service.get_user_by_hashed_email.assert_not_called()

    @pytest.mark.anyio
    async def test_cleanup_refuses_configured_test_account_hash(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes.auth_invite import cleanup_failed_signup
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest

        configured_email = "persistent@example.test"
        configured_hash = base64.b64encode(hashlib.sha256(configured_email.encode()).digest()).decode()
        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "cleanup-key")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_EMAIL", configured_email)
        directus_service = AsyncMock()
        cache_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_failed_signup(
                request=self._request(),
                cleanup_request=DevSignupCleanupRequest(hashed_email=configured_hash),
                directus_service=directus_service,
                cache_service=cache_service,
            )

        assert exc_info.value.status_code == 403
        directus_service.get_user_by_hashed_email.assert_not_called()

    @pytest.mark.anyio
    async def test_cleanup_returns_success_when_user_is_missing(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes.auth_invite import cleanup_failed_signup
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "cleanup-key")
        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(return_value=(False, None, "User not found"))
        cache_service = AsyncMock()

        response = await cleanup_failed_signup(
            request=self._request(),
            cleanup_request=DevSignupCleanupRequest(hashed_email="hash"),
            directus_service=directus_service,
            cache_service=cache_service,
        )

        assert response.success is True
        assert response.queued is False
        assert response.deleted is False
        cache_service.delete.assert_not_called()

    @pytest.mark.anyio
    async def test_cleanup_queues_account_deletion_and_clears_signup_cache(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes.auth_invite import cleanup_failed_signup
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "cleanup-key")
        send_task = MagicMock(return_value=SimpleNamespace(id="task-1"))
        fake_tasks_package = ModuleType("backend.core.api.app.tasks")
        fake_celery_config = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery_config.app = SimpleNamespace(send_task=send_task)
        monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks", fake_tasks_package)
        monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", fake_celery_config)
        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(
            return_value=(True, {"id": "target-user", "is_admin": False}, "User found")
        )
        cache_service = AsyncMock()

        response = await cleanup_failed_signup(
            request=self._request(),
            cleanup_request=DevSignupCleanupRequest(
                hashed_email="hash",
                test_file="signup-flow-passkey.spec.ts",
                reason="failed test",
            ),
            directus_service=directus_service,
            cache_service=cache_service,
        )

        assert response.success is True
        assert response.queued is True
        assert response.task_id == "task-1"
        send_task.assert_called_once()
        _, kwargs = send_task.call_args
        assert kwargs["name"] == "delete_user_account"
        assert kwargs["kwargs"]["user_id"] == "target-user"
        assert kwargs["kwargs"]["refund_invoices"] is False
        cache_service.delete.assert_awaited_once_with("require_invite_code")

    @pytest.mark.anyio
    async def test_cleanup_accepts_rotating_api_key_for_configured_test_account(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_invite
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest
        from backend.core.api.app.utils import api_key_auth

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "stale-cleanup-key")
        monkeypatch.setattr(auth_invite, "_configured_test_account_hashes", lambda: {"configured-hash"})

        async def fake_authenticate_api_key(_self, api_key, request=None):
            assert api_key == "sk-api-rotated"
            assert request is None
            return {"user_id": "configured-user"}

        monkeypatch.setattr(api_key_auth.ApiKeyAuthService, "authenticate_api_key", fake_authenticate_api_key)

        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(return_value=(False, None, "User not found"))
        cache_service = AsyncMock()

        response = await auth_invite.cleanup_failed_signup(
            request=self._request("sk-api-rotated"),
            cleanup_request=DevSignupCleanupRequest(hashed_email="disposable-hash"),
            directus_service=directus_service,
            cache_service=cache_service,
        )

        assert response.success is True
        assert response.queued is False
        directus_service.get_user_by_hashed_email.assert_awaited_once_with("disposable-hash")

    @pytest.mark.anyio
    async def test_cleanup_accepts_rotating_api_key_when_test_hashes_are_unconfigured(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_invite
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest
        from backend.core.api.app.utils import api_key_auth

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "stale-cleanup-key")
        monkeypatch.setattr(auth_invite, "_configured_test_account_hashes", lambda: set())

        async def fake_authenticate_api_key(_self, api_key, request=None):
            assert api_key == "sk-api-rotated"
            return {"user_id": "configured-user"}

        monkeypatch.setattr(api_key_auth.ApiKeyAuthService, "authenticate_api_key", fake_authenticate_api_key)

        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(return_value=(False, None, "User not found"))
        cache_service = AsyncMock()

        response = await auth_invite.cleanup_failed_signup(
            request=self._request("sk-api-rotated"),
            cleanup_request=DevSignupCleanupRequest(hashed_email="disposable-hash"),
            directus_service=directus_service,
            cache_service=cache_service,
        )

        assert response.success is True
        assert response.queued is False
        directus_service.get_user_by_hashed_email.assert_awaited_once_with("disposable-hash")

    @pytest.mark.anyio
    async def test_cleanup_rejects_invalid_rotating_api_key(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_invite
        from backend.core.api.app.schemas.auth import DevSignupCleanupRequest
        from backend.core.api.app.utils import api_key_auth

        monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
        monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "stale-cleanup-key")
        monkeypatch.setattr(auth_invite, "_configured_test_account_hashes", lambda: {"configured-hash"})

        async def fake_authenticate_api_key(_self, api_key, request=None):
            raise api_key_auth.ApiKeyNotFoundError("API key not found")

        monkeypatch.setattr(api_key_auth.ApiKeyAuthService, "authenticate_api_key", fake_authenticate_api_key)

        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock()
        cache_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await auth_invite.cleanup_failed_signup(
                request=self._request("sk-api-rotated"),
                cleanup_request=DevSignupCleanupRequest(hashed_email="disposable-hash"),
                directus_service=directus_service,
                cache_service=cache_service,
            )

        assert exc_info.value.status_code == 403
        directus_service.get_user_by_hashed_email.assert_not_called()


class TestHashUsernameImport:
    """Verify hash_username is importable and callable as a standalone function.

    This catches the recurring bug where hash_username was moved from a class
    method to a module-level function but call sites still used
    `directus_service.hash_username()`, passing `self` as the first argument.
    Commits: 85f4b48, 80895fb
    """

    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.signup.access-gates
    def test_hash_username_is_module_level_function(self):
        """hash_username should be importable directly, not as a class method."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        assert callable(hash_username)
        # It should NOT be a bound method
        assert not hasattr(hash_username, '__self__'), (
            "hash_username should be a module-level function, not a bound method"
        )

    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.signup.access-gates
    def test_hash_username_returns_string(self):
        """hash_username should accept a username string and return a hash string."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result = hash_username("testuser")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.signup.access-gates
    def test_hash_username_is_deterministic(self):
        """Same input should always produce the same hash."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result1 = hash_username("testuser")
        result2 = hash_username("testuser")
        assert result1 == result2

    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.signup.access-gates
    def test_hash_username_different_inputs_different_hashes(self):
        """Different usernames should produce different hashes."""
        from core.api.app.services.directus.user.user_lookup import hash_username
        result1 = hash_username("alice")
        result2 = hash_username("bob")
        assert result1 != result2

    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.signup.access-gates
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

class TestAuthClientVerification:
    """Test native iOS auth client classification without weakening web origins."""

    def make_request(self, headers: dict[str, str]):
        request = MagicMock()
        request.headers = Headers(headers)
        request.app.state = SimpleNamespace(
            allowed_origins=["https://app.dev.openmates.org"]
        )
        request.url.path = "/v1/auth/login"
        request.method = "POST"
        return request

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary
    async def test_valid_web_origin_accepted_for_login_and_lookup(self):
        from core.api.app.routes.auth_routes.auth_utils import verify_auth_client

        for path in ["/v1/auth/login", "/v1/auth/lookup"]:
            request = self.make_request({"Origin": "https://app.dev.openmates.org"})
            request.url.path = path

            assert await verify_auth_client(request) is True

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary
    async def test_invalid_web_origin_rejected(self):
        from fastapi import HTTPException
        from core.api.app.routes.auth_routes.auth_utils import verify_auth_client

        request = self.make_request({"Origin": "https://evil.example"})

        with pytest.raises(HTTPException) as exc_info:
            await verify_auth_client(request)

        assert exc_info.value.status_code == 403

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary
    async def test_missing_origin_without_native_headers_rejected(self):
        from fastapi import HTTPException
        from core.api.app.routes.auth_routes.auth_utils import verify_auth_client

        request = self.make_request({"User-Agent": "OpenMates-Apple/1.0"})

        with pytest.raises(HTTPException) as exc_info:
            await verify_auth_client(request)

        assert exc_info.value.status_code == 403

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary
    async def test_missing_origin_with_native_ios_headers_accepted(self):
        from core.api.app.routes.auth_routes.auth_utils import verify_auth_client

        request = self.make_request({
            "User-Agent": "OpenMates-Apple/1.0",
            "X-OpenMates-Client": "ios",
        })

        assert await verify_auth_client(request) is True

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.surface.first-party-boundary
    async def test_cli_pair_login_origin_still_accepted(self):
        from core.api.app.routes.auth_routes.auth_utils import verify_auth_client

        request = self.make_request({
            "Origin": "https://app.dev.openmates.org",
            "User-Agent": "OpenMates-CLI/0.1 (linux 6.0)",
        })
        request.url.path = "/v1/auth/login"

        assert await verify_auth_client(request) is True

    # contract-test: supporting surface=rest_api assertions=auth.surface.first-party-boundary
    def test_ios_login_routes_use_auth_client_verifier(self, doc_assert):
        doc_assert("auth-login-routes-use-client-verifier")
        import ast

        repo_root = Path(__file__).parent.parent.parent
        route_files = [
            (
                repo_root / "backend/core/api/app/routes/auth_routes/auth_login.py",
                {"/login", "/lookup"},
            ),
            (
                repo_root / "backend/core/api/app/routes/auth_routes/auth_passkey.py",
                {"/passkey/assertion/initiate", "/passkey/assertion/verify"},
            ),
        ]

        for file_path, expected_paths in route_files:
            tree = ast.parse(file_path.read_text(), filename=str(file_path))
            found_paths = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    if not isinstance(decorator.func, ast.Attribute):
                        continue
                    if decorator.func.attr != "post" or not decorator.args:
                        continue
                    path_arg = decorator.args[0]
                    if not isinstance(path_arg, ast.Constant):
                        continue
                    if path_arg.value not in expected_paths:
                        continue
                    decorator_source = ast.unparse(decorator)
                    assert "Depends(verify_auth_client)" in decorator_source
                    found_paths.add(path_arg.value)

            assert found_paths == expected_paths

    # contract-test: supporting surface=rest_api assertions=auth.lookup.anti-enumeration
    def test_lookup_omits_nullable_account_metadata(self):
        import ast

        route_path = Path(__file__).parent.parent / "core/api/app/routes/auth_routes/auth_login.py"
        tree = ast.parse(route_path.read_text(), filename=str(route_path))
        lookup_decorator = next(
            decorator
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lookup_user"
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "post"
        )
        exclude_none = next(
            keyword.value
            for keyword in lookup_decorator.keywords
            if keyword.arg == "response_model_exclude_none"
        )

        assert isinstance(exclude_none, ast.Constant)
        assert exclude_none.value is True

    # contract-test: direct surface=rest_api assertions=auth.passkey.origin-prf-bound
    def test_passkey_assertion_rejects_wrong_account_credential(self):
        repo_root = Path(__file__).parent.parent.parent
        source = (repo_root / "backend/core/api/app/routes/auth_routes/auth_passkey.py").read_text()

        assert "PASSKEY_WRONG_ACCOUNT_MESSAGE" in source
        assert 'provided_user_id = user_data.get("id") if exists_result and user_data else None' in source
        assert "provided_user_id != user_id" in source


class TestLookupUserCacheWarmup:
    """Regression coverage for login lookup latency under Directus pressure."""

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.lookup.anti-enumeration
    async def test_lookup_returns_salt_before_profile_cache_warmup(self):
        from backend.core.api.app.routes.auth_routes.auth_login import (
            _cache_lookup_user_profile,
            lookup_user,
        )
        from backend.core.api.app.schemas.auth import UserLookupRequest

        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(return_value=(
            True,
            {
                "id": "user-lookup-latency",
                "account_id": "account-lookup-latency",
                "user_email_salt": "real-email-salt",
            },
            "User found",
        ))
        directus_service.get_user_profile = AsyncMock(
            side_effect=AssertionError("lookup must not await profile warmup before returning salt")
        )
        metrics_service = MagicMock()
        metrics_service.track_login_attempt = MagicMock()
        cache_service = AsyncMock()
        background_tasks = BackgroundTasks()

        response = await lookup_user(
            request=MagicMock(),
            lookup_data=UserLookupRequest(hashed_email="hashed-email", stay_logged_in=True),
            background_tasks=background_tasks,
            directus_service=directus_service,
            metrics_service=metrics_service,
            cache_service=cache_service,
            compliance_service=MagicMock(),
        )

        assert response.user_email_salt == "real-email-salt"
        assert response.stay_logged_in is True
        directus_service.get_user_profile.assert_not_called()
        assert len(background_tasks.tasks) == 1
        assert background_tasks.tasks[0].func is _cache_lookup_user_profile

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.lookup.anti-enumeration
    async def test_lookup_returns_503_for_directus_lookup_error(self):
        from backend.core.api.app.routes.auth_routes.auth_login import lookup_user
        from backend.core.api.app.schemas.auth import UserLookupRequest

        directus_service = AsyncMock()
        directus_service.get_user_by_hashed_email = AsyncMock(return_value=(
            False,
            None,
            "Failed to query user by hashed email: 503 - Service unavailable",
        ))
        metrics_service = MagicMock()
        metrics_service.track_login_attempt = MagicMock()
        background_tasks = BackgroundTasks()

        response = await lookup_user(
            request=MagicMock(),
            lookup_data=UserLookupRequest(hashed_email="hashed-email", stay_logged_in=True),
            background_tasks=background_tasks,
            directus_service=directus_service,
            metrics_service=metrics_service,
            cache_service=AsyncMock(),
            compliance_service=MagicMock(),
        )

        assert response.status_code == 503
        assert b"temporarily unavailable" in response.body
        metrics_service.track_login_attempt.assert_not_called()
        assert background_tasks.tasks == []

    @pytest.mark.anyio
    # contract-test: supporting surface=rest_api assertions=auth.lookup.anti-enumeration
    async def test_lookup_cache_helper_writes_complete_profile(self):
        from backend.core.api.app.routes.auth_routes.auth_login import _cache_lookup_user_profile

        directus_service = AsyncMock()
        directus_service.get_user_profile = AsyncMock(return_value=(
            True,
            {
                "id": "user-cache-helper",
                "user_id": "user-cache-helper",
                "username": "testuser",
                "vault_key_id": "vault-key",
                "tfa_enabled": False,
                "last_opened": "/chat/new",
            },
            "Profile found",
        ))
        cache_service = AsyncMock()
        cache_service.is_user_cache_primed = AsyncMock(return_value=True)

        payload = await _cache_lookup_user_profile(
            user_id="user-cache-helper",
            user_email_salt="real-email-salt",
            user_data={"account_id": "account-cache-helper"},
            directus_service=directus_service,
            cache_service=cache_service,
            source="test",
        )

        assert payload is not None
        assert payload["username"] == "testuser"
        assert payload["vault_key_id"] == "vault-key"
        assert payload["account_id"] == "account-cache-helper"
        assert payload["user_email_salt"] == "real-email-salt"
        cache_service.set_user.assert_awaited_once_with(payload)

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence
    async def test_login_refetches_incomplete_user_cache_before_finalizing(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_login
        from backend.core.api.app.schemas.auth import LoginRequest

        user_id = "user-login-cache-fallback"
        directus_service = AsyncMock()
        directus_service.login_user_with_lookup_hash = AsyncMock(return_value=(
            True,
            {
                "user": {
                    "id": user_id,
                    "account_id": "account-login-cache-fallback",
                },
                "cookies": {"directus_refresh_token": "refresh-token"},
            },
            "Authentication successful",
        ))
        directus_service.get_user_fields_direct = AsyncMock(return_value={"user_email_salt": "real-email-salt"})
        directus_service.get_user_profile = AsyncMock(return_value=(
            True,
            {
                "id": user_id,
                "user_id": user_id,
                "account_id": "account-login-cache-fallback",
                "username": "testuser",
                "vault_key_id": "vault-key",
                "tfa_enabled": False,
                "last_opened": "/chat/new",
                "consent_privacy_and_apps_default_settings": True,
                "consent_mates_default_settings": True,
            },
            "Profile found",
        ))
        directus_service.get_encryption_key = AsyncMock(return_value={
            "encrypted_key": "encrypted-key",
            "key_iv": "key-iv",
            "salt": "key-salt",
        })

        cache_service = AsyncMock()
        cache_service.get_user_by_id = AsyncMock(return_value={
            "user_id": user_id,
            "username": "stale-user",
            "vault_key_id": "vault-key",
        })
        cache_service.set_user = AsyncMock(return_value=True)
        cache_service.is_user_cache_primed = AsyncMock(return_value=True)

        monkeypatch.setattr(
            auth_login,
            "generate_device_fingerprint_hash",
            lambda *args, **kwargs: (
                "device-hash",
                "connection-hash",
                "Linux",
                "DE",
                "Berlin",
                None,
                None,
                None,
            ),
        )
        monkeypatch.setattr(auth_login, "finalize_login_session", AsyncMock(return_value="refresh-token"))
        monkeypatch.setattr(auth_login, "_has_free_testing_credits_grant", AsyncMock(return_value=False))

        request = MagicMock()
        request.headers = Headers({"User-Agent": "OpenMates-E2E"})
        request.client = SimpleNamespace(host="127.0.0.1")

        response = await auth_login.login(
            request=request,
            login_data=LoginRequest(
                hashed_email="hashed-email",
                lookup_hash="lookup-hash",
                session_id="browser-session-id",
            ),
            response=Response(),
            directus_service=directus_service,
            cache_service=cache_service,
            encryption_service=AsyncMock(),
            metrics_service=MagicMock(track_login_attempt=MagicMock()),
            compliance_service=MagicMock(),
        )

        assert response.success is True
        assert response.user is not None
        assert response.user.user_email_salt == "real-email-salt"
        directus_service.get_user_fields_direct.assert_awaited_once_with(user_id, ["user_email_salt"])
        cache_service.set_user.assert_awaited_once()
        cached_payload = cache_service.set_user.await_args.args[0]
        assert cached_payload["user_email_salt"] == "real-email-salt"
        assert cached_payload["username"] == "testuser"


class TestLegacyLoginCompatibility:
    """Old and typed credentials retain fresh-device login without unearned proof."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("serialized", [False, True])
    # contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.login.verified-method
    async def test_pending_v2_cannot_authenticate_before_migration_confirmation(self, monkeypatch, serialized):
        from backend.core.api.app.services.directus.user import user_authentication
        from backend.core.api.app.services.password_v2 import KDF_ID

        staged = {"password": {
            "version": 2, "kdf": KDF_ID, "sealed_auth_key": "vault:v1:sealed",
            "wrapper_method": "password_v2_staged", "pending_v1_lookup_hash": "old-hash",
            "pending_v1_wrapper_method": "password",
        }}
        directus = SimpleNamespace(
            base_url="https://directus.example",
            encryption_service=AsyncMock(),
            _make_api_request=AsyncMock(return_value=SimpleNamespace(
                status_code=200, json=lambda: {"data": [{
                    "id": "user-1", "vault_key_id": "vault-key",
                    "lookup_hashes": ["old-hash"],
                    "credential_lookup_hashes": json.dumps(staged) if serialized else staged,
                }]},
            )),
        )
        verifier = AsyncMock(return_value=True)
        monkeypatch.setattr(user_authentication, "verify_challenge_proof", verifier)
        accepted, auth, _ = await user_authentication.login_user_with_lookup_hash(
            directus, "hashed-email", None, credential_version=2,
            challenge_id="challenge-id", password_proof="valid-proof",
            session_id="browser-session", cache_service=AsyncMock(),
        )
        assert accepted is False
        assert auth is None
        verifier.assert_not_awaited()
        directus.encryption_service.hash_email.assert_not_awaited()

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.login.verified-method
    async def test_pending_v2_service_result_cannot_create_login_session(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_login
        from backend.core.api.app.schemas.auth import LoginRequest

        directus = AsyncMock()
        directus.login_user_with_lookup_hash.return_value = (
            True, {"user": {"id": "user-1"}, "password_migration_pending": True}, "ok",
        )
        monkeypatch.setattr(auth_login, "finalize_login_session", AsyncMock())
        result = await auth_login.login(
            request=MagicMock(), login_data=LoginRequest(
                hashed_email="hashed-email", login_method="password",
                credential_version=2, challenge_id="challenge-id",
                password_proof="valid-proof", session_id="browser-session",
            ), response=Response(), directus_service=directus,
            cache_service=AsyncMock(), encryption_service=AsyncMock(),
            metrics_service=MagicMock(), compliance_service=MagicMock(),
        )
        assert result.success is False
        auth_login.finalize_login_session.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("password_v2_present,verified_method,requires_tfa", [
        (False, None, False), (True, None, True), (True, "recovery_key", False),
    ])
    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence,auth.login.verified-method
    async def test_untyped_recovery_on_v2_account_cannot_skip_totp(
        self, monkeypatch, password_v2_present, verified_method, requires_tfa,
    ):
        from backend.core.api.app.routes.auth_routes import auth_login
        from backend.core.api.app.schemas.auth import LoginRequest

        user_id = "legacy-recovery-user"
        directus = AsyncMock()
        directus.login_user_with_lookup_hash.return_value = (
            True, {"user": {"id": user_id, "user_email_salt": "salt"},
                   "verified_lookup_method": verified_method,
                   "verified_wrapper_method": "recovery_key_v2_committed" if verified_method else None,
                   "legacy_recovery_allowed": verified_method is None,
                   "password_v2_present": password_v2_present},
            "Authentication successful",
        )
        directus.get_user_fields_direct.return_value = {"encrypted_tfa_secret": "vault:secret"}
        directus.get_encryption_key.return_value = {
            "encrypted_key": "recovery-wrapped-root", "key_iv": "iv", "salt": "wrap-salt",
        }
        cache = AsyncMock()
        cache.get_user_by_id.return_value = {
            "id": user_id, "username": "legacy-user", "vault_key_id": "vault-key",
            "user_email_salt": "salt", "tfa_enabled": True, "last_opened": "/chat/new",
        }
        cache.is_user_cache_primed.return_value = True
        monkeypatch.setattr(auth_login, "finalize_login_session", AsyncMock(return_value="refresh-token"))
        monkeypatch.setattr(auth_login, "_has_free_testing_credits_grant", AsyncMock(return_value=False))
        monkeypatch.setattr(auth_login, "generate_device_fingerprint_hash", lambda *args, **kwargs: (
            "device", "connection", "Linux", "DE", "Berlin", None, None, None,
        ))
        request = MagicMock()
        request.headers = Headers({"User-Agent": "OpenMates-E2E"})
        request.client = SimpleNamespace(host="127.0.0.1")
        result = await auth_login.login(
            request=request,
            login_data=LoginRequest(
                hashed_email="hashed-email", lookup_hash="retained-untyped-hash",
                login_method="recovery_key", session_id="browser-session-id",
            ),
            response=Response(), directus_service=directus, cache_service=cache,
            encryption_service=AsyncMock(), metrics_service=MagicMock(),
            compliance_service=MagicMock(),
        )
        assert result.tfa_required is requires_tfa
        if requires_tfa:
            auth_login.finalize_login_session.assert_not_awaited()
        else:
            auth_login.finalize_login_session.assert_awaited_once()
            assert directus.get_encryption_key.await_args.args[1] == (
                "recovery_key_v2_committed" if verified_method else "recovery_key"
            )

    @pytest.mark.anyio
    @pytest.mark.parametrize("method,credential_id,expected_wrapper,strong_proof,verified_method", [
        ("password", None, "password", False, None),
        ("recovery_key", None, "recovery_key", False, None),
        ("recovery_key", None, "recovery_key_v2_committed", False, "recovery_key"),
        ("passkey", "credential-123", "passkey_", True, None),
    ])
    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence
    async def test_untyped_legacy_login_returns_usable_wrapper_without_unearned_proof(
        self, monkeypatch, method, credential_id, expected_wrapper, strong_proof, verified_method,
    ):
        from backend.core.api.app.routes.auth_routes import auth_login
        from backend.core.api.app.schemas.auth import LoginRequest

        user_id = "legacy-user-123"
        directus = AsyncMock()
        directus.login_user_with_lookup_hash.return_value = (
            True, {"user": {"id": user_id, "user_email_salt": "salt"},
                   "verified_lookup_method": verified_method,
                   "verified_wrapper_method": expected_wrapper if verified_method else None,
                   "legacy_recovery_allowed": verified_method is None},
            "Authentication successful",
        )
        directus.get_encryption_key.return_value = {
            "encrypted_key": "legacy-wrapped-key", "key_iv": "iv", "salt": "wrap-salt",
        }
        cache = AsyncMock()
        cache.get_user_by_id.return_value = {
            "id": user_id, "username": "legacy-user", "vault_key_id": "vault-key",
            "user_email_salt": "salt", "tfa_enabled": False, "last_opened": "/chat/new",
        }
        cache.get_and_delete.return_value = "verified"
        cache.is_user_cache_primed.return_value = True
        monkeypatch.setattr(auth_login, "finalize_login_session", AsyncMock(return_value="refresh-token"))
        monkeypatch.setattr(auth_login, "_has_free_testing_credits_grant", AsyncMock(return_value=False))
        monkeypatch.setattr(auth_login, "generate_device_fingerprint_hash", lambda *args, **kwargs: (
            "device", "connection", "Linux", "DE", "Berlin", None, None, None,
        ))
        request = MagicMock()
        request.headers = Headers({"User-Agent": "OpenMates-E2E"})
        request.client = SimpleNamespace(host="127.0.0.1")
        result = await auth_login.login(
            request=request,
            login_data=LoginRequest(
                hashed_email="hashed-email", lookup_hash="legacy-lookup",
                login_method=method, credential_id=credential_id, session_id="browser-session-id",
            ),
            response=Response(), directus_service=directus, cache_service=cache,
            encryption_service=AsyncMock(), metrics_service=MagicMock(),
            compliance_service=MagicMock(),
        )
        assert result.success is True
        assert result.user.encrypted_key == "legacy-wrapped-key"
        wrapper = directus.get_encryption_key.await_args.args[1]
        if credential_id:
            assert wrapper == expected_wrapper + hashlib.sha256(credential_id.encode()).hexdigest()
            cache.get_and_delete.assert_awaited_once()
        else:
            assert wrapper == expected_wrapper
        assert auth_login.finalize_login_session.await_args.kwargs["pair_strong_proof"] is strong_proof

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence
    async def test_typed_recovery_hash_cannot_be_relabelled_password(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_login
        from backend.core.api.app.schemas.auth import LoginRequest
        directus = AsyncMock()
        directus.login_user_with_lookup_hash.return_value = (
            True, {"user": {"id": "user-123"}, "verified_lookup_method": "recovery_key"},
            "Authentication successful",
        )
        monkeypatch.setattr(auth_login, "finalize_login_session", AsyncMock())
        result = await auth_login.login(
            request=MagicMock(), login_data=LoginRequest(
                hashed_email="hashed-email", lookup_hash="recovery-hash",
                login_method="password", session_id="browser-session-id",
            ), response=Response(), directus_service=directus,
            cache_service=AsyncMock(), encryption_service=AsyncMock(),
            metrics_service=MagicMock(), compliance_service=MagicMock(),
        )
        assert result.success is False
        auth_login.finalize_login_session.assert_not_awaited()


class TestPasswordCredentialReplacement:
    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement,auth.login.verified-method
    async def test_v2_password_update_defers_ambiguous_legacy_recovery(self, monkeypatch):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes import settings
        from backend.core.api.app.services import credential_verification, session_security_state
        from backend.core.api.app.services.password_v2 import encode_key

        monkeypatch.setattr(credential_verification, "acquire_credential_change_lock",
                            AsyncMock(return_value="lock"))
        monkeypatch.setattr(credential_verification, "release_credential_change_lock", AsyncMock())
        monkeypatch.setattr(session_security_state, "require_recent_strong_proof", AsyncMock())
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = {
            "lookup_hashes": ["old-password", "untyped-recovery"],
            "credential_lookup_hashes": {"password": "old-password"},
            "hashed_email": "hashed-email", "user_email_salt": "email-salt", "vault_key_id": "vault-key",
        }
        directus.get_encryption_key.return_value = {"encrypted_key": "old-wrapper"}
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        with pytest.raises(HTTPException) as deferred:
            await settings.update_password(
                request=request,
                password_request=settings.UpdatePasswordRequest(
                    hashed_email="hashed-email", credential_version=2,
                    password_auth_key=encode_key(bytes(range(32))),
                    encrypted_master_key="new-wrapper", salt="email-salt",
                    key_iv="iv", is_new_password=False,
                ),
                current_user=SimpleNamespace(id="user-123"), directus_service=directus,
                cache_service=AsyncMock(),
            )
        assert deferred.value.status_code == 409
        assert deferred.value.detail["migration_status"] == "deferred_legacy_credentials"
        directus.create_encryption_key.assert_not_awaited()
        directus.update_user.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("typed,expected_hashes,legacy_message", [
        ({}, ["old-untyped", "new-password"], True),
        ({"password": "old-untyped"}, ["new-password"], False),
    ])
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
    async def test_rotation_preserves_untyped_login_but_retires_typed_hash(
        self, monkeypatch, typed, expected_hashes, legacy_message,
    ):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes import settings
        from backend.core.api.app.services import credential_verification, session_security_state

        monkeypatch.setattr(credential_verification, "acquire_credential_change_lock",
                            AsyncMock(return_value="lock"))
        monkeypatch.setattr(credential_verification, "release_credential_change_lock", AsyncMock())
        monkeypatch.setattr(session_security_state, "require_recent_strong_proof", AsyncMock())
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = {
            "lookup_hashes": ["old-untyped"], "credential_lookup_hashes": typed,
            "hashed_email": "hashed-email",
        }
        directus.get_encryption_key.return_value = {"encrypted_key": "old-wrapper"}
        directus.create_encryption_key.return_value = True
        directus.update_user.return_value = True
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        result = await settings.update_password(
            request=request,
            password_request=settings.UpdatePasswordRequest(
                hashed_email="hashed-email", lookup_hash="new-password", encrypted_master_key="new-wrapper",
                salt="salt", key_iv="iv", is_new_password=False,
            ),
            current_user=SimpleNamespace(id="user-123"), directus_service=directus,
            cache_service=AsyncMock(),
        )
        assert result.success is True
        committed = directus.update_user.await_args.args[1]
        assert committed["lookup_hashes"] == expected_hashes
        assert committed["credential_lookup_hashes"]["password"]["lookup_hash"] == "new-password"
        assert committed["credential_lookup_hashes"]["password"]["wrapper_method"].startswith("password_v2_")
        assert ("previous legacy password remains valid" in result.message) is legacy_message

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
    async def test_wrong_account_email_cannot_retire_password(self, monkeypatch):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes import settings
        from backend.core.api.app.services import credential_verification, session_security_state
        monkeypatch.setattr(credential_verification, "acquire_credential_change_lock",
                            AsyncMock(return_value="lock"))
        monkeypatch.setattr(credential_verification, "release_credential_change_lock", AsyncMock())
        monkeypatch.setattr(session_security_state, "require_recent_strong_proof", AsyncMock())
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = {
            "hashed_email": "actual-email", "lookup_hashes": ["old-password"],
            "credential_lookup_hashes": {"password": "old-password"},
        }
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        result = await settings.update_password(
            request, settings.UpdatePasswordRequest(
                hashed_email="different-email", lookup_hash="new-password",
                encrypted_master_key="new-wrapper", salt="salt", key_iv="iv",
                is_new_password=False,
            ), SimpleNamespace(id="user-123"), directus, AsyncMock(),
        )
        assert result.success is False
        directus.create_encryption_key.assert_not_awaited()
        directus.update_user.assert_not_awaited()


class TestExistingPasskeyEnrollment:
    @pytest.mark.anyio
    @pytest.mark.parametrize("commit_succeeds", [False, True])
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement,auth.passkey.origin-prf-bound
    async def test_lookup_and_method_binding_commit_together(self, monkeypatch, commit_succeeds):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes.auth_routes import auth_passkey
        from backend.core.api.app.schemas.auth import PasskeyRegistrationCompleteRequest

        monkeypatch.setattr(auth_passkey, "get_current_user", AsyncMock(return_value=SimpleNamespace(id="user-123")))
        monkeypatch.setattr(auth_passkey, "require_recent_strong_proof", AsyncMock())
        monkeypatch.setattr(auth_passkey, "verify_registration_attestation",
                            AsyncMock(return_value=("verified-cose-key", None, None)))
        monkeypatch.setattr(auth_passkey, "acquire_credential_change_lock", AsyncMock(return_value="lock"))
        monkeypatch.setattr(auth_passkey, "release_credential_change_lock", AsyncMock())
        directus = AsyncMock()
        directus.get_passkey_by_credential_id.side_effect = [
            None, {"id": "new-passkey-id", "user_id": "user-123"},
        ]
        directus.get_user_profile.return_value = (True, {"vault_key_id": "vault-key"}, "ok")
        directus.get_user_fields_direct.return_value = {
            "lookup_hashes": ["existing-password"],
            "credential_lookup_hashes": {"password": "existing-password"},
        }
        directus.create_passkey.return_value = True
        directus.create_encryption_key.return_value = True
        directus.update_user.return_value = commit_succeeds
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        request.headers = Headers({"Origin": "https://example.com"})
        result = await auth_passkey.passkey_registration_complete(
            request=request,
            complete_request=PasskeyRegistrationCompleteRequest(
                credential_id="credential-123", attestation_response={},
                client_data_json="client-data", authenticator_data="auth-data",
                hashed_email="hashed-email", username="existing-user", invite_code="",
                encrypted_email="encrypted-email",
                encrypted_email_with_master_key="email-with-master",
                user_email_salt="email-salt", encrypted_master_key="wrapped-master",
                key_iv="iv", salt="salt", lookup_hash="new-passkey-lookup",
                prf_enabled=True, user_id="current",
            ),
            response=Response(), directus_service=directus, cache_service=AsyncMock(),
            metrics_service=MagicMock(), compliance_service=MagicMock(),
            encryption_service=AsyncMock(),
        )
        assert result.success is commit_succeeds
        directus.add_user_lookup_hash.assert_not_awaited()
        update = directus.update_user.await_args.args[1]
        assert update["lookup_hashes"] == ["existing-password", "new-passkey-lookup"]
        assert update["encrypted_email_with_master_key"] == "email-with-master"
        method = "passkey_" + hashlib.sha256(b"credential-123").hexdigest()
        assert update["credential_lookup_hashes"][method] == "new-passkey-lookup"
        if commit_succeeds:
            directus.delete_passkey.assert_not_awaited()
        else:
            directus.delete_passkey.assert_awaited_once_with("new-passkey-id")
            directus.delete_encryption_key.assert_awaited_once()

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
    async def test_failed_passkey_row_deletion_restores_committed_lookup(self, monkeypatch):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes.auth_routes import auth_passkey
        from backend.core.api.app.schemas.auth import PasskeyDeleteRequest
        monkeypatch.setattr(auth_passkey, "require_recent_strong_proof", AsyncMock())
        monkeypatch.setattr(auth_passkey, "acquire_credential_change_lock", AsyncMock(return_value="lock"))
        monkeypatch.setattr(auth_passkey, "release_credential_change_lock", AsyncMock())
        method = "passkey_" + hashlib.sha256(b"credential-123").hexdigest()
        original = {"lookup_hashes": ["old-passkey-hash"],
                    "credential_lookup_hashes": {method: "old-passkey-hash"}}
        directus = AsyncMock()
        directus.get_user_passkeys.return_value = [
            {"id": "target", "credential_id": "credential-123"},
            {"id": "other", "credential_id": "credential-456"},
        ]
        directus.get_encryption_key.return_value = None
        directus.get_user_fields_direct.return_value = original
        directus.update_user.return_value = True
        directus.delete_passkey.return_value = False
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        result = await auth_passkey.delete_passkey(
            request, PasskeyDeleteRequest(passkey_id="target"),
            SimpleNamespace(id="user-123"), directus, AsyncMock(),
        )
        assert result.success is False
        assert directus.update_user.await_count == 2
        assert directus.update_user.await_args_list[0].args[1]["lookup_hashes"] == []
        assert directus.update_user.await_args_list[1].args[1] == original


class TestSensitiveSettingsGuards:
    @pytest.mark.anyio
    @pytest.mark.parametrize("action", [
        "disable_2fa", "approve_api_key_device", "revoke_api_key_device",
        "confirm_email_change", "delete_account", "update_password",
    ])
    # contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification
    async def test_sensitive_mutation_stops_before_write_without_recent_proof(self, monkeypatch, action):
        fake_websockets = ModuleType("backend.core.api.app.routes.websockets")
        fake_websockets.manager = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.websockets", fake_websockets)
        from backend.core.api.app.routes import settings
        from backend.core.api.app.services import session_security_state

        denied = HTTPException(status_code=401, detail="Recent verification required")
        monkeypatch.setattr(settings, "require_recent_strong_proof", AsyncMock(side_effect=denied))
        monkeypatch.setattr(session_security_state, "require_recent_strong_proof", AsyncMock(side_effect=denied))
        monkeypatch.setattr(settings, "generate_device_fingerprint_hash", lambda *args, **kwargs: (
            "device", "connection", "Linux", "DE", None, None, None, None,
        ))
        request = MagicMock()
        request.cookies = {"auth_refresh_token": "session-token"}
        request.headers = Headers({"User-Agent": "OpenMates-E2E"})
        request.client = SimpleNamespace(host="127.0.0.1")
        user = SimpleNamespace(id="user-123", vault_key_id="vault-key")
        directus, cache = AsyncMock(), AsyncMock()

        calls = {
            "disable_2fa": lambda: settings.disable_2fa(
                request, settings.Disable2FARequest(confirmed_less_secure=True),
                user, directus, cache, MagicMock()),
            "approve_api_key_device": lambda: settings.approve_api_key_device(
                request, "device-id", user, directus, cache),
            "revoke_api_key_device": lambda: settings.revoke_api_key_device(
                request, "device-id", user, directus, cache),
            "confirm_email_change": lambda: settings.confirm_email_change(
                request, settings.ConfirmEmailChangeRequest(
                    new_email="new@example.com", hashed_email="hashed-new-email",
                    encrypted_email_address="encrypted-address",
                    encrypted_email_with_master_key="encrypted-master",
                    auth_method="passkey"),
                user, directus, cache, MagicMock(), AsyncMock()),
            "delete_account": lambda: settings.delete_account(
                request, settings.DeleteAccountRequest(
                    confirm_data_deletion=True, auth_method="passkey"),
                user, directus, AsyncMock(), MagicMock(), cache),
            "update_password": lambda: settings.update_password(
                request, settings.UpdatePasswordRequest(
                    hashed_email="hashed-email", lookup_hash="new-password",
                    encrypted_master_key="encrypted-master", salt="salt", key_iv="iv",
                    is_new_password=False),
                user, directus, cache),
        }
        with pytest.raises(HTTPException) as error:
            await calls[action]()
        assert error.value.status_code == 401
        directus.update_user.assert_not_awaited()
        directus.approve_api_key_device.assert_not_awaited()
        directus.revoke_api_key_device.assert_not_awaited()


class TestRecoveryKeyCacheSync:
    """Recovery credential writes preserve the prior committed login on failure."""

    @staticmethod
    def _request() -> Request:
        return Request({
            "type": "http", "method": "POST",
            "path": "/v1/auth/recovery-key/regenerate",
            "headers": [(b"cookie", b"auth_refresh_token=refresh-token")],
            "client": ("127.0.0.1", 12345),
        })

    @staticmethod
    def _permit(monkeypatch, module):
        monkeypatch.setattr(module, "require_recent_strong_proof", AsyncMock())
        monkeypatch.setattr(module, "acquire_credential_change_lock", AsyncMock(return_value="lock"))
        monkeypatch.setattr(module, "release_credential_change_lock", AsyncMock())

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence,auth.credentials.atomic-replacement
    async def test_confirm_stored_commits_typed_lookup_and_wrapper(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_recoverykey
        from backend.core.api.app.schemas.auth_recoverykey import ConfirmRecoveryKeyStoredRequest
        self._permit(monkeypatch, auth_recoverykey)
        user_data = {"user_id": "user-recovery-cache", "last_opened": "/chat/new"}
        monkeypatch.setattr(auth_recoverykey, "verify_authenticated_user",
                            AsyncMock(return_value=(True, user_data, "refresh-token", None)))
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = {
            "lookup_hashes": ["password-hash"], "credential_lookup_hashes": {"password": "password-hash"}}
        directus.get_encryption_key.return_value = None
        directus.create_encryption_key.return_value = True
        directus.update_user.return_value = True
        cache = AsyncMock()
        cache.set_user.return_value = True
        result = await auth_recoverykey.confirm_recovery_key_stored(
            self._request(), ConfirmRecoveryKeyStoredRequest(
                confirmed=True, lookup_hash="recovery-hash", wrapped_master_key="wrapped",
                key_iv="iv", salt="salt"), directus, cache, MagicMock())
        assert result.success
        committed = directus.update_user.await_args.args[1]
        assert committed["lookup_hashes"] == ["password-hash", "recovery-hash"]
        assert committed["credential_lookup_hashes"]["password"] == "password-hash"
        recovery = committed["credential_lookup_hashes"]["recovery_key"]
        assert recovery["lookup_hash"] == "recovery-hash"
        assert recovery["wrapper_method"].startswith("recovery_key_v2_")
        assert cache.set_user.await_args.kwargs["refresh_token"] == "refresh-token"

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
    async def test_regenerate_retires_only_old_recovery_hash(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_recoverykey
        from backend.core.api.app.schemas.auth_recoverykey import RegenerateRecoveryKeyRequest
        self._permit(monkeypatch, auth_recoverykey)
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = {
            "lookup_hashes": ["password-hash", "old-recovery"],
            "credential_lookup_hashes": {"password": "password-hash", "recovery_key": "old-recovery"}}
        directus.create_encryption_key.return_value = True
        directus.update_user.return_value = True
        cache = AsyncMock()
        result = await auth_recoverykey.regenerate_recovery_key(
            self._request(), RegenerateRecoveryKeyRequest(
                new_lookup_hash="new-recovery", new_wrapped_master_key="new-wrapped",
                new_key_iv="new-iv", new_salt="new-salt", old_lookup_hash="password-hash"),
            SimpleNamespace(id="user-recovery"), directus, cache, MagicMock())
        assert result.success
        committed = directus.update_user.await_args.args[1]
        assert committed["lookup_hashes"] == ["password-hash", "new-recovery"]
        assert committed["credential_lookup_hashes"]["recovery_key"]["lookup_hash"] == "new-recovery"
        directus.delete_encryption_key.assert_not_awaited()

    @pytest.mark.anyio
    # contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
    async def test_failed_regeneration_preserves_committed_credential(self, monkeypatch):
        from backend.core.api.app.routes.auth_routes import auth_recoverykey
        from backend.core.api.app.schemas.auth_recoverykey import RegenerateRecoveryKeyRequest
        self._permit(monkeypatch, auth_recoverykey)
        original = {"lookup_hashes": ["old-recovery"],
                    "credential_lookup_hashes": {"recovery_key": "old-recovery"}}
        directus = AsyncMock()
        directus.get_user_fields_direct.return_value = original
        directus.create_encryption_key.return_value = True
        directus.update_user.return_value = False
        cache = AsyncMock()
        result = await auth_recoverykey.regenerate_recovery_key(
            self._request(), RegenerateRecoveryKeyRequest(
                new_lookup_hash="new-recovery", new_wrapped_master_key="new-wrapped",
                new_key_iv="new-iv", new_salt="new-salt", old_lookup_hash="old-recovery"),
            SimpleNamespace(id="user-recovery"), directus, cache, MagicMock())
        assert not result.success
        assert original["lookup_hashes"] == ["old-recovery"]
        assert original["credential_lookup_hashes"] == {"recovery_key": "old-recovery"}
        removed_method = directus.delete_encryption_key.await_args.args[1]
        assert removed_method.startswith("recovery_key_v2_")
        cache.delete.assert_not_awaited()

class TestSignupGiftCardFreeTestingEligibility:
    @pytest.mark.anyio
    # contract-test: supporting surface=rest_api assertions=billing.purchase.provider-routing
    async def test_pending_signup_gift_card_requires_existing_redeemable_card(self):
        from core.api.app.routes.auth_routes.auth_utils import has_pending_signup_gift_card

        directus_service = AsyncMock()
        directus_service.get_gift_card_by_code = AsyncMock(return_value={"code": "AB23-CDEF-4567"})

        assert await has_pending_signup_gift_card(directus_service, "ab23-cdef-4567") is True
        directus_service.get_gift_card_by_code.assert_awaited_once_with("AB23-CDEF-4567")

    @pytest.mark.anyio
    # contract-test: supporting surface=rest_api assertions=billing.purchase.provider-routing
    async def test_pending_signup_gift_card_ignores_empty_invalid_or_unknown_codes(self):
        from core.api.app.routes.auth_routes.auth_utils import has_pending_signup_gift_card

        directus_service = AsyncMock()
        directus_service.get_gift_card_by_code = AsyncMock(return_value=None)

        assert await has_pending_signup_gift_card(directus_service, None) is False
        assert await has_pending_signup_gift_card(directus_service, "not-a-gift-card") is False
        assert await has_pending_signup_gift_card(directus_service, "AB23-CDEF-4567") is False
        directus_service.get_gift_card_by_code.assert_awaited_once_with("AB23-CDEF-4567")

    @pytest.mark.anyio
    # contract-test: supporting surface=rest_api assertions=billing.purchase.provider-routing
    async def test_pending_signup_gift_card_validation_errors_fail_closed(self):
        from core.api.app.routes.auth_routes.auth_utils import has_pending_signup_gift_card

        directus_service = AsyncMock()
        directus_service.get_gift_card_by_code = AsyncMock(side_effect=RuntimeError("lookup unavailable"))

        assert await has_pending_signup_gift_card(directus_service, "AB23-CDEF-4567") is True


class TestLoginRequestValidation:
    """Test that LoginRequest schema validates correctly.

    Catches bugs where required fields are missing or wrong field names
    are used (e.g., userEmailSalt vs hashed_email). Commit: 498d5c0
    """

    # contract-test: direct surface=rest_api assertions=auth.keys.client-wrapped,auth.login.method-convergence
    def test_login_request_requires_hashed_email(self, doc_assert):
        """LoginRequest should require hashed_email field."""
        doc_assert("auth-login-request-requires-lookup-fields")
        from core.api.app.schemas.auth import LoginRequest
        with pytest.raises(Exception):
            LoginRequest(lookup_hash="test-hash")  # Missing hashed_email

    # contract-test: direct surface=rest_api assertions=auth.keys.client-wrapped,auth.login.method-convergence
    def test_login_request_requires_lookup_hash(self, doc_assert):
        """LoginRequest should require lookup_hash field."""
        doc_assert("auth-login-request-requires-lookup-fields")
        from core.api.app.schemas.auth import LoginRequest
        with pytest.raises(Exception):
            LoginRequest(hashed_email="test-email")  # Missing lookup_hash

    # contract-test: direct surface=rest_api assertions=auth.keys.client-wrapped,auth.login.method-convergence
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

    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    def test_login_request_stay_logged_in_default_false(self, doc_assert):
        """stay_logged_in should default to False, not be omitted.

        Catches the bug where stay_logged_in was never sent to backend
        in pair login flow. Commit: 0973bc4
        """
        doc_assert("auth-login-request-defaults-stay-logged-in-off")
        from core.api.app.schemas.auth import LoginRequest
        req = LoginRequest(
            hashed_email="test",
            lookup_hash="test",
        )
        assert req.stay_logged_in is False

    # contract-test: direct surface=rest_api assertions=auth.login.method-convergence
    def test_login_request_accepts_all_login_methods(self, doc_assert):
        """LoginRequest should accept all valid login_method values."""
        doc_assert("auth-login-accepts-supported-methods")
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

    # contract-test: supporting surface=rest_api assertions=auth.login.method-convergence
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

    # contract-test: supporting surface=rest_api assertions=auth.login.method-convergence
    def test_login_response_failure_shape(self):
        """Failed login response should have success=False and message."""
        from core.api.app.schemas.auth import LoginResponse
        resp = LoginResponse(
            success=False,
            message="Invalid credentials",
        )
        assert resp.success is False
        assert resp.user is None

    # contract-test: supporting surface=rest_api assertions=auth.login.method-convergence
    def test_login_response_tfa_required(self):
        """2FA-required response should have tfa_required=True."""
        from core.api.app.schemas.auth import LoginResponse
        resp = LoginResponse(
            success=True,
            message="2FA required",
            tfa_required=True,
        )
        assert resp.tfa_required is True


class TestDirectusCookieNormalization:
    """Ensure Directus refresh cookies always become OpenMates auth cookies.

    Production can receive either ``directus_refresh_token`` or ``refresh_token``
    from Directus depending on Directus/cookie configuration. Both must feed the
    same ``auth_refresh_token`` cookie and ws_token/session-cache path.
    """

    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    def test_directus_refresh_token_cookie_is_normalized(self):
        from core.api.app.utils.directus_cookies import (
            extract_directus_refresh_token,
            normalize_directus_cookie,
        )

        cookies = {"directus_refresh_token": "directus-refresh"}

        assert extract_directus_refresh_token(cookies) == "directus-refresh"
        assert normalize_directus_cookie("directus_refresh_token") == "auth_refresh_token"

    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    def test_plain_refresh_token_cookie_is_normalized(self):
        from core.api.app.utils.directus_cookies import (
            extract_directus_refresh_token,
            normalize_directus_cookie,
        )

        cookies = {"refresh_token": "plain-refresh"}

        assert extract_directus_refresh_token(cookies) == "plain-refresh"
        assert normalize_directus_cookie("refresh_token") == "auth_refresh_token"

    # contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
    def test_other_directus_cookies_keep_existing_auth_prefix_behavior(self):
        from core.api.app.utils.directus_cookies import normalize_directus_cookie

        assert normalize_directus_cookie("directus_session_token") == "auth_session_token"
        assert normalize_directus_cookie("custom_cookie") == "custom_cookie"


# ─── Test: Cache miss fallback pattern ───────────────────────────────────────

class TestCacheMissFallback:
    """Test that auth services fall back to Directus on cache miss.

    Catches the anti-pattern where cache_service.get_user_data() returning None
    is treated as a terminal error instead of falling back to the database.
    Commits: e4d5ea5, 792526c, a20bacf
    """

    @pytest.fixture(autouse=True)
    def ordinary_session(self, monkeypatch):
        """These legacy fallback cases use ordinary, non-paired sessions."""
        from backend.core.api.app.services import pair_session_deadline
        from core.api.app.routes.auth_routes import auth_common, auth_dependencies
        monkeypatch.setattr(pair_session_deadline, "_record", AsyncMock(return_value=None))
        async def rotate(_cache, directus, token):
            return await directus.refresh_token(token)
        for module in (auth_common, auth_dependencies):
            monkeypatch.setattr(module, "refresh_session_token", rotate)
            monkeypatch.setattr(module, "complete_refresh_rotation", AsyncMock())

    @pytest.mark.anyio
    @pytest.mark.integration
    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    async def test_verify_authenticated_user_falls_back_on_cache_miss(
        self, mock_cache_service, mock_directus_service, doc_assert
    ):
        """When cache returns None, auth should try Directus refresh_token."""
        doc_assert("auth-session-falls-back-on-cache-miss")
        from core.api.app.routes.auth_routes import auth_common
        verify_authenticated_user = auth_common.verify_authenticated_user

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

    @pytest.mark.anyio
    @pytest.mark.integration
    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    async def test_verify_authenticated_user_preserves_stay_logged_in_on_rotated_fallback(self):
        """Cache-miss fallback must not downgrade stay_logged_in sessions to 24h."""
        from core.api.app.routes.auth_routes.auth_common import verify_authenticated_user

        old_token = "valid-refresh-token"
        new_token = "new-refresh-token"
        old_hash = hashlib.sha256(old_token.encode()).hexdigest()
        new_hash = hashlib.sha256(new_token.encode()).hexdigest()

        cache_service = AsyncMock()
        cache_service.SESSION_TTL = 86400
        cache_service.SESSION_KEY_PREFIX = "session:"
        cache_service.get_user_by_token = AsyncMock(return_value=None)
        async def cached_value(key):
            if key == "user_tokens:test-user-id":
                return {old_hash: {"created_at": 1710000000, "stay_logged_in": True}}
            return None
        cache_service.get = AsyncMock(side_effect=cached_value)
        cache_service.set = AsyncMock(return_value=True)
        cache_service.set_user = AsyncMock(return_value=True)

        directus_service = AsyncMock()
        directus_service.get_items = AsyncMock(return_value=[])
        directus_service.create_item = AsyncMock(
            side_effect=lambda _collection, payload, **_kwargs: (True, {"id": "session-ledger", **payload}))
        directus_service.refresh_token = AsyncMock(return_value=(
            True,
            {
                "cookies": {"directus_refresh_token": new_token},
                "data": {"access_token": "new-access-token"},
            },
            "Token refreshed",
        ))
        directus_service.validate_token = AsyncMock(return_value=(True, {"id": "test-user-id"}))
        directus_service.get_user_profile = AsyncMock(return_value=(
            True,
            {"id": "test-user-id", "username": "testuser", "vault_key_id": "vault-key"},
            "ok",
        ))

        mock_request = MagicMock()
        mock_request.cookies = {"auth_refresh_token": old_token}
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value="Mozilla/5.0")
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        success, user_data, refresh_token, auth_status = await verify_authenticated_user(
            request=mock_request,
            cache_service=cache_service,
            directus_service=directus_service,
            require_known_device=False,
        )

        assert success is True
        assert auth_status is None
        assert refresh_token == new_token
        assert user_data["stay_logged_in"] is True
        cache_service.set_user.assert_awaited_once()
        assert cache_service.set_user.await_args.kwargs["ttl"] == 2592000

        token_writes = [call for call in cache_service.set.await_args_list
                        if call.args and call.args[0] == "user_tokens:test-user-id"]
        assert len(token_writes) == 1
        token_map = token_writes[0].args[1]
        assert old_hash not in token_map
        assert token_map[new_hash]["stay_logged_in"] is True
        assert token_writes[0].kwargs["ttl"] == 2592000 * 7

    @pytest.mark.anyio
    @pytest.mark.integration
    # contract-test: direct surface=rest_api assertions=auth.session.lifecycle
    async def test_get_current_user_sets_rotated_cookie_on_cache_miss_fallback(self):
        """get_current_user fallback rotates Directus tokens and must update the browser cookie."""
        from core.api.app.routes.auth_routes.auth_dependencies import get_current_user

        old_token = "valid-refresh-token"
        new_token = "new-refresh-token"
        old_hash = hashlib.sha256(old_token.encode()).hexdigest()

        cache_service = AsyncMock()
        cache_service.SESSION_TTL = 86400
        cache_service.SESSION_KEY_PREFIX = "session:"
        cache_service.get_user_by_token = AsyncMock(return_value=None)
        async def cached_value(key):
            if key == "user_tokens:test-user-id":
                return {old_hash: {"created_at": 1710000000, "stay_logged_in": True}}
            return None
        cache_service.get = AsyncMock(side_effect=cached_value)
        cache_service.set = AsyncMock(return_value=True)
        cache_service.set_user = AsyncMock(return_value=True)

        directus_service = AsyncMock()
        directus_service.get_items = AsyncMock(return_value=[])
        directus_service.create_item = AsyncMock(
            side_effect=lambda _collection, payload, **_kwargs: (True, {"id": "session-ledger", **payload}))
        directus_service.refresh_token = AsyncMock(return_value=(
            True,
            {
                "cookies": {"directus_refresh_token": new_token},
                "data": {"access_token": "new-access-token"},
            },
            "Token refreshed",
        ))
        directus_service.validate_token = AsyncMock(return_value=(True, {"id": "test-user-id"}))
        directus_service.get_user_profile = AsyncMock(return_value=(
            True,
            {"id": "test-user-id", "username": "testuser", "vault_key_id": "vault-key"},
            "ok",
        ))
        response = Response()

        user = await get_current_user(
            directus_service=directus_service,
            cache_service=cache_service,
            refresh_token=old_token,
            response=response,
        )

        assert user.id == "test-user-id"
        cache_service.set_user.assert_awaited_once()
        assert cache_service.set_user.await_args.kwargs["refresh_token"] == new_token
        assert cache_service.set_user.await_args.kwargs["ttl"] == 2592000
        set_cookie_headers = [
            value.decode()
            for key, value in response.raw_headers
            if key == b"set-cookie"
        ]
        assert any("auth_refresh_token=new-refresh-token" in header for header in set_cookie_headers)
        assert any("Max-Age=2592000" in header for header in set_cookie_headers)

    @pytest.mark.anyio
    @pytest.mark.integration
    # contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
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

    # contract-test: direct surface=rest_api assertions=auth.signup.access-gates
    def test_requires_email_and_hashed_email(self):
        """Should require both email and hashed_email."""
        from core.api.app.schemas.auth import RequestEmailCodeRequest
        with pytest.raises(Exception):
            RequestEmailCodeRequest(email="test@example.com")  # Missing hashed_email

    # contract-test: direct surface=rest_api assertions=auth.signup.access-gates
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

    # contract-test: direct surface=rest_api assertions=auth.signup.access-gates
    def test_check_username_request_shape(self):
        """CheckUsernameRequest should accept a username string."""
        from core.api.app.schemas.auth import CheckUsernameRequest
        req = CheckUsernameRequest(username="testuser")
        assert req.username == "testuser"

    # contract-test: direct surface=rest_api assertions=auth.signup.access-gates
    def test_check_username_response_shape(self):
        """CheckUsernameResponse should have available flag."""
        from core.api.app.schemas.auth import CheckUsernameResponse
        resp = CheckUsernameResponse(available=True, message="Username available")
        assert resp.available is True
