# backend/tests/test_temp_image_presigned_url.py
#
# Regression test for GDPR audit finding C6 / OPE-372.
#
# Before the fix: `/internal/s3/upload-temp-image` returned a plain public URL
# (`https://{bucket}.{domain}/{key}`) because the `temp_images` bucket was
# public-read. Decrypted user images sent through the reverse-image-search
# path (SerpAPI Google Lens) were world-readable for up to 24h.
#
# After the fix: the bucket is private and the endpoint returns a short-lived
# presigned URL via `s3_service.generate_presigned_url()`. SerpAPI fetches the
# object once, then the skill deletes it.
#
# This test locks in the fix at the endpoint level by mocking the S3 service
# and asserting the returned `image_url` comes from `generate_presigned_url`
# — not from a hand-built bucket URL.
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_temp_image_presigned_url.py

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_upload_temp_image_returns_presigned_url_not_public_url():
    """The endpoint must return the presigned URL from s3_service, never a plain bucket URL."""
    from backend.core.api.app.routes.internal_api import (
        UploadTempImageRequest,
        upload_temp_image,
        TEMP_IMAGE_PRESIGN_SECONDS,
    )

    # Sentinel URL that unambiguously came from generate_presigned_url (has AWS
    # sig v4 query params). If the endpoint regresses to the old hand-built URL
    # this marker will not be present.
    presigned_sentinel = (
        "https://dev-openmates-temp-images.example.com/reverse_search/abc.webp"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef&X-Amz-Expires=900"
    )

    mock_s3_service = MagicMock()
    mock_s3_service.base_domain = "example.com"  # would be used by the old code path
    mock_s3_service.upload_file = AsyncMock(return_value=None)
    mock_s3_service.generate_presigned_url = MagicMock(return_value=presigned_sentinel)

    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    body = UploadTempImageRequest(
        image_bytes_b64=base64.b64encode(image_bytes).decode("ascii"),
        content_type="image/png",
        filename="test.png",
    )

    response = await upload_temp_image(
        request=MagicMock(),
        body=body,
        s3_service=mock_s3_service,
    )

    # The response exposes `image_url` (not `public_url`) and it must equal the
    # sentinel returned by generate_presigned_url — proving the endpoint is
    # using the presigned flow instead of building a public URL string itself.
    assert response.image_url == presigned_sentinel, (
        "upload_temp_image must return the URL from generate_presigned_url; "
        "if this assertion fails the endpoint has regressed to the hand-built "
        "public-bucket URL flow (GDPR C6 / OPE-372)."
    )

    # And make sure we called upload + presigned with a 15-minute TTL.
    assert mock_s3_service.upload_file.await_count == 1
    upload_kwargs = mock_s3_service.upload_file.await_args.kwargs
    assert upload_kwargs["bucket_key"] == "temp_images"
    assert upload_kwargs["file_key"].startswith("reverse_search/")

    assert mock_s3_service.generate_presigned_url.call_count == 1
    presign_args, presign_kwargs = mock_s3_service.generate_presigned_url.call_args
    # (bucket_name, s3_key, expiration=...)
    assert presign_kwargs.get("expiration") == TEMP_IMAGE_PRESIGN_SECONDS
    assert TEMP_IMAGE_PRESIGN_SECONDS == 15 * 60

    # s3_key in the response must match the key used when generating the URL.
    assert response.s3_key == presign_args[1]


@pytest.mark.asyncio
async def test_upload_temp_image_does_not_build_plain_public_url():
    """Belt-and-braces: even if generate_presigned_url somehow returned a plain URL,
    the endpoint must not fall back to the old `https://{bucket}.{domain}/{key}` pattern."""
    from backend.core.api.app.routes.internal_api import (
        UploadTempImageRequest,
        upload_temp_image,
    )

    # Return a value that does NOT contain the bucket hostname, to prove the
    # endpoint forwards generate_presigned_url's value verbatim instead of
    # concatenating `base_domain` itself.
    mock_s3_service = MagicMock()
    mock_s3_service.base_domain = "should-not-appear.example.com"
    mock_s3_service.upload_file = AsyncMock(return_value=None)
    mock_s3_service.generate_presigned_url = MagicMock(
        return_value="https://presigned.test/object?X-Amz-Signature=xyz"
    )

    body = UploadTempImageRequest(
        image_bytes_b64=base64.b64encode(b"data").decode("ascii"),
        content_type="image/webp",
        filename="x.webp",
    )

    response = await upload_temp_image(
        request=MagicMock(),
        body=body,
        s3_service=mock_s3_service,
    )

    assert "should-not-appear.example.com" not in response.image_url
    assert response.image_url == "https://presigned.test/object?X-Amz-Signature=xyz"
