"""Bounded public-image download and preparation entirely in memory.

No temporary files, persistent photo cache or upload is created. Transport pins
validated public DNS and never sends credentials or follows arbitrary redirects.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
import ipaddress
import socket
import warnings
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PIXELS = 16_000_000

def prepare_image(content: bytes) -> bytes:
    """Decode bounded still images and strip metadata into a small JPEG canvas."""
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("Image exceeds the input byte budget")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as source:
            if (source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "is_animated", False)
                    or source.width * source.height > MAX_SOURCE_PIXELS):
                raise ValueError("Unsupported or oversized still image")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((336, 336), Image.Resampling.LANCZOS)
            rgba = image.convert("RGBA")
            canvas = Image.new("RGB", (336, 336), "white")
            canvas.paste(rgba, ((336 - rgba.width) // 2, (336 - rgba.height) // 2), rgba)
            output = BytesIO()
            canvas.save(output, format="JPEG", quality=82)
            return output.getvalue()


class PublicImageHTTPUnavailable(ValueError):
    """Metadata-free HTTP failure category for aggregate preparation diagnostics."""

    def __init__(self, status_code: int):
        self.category = "redirect" if 300 <= status_code < 400 else "http_error"
        super().__init__("Public image could not be read")


MAX_FULL_SOURCE_BYTES = 20 * 1024 * 1024
MAX_FULL_SOURCE_PIXELS = 64_000_000
MAX_FULL_SIDE = 2560


@dataclass(frozen=True)
class FullPublicImage:
    """A public picture in full size (longest side at most ``MAX_FULL_SIDE``), metadata stripped."""

    content: bytes
    mime_type: str
    width: int
    height: int


def prepare_full_image(content: bytes) -> FullPublicImage:
    """Decode a bounded still image, strip metadata and reduce its longest side to ``MAX_FULL_SIDE``."""
    if not content or len(content) > MAX_FULL_SOURCE_BYTES:
        raise ValueError("Image exceeds the input byte budget")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as source:
            if (source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "is_animated", False)
                    or source.width * source.height > MAX_FULL_SOURCE_PIXELS):
                raise ValueError("Unsupported or oversized still image")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_FULL_SIDE, MAX_FULL_SIDE), Image.Resampling.LANCZOS)
            alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
            output = BytesIO()
            if alpha:
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                mime_type = "image/png"
            else:
                image.convert("RGB").save(output, format="JPEG", quality=90)
                mime_type = "image/jpeg"
            return FullPublicImage(content=output.getvalue(), mime_type=mime_type, width=image.width,
                                   height=image.height)


async def _fetch_public_image_bytes(url: str, *, max_bytes: int, timeout: float) -> bytes:
    """Fetch only public HTTPS, pin DNS to the validated IP and reject redirects.

    Pinning the connection (with the original TLS SNI/Host) prevents DNS rebinding.
    No environment proxy, cookies, authorization, or provider credentials are sent.
    """
    parsed = urlsplit(url)
    if (len(url) > 4096 or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Unsupported product image URL")
    hostname = parsed.hostname.encode("idna").decode("ascii")
    addresses = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM), timeout=1.0,
    )
    ips = list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Product image host is not public")
    pinned_url = httpx.URL(url).copy_with(host=ips[0])
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async with client.stream(
            "GET", pinned_url, headers={"Host": hostname, "Accept": "image/jpeg,image/png,image/webp"},
            extensions={"sni_hostname": hostname},
        ) as response:
            if response.status_code != 200:
                raise PublicImageHTTPUnavailable(response.status_code)
            if response.headers.get("content-type", "").split(";", 1)[0].lower() not in {
                "image/jpeg", "image/png", "image/webp", "image/jpg",
            }:
                raise ValueError("Product image response is not a supported image")
            length = response.headers.get("content-length")
            if length and int(length) > max_bytes:
                raise ValueError("Product image exceeds the byte budget")
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("Product image exceeds the byte budget")
            return bytes(content)


async def download_public_image(url: str) -> bytes:
    """Fetch a public picture with the rules of ``_fetch_public_image_bytes`` as a 336 px JPEG canvas."""
    content = await _fetch_public_image_bytes(url, max_bytes=MAX_SOURCE_BYTES, timeout=2.0)
    return await asyncio.to_thread(prepare_image, content)


async def download_public_image_full(url: str) -> FullPublicImage:
    """Fetch a public picture with the same rules in full size (at most 20 MB, longest side ≤ 2560 px)."""
    content = await _fetch_public_image_bytes(url, max_bytes=MAX_FULL_SOURCE_BYTES, timeout=10.0)
    return await asyncio.to_thread(prepare_full_image, content)

