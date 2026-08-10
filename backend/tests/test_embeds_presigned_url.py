"""Regression tests for encrypted embed asset presigned URLs.

Shared-chat recipients can be logged out while still having legitimate access
to encrypted embed assets: the share key decrypts the embed TOON content,
which contains both the S3 object key and AES material. These tests call the
route function directly so auth middleware does not hide the route contract.
"""

import importlib
import sys
import types

import pytest
from fastapi import HTTPException


class _StubLimiter:
    def limit(self, _rule: str):
        def decorator(func):
            return func

        return decorator


auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user_optional = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
s3_service_stub = types.ModuleType("backend.core.api.app.services.s3.service")
s3_service_stub.S3UploadService = object
s3_config_stub = types.ModuleType("backend.core.api.app.services.s3.config")
s3_config_stub.get_bucket_name = lambda bucket_key, environment: f"{environment}-{bucket_key}"
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
user_stub = types.ModuleType("backend.core.api.app.models.user")
user_stub.User = object

_STUB_MODULES = {
    "backend.core.api.app.routes.auth_routes.auth_dependencies": auth_deps_stub,
    "backend.core.api.app.services.directus": directus_stub,
    "backend.core.api.app.utils.encryption": encryption_stub,
    "backend.core.api.app.services.s3.service": s3_service_stub,
    "backend.core.api.app.services.s3.config": s3_config_stub,
    "backend.core.api.app.services.limiter": limiter_stub,
    "backend.core.api.app.models.user": user_stub,
}
_previous_modules = {name: sys.modules.get(name) for name in _STUB_MODULES}
try:
    sys.modules.update(_STUB_MODULES)
    embeds_api = importlib.import_module("backend.core.api.app.routes.embeds_api")
finally:
    sys.modules.pop("backend.core.api.app.routes.embeds_api", None)
    for name, previous_module in _previous_modules.items():
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module

get_presigned_url = getattr(
    embeds_api.get_presigned_url,
    "__wrapped__",
    embeds_api.get_presigned_url,
)


class FakeS3Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def generate_presigned_url(self, bucket_name: str, s3_key: str, expiration: int):
        self.calls.append((bucket_name, s3_key, expiration))
        return f"https://s3.example/{bucket_name}/{s3_key}?sig=test"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "s3_key",
    [
        "chatfiles/shared/pdf-preview-p1.png.bin",
        "chatfiles/shared/image-preview.webp.enc",
        "chatfiles/shared/recording-original.webm.enc",
        "chatfiles/shared/generated-music.wav.enc",
        "chatfiles/shared/generated-video.mp4.enc",
        "chatfiles/shared/application-preview.png.enc",
        "chatfiles/shared/weather-radar-frame.webp.enc",
        "chatfiles/shared/model-poster.webp.enc",
        "chatfiles/shared/document-artifact.docx.enc",
        "chatfiles/shared/code-artifact.zip.enc",
    ],
)
async def test_presigned_url_allows_logged_out_shared_embed_asset_access(monkeypatch, s3_key):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.setattr(
        embeds_api,
        "get_bucket_name",
        lambda bucket_key, environment: f"{environment}-{bucket_key}",
    )
    s3_service = FakeS3Service()

    result = await get_presigned_url(
        request=None,
        s3_key=s3_key,
        current_user=None,
        s3_service=s3_service,
    )

    assert result == {
        "url": f"https://s3.example/production-chatfiles/{s3_key}?sig=test",
        "expires_in": 900,
    }
    assert s3_service.calls == [("production-chatfiles", s3_key, 900)]


@pytest.mark.asyncio
@pytest.mark.parametrize("s3_key", ["../secret", "/absolute/key", "https://example.com/key"])
async def test_presigned_url_rejects_suspicious_s3_keys(s3_key):
    s3_service = FakeS3Service()

    with pytest.raises(HTTPException) as exc_info:
        await get_presigned_url(
            request=None,
            s3_key=s3_key,
            current_user=None,
            s3_service=s3_service,
        )

    assert exc_info.value.status_code == 400
    assert s3_service.calls == []
