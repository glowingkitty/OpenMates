"""OpenMates Python SDK facade.

Purpose: provide a lazy API-key client for Python integrations.
Architecture: thin REST facade over public /v1 endpoints.
Security: API keys are bearer credentials and are never persisted by this class.
Tests: packages/openmates-python/tests/test_sdk.py.
"""

from __future__ import annotations

import base64
import calendar
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import math
import re
import secrets
import string
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse, urlunparse
import uuid
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import requests

from .generated.app_skills import GeneratedAppSkills
from .chat_completion_recovery import derive_recovery_keypair, open_recovery_envelope


DEFAULT_API_URL = "https://api.openmates.org"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RECOVERY_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 60.0
PROMPT_INJECTION_DISABLED = "disabled"
SDK_KDF_ITERATIONS = 100_000
AES_GCM_IV_LENGTH = 12
CIPHERTEXT_HEADER_LENGTH = 6
CIPHERTEXT_MAGIC = b"OM"
SHARE_FIXED_SALT = b"openmates-share-v1"
CONNECTED_ACCOUNT_TRANSFER_PREFIX = "OMCA1."
API_KEY_PREFIX = "sk-api-"
API_KEY_RANDOM_LENGTH = 32
API_KEY_CHARS = string.ascii_letters + string.digits
TASK_PRIORITY_LEVELS = ("none", "low", "medium", "high", "urgent")
TASK_LABEL_INDEX_INFO = b"openmates-task-label-index-v1"
DESIGN_ICON_PATH_PATTERN = re.compile(r"^/v1/apps/design/icons/iconify/([a-z0-9][a-z0-9._-]*)/([a-z0-9][a-z0-9._-]*)\.svg$", re.IGNORECASE)
DESIGN_ICON_SEGMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
DESIGN_ICON_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
DEFAULT_ICON_PNG_SIZE = 256
MAX_ICON_PNG_SIZE = 4096
IDEABUCKET_DEFAULT_PROCESSING_PROMPT = "These are my captured ideas for today. Please process them, group related thoughts, suggest next actions, and ask clarifying questions where needed:\n\nIf an idea requires deeper work, create or suggest sub-chats for focused research, planning, todos, docs, or implementation."
ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES = {
    "access_token",
    "api_key",
    "backup_code_hash",
    "chat_key",
    "credential_secret",
    "device_key",
    "encrypted_master_key",
    "lookup_hash",
    "master_key",
    "password_hash",
    "private_key",
    "raw_key",
    "refresh_token",
    "share_key",
    "signing_secret",
    "token_hash",
    "totp_seed",
    "webhook_secret",
}
ACCOUNT_EXPORT_REDACTION_CATEGORIES = [
    "api_credentials",
    "authentication_tokens",
    "key_material",
    "password_and_recovery_hashes",
    "webhook_secrets",
]
ACCOUNT_EXPORT_FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}", re.IGNORECASE),
    re.compile(r"#key=[A-Za-z0-9_-]{8,}"),
]


class OpenMatesConfigError(RuntimeError):
    """Raised when the SDK is missing required configuration."""


class OpenMatesApiError(RuntimeError):
    """Raised when the OpenMates API returns a non-success response."""

    def __init__(self, status_code: int, data: Any):
        super().__init__(f"OpenMates API request failed with HTTP {status_code}")
        self.status_code = status_code
        self.data = data


@dataclass(frozen=True)
class ChatResponse:
    """Simple response wrapper for chat messages."""

    content: str | None = None
    raw: dict[str, Any] | None = None


def _with_app_skill_prompt_injection_option(
    input_data: dict[str, Any],
    prompt_injection_protection: bool | None,
) -> dict[str, Any]:
    if prompt_injection_protection is not False:
        return input_data
    current_security = input_data.get("security")
    security = dict(current_security) if isinstance(current_security, dict) else {}
    return {
        **input_data,
        "security": {
            **security,
            "prompt_injection_protection": PROMPT_INJECTION_DISABLED,
        },
    }


