"""Public, authored newsletter images and provider-safe HTML size limits.

The image index ships inside API/worker images; image bytes live on the public
website. Rendering never reads transient authoring files or fetches remote URLs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSET_MAP_PATH = Path("backend/newsletters/asset-map.json")
PUBLIC_ASSET_PATH = "/newsletter-assets/"
NEWSLETTER_HTML_MAX_BYTES = 80 * 1024
NEWSLETTER_IMAGE_MAX_BYTES = 200 * 1024
PUBLIC_FILENAME = re.compile(r"[a-f0-9]{64}\.(?:jpg|svg)\Z")


def validate_newsletter_html_size(html: str) -> None:
    """Leave a provider tracking buffer below email-client clipping limits."""
    size = len(html.encode("utf-8"))
    if size > NEWSLETTER_HTML_MAX_BYTES:
        raise ValueError(
            f"Newsletter HTML is {size} bytes; maximum is {NEWSLETTER_HTML_MAX_BYTES}. "
            "Publish compressed hosted images or shorten the campaign before sending."
        )


def newsletter_asset_key(value: str) -> str:
    """Normalize a public authoring reference; never accept arbitrary URLs."""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if (parsed.scheme != "https" or parsed.hostname != "images.lumacdn.com"
                or parsed.netloc != "images.lumacdn.com" or parsed.fragment):
            raise ValueError("Newsletter remote image must be an authored images.lumacdn.com HTTPS source")
        return value
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("Newsletter image path must be repo-relative")
    return path.as_posix()


def newsletter_asset_origin(base_url: str) -> str:
    origins = {
        "https://openmates.org": "https://openmates.org",
        "https://app.dev.openmates.org": "https://landing.dev.openmates.org",
        "https://landing.dev.openmates.org": "https://landing.dev.openmates.org",
    }
    try:
        return origins[base_url.rstrip("/")]
    except KeyError:
        raise ValueError("Newsletter images require a known first-party HTTPS base URL") from None


def newsletter_image_url(source: str, base_url: str, *, repo_root: Path | None = None) -> str:
    key = newsletter_asset_key(source)
    map_path = (repo_root or REPO_ROOT) / ASSET_MAP_PATH
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    asset = payload.get("assets", {}).get(key) if payload.get("schema_version") == 1 else None
    if not isinstance(asset, dict):
        raise ValueError(
            "Newsletter image has no published asset. Run scripts/publish_newsletter_assets.py "
            "with the campaign manifest, review the public assets, and deploy before sending."
        )
    filename = asset.get("filename", "")
    size = asset.get("size_bytes")
    if (not isinstance(filename, str) or not PUBLIC_FILENAME.fullmatch(filename)
            or not isinstance(size, int) or not 0 < size <= NEWSLETTER_IMAGE_MAX_BYTES):
        raise ValueError("Newsletter asset index contains an invalid public image")
    return newsletter_asset_origin(base_url) + PUBLIC_ASSET_PATH + filename
