"""Exercise the preview HTTP client's native Brotli response decoder safely."""

import brotli
import httpx
import pytest


# Public regression stream from Node.js v22.23.4 test-zlib-invalid-input.js.
# Check the patched library version before passing it to the native decoder.
INVALID_BLOCK_SWITCH = bytes.fromhex("200010414141fcffff07002228f00b60f7f41f000000")


# contract-test: infrastructure
@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_preview_httpx_brotli_response_decoder(malformed: bool) -> None:
    assert tuple(map(int, brotli.__version__.split("."))) >= (1, 2, 1)
    body = b"<html><title>Preview Brotli regression</title></html>"
    compressed = INVALID_BLOCK_SWITCH if malformed else brotli.compress(body)

    def origin(request: httpx.Request) -> httpx.Response:
        assert "br" in request.headers["accept-encoding"]
        return httpx.Response(200, headers={"content-encoding": "br"}, content=compressed)

    async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
        if malformed:
            with pytest.raises(httpx.DecodingError):
                await client.get("https://preview-origin.example.test/")
        else:
            response = await client.get("https://preview-origin.example.test/")
            assert response.content == body
