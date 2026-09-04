# contract-test-file: infrastructure
"""Tests for S3 bucket CORS configuration.

Purpose: keep browser media fetches working for presigned S3 objects.
Scope: validates the generated CORS rule passed to the S3 client.
Security: CORS changes must not silently drop range or content headers.
Run: python3 -m pytest backend/tests/test_cors.py.
"""

import importlib.util
import sys
import types
from pathlib import Path


def load_cors_module():
    root = Path(__file__).resolve().parents[2]
    package_name = "test_s3_package"
    config_path = root / "backend/core/api/app/services/s3/config.py"
    cors_path = root / "backend/core/api/app/services/s3/cors.py"

    package_module = types.ModuleType(package_name)
    package_module.__path__ = []
    sys.modules[package_name] = package_module

    config_spec = importlib.util.spec_from_file_location(
        f"{package_name}.config",
        config_path,
    )
    assert config_spec is not None
    assert config_spec.loader is not None
    config_module = importlib.util.module_from_spec(config_spec)
    sys.modules[f"{package_name}.config"] = config_module
    config_spec.loader.exec_module(config_module)

    inserted_botocore = False
    try:
        from botocore.exceptions import ClientError as _ClientError  # noqa: F401
    except ModuleNotFoundError:
        inserted_botocore = True
        botocore_module = types.ModuleType("botocore")
        exceptions_module = types.ModuleType("botocore.exceptions")

        class ClientError(Exception):
            def __init__(self, response, operation_name) -> None:
                super().__init__(operation_name)
                self.response = response

        exceptions_module.ClientError = ClientError
        botocore_module.exceptions = exceptions_module
        sys.modules["botocore"] = botocore_module
        sys.modules["botocore.exceptions"] = exceptions_module

    try:
        cors_spec = importlib.util.spec_from_file_location(
            f"{package_name}.cors",
            cors_path,
        )
        assert cors_spec is not None
        assert cors_spec.loader is not None
        cors_module = importlib.util.module_from_spec(cors_spec)
        sys.modules[f"{package_name}.cors"] = cors_module
        cors_spec.loader.exec_module(cors_module)
        return cors_module
    finally:
        if inserted_botocore:
            sys.modules.pop("botocore", None)
            sys.modules.pop("botocore.exceptions", None)


cors_module = load_cors_module()
apply_cors_settings = cors_module.apply_cors_settings


class FakeS3Client:
    def __init__(self) -> None:
        self.cors_calls = []

    def put_bucket_cors(self, **kwargs) -> None:
        self.cors_calls.append(kwargs)


class FailingS3Client(FakeS3Client):
    def __init__(self, error_code: str, failures: int) -> None:
        super().__init__()
        self.error_code = error_code
        self.failures = failures

    def put_bucket_cors(self, **kwargs) -> None:
        super().put_bucket_cors(**kwargs)
        if len(self.cors_calls) <= self.failures:
            raise cors_module.ClientError(
                {"Error": {"Code": self.error_code, "Message": "provider unavailable"}},
                "PutBucketCors",
            )


def test_apply_cors_settings_exposes_media_range_headers(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    s3_client = FakeS3Client()

    apply_cors_settings(
        s3_client,
        bucket_names=[
            "openmates-opencode-response-media",
            "dev-openmates-opencode-response-media",
        ],
    )

    assert len(s3_client.cors_calls) == 1
    assert s3_client.cors_calls[0]["Bucket"] == "dev-openmates-opencode-response-media"

    cors_rule = s3_client.cors_calls[0]["CORSConfiguration"]["CORSRules"][0]
    exposed_headers = set(cors_rule["ExposeHeaders"])

    assert cors_rule["AllowedMethods"] == ["GET", "HEAD"]
    assert "https://code.dev.openmates.org" in cors_rule["AllowedOrigins"]
    assert {
        "Accept-Ranges",
        "Content-Length",
        "Content-Range",
        "Content-Type",
        "ETag",
    } <= exposed_headers


def test_apply_cors_settings_retries_transient_provider_errors(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(cors_module.time, "sleep", lambda _seconds: None)
    s3_client = FailingS3Client("ServiceUnavailable", failures=2)

    apply_cors_settings(s3_client, bucket_names=["dev-openmates-chatfiles"])

    assert len(s3_client.cors_calls) == 3


def test_apply_cors_settings_does_not_retry_permission_errors(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(cors_module.time, "sleep", lambda _seconds: None)
    s3_client = FailingS3Client("AccessDenied", failures=3)

    try:
        apply_cors_settings(s3_client, bucket_names=["dev-openmates-chatfiles"])
    except RuntimeError as exc:
        assert "1 bucket(s)" in str(exc)
    else:
        raise AssertionError("Expected CORS reconciliation to fail")

    assert len(s3_client.cors_calls) == 1
