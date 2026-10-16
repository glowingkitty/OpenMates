"""Public, authored newsletter images and provider-safe HTML size limits.

The image index ships inside API/worker images; image bytes live on the public
    website/S3. Rendering never reads authoring files or fetches remote URLs.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSET_MAP_PATH = Path("backend/newsletters/asset-map.json")
PUBLIC_ASSET_PATH = "/newsletter-assets/"
NEWSLETTER_HTML_MAX_BYTES = 80 * 1024
NEWSLETTER_IMAGE_MAX_BYTES = 200 * 1024
PUBLIC_FILENAME = re.compile(r"[a-f0-9]{64}\.(?:jpg|svg)\Z")
NEWSLETTER_S3_BUCKETS = {"development": "dev-openmates-newsletter-assets", "production": "openmates-newsletter-assets"}
NEWSLETTER_S3_PREFIX = "newsletter-images/"
NEWSLETTER_S3_REGION = "nbg1"
CI_S3_ENDPOINT = "http://storage.ci.test:9000"
CI_ASSET_MAP_ROOT = Path("/app/logs")


def newsletter_isolated_s3() -> bool:
    return all(os.getenv(key) == value for key, value in {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development", "S3_ENDPOINT_URL": CI_S3_ENDPOINT,
    }.items())


def newsletter_s3_endpoint() -> str:
    override = os.getenv("S3_ENDPOINT_URL")
    if any(os.getenv(key, "").strip().lower() in {"1", "true", "yes", "on"}
           for key in ("CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_MAIL_CAPTURE")):
        if not newsletter_isolated_s3():
            raise ValueError("Newsletter S3 endpoint requires the complete exact isolated CI store")
        return CI_S3_ENDPOINT
    if override == "https://nbg1.your-objectstorage.com":
        return override
    if override:
        if not newsletter_isolated_s3():
            raise ValueError("Newsletter S3 endpoint override requires the exact isolated CI store")
        return CI_S3_ENDPOINT
    return "https://nbg1.your-objectstorage.com"


def newsletter_public_policy(bucket: str) -> dict:
    if bucket not in NEWSLETTER_S3_BUCKETS.values():
        raise ValueError("Newsletter publication bucket is not allowed")
    return {"Version": "2012-10-17", "Statement": [{
        "Sid": "OpenMatesNewsletterImages", "Effect": "Allow", "Principal": "*",
        "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/{NEWSLETTER_S3_PREFIX}*",
    }]}


def validate_asset_manifest(payload: dict) -> str:
    """Validate the whole authored index and fingerprint its exact asset set."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Invalid newsletter asset index version")
    assets = payload.get("assets")
    if not isinstance(assets, dict) or not 0 < len(assets) <= 512:
        raise ValueError("Newsletter asset index must contain a bounded nonempty asset set")
    identities = {}
    for source, asset in assets.items():
        if not isinstance(source, str) or newsletter_asset_key(source) != source:
            raise ValueError("Invalid newsletter asset source key")
        if not isinstance(asset, dict):
            raise ValueError("Invalid newsletter asset entry")
        filename, size = asset.get("filename"), asset.get("size_bytes")
        if (not isinstance(filename, str) or not PUBLIC_FILENAME.fullmatch(filename)
                or type(size) is not int or not 0 < size <= NEWSLETTER_IMAGE_MAX_BYTES):
            raise ValueError("Newsletter asset index contains an invalid public image")
        for dimension in ("width", "height"):
            if dimension in asset and (type(asset[dimension]) is not int or not 0 < asset[dimension] <= 10000):
                raise ValueError("Invalid newsletter image dimensions")
        if filename in identities and identities[filename] != asset:
            raise ValueError("Conflicting newsletter image identity")
        identities[filename] = asset
    return hashlib.sha256(json.dumps(assets, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def newsletter_s3_url(bucket: str, filename: str) -> str:
    newsletter_public_policy(bucket)
    if not PUBLIC_FILENAME.fullmatch(filename):
        raise ValueError("Invalid immutable newsletter image filename")
    if newsletter_isolated_s3():
        return f"{CI_S3_ENDPOINT}/{bucket}/{NEWSLETTER_S3_PREFIX}{filename}"
    return f"https://{bucket}.nbg1.your-objectstorage.com/{NEWSLETTER_S3_PREFIX}{filename}"


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
    if override := os.getenv("NEWSLETTER_CI_ASSET_MAP_PATH"):
        if (not newsletter_isolated_s3() or not Path(override).is_absolute()
                or ".." in Path(override).parts
                or not Path(override).resolve().is_relative_to(CI_ASSET_MAP_ROOT)
                or any(path.is_symlink() for path in (Path(override), *Path(override).parents))):
            raise ValueError("Newsletter CI asset index override is outside the isolated fixture scope")
        map_path = Path(override)
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    asset_hash = validate_asset_manifest(payload)
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
    origin = newsletter_asset_origin(base_url)
    transport = payload.get("delivery_transport", "website")
    if transport == "website":
        return origin + PUBLIC_ASSET_PATH + filename
    if transport != "s3":
        raise ValueError("Unknown newsletter asset delivery transport")
    environment = "production" if origin == "https://openmates.org" else "development"
    bucket = NEWSLETTER_S3_BUCKETS[environment]
    publications = payload.get("s3_publications", {})
    publication = publications.get(environment) if isinstance(publications, dict) else None
    filenames = sorted({entry["filename"] for entry in payload["assets"].values()})
    if (not isinstance(publication, dict) or publication.get("bucket") != bucket
            or publication.get("region") != NEWSLETTER_S3_REGION or publication.get("prefix") != NEWSLETTER_S3_PREFIX
            or publication.get("asset_manifest_sha256") != asset_hash or publication.get("verified_public") is not True
            or publication.get("object_count") != len(filenames) or publication.get("verified_filenames") != filenames):
        raise ValueError("Newsletter S3 target is unpublished or stale; verified publication is required before rendering")
    return newsletter_s3_url(bucket, filename)
