# backend/tests/test_sightengine_service.py
#
# Unit tests for the SightEngine image scanning service and health check probe.
#
# What is tested here (and why it matters):
#
#   1. SightEngineService.check_all() — the primary upload path — sends raw image
#      BYTES via multipart POST, never a URL.  A URL-based probe broke silently
#      after the S3 migration (private buckets → presigned URLs → no public URL),
#      and the old health check was using a Wikimedia URL that returned 404,
#      generating ~576 spurious 404 errors/day in the Sightengine account logs.
#      These tests guard against regressing to any URL-based approach.
#
#   2. ContentSafetyResult threshold logic — safety thresholds are enforced
#      correctly for all eight blocked score types.
#
#   3. Fail-open behaviour — an API error or timeout must NEVER block an upload.
#      Sightengine is a moderation layer, not a gatekeeper for availability.
#
#   4. Disabled state — when credentials are absent the service must skip cleanly.
#
#   5. Health check probe — _check_sightengine_health() must send a multipart POST
#      (not a GET with ?url=), and the inline JPEG constant must be a valid image.
#
# Architecture reference: docs/architecture/file-upload-pipeline.md
#
# Execution:
#   .venv/bin/python3 -m pytest -s backend/tests/test_sightengine_service.py

import importlib.util
import io
import json
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Import health_check_tasks directly from the file (not via the tasks package
# __init__.py) to avoid a polar_sdk dependency that isn't installed in the
# local venv (polar_sdk is only available inside the Docker containers).
# ---------------------------------------------------------------------------

def _load_health_check_tasks_module():
    """Load health_check_tasks without triggering the tasks package __init__."""
    import os
    file_path = os.path.join(
        os.path.dirname(__file__),
        "..", "core", "api", "app", "tasks", "health_check_tasks.py",
    )
    file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(
        "backend.core.api.app.tasks.health_check_tasks", file_path
    )
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so patch() can find it by dotted path
    sys.modules["backend.core.api.app.tasks.health_check_tasks"] = module
    spec.loader.exec_module(module)
    return module


# Load once at module import time (tests import from this module-level var)
_hct_load_error: str = ""
try:
    _hct = _load_health_check_tasks_module()
    _HEALTH_CHECK_TASKS_AVAILABLE = True
except Exception as _e:
    _hct_load_error = str(_e)
    _HEALTH_CHECK_TASKS_AVAILABLE = False
    _hct = None

# ---------------------------------------------------------------------------
# Helpers — build realistic fake Sightengine JSON responses
# ---------------------------------------------------------------------------

def _safe_response(
    sexual_activity: float = 0.0,
    sexual_display: float = 0.0,
    erotica: float = 0.0,
    sextoy: float = 0.0,
    suggestive: float = 0.0,
    weapon: float = 0.0,
    gore: float = 0.0,
    blood: float = 0.0,
    ai_generated: float = 0.1,
) -> dict:
    """Return a Sightengine-shaped JSON dict with the given scores."""
    return {
        "status": "success",
        "nudity": {
            "sexual_activity": sexual_activity,
            "sexual_display": sexual_display,
            "erotica": erotica,
            "sextoy": sextoy,
            "suggestive": suggestive,
        },
        "offensive": {"weapon": weapon},
        "gore": {"gore": gore, "blood": blood},
        "type": {"ai_generated": ai_generated},
    }


def _make_mock_response(json_body: dict, status_code: int = 200) -> MagicMock:
    """Build an httpx-like mock response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_body
    mock.text = json.dumps(json_body)
    return mock


# ---------------------------------------------------------------------------
# Fixture: an enabled SightEngineService
# ---------------------------------------------------------------------------

@pytest.fixture
def enabled_service():
    """SightEngineService pre-loaded with fake credentials (no Vault call)."""
    from backend.upload.services.sightengine_service import SightEngineService

    svc = SightEngineService()
    svc.api_user = "test_user"
    svc.api_secret = "test_secret"
    svc._enabled = True
    return svc


@pytest.fixture
def disabled_service():
    """SightEngineService with no credentials (as if Vault was unreachable)."""
    from backend.upload.services.sightengine_service import SightEngineService

    svc = SightEngineService()
    # _enabled is False by default
    return svc


DUMMY_IMAGE = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG-ish bytes


# ===========================================================================
# 1. API call shape — bytes, NOT a URL
# ===========================================================================

class TestApiCallShape:
    """
    The Sightengine API must be called via multipart POST with raw image bytes.

    Regression guard: before the S3 migration the health check (and an early
    version of the service) passed a ?url= parameter.  Once the S3 bucket
    became private, those URLs returned 404 to Sightengine's fetch servers.
    """

    @pytest.mark.asyncio
    async def test_check_all_posts_bytes_not_url(self, enabled_service):
        """check_all() must POST bytes via files={media: ...}, no url= param."""
        mock_resp = _make_mock_response(_safe_response())

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await enabled_service.check_all(DUMMY_IMAGE, filename="photo.jpg")

        mock_client.post.assert_called_once()
        _, kwargs = mock_client.post.call_args

        # Must use multipart files — never a URL string
        assert "files" in kwargs, "Must send bytes via files= (not url= param)"
        files = kwargs["files"]
        assert "media" in files, "files must contain 'media' key"
        media_tuple = files["media"]
        # Tuple is (filename, bytes, content_type)
        assert isinstance(media_tuple, tuple) and len(media_tuple) == 3
        assert isinstance(media_tuple[1], bytes), "Payload must be raw bytes"

        # Confirm no url= in form data
        data = kwargs.get("data", {})
        assert "url" not in data, "Must NOT pass url= to Sightengine"

        # Confirm method is POST (not GET)
        assert not mock_client.get.called, "Must use POST, not GET"

    @pytest.mark.asyncio
    async def test_check_content_safety_posts_bytes(self, enabled_service):
        """check_content_safety() (legacy) also sends bytes, not a URL."""
        mock_resp = _make_mock_response(_safe_response())

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await enabled_service.check_content_safety(DUMMY_IMAGE)

        _, kwargs = mock_client.post.call_args
        assert "files" in kwargs
        assert "url" not in kwargs.get("data", {})

    @pytest.mark.asyncio
    async def test_check_image_posts_bytes(self, enabled_service):
        """check_image() (legacy AI detection) also sends bytes, not a URL."""
        mock_resp = _make_mock_response(_safe_response(ai_generated=0.85))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await enabled_service.check_image(DUMMY_IMAGE)

        _, kwargs = mock_client.post.call_args
        assert "files" in kwargs
        assert "url" not in kwargs.get("data", {})


# ===========================================================================
# 2. ContentSafetyResult — threshold logic
# ===========================================================================

class TestSafetyThresholds:
    """Each of the eight moderated score types must trigger rejection."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,threshold,kwarg", [
        # (score_field_name, rejection_threshold, kwargs key for _safe_response)
        ("sexual_activity", 0.31, "sexual_activity"),
        ("sexual_display",  0.31, "sexual_display"),
        ("erotica",         0.41, "erotica"),
        ("sextoy",          0.31, "sextoy"),
        ("suggestive",      0.61, "suggestive"),
        ("weapon",          0.51, "weapon"),
        ("gore",            0.31, "gore"),
        ("blood",           0.41, "blood"),
    ])
    async def test_score_above_threshold_rejects(self, enabled_service, field, threshold, kwarg):
        """A score above the threshold must produce is_safe=False."""
        resp_body = _safe_response(**{kwarg: threshold})
        mock_resp = _make_mock_response(resp_body)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            safety_result, _ = await enabled_service.check_all(DUMMY_IMAGE)

        assert not safety_result.is_safe, (
            f"Expected rejection for {kwarg}={threshold} but got is_safe=True"
        )
        assert safety_result.reason is not None

    @pytest.mark.asyncio
    async def test_all_scores_below_threshold_allows(self, enabled_service):
        """Clean image (all scores below threshold) must pass."""
        mock_resp = _make_mock_response(_safe_response())

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            safety_result, ai_result = await enabled_service.check_all(DUMMY_IMAGE)

        assert safety_result.is_safe
        assert safety_result.reason is None
        assert ai_result is not None
        assert 0.0 <= ai_result.ai_generated <= 1.0


