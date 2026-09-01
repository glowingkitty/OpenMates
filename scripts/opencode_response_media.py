#!/usr/bin/env python3
# scripts/opencode_response_media.py
#
# Upload temporary media/documents for OpenCode responses without making a
# public bucket. The host script copies a local response file into the API
# container, where Vault-backed Hetzner S3 credentials are available, then
# creates/reconciles a private 48-hour bucket and returns a presigned URL.
#
# Usage: python3 scripts/opencode_response_media.py path/to/file.png --alt "Screenshot"

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


BUCKET_NAME = "openmates-opencode-response-media"
DEV_BUCKET_NAME = "dev-openmates-opencode-response-media"
BUCKET_KEY = "opencode_response_media"
LIFECYCLE_DAYS = 2
DEFAULT_EXPIRES_SECONDS = 48 * 60 * 60
MIN_EXPIRES_SECONDS = 60
MAX_EXPIRES_SECONDS = DEFAULT_EXPIRES_SECONDS
DEFAULT_CONTAINER = "api"
CONTAINER_TMP_DIR = "/tmp/opencode-response-media"
MAX_MEDIA_BYTES = 500 * 1024 * 1024
RUN_KEY_PREFIX = "opencode-responses/runs"
LATEST_RUN_TYPE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
WEBVTT_TIMESTAMP_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> (\d{2}):(\d{2}):(\d{2})\.(\d{3})$"
)

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp3": "audio/mpeg",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".vtt": "text/vtt",
    ".webm": "video/webm",
    ".webp": "image/webp",
}

ALLOWED_CONTENT_TYPES = set(CONTENT_TYPES.values())

INNER_UPLOAD_CODE = r'''
import asyncio
import json
import os
from pathlib import Path
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from backend.core.api.app.utils.secrets_manager import SecretsManager


REQUEST = json.loads(os.environ["OPENCODE_RESPONSE_MEDIA_REQUEST"])


def bucket_name(environment):
    return REQUEST["dev_bucket"] if environment == "development" else REQUEST["bucket"]


def allowed_origins(environment):
    if environment == "development":
        return [
            "https://code.dev.openmates.org",
            "http://127.0.0.1:4096",
            "http://localhost:4096",
        ]
    return ["https://code.openmates.org"]


def ensure_bucket(client, name):
    try:
        client.head_bucket(Bucket=name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=name)
        time.sleep(2)
    client.put_bucket_acl(Bucket=name, ACL="private")


def apply_lifecycle(client, name):
    days = int(REQUEST["lifecycle_days"])
    client.put_bucket_lifecycle_configuration(
        Bucket=name,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": f"ExpireAfter{days}Days",
                    "Status": "Enabled",
                    "Prefix": "",
                    "Expiration": {"Days": days},
                }
            ]
        },
    )


def apply_cors(client, name, origins):
    client.put_bucket_cors(
        Bucket=name,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": origins,
                    "AllowedMethods": ["GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": [
                        "Accept-Ranges",
                        "Content-Length",
                        "Content-Range",
                        "Content-Type",
                        "ETag",
                    ],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )


async def main():
    manager = SecretsManager()
    await manager.initialize()
    access_key = await manager.get_secret(
        secret_path="kv/data/providers/hetzner",
        secret_key="s3_access_key",
    )
    secret_key = await manager.get_secret(
        secret_path="kv/data/providers/hetzner",
        secret_key="s3_secret_key",
    )
    region = await manager.get_secret(
        secret_path="kv/data/providers/hetzner",
        secret_key="s3_region_name",
    ) or "nbg1"
    if not access_key or not secret_key:
        raise RuntimeError("Hetzner S3 credentials are unavailable in Vault")

    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://{region}.your-objectstorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 3},
        ),
    )

    environment = os.getenv("SERVER_ENVIRONMENT", "development")
    target_bucket = bucket_name(environment)
    ensure_bucket(client, target_bucket)
    apply_lifecycle(client, target_bucket)
    apply_cors(client, target_bucket, allowed_origins(environment))

    content = Path(REQUEST["container_path"]).read_bytes()
    metadata = {
        "media-kind": REQUEST["media_kind"],
        "purpose": "opencode-response-media",
        "lifecycle-policy": f"expire-after-{REQUEST['lifecycle_days']}-days",
        "source-sha256": REQUEST["sha256"],
    }
    client.put_object(
        Bucket=target_bucket,
        Key=REQUEST["key"],
        Body=content,
        ContentType=REQUEST["content_type"],
        CacheControl=f"private, max-age={REQUEST['expires_in']}",
        ACL="private",
        Metadata=metadata,
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": target_bucket, "Key": REQUEST["key"]},
        ExpiresIn=int(REQUEST["expires_in"]),
    )
    print(json.dumps({"bucket": target_bucket, "key": REQUEST["key"], "url": url}))


asyncio.run(main())
'''