class OpenMates:
    """Lazy API-key SDK client."""

    def __init__(self, api_key: str | None = None, api_url: str = DEFAULT_API_URL, *, device_id: str | None = None, device_id_path: str | os.PathLike[str] | None = None):
        self._api_key = api_key or os.getenv("OPENMATES_API_KEY")
        self._api_url = api_url.rstrip("/")
        self._device_id = device_id or _load_or_create_device_id(device_id_path)
        self._master_key: bytes | None = None
        self._sdk_session: dict[str, Any] | None = None
        self.apps = GeneratedAppSkills(self._run_app_skill)
        self.account = OpenMatesAccount(self)
        self.benchmark = OpenMatesBenchmark(self)
        self.billing = OpenMatesBilling(self)
        self.chats = OpenMatesChats(self)
        self.connected_accounts = OpenMatesConnectedAccounts(self)
        self.design = OpenMatesDesign(self)
        self.docs = OpenMatesDocs(self)
        self.drafts = OpenMatesDrafts(self)
        self.embeds = OpenMatesEmbeds(self)
        self.feedback = OpenMatesFeedback(self)
        self.ideabucket = OpenMatesIdeaBucket(self)
        self.inspirations = OpenMatesInspirations(self)
        self.api_keys = OpenMatesApiKeys(self)
        self.learning_mode = OpenMatesLearningMode(self)
        self.memories = OpenMatesMemories(self)
        self.new_chat_suggestions = OpenMatesNewChatSuggestions(self)
        self.notifications = OpenMatesNotifications(self)
        self.reminders = OpenMatesReminders(self)
        self.projects = OpenMatesProjects(self)
        self.settings = OpenMatesSettings(self)
        self.plans = OpenMatesPlans(self)
        self.tasks = OpenMatesTasks(self)
        self.teams = OpenMatesTeams(self)
        self.workflows = OpenMatesWorkflows(self)

    def _run_app_skill(
        self,
        app_id: str,
        skill_id: str,
        input_data: dict[str, Any],
        *,
        prompt_injection_protection: bool | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"/v1/apps/{app_id}/skills/{skill_id}",
            _with_app_skill_prompt_injection_option(input_data, prompt_injection_protection),
        )

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", path, payload, timeout=timeout, extra_headers=extra_headers)

    def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, payload)

    def _put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", path, payload)

    def _delete(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("DELETE", path, payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        request_kwargs = {
            "json": payload,
            "headers": {**self._headers(has_body=payload is not None), **(extra_headers or {})},
            "timeout": timeout,
        }
        if method == "POST":
            response = requests.post(f"{self._api_url}{path}", **request_kwargs)
        elif method == "PATCH":
            response = requests.patch(f"{self._api_url}{path}", **request_kwargs)
        elif method == "PUT":
            response = requests.put(f"{self._api_url}{path}", **request_kwargs)
        elif method == "DELETE":
            response = requests.delete(f"{self._api_url}{path}", **request_kwargs)
        else:
            response = requests.request(method, f"{self._api_url}{path}", **request_kwargs)
        return self._parse_response(response)

    def _get(self, path: str) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        response = requests.get(
            f"{self._api_url}{path}",
            headers=self._headers(has_body=False),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)

    def _get_public(self, path: str) -> dict[str, Any]:
        response = requests.get(
            f"{self._api_url}{path}",
            headers=self._public_headers(),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)

    def _get_raw(self, path: str) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        response = requests.get(
            f"{self._api_url}{path}",
            headers=self._headers(has_body=False),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            return self._parse_response(response)
        return {
            "content_type": response.headers.get("content-type", "application/octet-stream"),
            "filename": _extract_filename(response.headers.get("content-disposition")),
            "data": response.content,
        }

    def _headers(self, *, has_body: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-OpenMates-SDK": "pip",
            "X-OpenMates-Device-Identity": self._device_id,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _public_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-OpenMates-SDK": "pip",
            "X-OpenMates-Device-Identity": self._device_id,
        }

    def _parse_response(self, response: Any) -> dict[str, Any]:
        data = response.json()
        if response.status_code >= 400:
            raise OpenMatesApiError(response.status_code, data)
        return data

    def _get_master_key(self) -> bytes:
        if self._master_key is not None:
            return self._master_key
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        session = self._get_sdk_session()
        wrapper = session.get("key_wrapper") or {}
        encrypted_key = wrapper.get("encrypted_key")
        salt = wrapper.get("salt")
        key_iv = wrapper.get("key_iv")
        if not encrypted_key or not salt or not key_iv:
            raise OpenMatesConfigError("SDK session did not include API-key-wrapped master key material")

        master_key = _unwrap_api_key_master_key(self._api_key, encrypted_key, salt, key_iv)
        if master_key is None:
            raise OpenMatesConfigError("Unable to decrypt SDK session master key with API key")
        self._master_key = master_key
        return master_key

    def _get_sdk_session(self) -> dict[str, Any]:
        if self._sdk_session is None:
            self._sdk_session = self._post(
                "/v1/sdk/session",
                {"sdk_name": "pip", "device_identity": self._device_id},
            )
        return self._sdk_session

    def _resolve_loaded_chat_key(
        self,
        chat: dict[str, Any],
        chat_key_wrappers: list[dict[str, Any]] | None = None,
    ) -> bytes | None:
        chat_id = chat.get("id")
        hashed_chat_id = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest() if chat_id else ""
        wrapper = next(
            (
                entry
                for entry in (chat_key_wrappers or [])
                if entry.get("key_type") == "master"
                and entry.get("hashed_chat_id") == hashed_chat_id
                and isinstance(entry.get("encrypted_chat_key"), str)
            ),
            None,
        )
        encrypted_chat_key = (
            wrapper.get("encrypted_chat_key")
            if wrapper
            else chat.get("encrypted_chat_key")
        )
        return _decrypt_aes_gcm_bytes(encrypted_chat_key, self._get_master_key()) if isinstance(encrypted_chat_key, str) else None

    def _decrypt_chat_metadata(
        self,
        chat: dict[str, Any],
        chat_key_wrappers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        chat_key = self._resolve_loaded_chat_key(chat, chat_key_wrappers)
        if chat_key is None:
            return chat

        decrypted = dict(chat)
        if isinstance(chat.get("encrypted_title"), str):
            decrypted["title"] = _decrypt_aes_gcm_text(chat["encrypted_title"], chat_key)
        if isinstance(chat.get("encrypted_chat_summary"), str):
            decrypted["chat_summary"] = _decrypt_aes_gcm_text(chat["encrypted_chat_summary"], chat_key)
        if isinstance(chat.get("encrypted_category"), str):
            decrypted["category"] = _decrypt_aes_gcm_text(chat["encrypted_category"], chat_key)
        return decrypted

    def _decrypt_loaded_chat_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat = payload.get("chat")
        if not isinstance(chat, dict):
            return payload
        chat_key_wrappers = payload.get("chat_key_wrappers") if isinstance(payload.get("chat_key_wrappers"), list) else []
        decrypted_chat = self._decrypt_chat_metadata(chat, chat_key_wrappers)
        chat_key = self._resolve_loaded_chat_key(chat, chat_key_wrappers)
        if chat_key is None or not isinstance(payload.get("messages"), list):
            return {**payload, "chat": decrypted_chat}

        messages = []
        for raw_message in payload["messages"]:
            message = json.loads(raw_message) if isinstance(raw_message, str) else dict(raw_message)
            if isinstance(message.get("encrypted_content"), str):
                message["content"] = _decrypt_aes_gcm_text(message["encrypted_content"], chat_key)
            if isinstance(message.get("encrypted_sender_name"), str):
                message["sender_name"] = _decrypt_aes_gcm_text(message["encrypted_sender_name"], chat_key)
            if isinstance(message.get("encrypted_category"), str):
                message["category"] = _decrypt_aes_gcm_text(message["encrypted_category"], chat_key)
            if isinstance(message.get("encrypted_model_name"), str):
                message["model_name"] = _decrypt_aes_gcm_text(message["encrypted_model_name"], chat_key)
            messages.append(message)
        embeds = payload.get("embeds")
        if isinstance(embeds, list):
            embed_keys = payload.get("embed_keys") if isinstance(payload.get("embed_keys"), list) else []
            embeds = self._decrypt_loaded_chat_embeds(embeds, embed_keys, chat_key)
        return {**payload, "chat": decrypted_chat, "messages": messages, "embeds": embeds}

    def _decrypt_loaded_chat_embeds(
        self,
        embeds: list[dict[str, Any]],
        embed_keys: list[dict[str, Any]],
        chat_key: bytes,
    ) -> list[dict[str, Any]]:
        master_key = self._get_master_key()
        decrypted_embeds = []
        for raw_embed in embeds:
            embed = dict(raw_embed)
            embed_id = str(embed.get("embed_id") or embed.get("id") or "")
            if not embed_id:
                decrypted_embeds.append(embed)
                continue
            hashed_embed_id = hashlib.sha256(embed_id.encode("utf-8")).hexdigest()
            embed_key = _resolve_loaded_embed_key(embed_keys, hashed_embed_id, master_key, chat_key)
            if embed_key is None:
                decrypted_embeds.append(embed)
                continue
            if isinstance(embed.get("encrypted_type"), str):
                embed["type"] = _decrypt_aes_gcm_text(embed["encrypted_type"], embed_key)
            if isinstance(embed.get("encrypted_text_preview"), str):
                embed["text_preview"] = _decrypt_aes_gcm_text(embed["encrypted_text_preview"], embed_key)
            if isinstance(embed.get("encrypted_content"), str):
                content = _decrypt_aes_gcm_text(embed["encrypted_content"], embed_key)
                embed["content"] = _parse_maybe_json(content)
            decrypted_embeds.append(embed)
        return decrypted_embeds

    def _resolve_embed_key_for_share(self, embed_keys: list[dict[str, Any]], embed_id: str) -> bytes | None:
        hashed_embed_id = hashlib.sha256(embed_id.encode("utf-8")).hexdigest()
        master_key = self._get_master_key()
        return _resolve_loaded_embed_key(embed_keys, hashed_embed_id, master_key, master_key)

    def _web_origin(self) -> str:
        parsed = urlparse(self._api_url)
        if parsed.hostname == "api.dev.openmates.org":
            hostname = "app.dev.openmates.org"
        elif parsed.hostname == "api.openmates.org":
            hostname = "openmates.org"
        else:
            hostname = (parsed.hostname or "openmates.org").removeprefix("api.")
            if parsed.hostname and parsed.hostname.startswith("api."):
                hostname = f"app.{hostname}"
        return urlunparse((parsed.scheme or "https", hostname, "", "", "", ""))


def _quote(value: str) -> str:
    return quote(value, safe="")


def _load_or_create_device_id(custom_path: str | os.PathLike[str] | None) -> str:
    path = Path(custom_path) if custom_path is not None else Path.home() / ".openmates" / "sdk-device-id"
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    device_id = str(uuid.uuid4())
    path.write_text(f"{device_id}\n", encoding="utf-8")
    path.chmod(0o600)
    return device_id


def _with_query(path: str, **query: Any) -> str:
    cleaned = {key: value for key, value in query.items() if value is not None}
    if not cleaned:
        return path
    return f"{path}?{urlencode(cleaned, doseq=True)}"


def _require_confirmed(confirmed: bool, action: str) -> None:
    if confirmed is not True:
        raise OpenMatesConfigError(f"{action} requires confirmed=True")


def _unsupported_sdk_feature(feature: str) -> Any:
    raise OpenMatesConfigError(f"{feature} is not available through the API-key SDK yet")


def _extract_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    for part in content_disposition.split(";"):
        part = part.strip()
        if part.startswith("filename="):
            return part.removeprefix("filename=").strip('"')
    return None


def _resolve_design_icon_svg_path(*, svg_path: str | None = None, prefix: str | None = None, name: str | None = None) -> str:
    if svg_path:
        trimmed = svg_path.strip()
        if not DESIGN_ICON_PATH_PATTERN.match(trimmed):
            raise OpenMatesConfigError("svg_path must be an OpenMates Design Iconify SVG path")
        return trimmed
    if not prefix or not name:
        raise OpenMatesConfigError("Provide either svg_path or both prefix and name")
    prefix = prefix.strip()
    name = name.strip()
    if not DESIGN_ICON_SEGMENT_PATTERN.match(prefix) or not DESIGN_ICON_SEGMENT_PATTERN.match(name):
        raise OpenMatesConfigError("Icon prefix and name may contain only letters, numbers, dots, underscores, and dashes")
    return f"/v1/apps/design/icons/iconify/{quote(prefix, safe='')}/{quote(name, safe='')}.svg"


def _normalize_design_icon_color(color: str | None) -> str | None:
    if color is None:
        return None
    trimmed = color.strip()
    if not DESIGN_ICON_HEX_COLOR_PATTERN.match(trimmed):
        raise OpenMatesConfigError("Icon color must be a hex color such as #111827")
    return trimmed


def _apply_design_icon_color(svg: str, color: str | None) -> str:
    if color is None:
        return svg
    svg = re.sub(r"\bcurrentColor\b", color, svg)
    svg_tag = re.search(r"<svg\b([^>]*)>", svg, re.IGNORECASE)
    if not svg_tag:
        return svg
    attrs = svg_tag.group(1)
    if re.search(r"\scolor\s*=", attrs):
        replacement = re.sub(r"\scolor\s*=\s*(['\"])[^'\"]*\1", f' color="{color}"', svg_tag.group(0), count=1, flags=re.IGNORECASE)
    else:
        replacement = f"<svg{attrs} color=\"{color}\">"
    return f"{svg[:svg_tag.start()]}{replacement}{svg[svg_tag.end():]}"


def _normalize_icon_png_size(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0 or value > MAX_ICON_PNG_SIZE:
        raise OpenMatesConfigError(f"PNG {label} must be an integer from 1 to {MAX_ICON_PNG_SIZE}")
    return value


def _render_design_icon_png(svg: str, *, size: int | None = None, width: int | None = None, height: int | None = None) -> bytes:
    try:
        import cairosvg  # type: ignore[import]
    except ImportError as exc:
        raise OpenMatesConfigError("cairosvg is required for PNG icon export") from exc

    width = _normalize_icon_png_size(width, "width")
    height = _normalize_icon_png_size(height, "height")
    size = _normalize_icon_png_size(size, "size") or DEFAULT_ICON_PNG_SIZE
    kwargs: dict[str, Any] = {}
    if width is not None:
        kwargs["output_width"] = width
    elif height is not None:
        kwargs["output_height"] = height
    else:
        kwargs["output_width"] = size
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), **kwargs)


def _normalize_history(history: Any) -> list[dict[str, Any]]:
    if history is None:
        return []
    if isinstance(history, list):
        return [item for item in history if isinstance(item, dict)]
    if isinstance(history, dict) and isinstance(history.get("messages"), list):
        return [item for item in history["messages"] if isinstance(item, dict)]
    return []


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("utf-8"))


def _derive_api_key_wrapping_key(api_key: str, salt_b64: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode("utf-8"),
        _b64decode(salt_b64),
        SDK_KDF_ITERATIONS,
        dklen=32,
    )


def _unwrap_api_key_master_key(api_key: str, encrypted_key_b64: str, salt_b64: str, key_iv_b64: str) -> bytes | None:
    try:
        return AESGCM(_derive_api_key_wrapping_key(api_key, salt_b64)).decrypt(
            _b64decode(key_iv_b64),
            _b64decode(encrypted_key_b64),
            None,
        )
    except Exception:
        return None


def _assert_account_export_payload_safe(value: Any, path: str = "$export") -> None:
    if value is None:
        return
    if isinstance(value, str):
        for pattern in ACCOUNT_EXPORT_FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise OpenMatesConfigError(f"Account export contains forbidden secret-like value at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_account_export_payload_safe(item, f"{path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        if str(key).lower() in ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES:
            raise OpenMatesConfigError(f"Account export contains forbidden secret field '{key}' at {path}")
        _assert_account_export_payload_safe(child, f"{path}.{key}")


def _sanitize_account_export_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(manifest))
    report = sanitized.get("report")
    if isinstance(report, dict) and isinstance(report.get("redactions"), list):
        report["redactions"] = ACCOUNT_EXPORT_REDACTION_CATEGORIES
    _assert_account_export_payload_safe(sanitized, "$manifest")
    return sanitized


def _account_import_fingerprint(provider: str, source_chat_id: str, messages: list[dict[str, Any]]) -> str:
    payload = {
        "provider": provider,
        "source_chat_id": source_chat_id,
        "messages": [
            {
                "role": message.get("role"),
                "source_message_id": message.get("source_message_id"),
                "content": message.get("content"),
            }
            for message in messages
        ],
    }
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


def _parse_openmates_manifest_domains(manifest_text: str) -> list[str]:
    domains: list[str] = []
    in_domains = False
    for line in manifest_text.splitlines():
        if re.match(r"^domains:\s*$", line):
            in_domains = True
            continue
        if in_domains and re.match(r"^\S", line):
            break
        match = re.match(r"^\s{2}([a-zA-Z0-9_-]+):", line) if in_domains else None
        if match:
            domains.append(match.group(1))
    return domains


def _claude_message_content(message: dict[str, Any]) -> tuple[str, list[str]]:
    content = message.get("content") if isinstance(message.get("content"), list) else []
    block_types: list[str] = []
    text_parts: list[str] = []
    for raw_block in content:
        if not isinstance(raw_block, dict):
            continue
        block_type = str(raw_block.get("type") or "unknown")
        block_types.append(block_type)
        if block_type == "text" and isinstance(raw_block.get("text"), str):
            text_parts.append(raw_block["text"])
        if block_type == "tool_result" and isinstance(raw_block.get("content"), str):
            text_parts.append(raw_block["content"])
    return "\n".join(text_parts) if text_parts else str(message.get("text") or ""), block_types


def _parse_import_timestamp(value: Any) -> int:
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return int(value / 1000) if value > 10_000_000_000 else int(value)
    if isinstance(value, str) and value:
        try:
            parsed = calendar.timegm(time.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"))
            return int(parsed)
        except ValueError:
            pass
    return int(time.time())


def _split_combined_ciphertext(encrypted_b64: str) -> tuple[bytes, bytes]:
    combined = _b64decode(encrypted_b64)
    offset = CIPHERTEXT_HEADER_LENGTH if combined.startswith(CIPHERTEXT_MAGIC) else 0
    return combined[offset : offset + AES_GCM_IV_LENGTH], combined[offset + AES_GCM_IV_LENGTH :]


def _decrypt_aes_gcm_bytes(encrypted_b64: str, key: bytes) -> bytes | None:
    try:
        iv, ciphertext = _split_combined_ciphertext(encrypted_b64)
        return AESGCM(key).decrypt(iv, ciphertext, None)
    except Exception:
        return None


def _decrypt_aes_gcm_text(encrypted_b64: str, key: bytes) -> str | None:
    decrypted = _decrypt_aes_gcm_bytes(encrypted_b64, key)
    if decrypted is None:
        return None
    return decrypted.decode("utf-8")


def _encrypt_aes_gcm_text(plaintext: str, key: bytes) -> str:
    iv = os.urandom(AES_GCM_IV_LENGTH)
    encrypted = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(CIPHERTEXT_MAGIC + b"\x01\x00\x00\x00" + iv + encrypted).decode("utf-8")


def _encrypt_aes_gcm_bytes(plaintext: bytes, key: bytes) -> str:
    iv = os.urandom(AES_GCM_IV_LENGTH)
    return base64.b64encode(iv + AESGCM(key).encrypt(iv, plaintext, None)).decode("utf-8")


def _build_task_create_input(master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise OpenMatesConfigError("Task title is required")
    task_key = os.urandom(32)
    now = int(time.time())
    assignee_type, assignee_hash = _task_assignee(payload.get("assign") or payload.get("assignee"))
    project_ids = _string_list(payload.get("project_ids") or payload.get("linked_project_ids") or [])
    labels = _normalize_task_labels(payload.get("labels") if "labels" in payload else payload.get("tags"))
    status = str(payload.get("status") or ("in_progress" if assignee_type == "ai" and not payload.get("due_at") else "todo"))
    task: dict[str, Any] = {
        "task_id": str(payload.get("task_id") or uuid.uuid4()),
        "version": 1,
        "encrypted_task_key": _encrypt_aes_gcm_bytes(task_key, master_key),
        "encrypted_title": _encrypt_aes_gcm_text(title, task_key),
        "encrypted_description": _encrypt_aes_gcm_text(str(payload.get("description") or ""), task_key),
        "encrypted_labels": _encrypt_aes_gcm_text(json.dumps(labels), task_key),
        "encrypted_tags": _encrypt_aes_gcm_text(json.dumps(labels), task_key),
        "label_hashes": _task_label_hashes(master_key, labels),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text(json.dumps(project_ids), task_key),
        "status": status,
        "assignee_type": assignee_type,
        "assignee_hash": assignee_hash,
        "primary_chat_id": payload.get("chat_id") or payload.get("primary_chat_id") or None,
        "linked_project_ids": project_ids,
        "plan_id": payload.get("plan_id") or payload.get("plan") or None,
        "due_at": payload.get("due_at"),
        "priority": _normalize_task_priority(payload.get("priority")) or 0,
        "position": int(payload.get("position") or now),
        "created_at": int(payload.get("created_at") or now),
        "updated_at": int(payload.get("updated_at") or now),
    }
    return task


def _build_task_update_input(task: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    task_key = _task_key_from_record(task.get("encrypted") if isinstance(task.get("encrypted"), dict) else task, master_key)
    patch: dict[str, Any] = {"version": int(task["version"]), "updated_at": int(time.time())}
    if "title" in payload:
        patch["encrypted_title"] = _encrypt_aes_gcm_text(str(payload.get("title") or ""), task_key)
    if "description" in payload:
        patch["encrypted_description"] = _encrypt_aes_gcm_text(str(payload.get("description") or ""), task_key)
    if "status" in payload:
        patch["status"] = payload.get("status")
    if "assign" in payload or "assignee" in payload:
        assignee_type, assignee_hash = _task_assignee(payload.get("assign") or payload.get("assignee"))
        patch["assignee_type"] = assignee_type
        patch["assignee_hash"] = assignee_hash
    if "chat_id" in payload or "primary_chat_id" in payload:
        patch["primary_chat_id"] = payload.get("chat_id") if "chat_id" in payload else payload.get("primary_chat_id")
    if "project_ids" in payload or "linked_project_ids" in payload:
        project_ids = _string_list(payload.get("project_ids") or payload.get("linked_project_ids") or [])
        patch["linked_project_ids"] = project_ids
        patch["encrypted_linked_project_ids"] = _encrypt_aes_gcm_text(json.dumps(project_ids), task_key)
    if "plan_id" in payload or "plan" in payload:
        patch["plan_id"] = payload.get("plan_id") if "plan_id" in payload else payload.get("plan")
    if "priority" in payload:
        patch["priority"] = _normalize_task_priority(payload.get("priority")) or 0
    if any(key in payload for key in ("labels", "tags", "add_labels", "add_tags", "remove_labels", "remove_tags")):
        replace_labels = payload.get("labels") if "labels" in payload else payload.get("tags") if "tags" in payload else None
        remove = set(_normalize_task_labels([*_string_list(payload.get("remove_labels") or []), *_string_list(payload.get("remove_tags") or [])]))
        base = _normalize_task_labels(replace_labels) if replace_labels is not None else _normalize_task_labels(task.get("labels") or task.get("tags") or [])
        labels = _normalize_task_labels([*(label for label in base if label not in remove), *_string_list(payload.get("add_labels") or []), *_string_list(payload.get("add_tags") or [])])
        patch["encrypted_labels"] = _encrypt_aes_gcm_text(json.dumps(labels), task_key)
        patch["encrypted_tags"] = _encrypt_aes_gcm_text(json.dumps(labels), task_key)
        patch["label_hashes"] = _task_label_hashes(master_key, labels)
    return patch


def _decrypt_task_record(record: dict[str, Any], master_key: bytes) -> dict[str, Any]:
    if record.get("source") == "workflow_run":
        return _workflow_projection_task(record)
    task_key = _task_key_from_record(record, master_key)
    labels = _json_string_list(_decrypt_aes_gcm_text(str(record.get("encrypted_labels") or record.get("encrypted_tags") or ""), task_key))
    linked_project_ids = _json_string_list(_decrypt_aes_gcm_text(str(record.get("encrypted_linked_project_ids") or ""), task_key))
    task = {
        "task_id": record["task_id"],
        "short_id": record.get("short_id") or _derive_task_short_id(record),
        "title": _decrypt_aes_gcm_text(str(record.get("encrypted_title") or ""), task_key) or "(untitled task)",
        "description": _decrypt_aes_gcm_text(str(record.get("encrypted_description") or ""), task_key) or "",
        "labels": labels,
        "tags": labels,
        "latest_instruction": _decrypt_aes_gcm_text(str(record.get("encrypted_latest_instruction") or ""), task_key) or "",
        "status": record.get("status"),
        "assignee_type": record.get("assignee_type"),
        "assignee_hash": record.get("assignee_hash"),
        "primary_chat_id": record.get("primary_chat_id"),
        "linked_project_ids": linked_project_ids or _string_list(record.get("linked_project_ids") or []),
        "plan_id": record.get("plan_id"),
        "due_at": record.get("due_at"),
        "priority": int(record.get("priority") or 0),
        "priority_level": _task_priority_level(record.get("priority")),
        "position": int(record.get("position") or 0),
        "queue_state": record.get("queue_state") or "none",
        "blocked_reason_code": record.get("blocked_reason_code"),
        "ai_execution_state": record.get("ai_execution_state"),
        "version": int(record.get("version") or 1),
        "encrypted": record,
    }
    return task


def _task_key_from_record(record: dict[str, Any], master_key: bytes) -> bytes:
    encrypted_task_key = record.get("encrypted_task_key")
    if not isinstance(encrypted_task_key, str):
        raise OpenMatesConfigError(f"Task {record.get('task_id')} is missing encrypted task key")
    task_key = _decrypt_aes_gcm_bytes(encrypted_task_key, master_key)
    if task_key is None:
        raise OpenMatesConfigError(f"Failed to decrypt task key for {record.get('task_id')}")
    return task_key


def _find_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task.get("task_id") == task_id:
            return task
    matches = [task for task in tasks if task.get("short_id") == task_id]
    if len(matches) > 1:
        raise OpenMatesConfigError(f"Task '{task_id}' is ambiguous. Use the full task ID.")
    if not matches:
        raise OpenMatesConfigError(f"Task '{task_id}' was not found.")
    return matches[0]


def _task_assignee(value: Any) -> tuple[str, str | None]:
    if value in (None, "", "user"):
        return "user", None
    if value in ("ai", "openmates", "OpenMates"):
        return "ai", None
    return "user", str(value)


def _normalize_task_labels(value: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in _string_list(value):
        normalized = " ".join(item.strip().lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _task_label_hashes(master_key: bytes, labels: list[str]) -> list[str]:
    index_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=TASK_LABEL_INDEX_INFO,
    ).derive(master_key)
    return [hmac.new(index_key, label.encode("utf-8"), hashlib.sha256).hexdigest() for label in _normalize_task_labels(labels)]


def _normalize_task_priority(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OpenMatesConfigError(f"Invalid task priority '{value}'")
    if isinstance(value, int):
        if 0 <= value <= 4:
            return value
        raise OpenMatesConfigError(f"Invalid task priority '{value}'")
    normalized = str(value).strip().lower()
    if normalized.isdigit():
        return _normalize_task_priority(int(normalized))
    if normalized in TASK_PRIORITY_LEVELS:
        return TASK_PRIORITY_LEVELS.index(normalized)
    raise OpenMatesConfigError(f"Unknown task priority '{value}'. Expected one of: {', '.join(TASK_PRIORITY_LEVELS)}")


def _task_priority_level(value: Any) -> str:
    try:
        priority = int(value or 0)
    except (TypeError, ValueError):
        priority = 0
    return TASK_PRIORITY_LEVELS[max(0, min(4, priority))]


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _json_string_list(value: str | None) -> list[str]:
    parsed = _parse_maybe_json(value)
    return _string_list(parsed)


def _derive_task_short_id(record: dict[str, Any]) -> str:
    prefix = str(record.get("short_id_prefix") or "TASK")
    source = str(record.get("task_id") or f"{record.get('created_at', '')}-{record.get('position', '')}")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:4].upper()
    return f"{prefix}-{int(digest, 16) % 10000}"


def _workflow_projection_task(record: dict[str, Any]) -> dict[str, Any]:
    stable_id = str(record.get("workflow_run_id") or record.get("task_id") or "")
    short_id = record.get("short_id") or f"WF-{hashlib.sha256(stable_id.encode('utf-8')).hexdigest()[:6].upper()}"
    return {
        "task_id": record.get("task_id"),
        "source": "workflow_run",
        "short_id": short_id,
        "title": record.get("title") or "Workflow run",
        "description": record.get("blocked_message") or "",
        "labels": [],
        "tags": [],
        "latest_instruction": "",
        "status": record.get("status"),
        "assignee_type": "user",
        "assignee_hash": None,
        "primary_chat_id": None,
        "linked_project_ids": [],
        "plan_id": None,
        "due_at": record.get("due_at"),
        "priority": int(record.get("priority") or 0),
        "priority_level": _task_priority_level(record.get("priority")),
        "position": int(record.get("position") or 0),
        "queue_state": str(record.get("run_status") or "workflow"),
        "blocked_reason_code": record.get("blocked_reason_code") or record.get("blocked_reason"),
        "ai_execution_state": None,
        "read_only": True,
        "version": int(record.get("version") or 1),
        "encrypted": record,
    }


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items() if key != "encrypted"}


def _is_task_version_conflict(exc: OpenMatesApiError) -> bool:
    return exc.status_code == 409 and "TASK_VERSION_CONFLICT" in json.dumps(exc.data)


def _encrypt_raw_key_for_api_key(raw_key: bytes, api_key: str, salt: bytes) -> tuple[str, str]:
    wrapping_key = hashlib.pbkdf2_hmac("sha256", api_key.encode("utf-8"), salt, SDK_KDF_ITERATIONS, dklen=32)
    iv = os.urandom(AES_GCM_IV_LENGTH)
    encrypted = AESGCM(wrapping_key).encrypt(iv, raw_key, None)
    return base64.b64encode(encrypted).decode("utf-8"), base64.b64encode(iv).decode("utf-8")


def _generate_api_key() -> str:
    return API_KEY_PREFIX + "".join(secrets.choice(API_KEY_CHARS) for _ in range(API_KEY_RANDOM_LENGTH))


def _create_api_key_material(name: str, master_key: bytes) -> tuple[str, dict[str, Any]]:
    api_key = _generate_api_key()
    salt = os.urandom(16)
    encrypted_master_key, key_iv = _encrypt_raw_key_for_api_key(master_key, api_key, salt)
    key_prefix = f"{api_key[:12]}..."
    return api_key, {
        "encrypted_name": _encrypt_aes_gcm_text(name.strip(), master_key),
        "api_key_hash": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
        "encrypted_key_prefix": _encrypt_aes_gcm_text(key_prefix, master_key),
        "encrypted_master_key": encrypted_master_key,
        "salt": base64.b64encode(salt).decode("utf-8"),
        "key_iv": key_iv,
    }


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _derive_share_key(value: str, salt: bytes = SHARE_FIXED_SALT) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, SDK_KDF_ITERATIONS, dklen=32)


def _encrypt_share_blob(data: bytes, key: bytes) -> str:
    iv = os.urandom(AES_GCM_IV_LENGTH)
    encrypted = AESGCM(key).encrypt(iv, data, None)
    return _base64url_encode(iv + encrypted)


def _generate_share_blob(kind: str, item_id: str, item_key: bytes, *, expires: int | None = None, password: str | None = None) -> str:
    key_for_blob = base64.b64encode(item_key).decode("utf-8")
    pwd_flag = 0
    if password:
        key_for_blob = _encrypt_share_blob(key_for_blob.encode("utf-8"), _derive_share_key(password, f"openmates-pwd-{item_id}".encode("utf-8")))
        pwd_flag = 1
    serialized = urlencode({
        f"{kind}_encryption_key": key_for_blob,
        "generated_at": int(time.time()),
        "duration_seconds": expires or 0,
        "pwd": pwd_flag,
    })
    return _encrypt_share_blob(serialized.encode("utf-8"), _derive_share_key(item_id))


def _hash_item_key(app_id: str, item_type: str) -> str:
    return hashlib.sha256(f"{app_id}-{item_type}-{int(time.time() * 1000)}".encode("utf-8")).hexdigest()[:32]


def _decrypt_connected_account_payload(encrypted_payload: str, passcode: str) -> dict[str, Any]:
    if not encrypted_payload.startswith(CONNECTED_ACCOUNT_TRANSFER_PREFIX):
        raise OpenMatesConfigError("Connected account import payload must start with OMCA1.")
    if not passcode.strip():
        raise OpenMatesConfigError("A passcode is required to import a connected account.")
    envelope = json.loads(_base64url_decode(encrypted_payload.removeprefix(CONNECTED_ACCOUNT_TRANSFER_PREFIX)).decode("utf-8"))
    if envelope.get("version") != 1 or envelope.get("kdf", {}).get("iterations") != SDK_KDF_ITERATIONS:
        raise OpenMatesConfigError("Unsupported connected account import payload format.")
    try:
        key = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), _base64url_decode(envelope["kdf"]["salt"]), SDK_KDF_ITERATIONS, dklen=32)
        plaintext = AESGCM(key).decrypt(_base64url_decode(envelope["cipher"]["iv"]), _base64url_decode(envelope["cipher"]["text"]), None)
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise OpenMatesConfigError("Could not decrypt connected account import payload. Check the passcode and payload.") from exc
    if payload.get("version") != 1 or not payload.get("provider_id") or not payload.get("app_id"):
        raise OpenMatesConfigError("Connected account import payload is malformed.")
    return payload


def _connected_account_row(payload: dict[str, Any], *, user_id: str, master_key: bytes) -> dict[str, Any]:
    account_id = str(uuid.uuid4())
    provider_id = str(payload.get("provider_id") or "")
    app_id = "calendar" if payload.get("app_id") == "google_calendar" else str(payload.get("app_id") or provider_id)
    capabilities = [item for item in payload.get("capabilities", []) if isinstance(item, str)] or ["read"]
    actions = []
    for capability in capabilities:
        if capability == "read":
            actions.append("read")
        if capability == "write":
            actions.extend(["write", "update"])
        if capability == "delete":
            actions.append("delete")
    actions = list(dict.fromkeys(actions or ["read"]))
    refresh_bundle = payload.get("refresh_token_bundle") if isinstance(payload.get("refresh_token_bundle"), dict) else {}
    scopes = [item for item in refresh_bundle.get("scopes", []) if isinstance(item, str)]
    label = str(payload.get("label") or ("Google Calendar" if provider_id == "google_calendar" else "Connected account"))
    return {
        "id": account_id,
        "hashed_user_id": hashlib.sha256(user_id.encode("utf-8")).hexdigest(),
        "encrypted_provider_type": _encrypt_aes_gcm_text(provider_id, master_key),
        "provider_type_hash": hashlib.sha256(provider_id.encode("utf-8")).hexdigest(),
        "encrypted_account_label": _encrypt_aes_gcm_text(label, master_key),
        "encrypted_refresh_token_bundle": _encrypt_aes_gcm_text(json.dumps(refresh_bundle), master_key),
        "encrypted_capabilities": _encrypt_aes_gcm_text(json.dumps(capabilities), master_key),
        "encrypted_app_permissions": _encrypt_aes_gcm_text(json.dumps({"app_id": app_id, "allowed_actions": actions, "scopes": scopes}), master_key),
        "encrypted_account_directory_hint": _encrypt_aes_gcm_text(json.dumps({"account_ref": payload.get("account_ref") or account_id, "label": label, "capabilities": capabilities, "runtime_modes": payload.get("runtime_modes") or {action: "allow_automatically" if action == "read" else "always_ask" for action in actions}}), master_key),
    }


def _resolve_loaded_embed_key(
    embed_keys: list[dict[str, Any]],
    hashed_embed_id: str,
    master_key: bytes,
    chat_key: bytes,
) -> bytes | None:
    matching_keys = [key for key in embed_keys if key.get("hashed_embed_id") == hashed_embed_id]
    master_key_entry = next((key for key in matching_keys if key.get("key_type") == "master"), None)
    if isinstance(master_key_entry, dict) and isinstance(master_key_entry.get("encrypted_embed_key"), str):
        embed_key = _decrypt_aes_gcm_bytes(master_key_entry["encrypted_embed_key"], master_key)
        if embed_key is not None:
            return embed_key
    chat_key_entry = next((key for key in matching_keys if key.get("key_type") == "chat"), None)
    if isinstance(chat_key_entry, dict) and isinstance(chat_key_entry.get("encrypted_embed_key"), str):
        return _decrypt_aes_gcm_bytes(chat_key_entry["encrypted_embed_key"], chat_key)
    return None


def _parse_maybe_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def datetime_utc_date(unix_seconds: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(unix_seconds))


def default_ideabucket_scheduled_send_at(now_seconds: int) -> int:
    date = time.gmtime(now_seconds)
    return int(calendar.timegm((date.tm_year, date.tm_mon, date.tm_mday + 1, 9, 0, 0, 0, 0, 0)))


def build_ideabucket_markdown(prompt: str, idea_text: str) -> str:
    return f"{prompt.strip()}\n\n----- Idea 1 -----\n{idea_text.strip()}\n-----------------"


class OpenMatesChats:
    """Chat SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        data = self._client._get(f"/v1/sdk/chats?limit={limit}&offset={offset}")
        return [self._client._decrypt_chat_metadata(chat) for chat in data.get("chats", [])]

    def search(self, query: str, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        normalized = query.strip().lower()
        matches = [
            chat
            for chat in self.list(limit=0, offset=0)
            if normalized
            in "\n".join(
                str(value)
                for value in [chat.get("title"), chat.get("chat_summary"), chat.get("category"), chat.get("id")]
                if isinstance(value, str)
            ).lower()
        ]
        return matches[offset:] if limit == 0 else matches[offset : offset + limit]

    def load(self, chat_id: str) -> dict[str, Any]:
        return self._client._decrypt_loaded_chat_payload(self._client._get(f"/v1/sdk/chats/{_quote(chat_id)}"))

    def send(
        self,
        message: str,
        *,
        history: Any = None,
        save_to_account: bool = False,
        focus_mode: dict[str, str] | None = None,
        memory_ids: list[str] | None = None,
        model: str | None = None,
        chat_id: str | None = None,
        title: str | None = None,
        recovery_poll_interval_seconds: float = DEFAULT_RECOVERY_POLL_INTERVAL_SECONDS,
        recovery_timeout_seconds: float = DEFAULT_RECOVERY_TIMEOUT_SECONDS,
    ) -> ChatResponse:
        if save_to_account:
            return self._send_saved(
                message,
                history=history,
                focus_mode=focus_mode,
                memory_ids=memory_ids,
                model=model,
                chat_id=chat_id,
                title=title,
                recovery_poll_interval_seconds=recovery_poll_interval_seconds,
                recovery_timeout_seconds=recovery_timeout_seconds,
            )
        data = self._client._post(
            "/v1/sdk/chats",
            {
                "message": message,
                "history": _normalize_history(history),
                "save_to_account": save_to_account,
                "focus_mode": focus_mode,
                "memory_ids": memory_ids or [],
                "model": model,
            },
        )
        response = data.get("response") or {}
        return ChatResponse(content=response.get("content"), raw=data)

    def _send_saved(
        self,
        message: str,
        *,
        history: Any,
        focus_mode: dict[str, str] | None,
        memory_ids: list[str] | None,
        model: str | None,
        chat_id: str | None,
        title: str | None,
        recovery_poll_interval_seconds: float,
        recovery_timeout_seconds: float,
    ) -> ChatResponse:
        master_key = self._client._get_master_key()
        session = self._client._get_sdk_session()
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        if not user.get("id"):
            raise OpenMatesConfigError("SDK session did not include the authenticated user identity")

        saved_chat_id = chat_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        created_at = int(time.time())
        expected_messages_v = 0
        encrypted_chat_metadata = None
        if chat_id:
            loaded = self.load(chat_id)
            chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else {}
            encrypted_chat_key = chat.get("encrypted_chat_key")
            if not isinstance(encrypted_chat_key, str):
                raise OpenMatesConfigError("Saved chat does not include encrypted chat key material")
            chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, master_key)
            if chat_key is None:
                raise OpenMatesConfigError("Unable to decrypt saved chat key material")
            expected_messages_v = int(chat.get("messages_v") or 0)
        else:
            chat_key = os.urandom(32)
            encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
            encrypted_chat_metadata = {
                "encrypted_title": _encrypt_aes_gcm_text(title or message[:80], chat_key),
                "encrypted_chat_key": encrypted_chat_key,
                "created_at": created_at,
                "updated_at": created_at,
            }

        recovery_private_key, recovery_public_key = derive_recovery_keypair(
            base64.urlsafe_b64encode(chat_key).decode("utf-8").rstrip("="),
            saved_chat_id,
            1,
        )
        normalized_history = _normalize_history(history)
        inference_request = {
            "messages": [*normalized_history, {"role": "user", "content": message}],
            "model": model,
            "focus_mode": focus_mode,
            "memory_ids": memory_ids or [],
        }
        payload = {
            "message": message,
            "history": normalized_history,
            "save_to_account": True,
            "title": title,
            "focus_mode": focus_mode,
            "memory_ids": memory_ids or [],
            "model": model,
            "protocol_version": 1,
            "chat_id": saved_chat_id,
            "turn_id": turn_id,
            "message_id": message_id,
            "chat_key_version": 1,
            "encrypted_chat_key": encrypted_chat_key,
            "recovery_public_key": recovery_public_key,
            "expected_messages_v": expected_messages_v,
            "encrypted_user_message": {
                "client_message_id": message_id,
                "chat_id": saved_chat_id,
                "encrypted_content": _encrypt_aes_gcm_text(message, chat_key),
                "encrypted_sender_name": _encrypt_aes_gcm_text("User", chat_key),
                "role": "user",
                "created_at": created_at,
                "updated_at": created_at,
            },
            "encrypted_chat_metadata": encrypted_chat_metadata,
            "inference_request": inference_request,
        }
        data = self._client._post("/v1/sdk/chats", payload)
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise OpenMatesConfigError("Saved chat dispatch did not return a stable inference task id")
        claim = self._poll_recovery_claim(
            task_id,
            timeout_seconds=recovery_timeout_seconds,
            poll_interval_seconds=recovery_poll_interval_seconds,
        )
        recovered = self._open_recovery_claim(
            claim,
            recovery_private_key=recovery_private_key,
            owner_id=str(user["id"]),
            chat_id=saved_chat_id,
            turn_id=turn_id,
        )
        completed_at = int(time.time())
        encrypted_assistant_message = {
            "client_message_id": recovered["assistant_message_id"],
            "chat_id": saved_chat_id,
            "encrypted_content": _encrypt_aes_gcm_text(recovered["content"], chat_key),
            "encrypted_sender_name": _encrypt_aes_gcm_text("Assistant", chat_key),
            "role": "assistant",
            "user_message_id": message_id,
            "created_at": completed_at,
            "updated_at": completed_at,
        }
        if recovered["category"] is not None:
            encrypted_assistant_message["encrypted_category"] = _encrypt_aes_gcm_text(recovered["category"], chat_key)
        if recovered["model_name"] is not None:
            encrypted_assistant_message["encrypted_model_name"] = _encrypt_aes_gcm_text(recovered["model_name"], chat_key)
        terminal = self._client._post(
            f"/v1/sdk/chats/recovery/{_quote(task_id)}/persist",
            {
                "protocol_version": 1,
                "lease_generation": claim["lease_generation"],
                "lease_token": claim["lease_token"],
                "expected_messages_v": expected_messages_v + 1,
                "encrypted_assistant_message": encrypted_assistant_message,
            },
        )
        if terminal.get("state") != "TERMINAL":
            raise OpenMatesConfigError("Saved chat recovery did not reach terminal persistence")
        return ChatResponse(content=recovered["content"], raw={**data, "terminal": terminal})

    def _poll_recovery_claim(
        self,
        task_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        if not math.isfinite(timeout_seconds) or not math.isfinite(poll_interval_seconds) or timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise OpenMatesConfigError("Recovery timeout and poll interval must be finite and positive")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    break
                return self._client._post(
                    f"/v1/sdk/chats/recovery/{_quote(task_id)}/claim",
                    {"protocol_version": 1},
                    timeout=remaining_seconds,
                )
            except OpenMatesApiError as exc:
                if exc.status_code != 404:
                    raise
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            time.sleep(min(poll_interval_seconds, remaining_seconds))
        raise OpenMatesConfigError("Timed out waiting for saved chat recovery")

    @staticmethod
    def _open_recovery_claim(
        claim: dict[str, Any],
        *,
        recovery_private_key: str,
        owner_id: str,
        chat_id: str,
        turn_id: str,
    ) -> dict[str, Any]:
        job_id = claim.get("job_id")
        assistant_message_id = claim.get("assistant_message_id")
        key_version = claim.get("chat_key_version")
        if (
            claim.get("state") != "LEASED"
            or not isinstance(claim.get("lease_token"), str)
            or not isinstance(claim.get("lease_generation"), int)
            or not isinstance(job_id, str)
            or not isinstance(assistant_message_id, str)
            or key_version != 1
            or claim.get("chat_id") != chat_id
            or claim.get("turn_id") != turn_id
            or not isinstance(claim.get("sealed_payload"), str)
        ):
            raise OpenMatesConfigError("Recovery job claim returned invalid lease or identity data")
        try:
            envelope = json.loads(claim["sealed_payload"])
            plaintext = open_recovery_envelope(
                envelope,
                recovery_private_key=recovery_private_key,
                owner_id=owner_id,
                chat_id=chat_id,
                turn_id=turn_id,
                job_id=job_id,
                assistant_message_id=assistant_message_id,
                key_version=key_version,
            )
            recovered = json.loads(plaintext.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenMatesConfigError("Recovery job contained invalid encrypted terminal data") from exc
        expected_fields = {
            "assistant_message_id", "category", "chat_id", "content", "job_id", "key_version", "model_name", "turn_id"
        }
        if (
            not isinstance(recovered, dict)
            or set(recovered) != expected_fields
            or recovered.get("assistant_message_id") != assistant_message_id
            or recovered.get("chat_id") != chat_id
            or recovered.get("turn_id") != turn_id
            or recovered.get("job_id") != job_id
            or recovered.get("key_version") != key_version
            or not isinstance(recovered.get("content"), str)
            or (recovered.get("category") is not None and not isinstance(recovered.get("category"), str))
            or (recovered.get("model_name") is not None and not isinstance(recovered.get("model_name"), str))
        ):
            raise OpenMatesConfigError("Recovery job plaintext did not match the terminal completion identity")
        return recovered

    def export(self, chat_id: str, *, format: str | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/sdk/chats/{_quote(chat_id)}/export", {"format": format or "json", "payload": self.load(chat_id)})

    def delete(self, chat_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a chat")
        return self._client._delete(f"/v1/sdk/chats/{_quote(chat_id)}")

    def share(self, chat_id: str, *, expires: int | None = None, password: str | None = None) -> dict[str, Any]:
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else {}
        encrypted_chat_key = chat.get("encrypted_chat_key") if isinstance(chat, dict) else None
        if not isinstance(encrypted_chat_key, str):
            raise OpenMatesConfigError("Chat does not include an encrypted chat key")
        chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, self._client._get_master_key())
        if chat_key is None:
            raise OpenMatesConfigError("Unable to decrypt chat key for share link")
        blob = _generate_share_blob("chat", chat_id, chat_key, expires=expires, password=password)
        return {"url": f"{self._client._web_origin()}/share/chat/{chat_id}#key={blob}"}

    def follow_ups(self, chat_id: str) -> list[str]:
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else {}
        encrypted = chat.get("encrypted_follow_up_request_suggestions") if isinstance(chat, dict) else None
        if not isinstance(encrypted, str):
            return []
        raw = _decrypt_aes_gcm_text(encrypted, self._client._get_master_key())
        parsed = _parse_maybe_json(raw)
        return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []

    def incognito(self, message: str) -> ChatResponse:
        return self.send(message, save_to_account=False)


class OpenMatesIdeaBucket:
    """IdeaBucket SDK namespace using the existing OpenMates package."""

    def __init__(self, client: OpenMates):
        self._client = client

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        encrypted_payload = self._build_encrypted_add_payload(payload)
        bucket_id = str(encrypted_payload["ideabucket_processing_window_id"])
        return self._client._post(f"/v1/sdk/ideabucket/buckets/{_quote(bucket_id)}/add", encrypted_payload)

    def status(self, bucket_id: str | None = None) -> dict[str, Any]:
        if bucket_id:
            return self._client._get(f"/v1/sdk/ideabucket/buckets/{_quote(bucket_id)}")
        return self._client._get("/v1/sdk/ideabucket/buckets")

    def process(self, bucket_id: str, *, now: bool = False) -> dict[str, Any]:
        return self._client._post(
            f"/v1/sdk/ideabucket/buckets/{_quote(bucket_id)}/process",
            {"now": now is True},
        )

    def _build_encrypted_add_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        idea_text = str(payload.get("text") or "").strip()
        if not idea_text:
            raise OpenMatesConfigError("IdeaBucket add requires non-empty text")
        now = int(time.time())
        bucket_id = str(payload.get("bucket_id") or payload.get("bucketId") or datetime_utc_date(now))
        scheduled_send_at = int(payload.get("scheduled_send_at") or payload.get("scheduledSendAt") or default_ideabucket_scheduled_send_at(now))
        chat_id = str(payload.get("chat_id") or payload.get("chatId") or uuid.uuid4())
        prompt = str(payload.get("prompt") or IDEABUCKET_DEFAULT_PROCESSING_PROMPT)
        markdown = build_ideabucket_markdown(prompt, idea_text)
        preview = f"IdeaBucket {bucket_id}: {idea_text[:120]}"
        server_payload = json.dumps({
            "prompt": prompt,
            "bucket_id": bucket_id,
            "processing_window_id": bucket_id,
            "ideas": [{"index": 1, "type": "text", "text": idea_text}],
        }, separators=(",", ":"))
        payload_hash = hashlib.sha256(server_payload.encode("utf-8")).hexdigest()
        master_key = self._client._get_master_key()
        return {
            "chat_id": chat_id,
            "encrypted_draft_md": _encrypt_aes_gcm_text(markdown, master_key),
            "encrypted_draft_preview": _encrypt_aes_gcm_text(preview, master_key),
            "ideabucket": True,
            "ideabucket_processing_window_id": bucket_id,
            "ideabucket_processing_version": now,
            "scheduled_send_at": scheduled_send_at,
            "server_vault_encrypted_processing_payload": _encrypt_aes_gcm_text(server_payload, master_key),
            "client_encrypted_future_user_message": _encrypt_aes_gcm_text(markdown, master_key),
            "client_encrypted_ideabucket_system_event": _encrypt_aes_gcm_text(json.dumps({
                "type": "ideabucket_triggered_send",
                "bucket_id": bucket_id,
                "processing_window_id": bucket_id,
                "source": "openmates_pip_sdk",
            }, separators=(",", ":")), master_key),
            "payload_hash": payload_hash,
        }


class OpenMatesDrafts:
    """Read-only access to encrypted chat drafts."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list_encrypted(self) -> list[dict[str, Any]]:
        return [self._normalize(item) for item in self._client._get("/v1/sdk/drafts").get("drafts", [])]

    def list(self) -> list[dict[str, Any]]:
        return [self._decrypt(draft) for draft in self.list_encrypted()]

    def get_encrypted(self, chat_id: str) -> dict[str, Any] | None:
        draft = self._client._get(f"/v1/sdk/drafts/{_quote(chat_id)}").get("draft")
        return self._normalize(draft) if isinstance(draft, dict) else None

    def get(self, chat_id: str) -> dict[str, Any] | None:
        draft = self.get_encrypted(chat_id)
        return self._decrypt(draft) if draft else None

    def _decrypt(self, draft: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        markdown = _decrypt_aes_gcm_text(draft["encrypted_draft_md"], master_key)
        if markdown is None:
            raise OpenMatesConfigError("Unable to decrypt draft markdown")
        encrypted_preview = draft.get("encrypted_draft_preview")
        preview = _decrypt_aes_gcm_text(encrypted_preview, master_key) if isinstance(encrypted_preview, str) else markdown[:160]
        return {**draft, "markdown": markdown, "preview": preview}

    @staticmethod
    def _normalize(draft: dict[str, Any]) -> dict[str, Any]:
        return {
            "chat_id": str(draft.get("chat_id") or ""),
            "encrypted_draft_md": str(draft.get("encrypted_draft_md") or ""),
            "encrypted_draft_preview": draft.get("encrypted_draft_preview") if isinstance(draft.get("encrypted_draft_preview"), str) else None,
            "draft_v": int(draft.get("draft_v") or 0),
        }


class OpenMatesPlans:
    """Encrypted user plans SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        active_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._client._get(
            _with_query(
                "/v1/user-plans",
                status=status,
                chat_id=chat_id,
                project_id=project_id,
                active_only=active_only,
            )
        ).get("plans", [])

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post("/v1/user-plans", payload).get("plan", {})

    def update(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._patch(f"/v1/user-plans/{_quote(plan_id)}", payload).get("plan", {})

    def activate(self, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request_payload = payload or {}
        plan = self._client._post(f"/v1/user-plans/{_quote(plan_id)}/activate", request_payload).get("plan", {})
        if "primary_chat_id" not in plan and isinstance(request_payload.get("chat_id"), str):
            plan = {**plan, "primary_chat_id": request_payload["chat_id"]}
        return plan

    def complete(self, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(plan_id)}/complete", payload or {}).get("plan", {})

    def create_criterion(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(plan_id)}/criteria", payload).get("criterion", {})

    def list_criteria(self, plan_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/user-plans/{_quote(plan_id)}/criteria").get("criteria", [])

    def create_verification(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(plan_id)}/verification", payload).get("verification", {})

    def list_verifications(self, plan_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/user-plans/{_quote(plan_id)}/verification").get("verifications", [])

    def create_assumption(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(plan_id)}/assumptions", payload).get("assumption", {})

    def list_assumptions(self, plan_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/user-plans/{_quote(plan_id)}/assumptions").get("assumptions", [])

    def update_assumption(self, plan_id: str, assumption_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._patch(f"/v1/user-plans/{_quote(plan_id)}/assumptions/{_quote(assumption_id)}", payload).get("assumption", {})

    def create_reference_pattern(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(plan_id)}/reference-patterns", payload).get("reference_pattern", {})

    def list_reference_patterns(self, plan_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/user-plans/{_quote(plan_id)}/reference-patterns").get("reference_patterns", [])

    def add_verification_evidence(self, plan_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(
            f"/v1/user-plans/{_quote(plan_id)}/verification/{_quote(verification_id)}/evidence",
            payload,
        ).get("verification", {})


class OpenMatesTasks:
    """Encrypted user tasks SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        priority: str | int | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_decrypted(status=status, chat_id=chat_id, project_id=project_id, labels=labels, tags=tags, priority=priority)

    def _list_raw(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        priority: str | int | None = None,
    ) -> list[dict[str, Any]]:
        label_values = labels if labels is not None else tags
        label_hashes = _task_label_hashes(self._client._get_master_key(), _normalize_task_labels(label_values)) if label_values else None
        return self._client._get(
            _with_query(
                "/v1/user-tasks",
                status=status,
                chat_id=chat_id,
                project_id=project_id,
                label_hash=label_hashes,
                priority=_normalize_task_priority(priority),
            )
        ).get("tasks", [])

    def list_decrypted(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        priority: str | int | None = None,
    ) -> list[dict[str, Any]]:
        return [
            _public_task(task)
            for task in self._list_internal(status=status, chat_id=chat_id, project_id=project_id, labels=labels, tags=tags, priority=priority)
        ]

    def show(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return _public_task(self._resolve(task_id, filters))

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        created = self._create_raw(_build_task_create_input(master_key, payload))
        return _public_task(_decrypt_task_record(created, master_key))

    def _create_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post("/v1/user-tasks", payload).get("task", {})

    def update(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.edit(task_id, payload)

    def _update_raw(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._patch(f"/v1/user-tasks/{_quote(task_id)}", payload).get("task", {})

    def edit(self, task_id: str, payload: dict[str, Any], **filters: Any) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        master_key = self._client._get_master_key()
        for attempt in range(2):
            try:
                updated = self._update_raw(str(task["task_id"]), _build_task_update_input(task, master_key, payload))
                return _public_task(_decrypt_task_record(updated, master_key))
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task update retry failed unexpectedly")

    def start_ai(self, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.start(task_id)

    def _start_ai_raw(self, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/user-tasks/{_quote(task_id)}/start-ai", payload or {}).get("task", {})

    def start(self, task_id: str, **filters: Any) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        for attempt in range(2):
            try:
                started = self._start_ai_raw(str(task["task_id"]), {
                    "version": task["version"],
                    "primary_chat_id": task.get("primary_chat_id") or None,
                    "linked_project_ids": task.get("linked_project_ids") or [],
                    "plaintext_title": task.get("title") or "",
                    "plaintext_description": task.get("description") or "",
                    "plaintext_latest_instruction": task.get("latest_instruction") or "",
                })
                return _public_task(_decrypt_task_record(started, self._client._get_master_key()))
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task start retry failed unexpectedly")

    def delete(self, task_id: str, *, confirmed: bool = False, **filters: Any) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a task")
        task = self._resolve(task_id, filters)
        for attempt in range(2):
            try:
                return self._client._delete(f"/v1/user-tasks/{_quote(str(task['task_id']))}?version={_quote(str(task['version']))}")
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task delete retry failed unexpectedly")

    def delete_by_id(self, task_id: str, *, confirmed: bool = False, **filters: Any) -> dict[str, Any]:
        return self.delete(task_id, confirmed=confirmed, **filters)

    def complete(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return self.done(task_id, **filters)

    def done(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return self._action_by_id(task_id, "complete", {}, filters)

    def block(self, task_id: str, reason: str, **filters: Any) -> dict[str, Any]:
        return self._action_by_id(task_id, "block", {"blocked_reason_code": reason}, filters)

    def unblock(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return self._action_by_id(task_id, "unblock", {}, filters)

    def skip(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return self._action_by_id(task_id, "skip", {}, filters)

    def reorder(self, task_id: str, move: dict[str, Any], **filters: Any) -> list[dict[str, Any]]:
        return self.move(task_id, move, **filters)

    def move(self, task_id: str, move: dict[str, Any], **filters: Any) -> list[dict[str, Any]]:
        task = self._resolve(task_id, filters)
        for attempt in range(2):
            try:
                updated = self._client._post("/v1/user-tasks/reorder", {"moves": [{**move, "task_id": task["task_id"], "version": task["version"]}]}).get("tasks", [])
                master_key = self._client._get_master_key()
                return [_public_task(_decrypt_task_record(record, master_key)) for record in updated if isinstance(record, dict)]
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task reorder retry failed unexpectedly")

    def _action_raw(self, task_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-tasks/{_quote(task_id)}/{_quote(action)}", payload).get("task", {})

    def _action_by_id(self, task_id: str, action: str, patch: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        for attempt in range(2):
            try:
                updated = self._action_raw(str(task["task_id"]), action, {"version": task["version"], **patch})
                return _public_task(_decrypt_task_record(updated, self._client._get_master_key()))
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task action retry failed unexpectedly")

    def _list_internal(self, **filters: Any) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        return [
            _decrypt_task_record(task, master_key)
            for task in self._list_raw(**filters)
            if isinstance(task, dict)
        ]

    def _resolve(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return _find_task(self._list_internal(**filters), task_id)


class OpenMatesProjects:
    """Encrypted Project source SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/projects/{_quote(project_id)}/sources").get("sources", [])

    def create_source(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/projects/{_quote(project_id)}/sources", payload).get("source", {})


class OpenMatesWorkflows:
    """Server-side workflow SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self) -> list[dict[str, Any]]:
        return self._client._get("/v1/workflows").get("workflows", [])

    def temporary(self) -> list[dict[str, Any]]:
        return self._client._get("/v1/workflows/temporary").get("workflows", [])

    def capabilities(self) -> list[dict[str, Any]]:
        return self._client._get("/v1/workflows/capabilities").get("capabilities", [])

    def validate_yaml(self, source: str) -> dict[str, Any]:
        validation = self._client._post("/v1/workflows/validate", {"source": source}).get("validation")
        if not isinstance(validation, dict):
            raise OpenMatesApiError(500, {"detail": "Workflow validation response missing validation"})
        return validation

    def create_from_yaml(self, source: str) -> dict[str, Any]:
        response = self._client._post("/v1/workflows/yaml", {"source": source})
        if not isinstance(response.get("workflow"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing workflow"})
        if not isinstance(response.get("validation"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing validation"})
        return response

    def update_from_yaml(self, workflow_id: str, source: str) -> dict[str, Any]:
        response = self._client._post(f"/v1/workflows/{_quote(workflow_id)}/yaml", {"source": source})
        if not isinstance(response.get("workflow"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing workflow"})
        if not isinstance(response.get("validation"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing validation"})
        return response

    def start_input(
        self,
        *,
        text: str | None = None,
        input_type: str = "text",
        audio_ref: dict[str, Any] | None = None,
        selected_workflow_id: str | None = None,
        selected_project_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "input_type": input_type,
        }
        if text is not None:
            payload["text"] = text
        if audio_ref is not None:
            payload["audio_ref"] = audio_ref
        if selected_workflow_id is not None:
            payload["selected_workflow_id"] = selected_workflow_id
        if selected_project_id is not None:
            payload["selected_project_id"] = selected_project_id
        return self._client._post("/v1/workflows/input", payload).get("session", {})

    def input_session(self, session_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/workflows/input/{_quote(session_id)}").get("session", {})

    def input_events(self, session_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        return self._client._get(
            _with_query(
                f"/v1/workflows/input/{_quote(session_id)}/events",
                after_event_id=after_event_id,
            )
        ).get("events", [])

    def follow_up_input(self, session_id: str, text: str) -> dict[str, Any]:
        return self._client._post(
            f"/v1/workflows/input/{_quote(session_id)}/follow-up",
            {"text": text},
        ).get("session", {})

    def stop_input(self, session_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workflows/input/{_quote(session_id)}/stop", {}).get("session", {})

    def undo_input(self, session_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workflows/input/{_quote(session_id)}/undo", {}).get("session", {})

    def get(self, workflow_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/workflows/{_quote(workflow_id)}").get("workflow", {})

    def create(
        self,
        *,
        title: str,
        description: str | None = None,
        graph: dict[str, Any],
        enabled: bool = False,
        run_content_retention: str = "last_5",
        lifecycle: str = "persisted",
        source: str = "manual",
        source_chat_id: str | None = None,
        created_by_assistant: bool = False,
        auto_delete_at: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "title": title,
            "graph": graph,
            "enabled": enabled,
            "run_content_retention": run_content_retention,
            "lifecycle": lifecycle,
            "source": source,
            "created_by_assistant": created_by_assistant,
        }
        if description is not None:
            payload["description"] = description
        if source_chat_id is not None:
            payload["source_chat_id"] = source_chat_id
        if auto_delete_at is not None:
            payload["auto_delete_at"] = auto_delete_at
        return self._client._post(
            "/v1/workflows",
            payload,
        ).get("workflow", {})

    def update(
        self,
        workflow_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        graph: dict[str, Any] | None = None,
        enabled: bool | None = None,
        run_content_retention: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in {
                "title": title,
                "description": description,
                "graph": graph,
                "enabled": enabled,
                "run_content_retention": run_content_retention,
            }.items()
            if value is not None
        }
        return self._client._patch(f"/v1/workflows/{_quote(workflow_id)}", payload).get("workflow", {})

    def enable(self, workflow_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workflows/{_quote(workflow_id)}/enable", {}).get("workflow", {})

    def disable(self, workflow_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workflows/{_quote(workflow_id)}/disable", {}).get("workflow", {})

    def delete(self, workflow_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a workflow")
        return self._client._delete(f"/v1/workflows/{_quote(workflow_id)}")

    def keep(self, workflow_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workflows/{_quote(workflow_id)}/keep", {}).get("workflow", {})

    def run(
        self,
        workflow_id: str,
        *,
        idempotency_key: str,
        mode: str = "manual",
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise OpenMatesConfigError("Workflow run requires a stable idempotency_key")
        return self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/run",
            {"mode": mode, "input": input_data or {}},
            extra_headers={"Idempotency-Key": idempotency_key},
        ).get("run", {})

    def runs(self, workflow_id: str) -> list[dict[str, Any]]:
        return self._client._get(f"/v1/workflows/{_quote(workflow_id)}/runs").get("runs", [])

    def run_detail(self, workflow_id: str, run_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/workflows/{_quote(workflow_id)}/runs/{_quote(run_id)}").get("run", {})

    def step_test(
        self,
        workflow_id: str,
        step_id: str,
        *,
        input_data: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        response = self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/steps/{_quote(step_id)}/test",
            {"input": input_data or {}, "confirmed": confirmed},
        )
        run = response.get("run")
        if not isinstance(run, dict):
            raise OpenMatesApiError(500, {"detail": "Workflow response missing run"})
        return run

    def cancel_run(self, workflow_id: str, run_id: str) -> dict[str, Any]:
        result = self._client._post(f"/v1/workflows/{_quote(workflow_id)}/runs/{_quote(run_id)}/cancel", {})
        if result.get("status") not in {"cancellation_requested", "cancelled"}:
            raise OpenMatesApiError(500, {"detail": "Workflow response has invalid cancellation status"})
        return result

    def respond(self, workflow_id: str, run_id: str, step_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        response = self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/runs/{_quote(run_id)}/respond",
            {"step_id": step_id, "input": input_data},
        )
        run = response.get("run")
        if not isinstance(run, dict):
            raise OpenMatesApiError(500, {"detail": "Workflow response missing run"})
        return run

    def upsert_template_projection(
        self,
        workflow_id: str,
        *,
        template_id: str,
        source_version: int,
        ciphertext: str,
        ciphertext_checksum: str,
        owner_wrapped_key: str,
        projection_schema_version: int,
    ) -> dict[str, Any]:
        return self._client._put(
            f"/v1/workflows/{_quote(workflow_id)}/template-projection",
            {
                "template_id": template_id,
                "source_version": source_version,
                "ciphertext": ciphertext,
                "ciphertext_checksum": ciphertext_checksum,
                "owner_wrapped_key": owner_wrapped_key,
                "projection_schema_version": projection_schema_version,
            },
        )

    def get_public_template_projection(self, template_id: str) -> dict[str, Any]:
        return self._client._get_public(f"/v1/workflows/template-projections/{_quote(template_id)}")

    def revoke_template_projection(self, workflow_id: str) -> dict[str, Any]:
        return self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/template-projection/revoke",
            {},
        )

    def unrevoke_template_projection(self, workflow_id: str) -> dict[str, Any]:
        return self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/template-projection/unrevoke",
            {},
        )

    def complete_imported_binding(
        self,
        workflow_id: str,
        *,
        binding_type: str,
        node_id: str,
    ) -> dict[str, Any]:
        return self._client._post(
            f"/v1/workflows/{_quote(workflow_id)}/binding-requirements/complete",
            {"type": binding_type, "node_id": node_id},
        )

    def create_template_short_url(
        self,
        *,
        token: str,
        encrypted_url: str,
        template_id: str,
        ttl_seconds: int | None = None,
        password_protected: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "token": token,
            "encrypted_url": encrypted_url,
            "content_type": "workflow_template",
            "content_id": template_id,
            "password_protected": password_protected,
        }
        if ttl_seconds is not None:
            payload["ttl_seconds"] = ttl_seconds
        return self._client._post("/v1/share/short-url", payload)

    def revoke_short_url(self, token: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/share/short-url/{_quote(token)}")

    def import_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client._post("/v1/workflows/template-import", payload)
        workflow = response.get("workflow")
        if not isinstance(workflow, dict):
            raise OpenMatesApiError(500, {"detail": "Workflow template import response missing workflow"})
        return workflow


class OpenMatesAccount:
    """Account SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def info(self) -> dict[str, Any]:
        return self._client._get("/v1/sdk/account")

    def set_timezone(self, timezone: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/account/timezone", {"timezone": timezone})

    def list_interests(self) -> dict[str, Any]:
        data = self._client._get("/v1/sdk/account/topic-preferences")
        encrypted = data.get("encrypted_settings")
        if not isinstance(encrypted, str):
            return {"selected_tag_ids": []}
        raw = _decrypt_aes_gcm_text(encrypted, self._client._get_master_key())
        parsed = _parse_maybe_json(raw)
        selected = parsed.get("selected_tag_ids") if isinstance(parsed, dict) else []
        return {"selected_tag_ids": [item for item in selected if isinstance(item, str)] if isinstance(selected, list) else []}

    def set_interests(self, selected_tag_ids: list[str]) -> dict[str, Any]:
        encrypted_settings = _encrypt_aes_gcm_text(
            json.dumps({"selected_tag_ids": selected_tag_ids}),
            self._client._get_master_key(),
        )
        return self._client._post("/v1/sdk/account/topic-preferences", {"encrypted_settings": encrypted_settings})

    def clear_interests(self) -> dict[str, Any]:
        return self.set_interests([])

    def start_export(
        self,
        *,
        domains: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        format: str = "zip",
        include_advanced_metadata: bool = False,
    ) -> dict[str, Any]:
        return self._client._post(
            "/v1/account-exports",
            {
                "domains": domains,
                "filters": filters or {},
                "format": format,
                "include_advanced_metadata": include_advanced_metadata,
            },
        )

    def get_export(self, export_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/account-exports/{quote(export_id, safe='')}")

    def export_job_manifest(self, export_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/account-exports/{quote(export_id, safe='')}/manifest")

    def export_chunks(self, export_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/account-exports/{quote(export_id, safe='')}/chunks")

    def export_chunk(self, export_id: str, chunk_id: str) -> dict[str, Any]:
        chunk = self._client._get(
            f"/v1/account-exports/{quote(export_id, safe='')}/chunks/{quote(chunk_id, safe='')}"
        ).get("chunk", {})
        _assert_account_export_payload_safe(chunk)
        return chunk

    def iter_export_chunks(self, export_id: str):
        listed = self.export_chunks(export_id)
        for chunk in listed.get("chunks", []):
            chunk_id = chunk.get("chunk_id") if isinstance(chunk, dict) else None
            yield self.export_chunk(export_id, str(chunk_id)) if chunk_id else chunk

    def complete_export(self, export_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/account-exports/{quote(export_id, safe='')}/complete", {})

    def accept_partial_export(self, export_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/account-exports/{quote(export_id, safe='')}/accept-partial", {})

    def cancel_export(self, export_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/account-exports/{quote(export_id, safe='')}/cancel", {})

    def download_export(self, **options: Any) -> dict[str, Any]:
        accept_partial = options.pop("accept_partial", False)
        started = self.start_export(**options)
        export_id = str(started.get("export", {}).get("export_id", ""))
        manifest = self.export_job_manifest(export_id)
        chunks = self.export_chunks(export_id)
        downloaded_chunks: list[dict[str, Any]] = []
        try:
            for chunk in chunks.get("chunks", []):
                chunk_id = chunk.get("chunk_id") if isinstance(chunk, dict) else None
                downloaded_chunks.append(self.export_chunk(export_id, str(chunk_id)) if chunk_id else chunk)
        except Exception:
            try:
                self.cancel_export(export_id)
            finally:
                raise
        completed = self.complete_export(export_id)
        status = str(completed.get("export", {}).get("status", ""))
        if status == "partial":
            if accept_partial is not True:
                raise OpenMatesConfigError(f"Account export {export_id} is partial. Pass accept_partial=True to accept it explicitly.")
            completed = self.accept_partial_export(export_id)
        return {
            "export": completed.get("export", {}),
            "manifest": _sanitize_account_export_manifest(manifest.get("manifest", {})),
            "chunks": downloaded_chunks,
        }

    def parse_claude_import(self, payload: bytes | str, source_name: str = "claude-export") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            if raw[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:  # type: ignore[name-defined]
                    conversations = json.loads(archive.read("conversations.json").decode("utf-8"))
            else:
                conversations = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise OpenMatesConfigError(f"Claude export could not be parsed: {exc}") from exc
        if isinstance(conversations, dict) and isinstance(conversations.get("conversations"), list):
            conversations = conversations["conversations"]
        if not isinstance(conversations, list):
            raise OpenMatesConfigError("Claude export conversations must be an array")
        chats: list[dict[str, Any]] = []
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            source_chat_id = str(conversation.get("uuid") or "")
            if not source_chat_id:
                raise OpenMatesConfigError("Claude conversation is missing uuid")
            messages: list[dict[str, Any]] = []
            for raw_message in conversation.get("chat_messages") if isinstance(conversation.get("chat_messages"), list) else []:
                if not isinstance(raw_message, dict):
                    continue
                content, block_types = _claude_message_content(raw_message)
                sender = str(raw_message.get("sender") or "")
                messages.append({
                    "role": "user" if sender == "human" else "assistant" if sender == "assistant" else "system",
                    "content": content,
                    "created_at": raw_message.get("created_at") if isinstance(raw_message.get("created_at"), str) else None,
                    "source_message_id": raw_message.get("uuid") if isinstance(raw_message.get("uuid"), str) else None,
                    "provider_metadata": {"content_block_types": block_types},
                })
            chats.append({
                "provider": "claude",
                "source_chat_id": source_chat_id,
                "source_fingerprint": _account_import_fingerprint("claude", source_chat_id, messages),
                "title": conversation.get("name") if isinstance(conversation.get("name"), str) else None,
                "created_at": conversation.get("created_at") if isinstance(conversation.get("created_at"), str) else None,
                "updated_at": conversation.get("updated_at") if isinstance(conversation.get("updated_at"), str) else None,
                "messages": messages,
                "embeds": [],
                "uploads": [],
                "provider_labels": ["claude"],
                "source_metadata": {"source_name": source_name, "message_count": len(messages)},
            })
        return {"source": "claude", "chats": chats, "skipped_domains": []}

    def parse_openmates_import(self, payload: bytes | str, source_name: str = "openmates-export.zip") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:  # type: ignore[name-defined]
                manifest = archive.read("manifest.yml").decode("utf-8")
                if not re.search(r"format:\s*openmates-account-export", manifest) or not re.search(r"version:\s*[\"']?1[\"']?", manifest):
                    raise OpenMatesConfigError("Unsupported OpenMates Export V1 archive format or version")
                domains = _parse_openmates_manifest_domains(manifest)
                chat_files = [name for name in archive.namelist() if name.startswith("chats/") and re.search(r"\.ya?ml$", name)]
        except OpenMatesConfigError:
            raise
        except Exception as exc:
            raise OpenMatesConfigError(f"OpenMates import archive could not be parsed: {exc}") from exc
        chats = []
        for name in chat_files:
            source_chat_id = Path(name).name.removesuffix(".yaml").removesuffix(".yml")
            messages: list[dict[str, Any]] = []
            chats.append({
                "provider": "openmates",
                "source_chat_id": source_chat_id,
                "source_fingerprint": _account_import_fingerprint("openmates", source_chat_id, messages),
                "title": source_chat_id,
                "created_at": None,
                "updated_at": None,
                "messages": messages,
                "embeds": [],
                "uploads": [],
                "provider_labels": ["openmates"],
                "source_metadata": {"source_name": source_name, "archive_path": name},
            })
        if not chats:
            raise OpenMatesConfigError("OpenMates Export V1 archive contains no chat YAML files")
        skipped = sorted(domain for domain in domains if domain not in {"chats", "embeds", "uploads", "referenced_uploads"})
        return {"source": "openmates", "chats": chats, "skipped_domains": skipped}

    def preview_import(self, *, source: str, chats: list[dict[str, Any]] | None = None, chat_count: int | None = None, source_fingerprints: list[str] | None = None, estimated_tokens: int = 0, estimated_bytes: int = 0) -> dict[str, Any]:
        selected_chats = chats or []
        return self._client._post("/v1/account-imports/preview", {
            "source": source,
            "chat_count": chat_count if chat_count is not None else len(selected_chats),
            "source_fingerprints": source_fingerprints if source_fingerprints is not None else [str(chat.get("source_fingerprint") or "") for chat in selected_chats],
            "estimated_tokens": estimated_tokens,
            "estimated_bytes": estimated_bytes,
        })

    def scan_import(self, import_id: str, chats: list[dict[str, Any]]) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/scan", {"chats": chats})

    def persist_encrypted_import(self, import_id: str, chats: list[dict[str, Any]]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        encrypted_chats = []
        for chat in chats:
            chat_id = str(uuid.uuid4())
            chat_key = os.urandom(32)
            messages = []
            previous_user_message_id: str | None = None
            for message in chat.get("messages", []) if isinstance(chat.get("messages"), list) else []:
                if not isinstance(message, dict):
                    continue
                message_id = str(uuid.uuid4())
                role = str(message.get("role") or "user")
                row = {
                    "message_id": message_id,
                    "role": role,
                    "encrypted_content": _encrypt_aes_gcm_text(str(message.get("content") or ""), chat_key),
                    "encrypted_sender_name": _encrypt_aes_gcm_text("Assistant" if role == "assistant" else "System" if role == "system" else "User", chat_key),
                    "created_at": _parse_import_timestamp(message.get("created_at")),
                    "updated_at": int(time.time()),
                }
                if role == "assistant" and previous_user_message_id:
                    row["user_message_id"] = previous_user_message_id
                if role == "user":
                    previous_user_message_id = message_id
                messages.append(row)
            encrypted_chats.append({
                "chat_id": chat_id,
                "encrypted_title": _encrypt_aes_gcm_text(str(chat.get("title") or "Imported chat"), chat_key),
                "encrypted_chat_key": _encrypt_aes_gcm_bytes(chat_key, master_key),
                "created_at": _parse_import_timestamp(chat.get("created_at")),
                "updated_at": _parse_import_timestamp(chat.get("updated_at")),
                "source_fingerprint": str(chat.get("source_fingerprint") or ""),
                "messages": messages,
            })
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/persist-encrypted", {"chats": encrypted_chats})

    def complete_import(self, import_id: str, *, imported_chat_ids: list[str], source_fingerprints: list[str], encrypted_record_counts: dict[str, int], client_failures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/complete", {
            "imported_chat_ids": imported_chat_ids,
            "source_fingerprints": source_fingerprints,
            "encrypted_record_counts": encrypted_record_counts,
            "client_failures": client_failures or [],
        })

    def import_chats(self, parsed: dict[str, Any], *, select: str = "default") -> dict[str, Any]:
        chats = parsed.get("chats") if isinstance(parsed.get("chats"), list) else []
        preview = self.preview_import(source=str(parsed.get("source") or ""), chats=chats)
        if preview.get("can_import") is False:
            raise OpenMatesConfigError(f"Account import blocked: {preview.get('reason') or 'unknown'}")
        default_count = int(preview.get("default_selection_count") or 0)
        max_count = int(preview.get("max_batch_count") or default_count)
        selected_count = min(len(chats), max_count) if select == "all" else min(default_count, len(chats), max_count)
        if selected_count <= 0:
            raise OpenMatesConfigError("No chats are selected for import.")
        import_id = str(preview.get("import_id") or uuid.uuid4())
        selected_chats = chats[:selected_count]
        scan = self.scan_import(import_id, selected_chats)
        sanitized_chats = scan.get("chats") if isinstance(scan.get("chats"), list) and scan.get("chats") else selected_chats
        persistence = self.persist_encrypted_import(import_id, sanitized_chats)
        complete = self.complete_import(
            import_id,
            imported_chat_ids=[str(item) for item in persistence.get("imported_chat_ids", [])] if isinstance(persistence.get("imported_chat_ids"), list) else [],
            source_fingerprints=[str(chat.get("source_fingerprint") or "") for chat in sanitized_chats],
            encrypted_record_counts=persistence.get("encrypted_record_counts") if isinstance(persistence.get("encrypted_record_counts"), dict) else {"chats": 0, "messages": 0},
            client_failures=persistence.get("failures") if isinstance(persistence.get("failures"), list) else [],
        )
        return {"source": parsed.get("source"), "parsed": parsed, "preview": preview, "import_id": import_id, "scan": scan, "persistence": persistence, "complete": complete}

    def export_manifest(self) -> dict[str, Any]:
        return self._client._get("/v1/sdk/account/export/manifest")

    def export_data(self) -> dict[str, Any]:
        return self._client._get("/v1/sdk/account/export/data")

    def set_username(self, username: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/account/username", {"username": username})

    def storage_overview(self) -> dict[str, Any]:
        return self._client._get("/v1/sdk/account/storage")

    def storage_files(self, **query: Any) -> dict[str, Any]:
        return self._client._get(_with_query("/v1/sdk/account/storage/files", **query))

    def delete_storage(self, *, confirmed: bool = False, **payload: Any) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting stored account files")
        return self._client._delete("/v1/sdk/account/storage/files", payload)


class OpenMatesSettings:
    """Settings SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def set_language(self, language: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/settings/language", {"language": language})

    def set_dark_mode(self, enabled: bool) -> dict[str, Any]:
        return self._client._post("/v1/sdk/settings/dark-mode", {"enabled": enabled})

    def set_font(self, font: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/settings/font", {"font": font})

    def set_model_defaults(self, defaults: dict[str, Any]) -> dict[str, Any]:
        return self._client._post("/v1/sdk/settings/ai-model-defaults", defaults)

    def set_chat_auto_delete(self, period: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/settings/auto-delete/chats", {"period": period})

    def share_debug_logs(self, *, confirmed: bool = False, duration: str = "1h") -> dict[str, Any]:
        _require_confirmed(confirmed, "Sharing debug logs")
        return _unsupported_sdk_feature("Debug-log sharing")


class OpenMatesApiKeys:
    """Developer API-key management SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self) -> dict[str, Any]:
        data = self._client._get("/v1/sdk/settings/api-keys")
        master_key = self._client._get_master_key()
        return {"api_keys": [self._decrypt_record(key, master_key) for key in data.get("api_keys", []) if isinstance(key, dict)]}

    def create(
        self,
        name: str,
        *,
        full_access: bool = True,
        scopes: dict[str, Any] | None = None,
        credit_limit: dict[str, Any] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise OpenMatesConfigError("API key name is required")
        master_key = self._client._get_master_key()
        api_key, material = _create_api_key_material(clean_name, master_key)
        record = self._client._post("/v1/sdk/settings/api-keys", {
            **material,
            "full_access": full_access,
            "scopes": scopes or {},
            "credit_limit": credit_limit,
            "expires_at": expires_at,
        })
        return {"api_key": api_key, "key": self._decrypt_record(record, master_key)}

    def revoke(self, key_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/sdk/settings/api-keys/{quote(key_id, safe='')}")

    def _decrypt_record(self, record: dict[str, Any], master_key: bytes) -> dict[str, Any]:
        encrypted_name = record.get("encrypted_name") if isinstance(record.get("encrypted_name"), str) else ""
        encrypted_prefix = record.get("encrypted_key_prefix") if isinstance(record.get("encrypted_key_prefix"), str) else ""
        last_used_at = record.get("last_used_at") if isinstance(record.get("last_used_at"), str) else None
        return {
            "id": str(record.get("id") or ""),
            "name": (_decrypt_aes_gcm_text(encrypted_name, master_key) if encrypted_name else None) or encrypted_name or "Unnamed API key",
            "key_prefix": (_decrypt_aes_gcm_text(encrypted_prefix, master_key) if encrypted_prefix else None) or encrypted_prefix or "sk-api-...",
            "created_at": record.get("created_at") if isinstance(record.get("created_at"), str) else None,
            "expires_at": record.get("expires_at") if isinstance(record.get("expires_at"), str) else None,
            "last_used_at": last_used_at,
            "last_used_label": last_used_at or "Never used",
            "full_access": record.get("full_access") if isinstance(record.get("full_access"), bool) else True,
            "scopes": record.get("scopes") if isinstance(record.get("scopes"), dict) else {},
            "credit_limit": record.get("credit_limit") if isinstance(record.get("credit_limit"), dict) else None,
            "pending_device_count": record.get("pending_device_count") if isinstance(record.get("pending_device_count"), int) else 0,
        }


class OpenMatesMemories:
    """Encrypted memories SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, **query: Any) -> dict[str, Any]:
        data = self._client._get(_with_query("/v1/sdk/memories", **query))
        memories = []
        for memory in data.get("memories", []):
            if not isinstance(memory, dict):
                continue
            decrypted = dict(memory)
            encrypted_item_json = memory.get("encrypted_item_json")
            if isinstance(encrypted_item_json, str):
                raw = _decrypt_aes_gcm_text(encrypted_item_json, self._client._get_master_key())
                decrypted["data"] = _parse_maybe_json(raw)
            memories.append(decrypted)
        return {"memories": memories}

    def types(self, **query: Any) -> dict[str, Any]:
        return self._client._get(_with_query("/v1/sdk/memories/types", **query))

    def create(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._store_memory(input_data)

    def update(self, memory_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._store_memory({**input_data, "id": memory_id})

    def delete(self, memory_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a memory")
        return self._client._delete(f"/v1/sdk/memories/{_quote(memory_id)}")

    def _store_memory(self, input_data: dict[str, Any]) -> dict[str, Any]:
        app_id = str(input_data.get("appId") or input_data.get("app_id") or "")
        item_type = str(input_data.get("itemType") or input_data.get("item_type") or "")
        raw_item_value = input_data.get("itemValue") or input_data.get("item_value") or input_data.get("data") or {}
        item_value = raw_item_value if isinstance(raw_item_value, dict) else {"value": raw_item_value}
        if not app_id or not item_type:
            raise OpenMatesConfigError("Memory create/update requires appId and itemType")
        now = int(time.time())
        entry = {
            "id": str(input_data.get("id") or uuid.uuid4()),
            "app_id": app_id,
            "item_key": _hash_item_key(app_id, item_type),
            "item_type": item_type,
            "encrypted_item_json": _encrypt_aes_gcm_text(json.dumps({**item_value, "settings_group": app_id, "_original_item_key": item_type, "added_date": now}), self._client._get_master_key()),
            "encrypted_app_key": "",
            "created_at": int(input_data.get("created_at") or now),
            "updated_at": now,
            "item_version": int(input_data.get("itemVersion") or input_data.get("item_version") or 1),
        }
        return self._client._post("/v1/sdk/memories", {"entry": entry})


class OpenMatesBilling:
    """Billing-safe SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def overview(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing")
    def usage(self, **query: Any) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/billing/usage", **query))
    def usage_summaries(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/summaries")
    def usage_daily(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/daily")
    def usage_export(self, *, months: int | None = None) -> dict[str, Any]: return self._client._get_raw(_with_query("/v1/sdk/billing/usage/export", months=months))
    def create_bank_transfer_order(self, credits: int, *, email_encryption_key: str | None = None) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/bank-transfer-orders", {"credits_amount": credits, "currency": "eur", "email_encryption_key": email_encryption_key})
    def bank_transfer_status(self, order_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/billing/bank-transfer-orders/{_quote(order_id)}")
    def list_bank_transfer_orders(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/bank-transfer-orders")
    def list_invoices(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/invoices")
    def download_invoice(self, invoice_id: str) -> dict[str, Any]: return self._client._get_raw(f"/v1/sdk/billing/invoices/{_quote(invoice_id)}/download")
    def download_credit_note(self, invoice_id: str) -> dict[str, Any]: return self._client._get_raw(f"/v1/sdk/billing/invoices/{_quote(invoice_id)}/credit-note/download")
    def request_refund(self, invoice_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Requesting an invoice refund")
        return self._client._post("/v1/sdk/billing/refund", {"invoice_id": invoice_id})
    def redeem_gift_card(self, code: str) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/gift-cards/redeem", {"code": code})
    def list_redeemed_gift_cards(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/gift-cards/redeemed")
    def create_gift_card_bank_transfer_order(self, credits: int, *, email_encryption_key: str | None = None) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/gift-cards/bank-transfer-orders", {"credits_amount": credits, "currency": "eur", "email_encryption_key": email_encryption_key})
    def gift_card_purchase_status(self, order_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/billing/gift-cards/purchases/{_quote(order_id)}")
    def list_purchased_gift_cards(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/gift-cards/purchased")
    def set_low_balance_auto_topup(self, input_data: dict[str, Any]) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/auto-topup/low-balance", input_data)


class OpenMatesDesign:
    """Design SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def export_icon(
        self,
        *,
        svg_path: str | None = None,
        prefix: str | None = None,
        name: str | None = None,
        output_path: str | os.PathLike[str] | None = None,
        format: str | None = None,
        color: str | None = None,
        palette: bool = False,
        allow_palette_recolor: bool = False,
        size: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        resolved_svg_path = _resolve_design_icon_svg_path(svg_path=svg_path, prefix=prefix, name=name)
        export_format = (format or ("png" if output_path and Path(output_path).suffix.lower() == ".png" else "svg")).lower()
        if export_format not in {"svg", "png"}:
            raise OpenMatesConfigError("format must be 'svg' or 'png'")
        normalized_color = _normalize_design_icon_color(color)
        if normalized_color and palette and not allow_palette_recolor:
            raise OpenMatesConfigError("Palette icons cannot be recolored unless allow_palette_recolor=True")

        raw = self._client._get_raw(resolved_svg_path)
        svg = _apply_design_icon_color(raw["data"].decode("utf-8"), normalized_color)
        data = svg.encode("utf-8") if export_format == "svg" else _render_design_icon_png(svg, size=size, width=width, height=height)
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {
            "format": export_format,
            "content_type": "image/svg+xml" if export_format == "svg" else "image/png",
            "data": data,
            "svg": svg,
            "svg_path": resolved_svg_path,
            "output_path": str(output_path) if output_path is not None else None,
        }


class OpenMatesNotifications:
    def __init__(self, client: OpenMates): self._client = client
    def status(self) -> dict[str, Any]: return self._client._get("/v1/sdk/notifications/status")
    def list(self, *, limit: int | None = None) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/notifications", limit=limit))


class OpenMatesReminders:
    def __init__(self, client: OpenMates): self._client = client
    def list(self) -> dict[str, Any]: return self._client._get("/v1/sdk/reminders")
    def update(self, reminder_id: str, input_data: dict[str, Any]) -> dict[str, Any]: return self._client._patch(f"/v1/sdk/reminders/{_quote(reminder_id)}", input_data)
    def delete(self, reminder_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a reminder")
        return self._client._delete(f"/v1/sdk/reminders/{_quote(reminder_id)}")


class OpenMatesDocs:
    def __init__(self, client: OpenMates): self._client = client
    def list(self) -> dict[str, Any]: return self._client._get("/v1/sdk/docs")
    def search(self, query: str) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/docs/search", q=query))
    def show(self, slug: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/docs/{_quote(slug)}")
    def download(self, slug: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/docs/{_quote(slug)}/download")


class OpenMatesEmbeds:
    def __init__(self, client: OpenMates):
        self._client = client
        self.preview = OpenMatesEmbedPreview(client)
    def show(self, embed_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}")
    def share(self, embed_id: str, *, expires: int | None = None, password: str | None = None) -> dict[str, Any]:
        shown = self.show(embed_id)
        embed_keys = shown.get("embed_keys") if isinstance(shown.get("embed_keys"), list) else []
        embed_key = self._client._resolve_embed_key_for_share(embed_keys, embed_id)
        if embed_key is None:
            raise OpenMatesConfigError("Unable to resolve embed key for share link")
        blob = _generate_share_blob("embed", embed_id, embed_key, expires=expires, password=password)
        return {"url": f"{self._client._web_origin()}/share/embed/{embed_id}#key={blob}"}
    def versions(self, embed_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}/versions")
    def version(self, embed_id: str, version: int) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}/versions/{version}")
    def restore_version(self, embed_id: str, version: int, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Restoring an embed version")
        return self._client._post(f"/v1/sdk/embeds/{_quote(embed_id)}/versions/{version}/restore", {})


class OpenMatesEmbedPreview:
    def __init__(self, client: OpenMates): self._client = client

    def start(
        self,
        embed_id: str,
        *,
        chat_id: str,
        shared_context: str | None = None,
        requested_runtime: str | None = None,
        source_message_id: str | None = None,
        wait: bool = False,
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id}
        if shared_context:
            payload["shared_context"] = shared_context
        if requested_runtime:
            payload["requested_runtime"] = requested_runtime
        if source_message_id:
            payload["source_message_id"] = source_message_id
        started = self._client._post(f"/v1/applications/{_quote(embed_id)}/preview/start", payload)
        return self._wait_for_running(str(started["session_id"]), timeout_s=timeout_s) if wait else started

    def status(self, session_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/applications/preview/{_quote(session_id)}")

    def open(self, session_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/applications/preview/{_quote(session_id)}/open", {})

    def stop(self, session_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/applications/preview/{_quote(session_id)}/stop", {})

    def _wait_for_running(self, session_id: str, *, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self.status(session_id)
            if status.get("status") in {"running", "failed", "timeout", "cancelled", "stopped"}:
                return status
            time.sleep(1.0)
        raise OpenMatesApiError(408, {"detail": "Application preview did not reach running state before timeout"})


class OpenMatesConnectedAccounts:
    def __init__(self, client: OpenMates): self._client = client
    def import_account(self, *, payload: str, passcode: str, team_id: str | None = None) -> dict[str, Any]:
        if team_id:
            raise OpenMatesConfigError("Team connected accounts are not supported yet.")
        decrypted = _decrypt_connected_account_payload(payload, passcode)
        account = self._client._get("/v1/sdk/account")
        user_id = str(account.get("id") or "")
        if not user_id:
            raise OpenMatesConfigError("Could not resolve current user id for connected account import")
        row = _connected_account_row(decrypted, user_id=user_id, master_key=self._client._get_master_key())
        return self._client._post("/v1/sdk/connected-accounts/import", {"row": row})


class OpenMatesTeams:
    def __init__(self, client: OpenMates): self._client = client

    def list(self) -> list[dict[str, Any]]:
        return list(self._client._get("/v1/teams").get("teams") or [])

    def get(self, team_id: str) -> dict[str, Any]:
        result = self._client._get(f"/v1/teams/{_quote(team_id)}")
        return dict(result.get("team") or result)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client._post("/v1/teams", payload)
        return dict(result.get("team") or result)

    def update(self, team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client._patch(f"/v1/teams/{_quote(team_id)}", payload)
        return dict(result.get("team") or result)

    def invite(self, team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client._post(f"/v1/teams/{_quote(team_id)}/invites", payload)
        return dict(result.get("invite") or result)

    def accept_invite(self, invite_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/team-invites/{_quote(invite_id)}/accept", payload or {})

    def decline_invite(self, invite_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/team-invites/{_quote(invite_id)}/decline", payload or {})

    def access_requests(self, team_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        result = self._client._get(_with_query(f"/v1/teams/{_quote(team_id)}/access-requests", status=status))
        return list(result.get("access_requests") or [])

    def approve_access(self, team_id: str, access_request_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._client._post(f"/v1/teams/{_quote(team_id)}/access-requests/{_quote(access_request_id)}/approve", payload or {})
        return dict(result.get("membership") or result)

    def reject_access(self, team_id: str, access_request_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/teams/{_quote(team_id)}/access-requests/{_quote(access_request_id)}/reject", payload or {})

    def remove_member(self, team_id: str, member_user_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/teams/{_quote(team_id)}/members/{_quote(member_user_id)}/remove", payload or {})

    def billing(self, team_id: str) -> dict[str, Any]:
        result = self._client._get(f"/v1/teams/{_quote(team_id)}/billing")
        return dict(result.get("billing") or result)

    def usage(self, team_id: str, *, member_user_id: str | None = None) -> list[dict[str, Any]]:
        result = self._client._get(_with_query(f"/v1/teams/{_quote(team_id)}/billing/usage", member_user_id=member_user_id))
        return list(result.get("usage") or [])

    def create_bank_transfer_order(self, team_id: str, credits: int, *, email_encryption_key: str | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/teams/{_quote(team_id)}/billing/bank-transfer-orders", {"credits_amount": credits, "currency": "eur", "email_encryption_key": email_encryption_key})

    def bank_transfer_status(self, team_id: str, order_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/teams/{_quote(team_id)}/billing/bank-transfer-orders/{_quote(order_id)}")

    def list_bank_transfer_orders(self, team_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/teams/{_quote(team_id)}/billing/bank-transfer-orders")

    def memories(self, team_id: str) -> list[dict[str, Any]]:
        result = self._client._get(f"/v1/teams/{_quote(team_id)}/memories")
        return list(result.get("memories") or [])

    def export(self, team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/teams/{_quote(team_id)}/export", payload or {})

    def import_team(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post("/v1/teams/import", payload)


class OpenMatesLearningMode:
    def __init__(self, client: OpenMates): self._client = client
    def status(self) -> dict[str, Any]: return self._client._get("/v1/sdk/learning-mode")
    def enable(self, *, age_group: str, passcode: str) -> dict[str, Any]: return self._client._post("/v1/sdk/learning-mode/enable", {"age_group": age_group, "passcode": passcode})
    def disable(self, passcode: str) -> dict[str, Any]: return self._client._post("/v1/sdk/learning-mode/disable", {"passcode": passcode})


class OpenMatesInspirations:
    def __init__(self, client: OpenMates): self._client = client
    def list(self, *, language: str | None = None) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/inspirations", lang=language))


class OpenMatesNewChatSuggestions:
    def __init__(self, client: OpenMates): self._client = client
    def list(self, *, limit: int = 10) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/new-chat-suggestions", limit=limit))


class OpenMatesFeedback:
    def __init__(self, client: OpenMates): self._client = client
    def assistant_response(self, *, rating: int) -> dict[str, Any]: return self._client._post("/v1/sdk/feedback/assistant-response", {"rating": rating})


class OpenMatesBenchmark:
    def __init__(self, client: OpenMates): self._client = client
    def run(self, input_data: dict[str, Any]) -> dict[str, Any]: return self._client._post("/v1/sdk/benchmark/run", input_data)
    def estimate(self, input_data: dict[str, Any]) -> dict[str, Any]: return self._client._post("/v1/sdk/benchmark/estimate", input_data)