# ===========================================================================
# 3. Fail-open behaviour — API errors must never block uploads
# ===========================================================================

class TestFailOpen:
    """Sightengine outages / errors must never prevent legitimate uploads."""

    @pytest.mark.asyncio
    async def test_http_500_fails_open(self, enabled_service):
        """HTTP 500 from Sightengine → is_safe=True (allow upload)."""
        mock_resp = _make_mock_response({}, status_code=500)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            safety_result, ai_result = await enabled_service.check_all(DUMMY_IMAGE)

        assert safety_result.is_safe
        assert safety_result.error is not None
        assert ai_result is None

    @pytest.mark.asyncio
    async def test_timeout_fails_open(self, enabled_service):
        """Network timeout → is_safe=True (allow upload)."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            safety_result, ai_result = await enabled_service.check_all(DUMMY_IMAGE)

        assert safety_result.is_safe
        assert safety_result.error == "timeout"
        assert ai_result is None

    @pytest.mark.asyncio
    async def test_non_success_status_in_json_fails_open(self, enabled_service):
        """Sightengine returning status!=success in JSON body → fail open."""
        mock_resp = _make_mock_response({
            "status": "failure",
            "error": {"type": 3, "message": "image unavailable"},
        })

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            safety_result, ai_result = await enabled_service.check_all(DUMMY_IMAGE)

        assert safety_result.is_safe
        assert ai_result is None


# ===========================================================================
# 4. Disabled state
# ===========================================================================

class TestDisabledState:
    """When credentials are absent every method must skip cleanly."""

    @pytest.mark.asyncio
    async def test_check_all_skips_when_disabled(self, disabled_service):
        """check_all() must return (safe=True, None) without any HTTP call."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            safety_result, ai_result = await disabled_service.check_all(DUMMY_IMAGE)
            mock_client_cls.assert_not_called()

        assert safety_result.is_safe
        assert ai_result is None

    @pytest.mark.asyncio
    async def test_check_content_safety_skips_when_disabled(self, disabled_service):
        with patch("httpx.AsyncClient") as mock_client_cls:
            result = await disabled_service.check_content_safety(DUMMY_IMAGE)
            mock_client_cls.assert_not_called()

        assert result.is_safe

    def test_is_enabled_false_by_default(self):
        from backend.upload.services.sightengine_service import SightEngineService
        svc = SightEngineService()
        assert not svc.is_enabled


