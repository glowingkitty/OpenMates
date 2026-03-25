# backend/shared/providers/protonmail/protonmail_bridge.py
#
# Proton Mail Bridge provider helpers for the Mail search skill.
# Handles Vault/env configuration loading, access control checks, IMAP access,
# and lightweight provider health checks.
#
# Architecture: docs/architecture/prompt-injection.md
# Tests: exercised through mail search skill execution paths.

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
from dataclasses import dataclass
from datetime import timezone
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

PROTONMAIL_SECRET_PATH = "kv/data/providers/protonmail"
PROTONMAIL_INTERNAL_PROVIDER_ID = "protonmail"

DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_IMAP_PORT = 1143
DEFAULT_MAILBOX = "INBOX"
DEFAULT_MAX_RESULTS = 10
MAX_RESULTS_HARD_LIMIT = 50
RECENT_SCAN_WINDOW = 200

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


@dataclass
class ProtonMailBridgeConfig:
    enabled: bool
    bridge_host: str
    bridge_imap_port: int
    bridge_username: str
    bridge_password: str
    mailbox: str
    allowed_openmates_email: str


class _HTMLToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(part.strip() for part in self._parts if part and part.strip()).strip()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _clean_string(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _parse_bool(value: str, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


async def _get_secret_or_env(
    *,
    secrets_manager: SecretsManager,
    secret_key: str,
    env_var: str,
    default: str = "",
) -> str:
    try:
        value = await secrets_manager.get_secret(
            secret_path=PROTONMAIL_SECRET_PATH,
            secret_key=secret_key,
        )
        cleaned = _clean_string(value)
        if cleaned:
            return cleaned
    except Exception as exc:
        logger.debug("ProtonMail secret lookup failed for key '%s': %s", secret_key, exc)

    return _clean_string(os.getenv(env_var, default))


async def get_protonmail_bridge_config(
    secrets_manager: SecretsManager,
) -> ProtonMailBridgeConfig:
    enabled_raw = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="enabled",
        env_var="SECRET__PROTONMAIL__ENABLED",
        default="false",
    )
    host = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="bridge_host",
        env_var="SECRET__PROTONMAIL__BRIDGE_HOST",
        default=DEFAULT_BRIDGE_HOST,
    )
    port_raw = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="bridge_imap_port",
        env_var="SECRET__PROTONMAIL__BRIDGE_IMAP_PORT",
        default=str(DEFAULT_BRIDGE_IMAP_PORT),
    )
    username = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="bridge_username",
        env_var="SECRET__PROTONMAIL__BRIDGE_USERNAME",
    )
    password = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="bridge_password",
        env_var="SECRET__PROTONMAIL__BRIDGE_PASSWORD",
    )
    mailbox = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="mailbox",
        env_var="SECRET__PROTONMAIL__MAILBOX",
        default=DEFAULT_MAILBOX,
    )
    allowed_email = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="allowed_openmates_email",
        env_var="SECRET__PROTONMAIL__ALLOWED_OPENMATES_EMAIL",
    )

    try:
        port = int(port_raw)
    except ValueError:
        logger.warning(
            "Invalid ProtonMail bridge IMAP port '%s'. Falling back to %s",
            port_raw,
            DEFAULT_BRIDGE_IMAP_PORT,
        )
        port = DEFAULT_BRIDGE_IMAP_PORT

    return ProtonMailBridgeConfig(
        enabled=_parse_bool(enabled_raw, default=False),
        bridge_host=host or DEFAULT_BRIDGE_HOST,
        bridge_imap_port=port,
        bridge_username=username,
        bridge_password=password,
        mailbox=mailbox or DEFAULT_MAILBOX,
        allowed_openmates_email=_normalize_email(allowed_email),
    )


def is_bridge_configured(config: ProtonMailBridgeConfig) -> bool:
    return bool(
        config.enabled
        and config.bridge_host
        and config.bridge_imap_port
        and config.bridge_username
        and config.bridge_password
        and config.allowed_openmates_email
    )


