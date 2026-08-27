"""Contract tests for isolated upload record registration.

Upload completion depends on the core API persisting metadata and regional
replication intent. Registration failures must therefore reach the caller
instead of allowing an upload without durable redundancy to be acknowledged.
"""

import sys
import types

import pytest

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
