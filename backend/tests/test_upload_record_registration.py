"""Contract tests for isolated upload record registration.

Upload completion depends on the core API persisting metadata and regional
replication intent. Registration failures must therefore reach the caller
instead of allowing an upload without durable redundancy to be acknowledged.
"""

import sys
import types
import io

import pytest
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

if "python_multipart" not in sys.modules:
    python_multipart_module = types.ModuleType("python_multipart")
    python_multipart_module.__version__ = "0.0.99"
    sys.modules["python_multipart"] = python_multipart_module
if "multipart.multipart" not in sys.modules:
    multipart_module = types.ModuleType("multipart")
    multipart_submodule = types.ModuleType("multipart.multipart")
    multipart_submodule.parse_options_header = lambda value: (value, {})
    multipart_module.multipart = multipart_submodule
    sys.modules["multipart"] = multipart_module
    sys.modules["multipart.multipart"] = multipart_submodule

from backend.upload.routes import upload_route
from backend.upload.services.s3_upload import UploadsS3Service


_UPLOAD_ENVIRONMENT_CASES = [
    ("development", None, "dev"),
    ("dev", None, "dev"),
    (" Development ", None, "dev"),
    ("production", None, "prod"),
    ("prod", None, "prod"),
    (None, None, "prod"),
    ("unknown", None, "prod"),
    ("development", "prod", "prod"),
    ("production", "dev", "dev"),
    ("production", "DEV", "dev"),
    ("development", "unknown", "prod"),
    ("development", "", "prod"),
]