async def _get_user_normalized_email(user_id: str) -> Optional[str]:
    if not INTERNAL_API_SHARED_TOKEN:
        logger.error("INTERNAL_API_SHARED_TOKEN is missing; cannot validate ProtonMail access")
        return None

    url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/internal/users/{user_id}/normalized-email"
    headers = {"X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            email_value = payload.get("email") if isinstance(payload, dict) else None
            if not isinstance(email_value, str):
                return None
            return _normalize_email(email_value)
    except Exception as exc:
        logger.error("Failed to resolve normalized email for user '%s': %s", user_id, exc, exc_info=True)
        return None


async def is_user_allowed_for_protonmail(
    *,
    user_id: str,
    config: ProtonMailBridgeConfig,
) -> bool:
    if not user_id:
        return False
    if not config.allowed_openmates_email:
        return False

    user_email = await _get_user_normalized_email(user_id)
    if not user_email:
        return False
    return user_email == config.allowed_openmates_email


def _decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    decoded_chunks: List[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            decoded_chunks.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded_chunks.append(chunk)
    return "".join(decoded_chunks).strip()


def _to_text_from_html(html_value: str) -> str:
    parser = _HTMLToTextParser()
    parser.feed(html_value)
    return parser.text()


def _message_bodies(message_obj: Message) -> Tuple[str, str]:
    text_parts: List[str] = []
    html_parts: List[str] = []

    if message_obj.is_multipart():
        for part in message_obj.walk():
            content_type = part.get_content_type()
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                text_parts.append(decoded)
            elif content_type == "text/html":
                html_parts.append(decoded)
    else:
        payload = message_obj.get_payload(decode=True)
        if payload:
            charset = message_obj.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if message_obj.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

    text_body = "\n\n".join(part.strip() for part in text_parts if part and part.strip()).strip()
    html_body = "\n\n".join(part.strip() for part in html_parts if part and part.strip()).strip()

    if not text_body and html_body:
        text_body = _to_text_from_html(html_body)

    return text_body, html_body


def _safe_datetime_to_timestamp(value: Optional[str]) -> int:
    if not value:
        return 0
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _snippet(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _query_matches(result: Dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    for field in ("subject", "from", "to", "snippet", "body_text"):
        value = result.get(field)
        if isinstance(value, str) and q in value.lower():
            return True
    return False


def _search_messages_sync(
    *,
    config: ProtonMailBridgeConfig,
    query: str,
    mailbox: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    imap_client = imaplib.IMAP4(config.bridge_host, config.bridge_imap_port)
    try:
        imap_client.login(config.bridge_username, config.bridge_password)
        mailbox_to_use = mailbox or config.mailbox or DEFAULT_MAILBOX
        status, _ = imap_client.select(mailbox_to_use, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Failed to select mailbox '{mailbox_to_use}'")

        status, data = imap_client.uid("SEARCH", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        all_uids = data[0].decode("utf-8").split()
        if not all_uids:
            return []

        scan_count = RECENT_SCAN_WINDOW if query.strip() else limit
        selected_uids = list(reversed(all_uids[-scan_count:]))

        results: List[Dict[str, Any]] = []
        for uid in selected_uids:
            fetch_status, msg_data = imap_client.uid("FETCH", uid, "(BODY.PEEK[] FLAGS)")
            if fetch_status != "OK" or not msg_data:
                continue

            raw_message: Optional[bytes] = None
            flags_raw = ""
            for entry in msg_data:
                if isinstance(entry, tuple):
                    raw_message = entry[1]
                    try:
                        flags_raw = entry[0].decode("utf-8", errors="ignore")
                    except Exception:
                        flags_raw = ""
                    break

            if not raw_message:
                continue

            parsed = email.message_from_bytes(raw_message)
            subject = _decode_mime_header(parsed.get("Subject", ""))
            sender = _decode_mime_header(parsed.get("From", ""))
            recipient = _decode_mime_header(parsed.get("To", ""))
            date_raw = parsed.get("Date", "")
            message_id = _decode_mime_header(parsed.get("Message-ID", ""))

            body_text, body_html = _message_bodies(parsed)
            snippet = _snippet(body_text or _to_text_from_html(body_html))

            result = {
                "uid": uid,
                "message_id": message_id,
                "subject": subject,
                "from": sender,
                "to": recipient,
                "receiver": sender,
                "date": date_raw,
                "timestamp": _safe_datetime_to_timestamp(date_raw),
                "snippet": snippet,
                "content": snippet,
                "body_text": body_text,
                "body_html": body_html,
                "has_html": bool(body_html),
                "is_unread": "\\Seen" not in flags_raw,
            }

            if _query_matches(result, query):
                results.append(result)
                if len(results) >= limit:
                    break

        results.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
        return results
    finally:
        try:
            imap_client.logout()
        except Exception:
            pass


async def search_protonmail_messages(
    *,
    config: ProtonMailBridgeConfig,
    query: str,
    mailbox: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    normalized_limit = max(1, min(limit, MAX_RESULTS_HARD_LIMIT))
    return await asyncio.to_thread(
        _search_messages_sync,
        config=config,
        query=query,
        mailbox=mailbox,
        limit=normalized_limit,
    )


async def check_protonmail_bridge_health(
    secrets_manager: SecretsManager,
) -> Tuple[bool, Optional[str]]:
    try:
        config = await get_protonmail_bridge_config(secrets_manager)
        if not config.enabled:
            return False, "protonmail_disabled"
        if not is_bridge_configured(config):
            return False, "protonmail_config_missing"

        await asyncio.to_thread(
            lambda: _search_messages_sync(
                config=config,
                query="",
                mailbox=config.mailbox,
                limit=1,
            )
        )
        return True, None
    except Exception as exc:
        logger.error("ProtonMail Bridge health check failed: %s", exc, exc_info=True)
        return False, str(exc)


def build_connected_account_label(config: ProtonMailBridgeConfig) -> str:
    if not config.bridge_username:
        return "Proton Mail Bridge"
    return f"Proton Mail Bridge ({config.bridge_username})"


def normalize_provider_email(email_value: str) -> str:
    return _normalize_email(email_value)


def build_default_query_label(query: str) -> str:
    stripped = query.strip()
    if stripped:
        return stripped
    return "Recent emails"
