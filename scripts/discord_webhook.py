#!/usr/bin/env python3
"""Shared privacy-safe Discord webhook attachment helpers.

The helper builds stdlib-only multipart requests and confirms message creation
with wait=true. Callers receive sanitized message and attachment identifiers;
webhook URLs and raw response bodies are never returned or persisted.
Architecture: docs/specs/narrated-spec-demonstration-videos/spec.yml.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
from typing import Any, Callable
import urllib.error
import urllib.request


def build_multipart_body(
    payload_json: dict[str, Any],
    files: list[tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----openmates-{int(time.time())}-{os.getpid()}"
    crlf = b"\r\n"
    parts: list[bytes] = [
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="payload_json"',
        b"Content-Type: application/json",
        b"",
        json.dumps(payload_json).encode("utf-8"),
    ]
    for field_name, content, filename in files:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode(),
                f"Content-Type: {content_type}".encode(),
                b"",
                content,
            ]
        )
    parts.extend([f"--{boundary}--".encode(), b""])
    return crlf.join(parts), f"multipart/form-data; boundary={boundary}"


def post_attachment(
    *,
    webhook_url: str,
    payload: dict[str, Any],
    content: bytes,
    filename: str,
    timeout: int = 30,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, str] | None:
    if not webhook_url or not content or not filename:
        return None
    separator = "&" if "?" in webhook_url else "?"
    post_url = webhook_url if "wait=" in webhook_url else f"{webhook_url}{separator}wait=true"
    body, content_type = build_multipart_body(payload, [("files[0]", content, filename)])
    request = urllib.request.Request(
        post_url,
        data=body,
        headers={"Content-Type": content_type, "User-Agent": "OpenMates-Spec-Demo/1.0"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
        message = json.loads(raw.decode("utf-8")) if raw else {}
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    message_id = str(message.get("id") or "")
    attachments = message.get("attachments")
    attachment_id = ""
    if isinstance(attachments, list) and attachments and isinstance(attachments[0], dict):
        attachment_id = str(attachments[0].get("id") or "")
    if not message_id or not attachment_id:
        return None
    return {"message_id": message_id, "attachment_id": attachment_id}


def post_message(
    *,
    webhook_url: str,
    payload: dict[str, Any],
    timeout: int = 30,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, str] | None:
    if not webhook_url or not payload.get("content"):
        return None
    separator = "&" if "?" in webhook_url else "?"
    post_url = webhook_url if "wait=" in webhook_url else f"{webhook_url}{separator}wait=true"
    request = urllib.request.Request(
        post_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "OpenMates-Spec-Demo/1.0"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
        message = json.loads(raw.decode("utf-8")) if raw else {}
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    message_id = str(message.get("id") or "")
    return {"message_id": message_id} if message_id else None
