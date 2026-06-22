"""OpenMates Python SDK facade.

Purpose: provide a lazy API-key client for Python integrations.
Architecture: thin REST facade over public /v1 endpoints.
Security: API keys are bearer credentials and are never persisted by this class.
Tests: packages/openmates-python/tests/test_sdk.py.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from typing import Any
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests

from .generated.app_skills import GeneratedAppSkills


DEFAULT_API_URL = "https://api.openmates.org"
DEFAULT_TIMEOUT_SECONDS = 60
SDK_KDF_ITERATIONS = 100_000
AES_GCM_IV_LENGTH = 12
CIPHERTEXT_HEADER_LENGTH = 6
CIPHERTEXT_MAGIC = b"OM"


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


class OpenMates:
    """Lazy API-key SDK client."""

    def __init__(self, api_key: str | None = None, api_url: str = DEFAULT_API_URL):
        self._api_key = api_key or os.getenv("OPENMATES_API_KEY")
        self._api_url = api_url.rstrip("/")
        self._master_key: bytes | None = None
        self.apps = GeneratedAppSkills(self._run_app_skill)
        self.account = OpenMatesAccount(self)
        self.benchmark = OpenMatesBenchmark(self)
        self.billing = OpenMatesBilling(self)
        self.chats = OpenMatesChats(self)
        self.connected_accounts = OpenMatesConnectedAccounts(self)
        self.docs = OpenMatesDocs(self)
        self.embeds = OpenMatesEmbeds(self)
        self.feedback = OpenMatesFeedback(self)
        self.inspirations = OpenMatesInspirations(self)
        self.learning_mode = OpenMatesLearningMode(self)
        self.memories = OpenMatesMemories(self)
        self.new_chat_suggestions = OpenMatesNewChatSuggestions(self)
        self.notifications = OpenMatesNotifications(self)
        self.reminders = OpenMatesReminders(self)
        self.settings = OpenMatesSettings(self)

    def _run_app_skill(self, app_id: str, skill_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            f"/v1/apps/{app_id}/skills/{skill_id}",
            {"input_data": input_data, "parameters": {}},
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, payload)

    def _delete(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("DELETE", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        request_kwargs = {
            "json": payload,
            "headers": self._headers(has_body=payload is not None),
            "timeout": DEFAULT_TIMEOUT_SECONDS,
        }
        if method == "POST":
            response = requests.post(f"{self._api_url}{path}", **request_kwargs)
        elif method == "PATCH":
            response = requests.patch(f"{self._api_url}{path}", **request_kwargs)
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

    def _headers(self, *, has_body: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-OpenMates-SDK": "pip",
            "X-OpenMates-Device-Identity": os.name,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

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

        session = self._post(
            "/v1/sdk/session",
            {"sdk_name": "pip", "device_identity": os.name},
        )
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

    def _decrypt_chat_metadata(self, chat: dict[str, Any]) -> dict[str, Any]:
        encrypted_chat_key = chat.get("encrypted_chat_key")
        if not isinstance(encrypted_chat_key, str):
            return chat
        chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, self._get_master_key())
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
        decrypted_chat = self._decrypt_chat_metadata(chat)
        encrypted_chat_key = chat.get("encrypted_chat_key")
        chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, self._get_master_key()) if isinstance(encrypted_chat_key, str) else None
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


def _quote(value: str) -> str:
    return quote(value, safe="")


def _with_query(path: str, **query: Any) -> str:
    cleaned = {key: value for key, value in query.items() if value is not None}
    if not cleaned:
        return path
    return f"{path}?{urlencode(cleaned)}"


def _require_confirmed(confirmed: bool, action: str) -> None:
    if confirmed is not True:
        raise OpenMatesConfigError(f"{action} requires confirmed=True")


def _unsupported_sdk_feature(feature: str) -> Any:
    raise OpenMatesConfigError(f"{feature} is not available through the API-key SDK yet")


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


class OpenMatesChats:
    """Chat SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def create(
        self,
        *,
        save_to_account: bool = False,
        focus_mode: dict[str, str] | None = None,
    ) -> "OpenMatesChat":
        return OpenMatesChat(
            self._client,
            save_to_account=save_to_account,
            focus_mode=focus_mode,
        )

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

    def export(self, chat_id: str, *, format: str | None = None) -> dict[str, Any]:
        return _unsupported_sdk_feature("Chat export")

    def delete(self, chat_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a chat")
        return _unsupported_sdk_feature("Chat deletion")

    def share(self, chat_id: str, *, expires: int | None = None, password: str | None = None) -> dict[str, Any]:
        return _unsupported_sdk_feature("Chat sharing")

    def follow_ups(self, chat_id: str) -> list[str]:
        return _unsupported_sdk_feature("Chat follow-up suggestions")

    def incognito(self, message: str) -> ChatResponse:
        return self.create(save_to_account=False).send(message)


class OpenMatesChat:
    """Single SDK chat handle."""

    def __init__(
        self,
        client: OpenMates,
        *,
        save_to_account: bool,
        focus_mode: dict[str, str] | None = None,
    ):
        self._client = client
        self._save_to_account = save_to_account
        self._focus_mode = focus_mode

    def send(self, message: str) -> ChatResponse:
        data = self._client._post(
            "/v1/sdk/chats",
            {
                "message": message,
                "save_to_account": self._save_to_account,
                "focus_mode": self._focus_mode,
            },
        )
        response = data.get("response") or {}
        return ChatResponse(content=response.get("content"), raw=data)


class OpenMatesAccount:
    """Account SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def info(self) -> dict[str, Any]:
        return self._client._get("/v1/sdk/account")

    def set_timezone(self, timezone: str) -> dict[str, Any]:
        return self._client._post("/v1/sdk/account/timezone", {"timezone": timezone})

    def list_interests(self) -> dict[str, Any]:
        return _unsupported_sdk_feature("Account interests")

    def set_interests(self, selected_tag_ids: list[str]) -> dict[str, Any]:
        return _unsupported_sdk_feature("Account interests")

    def clear_interests(self) -> dict[str, Any]:
        return _unsupported_sdk_feature("Account interests")

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


class OpenMatesMemories:
    """Encrypted memories SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, **query: Any) -> dict[str, Any]:
        return _unsupported_sdk_feature("Encrypted memories")

    def types(self, **query: Any) -> dict[str, Any]:
        return _unsupported_sdk_feature("Encrypted memories")

    def create(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return _unsupported_sdk_feature("Encrypted memories")

    def update(self, memory_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return _unsupported_sdk_feature("Encrypted memories")

    def delete(self, memory_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a memory")
        return _unsupported_sdk_feature("Encrypted memories")


class OpenMatesBilling:
    """Billing-safe SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def overview(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing")
    def usage(self) -> dict[str, Any]: return _unsupported_sdk_feature("Billing usage list")
    def usage_summaries(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/summaries")
    def usage_daily(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/daily")
    def usage_export(self) -> dict[str, Any]: return _unsupported_sdk_feature("Billing usage export")
    def create_bank_transfer_order(self, credits: int) -> dict[str, Any]: return _unsupported_sdk_feature("Bank-transfer orders")
    def bank_transfer_status(self, order_id: str) -> dict[str, Any]: return _unsupported_sdk_feature("Bank-transfer orders")
    def list_bank_transfer_orders(self) -> dict[str, Any]: return _unsupported_sdk_feature("Bank-transfer orders")
    def list_invoices(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/invoices")
    def download_invoice(self, invoice_id: str) -> dict[str, Any]: return _unsupported_sdk_feature("Invoice downloads")
    def download_credit_note(self, invoice_id: str) -> dict[str, Any]: return _unsupported_sdk_feature("Credit-note downloads")
    def request_refund(self, invoice_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Requesting an invoice refund")
        return _unsupported_sdk_feature("Invoice refunds")
    def redeem_gift_card(self, code: str) -> dict[str, Any]: return _unsupported_sdk_feature("Gift cards")
    def list_redeemed_gift_cards(self) -> dict[str, Any]: return _unsupported_sdk_feature("Gift cards")
    def create_gift_card_bank_transfer_order(self, credits: int) -> dict[str, Any]: return _unsupported_sdk_feature("Gift cards")
    def gift_card_purchase_status(self, order_id: str) -> dict[str, Any]: return _unsupported_sdk_feature("Gift cards")
    def list_purchased_gift_cards(self) -> dict[str, Any]: return _unsupported_sdk_feature("Gift cards")
    def set_low_balance_auto_topup(self, input_data: dict[str, Any]) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/auto-topup/low-balance", input_data)


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
    def __init__(self, client: OpenMates): self._client = client
    def show(self, embed_id: str) -> dict[str, Any]: return _unsupported_sdk_feature("Embed show")
    def share(self, embed_id: str, **input_data: Any) -> dict[str, Any]: return _unsupported_sdk_feature("Embed sharing")
    def versions(self, embed_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}/versions")
    def version(self, embed_id: str, version: int) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}/versions/{version}")
    def restore_version(self, embed_id: str, version: int, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Restoring an embed version")
        return self._client._post(f"/v1/sdk/embeds/{_quote(embed_id)}/versions/{version}/restore", {})


class OpenMatesConnectedAccounts:
    def __init__(self, client: OpenMates): self._client = client
    def import_account(self, *, payload: str, passcode: str) -> dict[str, Any]:
        return _unsupported_sdk_feature("Connected account import")


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
    def assistant_response(self, *, rating: int) -> dict[str, Any]: return _unsupported_sdk_feature("Assistant response feedback")


class OpenMatesBenchmark:
    def __init__(self, client: OpenMates): self._client = client
    def run(self, input_data: dict[str, Any]) -> dict[str, Any]: return _unsupported_sdk_feature("Benchmark runs")
    def estimate(self, input_data: dict[str, Any]) -> dict[str, Any]: return _unsupported_sdk_feature("Benchmark estimates")