# contract-test: supporting surface=rest_api assertions=storage.files.reference-safe-single-copy
@pytest.mark.asyncio
@pytest.mark.parametrize("server_env, proxy_env, expected_env", _UPLOAD_ENVIRONMENT_CASES)
async def test_upload_request_core_credentials_and_s3_bucket_agree(
    monkeypatch, server_env, proxy_env, expected_env,
):
    if server_env is None:
        monkeypatch.delenv("SERVER_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("SERVER_ENVIRONMENT", server_env)
    for env in ("DEV", "PROD"):
        monkeypatch.setenv(f"{env}_CORE_API_URL", f"https://{env.lower()}.example.test")
        monkeypatch.setenv(f"{env}_INTERNAL_API_SHARED_TOKEN", f"{env.lower()}-token")

    # Exercise route-level selection through safe PDF reuse, stopping before
    # encryption/upload. The S3 probe uses the real bucket resolver, without I/O.
    service = UploadsS3Service()
    service.region_name = "nbg1"
    observed = {}

    async def check_file_exists(s3_key, *, target_env, region=None):
        observed["bucket"] = service.get_bucket_for_env(target_env, region=region)
        return True

    service.check_file_exists = check_file_exists
    record = {"embed_id": "old-embed", "aes_key": "existing-key", "files_metadata": {
        "original": {"s3_key": "owner/hash/embed/original.bin", "active_region": "nbg1"},
    }}

    async def check_duplicate(core_api_url, internal_token, user_id, content_hash):
        observed["credentials"] = (core_api_url, internal_token)
        assert user_id == "owner"
        return record

    async def handle_pdf(**kwargs):
        observed["handler_env"] = kwargs["target_env"]
        assert kwargs["reuse_s3_data"] is record
        return "pdf-handler-reached"

    monkeypatch.setattr(upload_route, "_check_duplicate_via_api", check_duplicate)
    monkeypatch.setattr(upload_route, "_handle_pdf_upload", handle_pdf)
    monkeypatch.setitem(sys.modules, "magic", types.SimpleNamespace(from_buffer=lambda *_args, **_kwargs: "application/pdf"))
    headers = [] if proxy_env is None else [(b"x-target-env", proxy_env.encode())]
    request = Request({"type": "http", "headers": headers,
                       "app": types.SimpleNamespace(state=types.SimpleNamespace(s3=service))})
    result = await upload_route.upload_file(
        request=request,
        file=UploadFile(io.BytesIO(b"%PDF-1.4 test"), filename="test.pdf",
                        headers=Headers({"content-type": "application/pdf"})),
        user={"user_id": "owner", "vault_key_id": "owner-vault"},
    )

    assert result == "pdf-handler-reached"
    assert observed == {
        "credentials": (f"https://{expected_env}.example.test", f"{expected_env}-token"),
        "bucket": "dev-openmates-chatfiles" if expected_env == "dev" else "openmates-chatfiles",
        "handler_env": expected_env,
    }


# contract-test: supporting surface=rest_api assertions=storage.files.reference-safe-single-copy
def test_upload_development_requires_configured_core_api(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.delenv("DEV_CORE_API_URL", raising=False)
    request = Request({"type": "http", "headers": []})
    with pytest.raises(upload_route.HTTPException) as error:
        upload_route._get_core_api_credentials(request)
    assert error.value.status_code == 503


class FailedRegistrationClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, *, json, headers):
        return type("Response", (), {"status_code": 503, "text": "unavailable"})()


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_upload_record_registration_failure_reaches_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        upload_route.httpx,
        "AsyncClient",
        lambda *, timeout: FailedRegistrationClient(),
    )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await upload_route._store_record_via_api(
            "https://api.example.test",
            "internal-token",
            {"id": "upload-record"},
        )


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_upload_route_requires_one_active_region_for_variant_metadata() -> None:
    first = types.SimpleNamespace(key="one.bin", region="fsn1")
    second = types.SimpleNamespace(key="two.bin", region="fsn1")
    mismatched = types.SimpleNamespace(key="three.bin", region="hel1")

    class S3Service:
        def get_base_url(self, target_env="prod", *, region=None):
            return f"{target_env}:{region or 'primary'}"

    assert upload_route._single_upload_region(first, second) == "fsn1"
    assert upload_route._active_region_map(first, second) == {
        "one.bin": "fsn1",
        "two.bin": "fsn1",
    }
    with pytest.raises(RuntimeError, match="different active regions"):
        upload_route._single_upload_region(first, mismatched)
    assert upload_route._s3_base_url_for_stored_files(
        S3Service(),
        "dev",
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}},
    ) == "dev:fsn1"
    assert upload_route._active_region_map_from_stored_files(
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}}
    ) == {"one.bin": "fsn1"}
    assert upload_route._sample_stored_file_reference(
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}}
    ) == ("one.bin", "fsn1")
    assert upload_route._stored_file_references(
        {
            "original": {"s3_key": "one.bin", "active_region": "fsn1"},
            "preview": {"s3_key": "two.bin", "active_region": "fsn1"},
        }
    ) == [("one.bin", "fsn1"), ("two.bin", "fsn1")]
    assert upload_route._s3_base_url_for_stored_files(
        S3Service(),
        "dev",
        {"original": {"s3_key": "legacy.bin"}},
    ) == "dev:primary"


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.failover.health-reconciled
@pytest.mark.asyncio
async def test_stored_file_reference_probe_requires_every_variant() -> None:
    class S3Service:
        def __init__(self) -> None:
            self.calls = []

        async def check_file_exists(self, s3_key, *, target_env, region=None):
            self.calls.append((s3_key, target_env, region))
            return s3_key != "preview.bin"

    service = S3Service()

    assert not await upload_route._stored_file_references_available(
        service,
        target_env="dev",
        files_metadata={
            "original": {"s3_key": "original.bin", "active_region": "fsn1"},
            "preview": {"s3_key": "preview.bin", "active_region": "fsn1"},
        },
    )
    assert service.calls == [
        ("original.bin", "dev", "fsn1"),
        ("preview.bin", "dev", "fsn1"),
    ]


# contract-test: supporting surface=rest_api assertions=design-embroidery.request.vector-source
def test_svg_uploads_are_recognised_by_type_or_content() -> None:
    assert upload_route.is_svg_upload("image/svg+xml", b"anything")
    assert upload_route.is_svg_upload("application/octet-stream", b"  <svg xmlns='http://www.w3.org/2000/svg'/>")
    assert upload_route.is_svg_upload("text/xml", b"<?xml version='1.0'?>\n<svg/>")
    assert not upload_route.is_svg_upload("image/png", b"\x89PNG\r\n")
    assert not upload_route.is_svg_upload("text/html", b"<html><body><svg/></body></html>")
