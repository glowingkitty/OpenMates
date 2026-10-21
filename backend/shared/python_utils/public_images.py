"""Bounded public-image download and preparation entirely in memory.

No temporary files, persistent photo cache or upload is created. Transport pins
validated public DNS and never sends credentials or follows arbitrary redirects.
"""
from __future__ import annotations

import asyncio
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


async def download_public_image(url: str) -> bytes:
    """Fetch only public HTTPS, pin DNS to the validated IP and reject redirects.

    Pinning the connection (with the original TLS SNI/Host) prevents DNS rebinding.
    No environment proxy, cookies, authorization, or provider credentials are sent.
    """
    parsed = urlsplit(url)
    if (len(url) > 4096 or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Unsupported product image URL")
    # This Stoffe.de tenant migrated its image CDN with a same-path 301. Map
    # only that verified alias before the normal public-DNS and pinned-IP checks.
    # Result gallery URLs stay provider supplied; arbitrary redirects stay denied.
    if (parsed.hostname == "cdn02.plentymarkets.com"
            and parsed.path.startswith("/5rtbqcd0flq3/item/images/")):
        url = str(httpx.URL(url).copy_with(host="cdn02.plentyone.com"))
        parsed = urlsplit(url)
    hostname = parsed.hostname.encode("idna").decode("ascii")
    addresses = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM), timeout=1.0,
    )
    ips = list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Product image host is not public")
    pinned_url = httpx.URL(url).copy_with(host=ips[0])
    async with httpx.AsyncClient(timeout=2.0, follow_redirects=False, trust_env=False) as client:
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
            if length and int(length) > MAX_SOURCE_BYTES:
                raise ValueError("Product image exceeds the byte budget")
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_SOURCE_BYTES:
                    raise ValueError("Product image exceeds the byte budget")
            return await asyncio.to_thread(prepare_image, bytes(content))

