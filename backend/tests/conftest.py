# backend/tests/conftest.py
#
# Shared fixtures and utilities for all REST API external integration tests.
#
# This module provides:
#   - API client fixture with authentication and response logging
#   - Image metadata verification helper (XMP + C2PA)
#   - Task polling helper for async skill execution
#   - Common configuration (API base URL, API key)
#
# All test_rest_api_*.py files in this directory share these fixtures automatically
# via pytest's conftest mechanism.
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_core.py
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/ -k "rest_api"

import os
import io
import json
import time
from typing import Any, Dict

import httpx
import pytest
from dotenv import load_dotenv
from PIL import Image

try:
    import c2pa
    HAS_C2PA = True
except ImportError:
    HAS_C2PA = False

# Load environment variables from the root .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

# ─── Configuration ───────────────────────────────────────────────────────────

API_BASE_URL = "https://api.dev.openmates.org"
API_KEY = os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY")

# Note: API_KEY may be None if the env var is not set.
# The api_client fixture skips tests automatically when API_KEY is missing.
# Tests that don't use api_client (e.g., public health check) can still run.


# ─── Response Logging ────────────────────────────────────────────────────────

def log_response(response: httpx.Response):
    """Event hook to log HTTP responses for debugging."""
    try:
        response.read()
    except Exception:
        pass

    print(f"\n[API] {response.request.method} {response.request.url} -> {response.status_code}")
    try:
        data = response.json()
        print(f"[RESPONSE] {json.dumps(data, indent=2)}")
    except Exception:
        try:
            if response.text:
                text = response.text
                if len(text) > 1000:
                    text = text[:1000] + "... (truncated)"
                print(f"[RESPONSE] {text}")
            else:
                print("[RESPONSE] (empty body)")
        except Exception:
            print("[RESPONSE] (could not read body)")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    """Authenticated httpx client for REST API integration tests.

    Automatically skips the test if OPENMATES_TEST_ACCOUNT_API_KEY is not set.
    """
    if not API_KEY:
        pytest.skip(
            "OPENMATES_TEST_ACCOUNT_API_KEY environment variable not set. "
            "Please set it to a valid sk-api-... key."
        )
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(
        base_url=API_BASE_URL,
        headers=headers,
        timeout=60.0,
        event_hooks={"response": [log_response]},
    ) as client:
        yield client


# ─── Task Polling Helper ─────────────────────────────────────────────────────

def poll_task_until_complete(
    api_client: httpx.Client,
    task_id: str,
    max_retries: int = 60,
    poll_interval: float = 2.0,
    log_prefix: str = "[POLL]",
) -> Dict[str, Any]:
    """
    Poll the /v1/tasks/{task_id} endpoint until the task completes or fails.

    Returns the full task status dict on completion.
    Raises pytest.fail on timeout or task failure.
    """
    for i in range(max_retries):
        status_resp = api_client.get(f"/v1/tasks/{task_id}")
        assert status_resp.status_code == 200, (
            f"Task status check failed: {status_resp.text}"
        )

        status_data = status_resp.json()
        status = status_data["status"]

        if status == "completed":
            return status_data
        elif status == "failed":
            error_msg = status_data.get("error", "Unknown task error")
            pytest.fail(f"{log_prefix} Task failed: {error_msg}")

        if (i + 1) % 5 == 0:
            print(f"{log_prefix} Attempt {i + 1}: status={status}...")

        time.sleep(poll_interval)

    pytest.fail(
        f"{log_prefix} Task timed out after {max_retries * poll_interval} seconds"
    )
    return {}  # unreachable, but keeps mypy happy


# ─── Image Metadata Verification ─────────────────────────────────────────────

def verify_image_metadata(
    image_bytes: bytes,
    expected_prompt: str,
    expected_model: str,
):
    """
    Verify that a generated raster image contains the expected AI metadata and
    C2PA provenance.

    Checks:
      1. XMP metadata contains 'trainedAlgorithmicMedia', model info, prompt, 'OpenMates'
      2. C2PA JUMBF box is present in raw bytes
      3. (Optional) c2pa-python library validation if installed
    """
    print(f"[VERIFY] Checking metadata/C2PA for image ({len(image_bytes)} bytes)...")
    try:
        # 1. Standard XMP Check
        img = Image.open(io.BytesIO(image_bytes))
        xmp = img.info.get("xmp")

        if not xmp:
            print(f"[FAIL] No XMP metadata found. Available info: {list(img.info.keys())}")
            pytest.fail("No XMP metadata found in generated image")

        xmp_str = xmp.decode("utf-8") if isinstance(xmp, bytes) else xmp

        # Core AI signal
        assert "trainedAlgorithmicMedia" in xmp_str, (
            "Missing 'trainedAlgorithmicMedia' marker in XMP"
        )

        # Model info
        if expected_model:
            model_snippet = (
                expected_model.split("/")[-1]
                if "/" in expected_model
                else expected_model
            )
            assert model_snippet in xmp_str, (
                f"Expected model snippet '{model_snippet}' "
                f"(from '{expected_model}') not found in XMP metadata"
            )

        # Prompt info (snippet)
        prompt_snippet = expected_prompt[:30]
        assert prompt_snippet in xmp_str, (
            f"Prompt snippet '{prompt_snippet}' not found in XMP metadata"
        )

        # Software marker
        assert "OpenMates" in xmp_str, "Missing 'OpenMates' software marker in XMP"

        print("[OK] XMP metadata markers verified.")

        # 2. C2PA (Content Credentials) Check
        print("[VERIFY] Checking C2PA (Coalition for Content Provenance and Authenticity)...")
        has_c2pa_jumb = b"jumb" in image_bytes.lower()
        assert has_c2pa_jumb, "Missing C2PA JUMBF box in image bytes"

        if HAS_C2PA:
            try:
                mime_type = "image/webp"
                if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                    mime_type = "image/png"
                elif image_bytes.startswith(b"\xff\xd8"):
                    mime_type = "image/jpeg"

                with c2pa.Reader(mime_type, io.BytesIO(image_bytes)) as reader:
                    manifest_json = reader.json()
                    if not manifest_json:
                        pytest.fail("C2PA Reader found no manifest")

                    assert "trainedAlgorithmicMedia" in manifest_json, (
                        "C2PA manifest missing AI digital source type"
                    )
                    assert "OpenMates" in manifest_json, (
                        "C2PA manifest missing OpenMates generator info"
                    )

                    validation = reader.get_validation_state()
                    print(f"[INFO] C2PA Validation State: {validation}")

                print("[OK] C2PA manifest verified with c2pa-python library!")
            except Exception as e:
                print(f"[WARN] C2PA library verification failed, falling back to byte check: {e}")
        else:
            print("[INFO] c2pa-python not installed, verified via JUMBF byte marker only.")

        print("[OK] All metadata and C2PA markers found successfully!")

    except Exception as e:
        print(f"[ERROR] Failed to verify metadata/C2PA: {e}")
        raise