# ===========================================================================
# 5. Health check probe — inline bytes constant + POST shape
# ===========================================================================

@pytest.mark.skipif(
    not _HEALTH_CHECK_TASKS_AVAILABLE,
    reason=f"health_check_tasks module could not be loaded: {_hct_load_error}",
)
class TestHealthCheckProbe:
    """
    Guards against regressing back to a URL-based health check probe.

    The previous probe used:
        GET /check.json?url=https://upload.wikimedia.org/...Transparent.gif
    That URL returned 404, generating ~576 spurious errors/day in Sightengine
    account logs across both servers.

    The current probe sends a tiny inline JPEG via multipart POST, mirroring
    the real upload pipeline and eliminating any external URL dependency.

    Note: imports are resolved from the pre-loaded _hct module-level variable
    to avoid triggering the tasks/__init__.py which transitively imports
    polar_sdk (only available inside Docker containers, not in the local venv).
    """

    def test_health_check_image_constant_is_valid_jpeg(self):
        """SIGHTENGINE_HEALTH_CHECK_IMAGE_BYTES must decode to a valid JPEG."""
        data = _hct.SIGHTENGINE_HEALTH_CHECK_IMAGE_BYTES

        assert len(data) > 0, "Constant must not be empty"
        assert data[:2] == bytes([0xFF, 0xD8]), "Must start with JPEG SOI marker (FFD8)"
        assert data[-2:] == bytes([0xFF, 0xD9]), "Must end with JPEG EOI marker (FFD9)"

        # Verify Pillow can decode it (catches truncated/corrupt bytes)
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.verify()  # raises on corrupt JPEG

    def test_health_check_image_constant_is_bytes(self):
        """The constant must be a bytes object (not str or None)."""
        # If base64.b64decode raised at module load, _HEALTH_CHECK_TASKS_AVAILABLE
        # would be False and this class would be skipped. This test documents intent.
        assert isinstance(_hct.SIGHTENGINE_HEALTH_CHECK_IMAGE_BYTES, bytes)

    @pytest.mark.asyncio
    async def test_health_check_uses_post_with_files_not_get_with_url(self):
        """
        _check_sightengine_health() must use POST with files=, NOT GET with url=.

        This test directly encodes the original bug: the probe was a GET request
        with a ?url= param pointing at a now-404 Wikimedia image.
        """
        _check_sightengine_health = _hct._check_sightengine_health

        mock_secrets = AsyncMock()
        mock_secrets.get_secret = AsyncMock(side_effect=["test_user", "test_secret"])

        mock_resp = _make_mock_response({"status": "success", "nudity": {}})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.get = AsyncMock()  # must NOT be called
            mock_client_cls.return_value = mock_client

            # Patch cache and health event recording to keep test isolated
            with patch.object(_hct, "CacheService") as mock_cache_cls, \
                 patch.object(_hct, "_record_health_event_if_changed", new_callable=AsyncMock):
                mock_cache = AsyncMock()
                mock_cache.client = AsyncMock(return_value=None)
                mock_cache_cls.return_value = mock_cache

                await _check_sightengine_health(mock_secrets)

        # Verify POST was used
        mock_client.post.assert_called_once()
        _, kwargs = mock_client.post.call_args

        # Must send files=, not url=
        assert "files" in kwargs, (
            "Health check must send image bytes via files= (multipart POST)"
        )
        assert "media" in kwargs["files"], "files must contain 'media' key"

        form_data = kwargs.get("data", {})
        assert "url" not in form_data, (
            "Health check must NOT pass url= to Sightengine — "
            "URL-based probes break silently when the target URL goes stale"
        )

        # Verify GET was never called
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_skipped_when_no_credentials(self):
        """Health check must return skipped (not unhealthy) if credentials absent."""
        _check_sightengine_health = _hct._check_sightengine_health

        mock_secrets = AsyncMock()
        mock_secrets.get_secret = AsyncMock(return_value=None)  # no credentials

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch.object(_hct, "CacheService"):
            result = await _check_sightengine_health(mock_secrets)
            mock_client_cls.assert_not_called()

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy_on_200(self):
        """A 200 response from Sightengine must produce status=healthy."""
        _check_sightengine_health = _hct._check_sightengine_health

        mock_secrets = AsyncMock()
        mock_secrets.get_secret = AsyncMock(side_effect=["u", "s"])

        mock_resp = _make_mock_response({"status": "success", "nudity": {}})

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch.object(_hct, "CacheService") as mock_cache_cls, \
             patch.object(_hct, "_record_health_event_if_changed", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            mock_cache = AsyncMock()
            mock_cache.client = AsyncMock(return_value=None)
            mock_cache_cls.return_value = mock_cache

            result = await _check_sightengine_health(mock_secrets)

        assert result["status"] == "healthy"