def guess_content_type(path: Path) -> str:
    value = CONTENT_TYPES.get(path.suffix.lower())
    if value:
        return value
    guessed, _encoding = mimetypes.guess_type(str(path))
    if guessed in ALLOWED_CONTENT_TYPES:
        return guessed
    raise ValueError(f"Unsupported media type for {path.name}")


def media_kind(content_type: str) -> str:
    if content_type == "audio/mpeg":
        return "audio"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type == "application/pdf":
        return "document"
    raise ValueError(f"Unsupported content type: {content_type}")


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return stem[:96] or "media"


def object_key(path: Path, content: bytes, now: dt.datetime | None = None) -> str:
    instant = now or dt.datetime.now(dt.timezone.utc)
    digest = hashlib.sha256(content).hexdigest()[:16]
    unique = uuid.uuid4().hex[:12]
    return (
        f"opencode-responses/{instant:%Y/%m/%d}/"
        f"{unique}-{digest}-{safe_filename(path.name)}"
    )


def run_object_prefix(run_type: str, content_sha256: str) -> str:
    if not LATEST_RUN_TYPE_RE.fullmatch(run_type):
        raise ValueError("--latest-run-type must be 1-80 chars of letters, numbers, dots, underscores, or hyphens")
    return f"{RUN_KEY_PREFIX}/{run_type}/{content_sha256}"


def latest_run_object_key(path: Path, content_type: str, run_type: str, content_sha256: str) -> str:
    stem = media_kind(content_type)
    return f"{run_object_prefix(run_type, content_sha256)}/{stem}{path.suffix.lower()}"


def run_poster_object_key(run_type: str, video_sha256: str, poster_path: Path, poster_sha256: str) -> str:
    if not LATEST_RUN_TYPE_RE.fullmatch(run_type):
        raise ValueError("--latest-run-type must be 1-80 chars of letters, numbers, dots, underscores, or hyphens")
    return f"opencode-responses/runs/{run_type}/{video_sha256}/poster-{poster_sha256}{poster_path.suffix.lower()}"


def container_path_for(source: Path, key: str) -> str:
    return f"{CONTAINER_TMP_DIR}/{Path(key).name}"


def ensure_expires(value: int) -> int:
    if value < MIN_EXPIRES_SECONDS:
        raise ValueError(f"--expires-in must be at least {MIN_EXPIRES_SECONDS} seconds")
    if value > MAX_EXPIRES_SECONDS:
        raise ValueError(f"--expires-in must be at most {MAX_EXPIRES_SECONDS} seconds")
    return value


