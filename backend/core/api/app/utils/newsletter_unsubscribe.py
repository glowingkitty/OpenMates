"""Recipient-token newsletter unsubscribe and RFC 8058 header helpers.

The token authorizes removal from the newsletter only. No account, cookie,
Origin, plaintext address, or global email suppression is involved.
"""

import os
import re
import hashlib
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from fastapi import HTTPException, Request


ONE_CLICK_PATH = "/v1/newsletter/unsubscribe/one-click/"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,128}")
MAX_ONE_CLICK_BODY_BYTES = 4096
NEUTRAL_MESSAGE = "Your newsletter unsubscribe request has been processed."


def newsletter_one_click_rate_key(request: Request) -> str:
    """Rate cache keys must contain only a digest of the recipient credential."""
    token = str(request.path_params.get("token", ""))
    return "newsletter-one-click:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def newsletter_api_origin() -> str:
    is_dev = os.getenv("SERVER_ENVIRONMENT", "production").lower() in ("development", "dev", "test")
    default = "https://api.dev.openmates.org" if is_dev else "https://api.openmates.org"
    origin = os.getenv("NEWSLETTER_PUBLIC_API_ORIGIN", default).rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or origin != f"https://{parsed.netloc}"):
        raise ValueError("NEWSLETTER_PUBLIC_API_ORIGIN must be an exact HTTPS origin")
    return origin


def build_newsletter_one_click_url(token: str) -> str:
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid newsletter unsubscribe token")
    return f"{newsletter_api_origin()}{ONE_CLICK_PATH}{token}"


def newsletter_one_click_headers(url: Any) -> dict[str, str]:
    """Advertise only our actual POST endpoint, never a browser hash/block link.

    RFC 8058 additionally requires the delivery provider to DKIM-sign both
    headers. Verify that on a received message; application headers alone do
    not configure or prove the provider's signing policy.
    """
    if not isinstance(url, str):
        return {}
    try:
        parsed = urlsplit(url)
    except ValueError:
        return {}
    token = parsed.path.removeprefix(ONE_CLICK_PATH)
    if not parsed.path.startswith(ONE_CLICK_PATH) or not TOKEN_PATTERN.fullmatch(token):
        return {}
    if url != build_newsletter_one_click_url(token):
        return {}
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


async def _validate_one_click_form(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    if len(content_type) > 512 or "\r" in content_type or "\n" in content_type:
        raise HTTPException(400, "Invalid one-click unsubscribe form")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_ONE_CLICK_BODY_BYTES:
            raise HTTPException(413, "One-click unsubscribe form is too large")
        body.extend(chunk)
    try:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == "application/x-www-form-urlencoded":
            fields = parse_qsl(body.decode("ascii"), strict_parsing=True, max_num_fields=1,
                               encoding="ascii", errors="strict")
        elif media_type == "multipart/form-data":
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
            )
            parts = list(message.iter_parts())
            if message.defects or not message.is_multipart() or len(parts) != 1:
                raise ValueError("Invalid multipart form")
            part = parts[0]
            if part.defects or part.is_multipart() or part.get_content_disposition() != "form-data" or part.get_filename():
                raise ValueError("Invalid multipart field")
            fields = [(part.get_param("name", header="content-disposition"), part.get_payload(decode=True).decode("ascii"))]
        else:
            raise ValueError("Unsupported form encoding")
        if fields != [("List-Unsubscribe", "One-Click")]:
            raise ValueError("Invalid one-click action")
    except (ValueError, UnicodeError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "Invalid one-click unsubscribe form") from exc


async def process_newsletter_one_click(request: Request, token: str, directus_service: Any) -> dict[str, Any]:
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(400, "Invalid newsletter unsubscribe token")
    await _validate_one_click_form(request)
    url = f"{directus_service.base_url}/items/newsletter_subscribers"
    try:
        response = await directus_service._make_api_request("GET", url, params={
            "filter[unsubscribe_token][_eq]": token, "fields": "id", "limit": 1,
        })
        if response.status_code != 200:
            raise HTTPException(503, "Newsletter unsubscribe is temporarily unavailable")
        items = response.json().get("data", [])
        if items:
            subscriber_id = items[0].get("id")
            if not subscriber_id:
                raise HTTPException(503, "Newsletter unsubscribe is temporarily unavailable")
            deleted = await directus_service._make_api_request("DELETE", f"{url}/{subscriber_id}")
            # A concurrent one-click or browser request may have deleted it.
            if deleted.status_code not in (200, 204, 404):
                raise HTTPException(503, "Newsletter unsubscribe is temporarily unavailable")
        # Missing tokens include successful replays. Never disclose whether a
        # subscription exists, and never look up or block the email identity.
        return {"success": True, "message": NEUTRAL_MESSAGE}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Newsletter unsubscribe is temporarily unavailable") from exc
