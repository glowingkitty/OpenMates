# contract-test-file: infrastructure
"""Tests for the temporary OpenCode response-media S3 bucket.

Purpose: keep assistant response media private while still embeddable in
OpenCode Web via short-lived presigned URLs.
Security: the bucket must never become public-read and must auto-expire.
Run: python3 -m pytest backend/tests/test_opencode_response_media_bucket.py.
"""

import importlib.util
from pathlib import Path


def load_s3_config_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "backend/core/api/app/services/s3/config.py"
    spec = importlib.util.spec_from_file_location("test_s3_config", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


s3_config = load_s3_config_module()
BUCKETS = s3_config.BUCKETS
CORS_ENABLED_BUCKETS = s3_config.CORS_ENABLED_BUCKETS
get_allowed_origins = s3_config.get_allowed_origins


def test_opencode_response_media_bucket_is_private_and_short_lived() -> None:
    bucket = BUCKETS["opencode_response_media"]

    assert bucket["name"] == "openmates-opencode-response-media"
    assert bucket["dev_name"] == "dev-openmates-opencode-response-media"
    assert bucket["access"] == "private"
    assert bucket["lifecycle_policy"] == 2
    assert bucket["cache_control"] == "private, max-age=172800"
    assert "image/png" in bucket["allowed_types"]
    assert "video/mp4" in bucket["allowed_types"]


def test_opencode_response_media_bucket_gets_cors_for_web_chat() -> None:
    assert "openmates-opencode-response-media" in CORS_ENABLED_BUCKETS
    assert "dev-openmates-opencode-response-media" in CORS_ENABLED_BUCKETS

    dev_origins = get_allowed_origins("development")

    assert "https://code.dev.openmates.org" in dev_origins
    assert "http://127.0.0.1:4096" in dev_origins
    assert "http://localhost:4096" in dev_origins