def validate_webvtt(text: str) -> None:
    """Validate the canonical cue subset used by proof-video sidecars."""
    if not text.startswith("WEBVTT\n"):
        raise ValueError("WebVTT captions must start with WEBVTT")
    blocks = [block for block in text.removeprefix("WEBVTT").strip().split("\n\n") if block.strip()]
    if not blocks:
        raise ValueError("WebVTT captions require at least one cue")

    def seconds(values: tuple[str, ...]) -> float:
        hours, minutes, whole_seconds, milliseconds = map(int, values)
        if minutes >= 60 or whole_seconds >= 60:
            raise ValueError("WebVTT captions contain an invalid timestamp")
        return hours * 3600 + minutes * 60 + whole_seconds + milliseconds / 1000

    previous_end = 0.0
    for block in blocks:
        lines = block.splitlines()
        if len(lines) != 2 or not lines[1].strip():
            raise ValueError("WebVTT cues require one timestamp line and one text line")
        match = WEBVTT_TIMESTAMP_RE.fullmatch(lines[0])
        if match is None:
            raise ValueError("WebVTT captions contain an invalid timestamp")
        start = seconds(match.groups()[:4])
        end = seconds(match.groups()[4:])
        if start < previous_end or start >= end:
            raise ValueError("WebVTT cues must be ordered and non-overlapping")
        previous_end = end


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def upload_via_api_container(
    *,
    source: Path,
    container: str,
    request: dict[str, object],
) -> dict[str, str]:
    mkdir = run_command(["docker", "exec", container, "mkdir", "-p", CONTAINER_TMP_DIR])
    if mkdir.returncode != 0:
        raise RuntimeError(mkdir.stderr.strip() or mkdir.stdout.strip())

    copy = run_command(["docker", "cp", str(source), f"{container}:{request['container_path']}"])
    if copy.returncode != 0:
        raise RuntimeError(copy.stderr.strip() or copy.stdout.strip())

    env = os.environ.copy()
    env["OPENCODE_RESPONSE_MEDIA_REQUEST"] = json.dumps(request, sort_keys=True)
    upload = run_command(
        ["docker", "exec", "-e", "OPENCODE_RESPONSE_MEDIA_REQUEST", container, "python", "-c", INNER_UPLOAD_CODE],
        env=env,
    )
    if upload.returncode != 0:
        raise RuntimeError(upload.stderr.strip() or upload.stdout.strip())
    lines = [line for line in upload.stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError("Upload completed without JSON output")
    return json.loads(lines[-1])


def build_snippets(
    url: str,
    *,
    content_type: str,
    alt: str,
    width: int | None,
    poster_url: str = "",
    captions_url: str = "",
    captions_language: str = "und",
    captions_label: str = "Captions",
) -> dict[str, str]:
    kind = media_kind(content_type)
    escaped_url = html.escape(url, quote=True)
    escaped_alt = html.escape(alt, quote=True)
    if kind == "document":
        return {
            "markdown": f"[{alt}]({url})",
            "html": (
                f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer" '
                f'type="application/pdf">{escaped_alt}</a>'
            ),
        }
    if kind == "audio":
        return {
            "markdown": f"[{alt}]({url})",
            "html": (
                "<figure>\n"
                f"  <figcaption>{escaped_alt}</figcaption>\n"
                '  <audio controls crossorigin="anonymous" preload="metadata" style="width: 100%;">\n'
                f'    <source src="{escaped_url}" type="{html.escape(content_type, quote=True)}">\n'
                f'    Audio fallback text: <a href="{escaped_url}">{escaped_alt}</a>\n'
                "  </audio>\n"
                "</figure>"
            ),
        }
    if kind == "image":
        width_attr = f' width="{width}"' if width else ""
        return {
            "markdown": f"![{alt}]({url})",
            "html": f'<img src="{escaped_url}" alt="{escaped_alt}"{width_attr}>',
        }
    style = "width: 100%; height: auto;"
    if width:
        style += f" max-width: {width}px;"
    track = ""
    poster_attr = f' poster="{html.escape(poster_url, quote=True)}"' if poster_url else ""
    if captions_url:
        escaped_captions_url = html.escape(captions_url, quote=True)
        track = (
            f'  <track kind="captions" src="{escaped_captions_url}" '
            f'srclang="{html.escape(captions_language, quote=True)}" '
            f'label="{html.escape(captions_label, quote=True)}" default>\n'
        )
    return {
        "markdown": f"[{alt}]({url})",
        "html": (
            f'<video controls crossorigin="anonymous" style="{style}" preload="metadata" playsinline{poster_attr}>\n'
            f"  <source src=\"{escaped_url}\" type=\"{html.escape(content_type, quote=True)}\">\n"
            f"{track}"
            "  Video fallback text.\n"
            "</video>"
        ),
    }


def render_text(result: dict[str, object]) -> str:
    snippets = result["snippets"]
    assert isinstance(snippets, dict)
    lines = [
        "URL:",
        str(result["url"]),
        "",
        "Markdown:",
        str(snippets["markdown"]),
        "",
        "HTML:",
        str(snippets["html"]),
        "",
        f"Expires in: {result['expires_in']} seconds",
        f"S3 key: {result['key']}",
    ]
    return "\n".join(lines)


def human_label(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title()


def default_alt_for_path(source: Path, root: Path | None = None) -> str:
    if root is None:
        return source.stem.replace("-", " ").replace("_", " ")
    relative = source.relative_to(root).with_suffix("")
    parts = relative.parts
    if len(parts) >= 3 and re.fullmatch(
        r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*",
        parts[-2],
    ):
        return f"{human_label(parts[-3])} {human_label(parts[-1])}"
    return human_label(" ".join(parts))


def is_uploadable_response_file(path: Path) -> bool:
    try:
        media_kind(guess_content_type(path))
    except ValueError:
        return False
    return True


def collect_sources(path: Path, *, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError(f"Media path does not exist: {path}")
    if not recursive:
        raise ValueError("Directory uploads require --recursive")
    sources = sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file() and is_uploadable_response_file(candidate)
    )
    if not sources:
        raise ValueError(f"No supported response media files found under {path}")
    return sources


def build_result(args: argparse.Namespace, *, dry_run: bool = False) -> dict[str, object]:
    source = Path(args.path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Media file does not exist: {source}")
    content = source.read_bytes()
    if not content:
        raise ValueError("Media file is empty")
    if len(content) > MAX_MEDIA_BYTES:
        raise ValueError(f"Media file exceeds {MAX_MEDIA_BYTES} bytes")

    content_type = guess_content_type(source)
    kind = media_kind(content_type)
    expires_in = ensure_expires(args.expires_in)
    latest_run_type = args.latest_run_type.strip()
    sha256 = hashlib.sha256(content).hexdigest()
    key = (
        latest_run_object_key(source, content_type, latest_run_type, sha256)
        if latest_run_type
        else object_key(source, content)
    )
    container_path = container_path_for(source, key)
    request = {
        "bucket": BUCKET_NAME,
        "bucket_key": BUCKET_KEY,
        "container_path": container_path,
        "content_type": content_type,
        "dev_bucket": DEV_BUCKET_NAME,
        "expires_in": expires_in,
        "key": key,
        "lifecycle_days": LIFECYCLE_DAYS,
        "media_kind": kind,
        "sha256": sha256,
    }

    captions_result: dict[str, object] | None = None
    captions_source: Path | None = None
    captions_request: dict[str, object] | None = None
    poster_result: dict[str, object] | None = None
    poster_source: Path | None = None
    poster_request: dict[str, object] | None = None
    if getattr(args, "poster", None):
        if kind != "video":
            raise ValueError("--poster is only supported for video media")
        poster_source = Path(args.poster).expanduser().resolve()
        if not poster_source.is_file():
            raise ValueError(f"Poster file does not exist: {poster_source}")
        poster_content = poster_source.read_bytes()
        if not poster_content:
            raise ValueError("Poster file is empty")
        if len(poster_content) > MAX_MEDIA_BYTES:
            raise ValueError(f"Poster file exceeds {MAX_MEDIA_BYTES} bytes")
        poster_content_type = guess_content_type(poster_source)
        if not poster_content_type.startswith("image/"):
            raise ValueError("--poster requires an image file")
        poster_sha256 = hashlib.sha256(poster_content).hexdigest()
        poster_key = (
            run_poster_object_key(latest_run_type, sha256, poster_source, poster_sha256)
            if latest_run_type
            else object_key(poster_source, poster_content)
        )
        poster_request = {
            **request,
            "container_path": container_path_for(poster_source, poster_key),
            "content_type": poster_content_type,
            "key": poster_key,
            "sha256": poster_sha256,
        }
    if args.captions:
        if kind != "video":
            raise ValueError("--captions is only supported for video media")
        captions_source = Path(args.captions).expanduser().resolve()
        if not captions_source.is_file():
            raise ValueError(f"Caption file does not exist: {captions_source}")
        captions_content = captions_source.read_bytes()
        if not captions_content:
            raise ValueError("Caption file is empty")
        try:
            captions_text = captions_content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as exc:
            raise ValueError("WebVTT captions must be UTF-8") from exc
        validate_webvtt(captions_text)
        captions_content_type = guess_content_type(captions_source)
        if captions_content_type != "text/vtt":
            raise ValueError("--captions requires a WebVTT .vtt file")
        captions_sha256 = hashlib.sha256(captions_content).hexdigest()
        captions_key = (
            f"{run_object_prefix(latest_run_type, sha256)}/captions-{captions_sha256}.vtt"
            if latest_run_type
            else object_key(captions_source, captions_content)
        )
        captions_request = {
            **request,
            "container_path": container_path_for(captions_source, captions_key),
            "content_type": captions_content_type,
            "key": captions_key,
            "sha256": captions_sha256,
        }
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", args.captions_language):
        raise ValueError("--captions-language must be a valid BCP-47 language tag")
    if not args.captions_label.strip():
        raise ValueError("--captions-label must not be empty")

    captions_upload: dict[str, object] | None = None
    poster_upload: dict[str, object] | None = None
    if poster_source is not None and poster_request is not None:
        if dry_run:
            poster_upload = {
                "bucket": DEV_BUCKET_NAME,
                "key": poster_request["key"],
                "url": f"https://example.invalid/{poster_request['key']}?X-Amz-Expires={expires_in}",
            }
        else:
            poster_upload = upload_via_api_container(
                source=poster_source,
                container=args.container,
                request=poster_request,
            )
    if captions_source is not None and captions_request is not None:
        if dry_run:
            captions_upload = {
                "bucket": DEV_BUCKET_NAME,
                "key": captions_request["key"],
                "url": f"https://example.invalid/{captions_request['key']}?X-Amz-Expires={expires_in}",
            }
        else:
            captions_upload = upload_via_api_container(
                source=captions_source,
                container=args.container,
                request=captions_request,
            )

    if dry_run:
        upload = {
            "bucket": DEV_BUCKET_NAME,
            "key": key,
            "url": f"https://example.invalid/{key}?X-Amz-Expires={expires_in}",
        }
    else:
        upload = upload_via_api_container(source=source, container=args.container, request=request)

    if captions_upload is not None and captions_request is not None:
        captions_result = {
            "content_type": "text/vtt",
            "expires_in": expires_in,
            "key": captions_upload["key"],
            "sha256": f"sha256:{captions_request['sha256']}",
            "url": captions_upload["url"],
            "language": args.captions_language,
            "label": args.captions_label.strip(),
        }

    if poster_upload is not None and poster_request is not None:
        poster_result = {
            "content_type": poster_request["content_type"],
            "expires_in": expires_in,
            "key": poster_upload["key"],
            "sha256": f"sha256:{poster_request['sha256']}",
            "url": poster_upload["url"],
        }

    alt = args.alt or source.stem.replace("-", " ").replace("_", " ")
    snippets = build_snippets(
        upload["url"],
        content_type=content_type,
        alt=alt,
        width=args.width,
        poster_url=str(poster_result["url"]) if poster_result else "",
        captions_url=str(captions_result["url"]) if captions_result else "",
        captions_language=args.captions_language,
        captions_label=args.captions_label.strip(),
    )
    return {
        "bucket": upload["bucket"],
        "content_type": content_type,
        "expires_in": expires_in,
        "key": upload["key"],
        "kind": kind,
        "sha256": f"sha256:{sha256}",
        "snippets": snippets,
        "url": upload["url"],
        **({"latest_run_type": latest_run_type} if latest_run_type else {}),
        **({"poster": poster_result} if poster_result else {}),
        **({"captions": captions_result} if captions_result else {}),
    }


def build_batch_result(args: argparse.Namespace, *, dry_run: bool = False) -> dict[str, object]:
    root = Path(args.path).expanduser().resolve()
    sources = collect_sources(root, recursive=args.recursive)
    if len(sources) == 1 and sources[0] == root:
        return build_result(args, dry_run=dry_run)

    files: list[dict[str, object]] = []
    for source in sources:
        item_args = argparse.Namespace(**vars(args))
        item_args.path = str(source)
        item_args.alt = default_alt_for_path(source, root)
        result = build_result(item_args, dry_run=dry_run)
        result["relative_path"] = source.relative_to(root).as_posix()
        files.append(result)
    return {
        "count": len(files),
        "expires_in": ensure_expires(args.expires_in),
        "files": files,
        "kind": "batch",
        "root": str(root),
    }


def is_batch_result(result: dict[str, object]) -> bool:
    return "files" in result


def render_batch_snippets(result: dict[str, object], output: str) -> str:
    files = result["files"]
    assert isinstance(files, list)
    lines: list[str] = []
    for file_result in files:
        assert isinstance(file_result, dict)
        snippets = file_result["snippets"]
        assert isinstance(snippets, dict)
        lines.append(str(snippets[output]))
    return "\n\n".join(lines)


def render_batch_text(result: dict[str, object]) -> str:
    files = result["files"]
    assert isinstance(files, list)
    lines = [
        f"Uploaded {result['count']} files:",
        "",
    ]
    for file_result in files:
        assert isinstance(file_result, dict)
        lines.extend([
            str(file_result["relative_path"]),
            str(file_result["url"]),
            "",
        ])
    lines.append(f"Expires in: {result['expires_in']} seconds")
    return "\n".join(lines)


def upload_file(
    path: str | Path,
    *,
    alt: str = "",
    container: str = DEFAULT_CONTAINER,
    expires_in: int = DEFAULT_EXPIRES_SECONDS,
    width: int | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Upload one supported response file through the same validated CLI path."""
    args = argparse.Namespace(
        path=str(path),
        alt=alt,
        container=container,
        expires_in=expires_in,
        width=width,
        captions=None,
        captions_language="und",
        captions_label="Captions",
        latest_run_type="",
        recursive=False,
    )
    return build_result(args, dry_run=dry_run)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload temporary images, videos, audio clips, or PDF documents for OpenCode responses.",
    )
    parser.add_argument("path", help="Image, video, audio, PDF, or directory to upload")
    parser.add_argument("--alt", help="Alt text or video label")
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="API container name")
    parser.add_argument(
        "--expires-in",
        type=int,
        default=DEFAULT_EXPIRES_SECONDS,
        help="Presigned URL lifetime in seconds; max/default is 48 hours",
    )
    parser.add_argument("--width", type=int, help="Width attribute for generated HTML")
    parser.add_argument("--poster", help="Optional poster image for video media")
    parser.add_argument("--captions", help="Optional WebVTT caption sidecar for video media")
    parser.add_argument("--captions-language", default="und", help="BCP-47 caption language tag")
    parser.add_argument("--captions-label", default="Captions", help="Caption track label shown by the video player")
    parser.add_argument(
        "--latest-run-type",
        default="",
        help="Group test or CLI response media by run type while keeping each emitted artifact immutable",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Upload supported files under a directory recursively",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json", "url", "markdown", "html"),
        default="text",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not contact Docker/S3")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_batch_result(args, dry_run=args.dry_run)
    except Exception as exc:
        print(f"opencode_response_media: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.output == "url":
        if is_batch_result(result):
            files = result["files"]
            assert isinstance(files, list)
            for file_result in files:
                assert isinstance(file_result, dict)
                print(file_result["url"])
        else:
            print(result["url"])
    elif args.output in {"markdown", "html"}:
        if is_batch_result(result):
            print(render_batch_snippets(result, args.output))
        else:
            snippets = result["snippets"]
            assert isinstance(snippets, dict)
            print(snippets[args.output])
    else:
        print(render_batch_text(result) if is_batch_result(result) else render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
