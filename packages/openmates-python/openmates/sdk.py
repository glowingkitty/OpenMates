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
from typing import Any, NotRequired, TypedDict
import unicodedata
from urllib.parse import quote, urlencode, urlparse, urlunparse
import uuid
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import requests

from .generated.app_skills import GeneratedAppSkills
from .chat_completion_recovery import derive_recovery_keypair, open_recovery_envelope
from .work_control import WorkDependenciesFacade as _WorkDependenciesFacade


DEFAULT_API_URL = "https://api.openmates.org"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RECOVERY_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 60.0
SKILL_TASK_POLL_INTERVAL_SECONDS = 2.0
SKILL_TASK_POLL_TIMEOUT_SECONDS = 1200.0


class AiModelDefaults(TypedDict):
    """Three-tier default model settings; omitted fields remain unchanged."""

    default_ai_model_simple: NotRequired[str | None]
    default_ai_model_complex: NotRequired[str | None]
    default_ai_model_most_demanding: NotRequired[str | None]


SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS = 500
CODE_RUN_POLL_INTERVAL_SECONDS = 1.0
CODE_RUN_POLL_TIMEOUT_SECONDS = 1200.0
CODE_RUN_TERMINAL_STATUSES = {"finished", "failed", "timeout", "cancelled"}
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
EXTERNAL_CHAT_INDEX_INFO = b"openmates-task-external-chat-index-v1"
EXTERNAL_CHAT_PROVIDER = "opencode"
BLOCKED_REASON_CODES = (
    "needs_user_input",
    "waiting_for_approval",
    "missing_credentials",
    "ambiguous_requirement",
    "external_dependency",
    "environment_unavailable",
    "verification_failed",
    "other",
)
SLUG_LOOKUP_HASH_INFO = b"openmates-object-slug-index-v1"
MAX_OBJECT_SLUG_LENGTH = 80
DESIGN_ICON_PATH_PATTERN = re.compile(r"^/v1/apps/design/icons/iconify/([a-z0-9][a-z0-9._-]*)/([a-z0-9][a-z0-9._-]*)\.svg$", re.IGNORECASE)
DESIGN_ICON_SEGMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
DESIGN_ICON_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
DEFAULT_ICON_PNG_SIZE = 256
MAX_ICON_PNG_SIZE = 4096
DEFAULT_TEAM_PROFILE_ICON_NAME = "users"
DEFAULT_TEAM_PROFILE_BACKGROUND_COLOR = "#4d73ff"
IDEABUCKET_DEFAULT_PROCESSING_PROMPT = "These are my captured ideas for today. Please process them, group related thoughts, suggest next actions, and ask clarifying questions where needed:\n\nIf an idea requires deeper work, create or suggest sub-chats for focused research, planning, todos, docs, or implementation."
IDEABUCKET_APP_ID = "ideabucket"
IDEABUCKET_SETTINGS_ITEM_TYPE = "processing_settings"
IDEABUCKET_DEFAULT_PROCESSING_TIMES = ("09:00",)
IDEABUCKET_PROCESSING_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
REMEMBER_MESSAGE_PREFIX = "Remember my earlier message:"
REMEMBER_MESSAGE_REFERENCE_RE = re.compile(r"\bRemember my (?:earlier )?message @([A-Za-z0-9-]{4,36})\b", re.IGNORECASE)
ENCRYPTED_ACCOUNT_EXPORT_MAGIC = b"OMZIP1\n"
ENCRYPTED_ACCOUNT_EXPORT_KEY_BYTES = 32
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
    plan: dict[str, Any] | None = None


def _app_skill_chat_content(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("content", "response", "answer"):
        if isinstance(value.get(key), str):
            return value[key]
    choices = value.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(first.get("text"), str):
            return first["text"]
    return _app_skill_chat_content(value.get("data"))


def _normalize_optional_goal(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        raise OpenMatesConfigError("Chat goal must not be empty")
    return trimmed


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


def _safe_response_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


class _PlanRevisionsFacade:
    def __init__(self, plans: Any):
        self._plans = plans

    def create(self, plan_id: str) -> dict[str, Any]:
        plan = self._plans.show(plan_id)
        canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
        raw = self._plans._get_raw_plan(plan_id)
        master_key = self._plans._client._get_master_key()
        fingerprint = hmac.new(master_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        encrypted_snapshot = _encrypt_aes_gcm_text(canonical, _plan_key_from_record(raw, master_key))
        return self._plans._client._post(
            f"/v1/user-plans/{_quote(str(raw['plan_id']))}/revisions",
            {"fingerprint": fingerprint, "encrypted_snapshot": encrypted_snapshot, "created_at": int(time.time())},
        )

    def list(self, plan_id: str) -> list[dict[str, Any]]:
        raw = self._plans._get_raw_plan(plan_id)
        return self._plans._client._get(f"/v1/user-plans/{_quote(str(raw['plan_id']))}/revisions").get("revisions", [])


class _PlanReviewFacade:
    def __init__(self, plans: Any):
        self._plans = plans

    def submit(self, plan_id: str) -> dict[str, Any]:
        result = self._plans.revisions.create(plan_id)
        revision = result.get("revision") if isinstance(result.get("revision"), dict) else None
        if not revision or not revision.get("revision_id"):
            raise OpenMatesApiError(500, {"detail": "Plan revision response missing revision"})
        raw = self._plans._get_raw_plan(plan_id)
        return {"revision": revision, "review_url": f"{self._plans._client._web_origin()}/plans/{raw['plan_id']}/review?revision={revision['revision_id']}"}


class _PlanApprovalFacade:
    def __init__(self, plans: Any):
        self._plans = plans

    def status(self, plan_id: str) -> dict[str, Any]:
        raw = self._plans._get_raw_plan(plan_id)
        return self._plans._client._get(f"/v1/user-plans/{_quote(str(raw['plan_id']))}/approval-status").get("approval", {})


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
        self.finance = OpenMatesFinance(self)
        self.ideabucket = OpenMatesIdeaBucket(self)
        self.inspirations = OpenMatesInspirations(self)
        self.api_keys = OpenMatesApiKeys(self)
        self.learning_mode = OpenMatesLearningMode(self)
        self.memories = OpenMatesMemories(self)
        self.new_chat_suggestions = OpenMatesNewChatSuggestions(self)
        self.notifications = OpenMatesNotifications(self)
        self.reminders = OpenMatesReminders(self)
        self.history = OpenMatesHistory(self)
        self.projects = OpenMatesProjects(self)
        self.settings = OpenMatesSettings(self)
        self.plans = OpenMatesPlans(self)
        self.tasks = OpenMatesTasks(self)
        self.teams = OpenMatesTeams(self)
        self.workflows = OpenMatesWorkflows(self)
        self.wikipedia = OpenMatesWikipedia(self)

    def _run_app_skill(
        self,
        app_id: str,
        skill_id: str,
        input_data: dict[str, Any],
        *,
        prompt_injection_protection: bool | None = None,
    ) -> dict[str, Any]:
        response = self._post(
            f"/v1/apps/{app_id}/skills/{skill_id}",
            _with_app_skill_prompt_injection_option(input_data, prompt_injection_protection),
        )
        if app_id == "code" and skill_id == "run":
            return self._resolve_code_run_skill_response(response)
        return self._resolve_async_skill_response(response)

    def run_connected_account_skill(
        self,
        app_id: str,
        skill_id: str,
        input_data: dict[str, Any],
        *,
        connected_account_token_ref_inputs: list[dict[str, Any]] | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        prompt_injection_protection: bool | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"/v1/sdk/connected-account-skills/{_quote(app_id)}/{_quote(skill_id)}",
            {
                "input": _with_app_skill_prompt_injection_option(input_data, prompt_injection_protection),
                "connected_account_token_ref_inputs": connected_account_token_ref_inputs or [],
                "chat_id": chat_id,
                "message_id": message_id,
            },
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

    def _resolve_async_skill_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        data = response_data.get("data") if isinstance(response_data.get("data"), dict) else response_data
        task_id = data.get("task_id") if isinstance(data, dict) else None
        task_ids_raw = data.get("task_ids") if isinstance(data, dict) else None
        task_ids = [task_id for task_id in task_ids_raw or [] if isinstance(task_id, str)] if isinstance(task_ids_raw, list) else []

        if isinstance(task_id, str) and task_id:
            task = self._poll_task_until_complete(task_id)
            return self._wrap_resolved_skill_result(response_data, task.get("result"))
        if task_ids:
            tasks = [self._poll_task_until_complete(task_id) for task_id in task_ids]
            return self._wrap_resolved_skill_result(response_data, self._merge_task_results([task.get("result") for task in tasks]))
        return response_data

    def _resolve_code_run_skill_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        data = response_data.get("data") if isinstance(response_data.get("data"), dict) else response_data
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return response_data
        resolved_results = []
        for result in results:
            if not isinstance(result, dict):
                resolved_results.append(result)
                continue
            status_path = result.get("status_path")
            if not isinstance(status_path, str):
                resolved_results.append(result)
                continue
            resolved_results.append({**result, "final": self._poll_code_run_until_complete(status_path)})
        resolved_data = {**data, "results": resolved_results}
        if "success" in response_data:
            return {**response_data, "data": resolved_data}
        return resolved_data

    def _poll_code_run_until_complete(self, status_path: str) -> dict[str, Any]:
        path = self._normalize_code_run_status_path(status_path)
        started = time.monotonic()
        last_transient_error: str | None = None
        while time.monotonic() - started < CODE_RUN_POLL_TIMEOUT_SECONDS:
            try:
                response = requests.get(
                    f"{self._api_url}{path}",
                    headers=self._headers(has_body=False),
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_transient_error = str(exc)
                time.sleep(CODE_RUN_POLL_INTERVAL_SECONDS)
                continue

            if not response.ok:
                if response.status_code >= SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS:
                    last_transient_error = f"HTTP {response.status_code}"
                    time.sleep(CODE_RUN_POLL_INTERVAL_SECONDS)
                    continue
                raise OpenMatesApiError(response.status_code, _safe_response_json(response))

            last_transient_error = None
            status = self._parse_response(response)
            if status.get("status") in CODE_RUN_TERMINAL_STATUSES:
                return status
            time.sleep(CODE_RUN_POLL_INTERVAL_SECONDS)

        if last_transient_error:
            raise RuntimeError(
                f"Code Run did not complete within {CODE_RUN_POLL_TIMEOUT_SECONDS:.0f}s; last polling error: {last_transient_error}"
            )
        raise RuntimeError(f"Code Run did not complete within {CODE_RUN_POLL_TIMEOUT_SECONDS:.0f}s")

    def _normalize_code_run_status_path(self, status_path: str) -> str:
        if not status_path.startswith("/v1/code/run/"):
            raise OpenMatesConfigError("Code Run returned an invalid status path.")
        return status_path

    def _poll_task_until_complete(self, task_id: str) -> dict[str, Any]:
        started = time.monotonic()
        last_transient_error: str | None = None
        while time.monotonic() - started < SKILL_TASK_POLL_TIMEOUT_SECONDS:
            try:
                response = requests.get(
                    f"{self._api_url}/v1/tasks/{_quote(task_id)}",
                    headers=self._headers(has_body=False),
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_transient_error = str(exc)
                time.sleep(SKILL_TASK_POLL_INTERVAL_SECONDS)
                continue

            if not response.ok:
                if response.status_code >= SKILL_TASK_POLL_TRANSIENT_ERROR_STATUS:
                    last_transient_error = f"HTTP {response.status_code}"
                    time.sleep(SKILL_TASK_POLL_INTERVAL_SECONDS)
                    continue
                raise OpenMatesApiError(response.status_code, _safe_response_json(response))

            last_transient_error = None
            task = self._parse_response(response)
            status = task.get("status")
            if status == "completed":
                return task
            if status == "failed":
                raise RuntimeError(str(task.get("error") or "Task failed"))
            time.sleep(SKILL_TASK_POLL_INTERVAL_SECONDS)

        if last_transient_error:
            raise RuntimeError(
                f"Task {task_id} did not complete within {SKILL_TASK_POLL_TIMEOUT_SECONDS:.0f}s; last polling error: {last_transient_error}"
            )
        raise RuntimeError(f"Task {task_id} did not complete within {SKILL_TASK_POLL_TIMEOUT_SECONDS:.0f}s")

    def _wrap_resolved_skill_result(self, original: dict[str, Any], result: Any) -> dict[str, Any]:
        if "success" in original:
            return {**original, "data": result}
        return result if isinstance(result, dict) else {"result": result}

    def _merge_task_results(self, results: list[Any]) -> dict[str, Any]:
        result_objects = [result for result in results if isinstance(result, dict)]
        grouped_results = [item for result in result_objects for item in result.get("results", []) if isinstance(result.get("results"), list)]
        if not grouped_results:
            return {"results": results}
        first = result_objects[0] if result_objects else {}
        return {**first, "results": grouped_results}

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
        parsed_api_url = urlparse(self._api_url)
        origin = os.getenv("OPENMATES_APP_URL", "").rstrip("/")
        if not origin and parsed_api_url.hostname == "api.dev.openmates.org":
            origin = "https://app.dev.openmates.org"
        elif not origin and parsed_api_url.hostname == "api.openmates.org":
            origin = "https://openmates.org"
        elif not origin:
            origin = f"{parsed_api_url.scheme}://{parsed_api_url.netloc}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Origin": origin,
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
        if isinstance(chat.get("encrypted_slug"), str):
            decrypted["slug"] = _decrypt_object_slug(chat["encrypted_slug"], chat_key)
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


def _project_context(*, personal: bool = False, team_id: str | None = None) -> str | None:
    normalized_team_id = team_id.strip() if isinstance(team_id, str) else ""
    if personal == bool(normalized_team_id):
        raise OpenMatesConfigError("Projects require explicit Personal or Team context")
    return normalized_team_id or None


def _generated_team_profile_image_metadata(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "version": 1,
        "mode": "generated",
        "icon_name": payload.get("icon_name") or payload.get("iconName") or DEFAULT_TEAM_PROFILE_ICON_NAME,
        "icon_color": "#ffffff",
        "background_color": payload.get("background_color") or payload.get("backgroundColor") or DEFAULT_TEAM_PROFILE_BACKGROUND_COLOR,
    }


def _team_key_from_record(client: OpenMates, team: dict[str, Any]) -> bytes:
    encrypted_team_key = team.get("encrypted_team_key")
    if not isinstance(encrypted_team_key, str):
        raise OpenMatesConfigError("Team response is missing encrypted Team key")
    team_key = _decrypt_aes_gcm_bytes(encrypted_team_key, client._get_master_key())
    if team_key is None:
        raise OpenMatesConfigError("Failed to decrypt Team key")
    return team_key


def _build_team_plain_create_payload(client: OpenMates, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise OpenMatesConfigError("Team name is required")
    team_key = os.urandom(32)
    created_at = int(payload.get("created_at") or payload.get("createdAt") or time.time())
    return {
        "team_id": str(payload.get("team_id") or payload.get("teamId") or uuid.uuid4()),
        "slug": payload.get("slug"),
        "encrypted_name": _encrypt_aes_gcm_text(name, team_key),
        "encrypted_description": _encrypt_aes_gcm_text(str(payload.get("description")), team_key) if payload.get("description") else None,
        "encrypted_profile_image_metadata": _encrypt_aes_gcm_text(json.dumps(_generated_team_profile_image_metadata(payload.get("profile") if isinstance(payload.get("profile"), dict) else None)), team_key),
        "encrypted_team_key": _encrypt_aes_gcm_bytes(team_key, client._get_master_key()),
        "encrypted_zero_balance": _encrypt_aes_gcm_text("0", team_key),
        "created_at": created_at,
        "updated_at": created_at,
    }


def _project_wrapping_key(client: OpenMates, team_id: str | None) -> bytes:
    master_key = client._get_master_key()
    if not team_id:
        return master_key
    team = client._get(f"/v1/teams/{_quote(team_id)}").get("team", {})
    encrypted_team_key = team.get("encrypted_team_key") if isinstance(team, dict) else None
    if not isinstance(encrypted_team_key, str):
        raise OpenMatesConfigError(f"Team {team_id} is missing encrypted team key")
    team_key = _decrypt_aes_gcm_bytes(encrypted_team_key, master_key)
    if team_key is None:
        raise OpenMatesConfigError(f"Failed to decrypt Team key for {team_id}")
    return team_key


def _project_key_from_record(record: dict[str, Any], wrapping_key: bytes, team_id: str | None) -> bytes:
    encrypted_project_key = record.get("encrypted_project_key")
    if team_id:
        team_hash = hashlib.sha256(team_id.encode("utf-8")).hexdigest()
        wrapper = next((
            item for item in record.get("key_wrappers", [])
            if isinstance(item, dict)
            and item.get("key_type") == "team"
            and item.get("hashed_team_id") == team_hash
            and item.get("team_key_epoch") == 1
        ), None)
        encrypted_project_key = wrapper.get("encrypted_project_key") if isinstance(wrapper, dict) else None
    if not isinstance(encrypted_project_key, str):
        raise OpenMatesConfigError("Project response is missing encrypted Project key wrapper")
    project_key = _decrypt_aes_gcm_bytes(encrypted_project_key, wrapping_key)
    if project_key is None:
        raise OpenMatesConfigError("Failed to decrypt Project key")
    return project_key


def _resolve_project_key(client: OpenMates, project_id: str, *, personal: bool = True, team_id: str | None = None) -> bytes:
    context_team_id = _project_context(personal=personal, team_id=team_id)
    resolved_project_id = _resolve_project_id(client, project_id, personal=personal, team_id=context_team_id)
    response = client._get(_with_query(f"/v1/projects/{_quote(resolved_project_id)}", team_id=context_team_id))
    record = response.get("project")
    if not isinstance(record, dict):
        raise OpenMatesApiError(404, {"detail": "Project not found"})
    return _project_key_from_record(record, _project_wrapping_key(client, context_team_id), context_team_id)


def _resolve_project_id(client: OpenMates, project_id: str, *, personal: bool = True, team_id: str | None = None) -> str:
    if _is_uuid(project_id):
        return project_id
    context_team_id = _project_context(personal=personal, team_id=team_id)
    projects = client.projects.list(personal=context_team_id is None, team_id=context_team_id, include_archived=True)
    exact = next((project for project in projects if project.get("project_id") == project_id), None)
    if exact:
        return str(exact.get("project_id"))
    lowered = project_id.lower()
    prefix_matches = [project for project in projects if len(project_id) >= 8 and str(project.get("project_id") or "").lower().startswith(lowered)]
    if len(prefix_matches) > 1:
        raise OpenMatesConfigError(f"Project '{project_id}' is ambiguous. Use the full project ID.")
    if prefix_matches:
        return str(prefix_matches[0].get("project_id"))
    slug_matches = [project for project in projects if _object_slug_matches(project.get("slug"), project_id)]
    if len(slug_matches) > 1:
        raise OpenMatesConfigError(f"Project slug '{project_id}' is ambiguous. Use the full project ID.")
    if slug_matches:
        return str(slug_matches[0].get("project_id"))
    normalized_name = " ".join(project_id.strip().lower().split())
    name_matches = [project for project in projects if " ".join(str(project.get("name") or "").strip().lower().split()) == normalized_name]
    if len(name_matches) > 1:
        raise OpenMatesConfigError(f"Project '{project_id}' is ambiguous. Use the full project ID.")
    if name_matches:
        return str(name_matches[0].get("project_id"))
    raise OpenMatesConfigError(f"Project '{project_id}' was not found")


def _resolve_chat_id(client: OpenMates, chat_id: str) -> str:
    if _is_uuid(chat_id):
        return chat_id
    chats = client.chats.list(limit=0)
    lowered = chat_id.lower()
    exact = next((chat for chat in chats if chat.get("id") == chat_id), None)
    if exact:
        return str(exact.get("id"))
    prefix_matches = [chat for chat in chats if len(chat_id) >= 8 and str(chat.get("id") or "").lower().startswith(lowered)]
    if len(prefix_matches) > 1:
        raise OpenMatesConfigError(f"Chat '{chat_id}' is ambiguous. Use the full chat ID.")
    if prefix_matches:
        return str(prefix_matches[0].get("id"))
    slug_matches = [chat for chat in chats if _object_slug_matches(chat.get("slug"), chat_id)]
    if len(slug_matches) > 1:
        raise OpenMatesConfigError(f"Chat slug '{chat_id}' is ambiguous. Use the full chat ID.")
    if slug_matches:
        return str(slug_matches[0].get("id"))
    normalized_title = " ".join(chat_id.strip().lower().split())
    title_matches = [chat for chat in chats if " ".join(str(chat.get("title") or "").strip().lower().split()) == normalized_title]
    if len(title_matches) > 1:
        raise OpenMatesConfigError(f"Chat '{chat_id}' is ambiguous. Use the full chat ID.")
    if title_matches:
        return str(title_matches[0].get("id"))
    raise OpenMatesConfigError(f"Chat '{chat_id}' was not found")


def _resolve_workflow_id(client: OpenMates, workflow_id: str) -> str:
    if _is_uuid(workflow_id):
        return workflow_id
    workflows = client.workflows.list()
    exact = next((workflow for workflow in workflows if workflow.get("id") == workflow_id), None)
    if exact:
        return str(exact.get("id"))
    lowered = workflow_id.lower()
    prefix_matches = [workflow for workflow in workflows if len(workflow_id) >= 8 and str(workflow.get("id") or "").lower().startswith(lowered)]
    if len(prefix_matches) > 1:
        raise OpenMatesConfigError(f"Workflow '{workflow_id}' is ambiguous. Use the full workflow ID.")
    if prefix_matches:
        return str(prefix_matches[0].get("id"))
    slug_matches = [workflow for workflow in workflows if _object_slug_matches(workflow.get("slug"), workflow_id)]
    if len(slug_matches) > 1:
        raise OpenMatesConfigError(f"Workflow slug '{workflow_id}' is ambiguous. Use the full workflow ID.")
    if slug_matches:
        return str(slug_matches[0].get("id"))
    normalized_title = " ".join(workflow_id.strip().lower().split())
    title_matches = [workflow for workflow in workflows if " ".join(str(workflow.get("title") or "").strip().lower().split()) == normalized_title]
    if len(title_matches) > 1:
        raise OpenMatesConfigError(f"Workflow '{workflow_id}' is ambiguous. Use the full workflow ID.")
    if title_matches:
        return str(title_matches[0].get("id"))
    raise OpenMatesConfigError(f"Workflow '{workflow_id}' was not found")


def _workflow_resource_request(
    client: OpenMates,
    method: str,
    workflow_id: str,
    suffix: str = "",
    payload: dict[str, Any] | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_workflow_id = workflow_id if _is_uuid(workflow_id) else _resolve_workflow_id(client, workflow_id)

    def request(target_workflow_id: str) -> dict[str, Any]:
        path = f"/v1/workflows/{_quote(target_workflow_id)}{suffix}"
        if method == "GET":
            return client._get(path)
        if method == "POST":
            return client._post(path, payload or {}, extra_headers=extra_headers)
        if method == "PATCH":
            return client._patch(path, payload or {})
        if method == "PUT":
            return client._put(path, payload or {})
        if method == "DELETE":
            return client._delete(path)
        raise OpenMatesConfigError(f"Unsupported workflow request method '{method}'")

    return request(resolved_workflow_id)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _resolve_chat_key(client: OpenMates, chat_id: str) -> bytes:
    resolved_chat_id = _resolve_chat_id(client, chat_id)
    payload = client._get(f"/v1/sdk/chats/{_quote(resolved_chat_id)}")
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
    resolved_chat_id = str(chat.get("id") or resolved_chat_id)
    hashed_chat_id = hashlib.sha256(resolved_chat_id.encode("utf-8")).hexdigest()
    chat_key_wrappers = payload.get("chat_key_wrappers") if isinstance(payload.get("chat_key_wrappers"), list) else chat.get("chat_key_wrappers")
    wrapper = next(
        (
            entry
            for entry in (chat_key_wrappers or [])
            if isinstance(entry, dict)
            and entry.get("key_type") == "master"
            and entry.get("hashed_chat_id") == hashed_chat_id
            and isinstance(entry.get("encrypted_chat_key"), str)
        ),
        None,
    )
    encrypted_chat_key = wrapper.get("encrypted_chat_key") if wrapper else chat.get("encrypted_chat_key")
    if not isinstance(encrypted_chat_key, str):
        raise OpenMatesConfigError("Saved chat does not include encrypted chat key material")
    chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, client._get_master_key())
    if chat_key is None:
        raise OpenMatesConfigError("Unable to decrypt saved chat key material")
    return chat_key


def _build_plan_key_wrappers(
    client: OpenMates,
    plan_key: bytes,
    *,
    primary_chat_id: str | None,
    linked_project_ids: list[str],
    created_at: int,
    primary_chat_key: bytes | None = None,
) -> list[dict[str, Any]]:
    master_key = client._get_master_key()
    wrappers: list[dict[str, Any]] = [{
        "key_type": "master",
        "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, master_key),
        "created_at": created_at,
    }]
    if primary_chat_id:
        resolved_chat_id = _resolve_chat_id(client, primary_chat_id)
        chat_key = primary_chat_key or _resolve_chat_key(client, resolved_chat_id)
        wrappers.append({
            "key_type": "chat",
            "hashed_chat_id": hashlib.sha256(resolved_chat_id.encode("utf-8")).hexdigest(),
            "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, chat_key),
            "created_at": created_at,
        })
    for project_id in linked_project_ids:
        resolved_project_id = _resolve_project_id(client, project_id)
        project_key = _resolve_project_key(client, resolved_project_id)
        wrappers.append({
            "key_type": "project",
            "hashed_project_id": hashlib.sha256(resolved_project_id.encode("utf-8")).hexdigest(),
            "encrypted_plan_key": _encrypt_aes_gcm_bytes(plan_key, project_key),
            "created_at": created_at,
        })
    return wrappers


def _create_encrypted_project_item(
    client: OpenMates,
    project_id: str,
    project_key: bytes,
    *,
    item_type: str,
    target_id: str,
    display_name: str,
    folder: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    response = client._post(f"/v1/projects/{_quote(project_id)}/items", {
        "project_item_id": str(uuid.uuid4()),
        "folder_id": folder,
        "item_type": item_type,
        "target_id": target_id,
        "target_id_encrypted": _encrypt_aes_gcm_text(target_id, project_key),
        "encrypted_display_name": _encrypt_aes_gcm_text(display_name, project_key),
        "encrypted_note": _encrypt_aes_gcm_text("", project_key),
        "encrypted_metadata": _encrypt_aes_gcm_text(json.dumps(metadata or {}), project_key),
        "created_at": now,
        "updated_at": now,
        "position": now,
    })
    item = response.get("item")
    if not isinstance(item, dict):
        raise OpenMatesApiError(500, {"detail": "Project item response missing item"})
    return item


def _delete_project_item_by_target(
    client: OpenMates,
    project_id: str,
    item_type: str,
    target_id: str,
) -> dict[str, Any]:
    response = client._delete(_with_query(
        f"/v1/projects/{_quote(project_id)}/items",
        item_type=item_type,
        target_id=target_id,
    ))
    return {
        "deleted": response.get("deleted") is True,
        "deleted_count": int(response.get("deleted_count") or 0),
    }


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


def _format_remember_message_draft(content: str) -> str:
    trimmed = content.strip()
    if not trimmed:
        return REMEMBER_MESSAGE_PREFIX
    quoted = "\n".join(f"> {line}" for line in re.split(r"\r?\n", trimmed))
    return f"{REMEMBER_MESSAGE_PREFIX}\n\n{quoted}"


def _rewrite_remember_message_references(message: str, messages: list[dict[str, Any]]) -> str:
    def replace(match: re.Match[str]) -> str:
        message_id = match.group(1)
        for candidate in messages:
            candidate_id = candidate.get("id") or candidate.get("client_message_id") or candidate.get("message_id")
            content = candidate.get("content")
            if isinstance(candidate_id, str) and isinstance(content, str) and (candidate_id == message_id or candidate_id.startswith(message_id)):
                return _format_remember_message_draft(content)
        return match.group(0)

    return REMEMBER_MESSAGE_REFERENCE_RE.sub(replace, message)


def _has_remember_message_reference(message: str) -> bool:
    return REMEMBER_MESSAGE_REFERENCE_RE.search(message) is not None


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
        normalized_key = str(key).lower()
        if normalized_key.startswith("encrypted_") or normalized_key in ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES:
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


ACCOUNT_IMPORT_SOURCE_IDENTITIES: dict[str, dict[str, str]] = {
    "openmates": {"category": "openmates", "sender_name": "OpenMates", "model_name": "OpenMates", "avatar_key": "openmates"},
    "chatgpt": {"category": "chatgpt", "sender_name": "ChatGPT", "model_name": "ChatGPT", "avatar_key": "chatgpt"},
    "claude": {"category": "claude", "sender_name": "Claude", "model_name": "Claude", "avatar_key": "claude"},
    "gemini": {"category": "gemini", "sender_name": "Gemini", "model_name": "Gemini", "avatar_key": "gemini"},
    "opencode": {"category": "opencode", "sender_name": "OpenCode", "model_name": "OpenCode", "avatar_key": "opencode"},
    "other": {"category": "other", "sender_name": "AI assistant", "model_name": "Other", "avatar_key": "ai-star"},
}
ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE = 250
COMPRESSION_SUMMARY_CATEGORY = "compression_summary"


def _finalize_account_import(parsed: dict[str, Any], parser_format: str, selected_source: str) -> dict[str, Any]:
    if selected_source not in ACCOUNT_IMPORT_SOURCE_IDENTITIES:
        raise OpenMatesConfigError(f"Unsupported account import source: {selected_source}")
    identity = ACCOUNT_IMPORT_SOURCE_IDENTITIES[selected_source]
    parsed["source"] = selected_source
    parsed["parser_format"] = parser_format
    for chat in parsed.get("chats", []):
        chat["provider"] = selected_source
        chat["parser_format"] = parser_format
        chat["selected_source"] = selected_source
        for message in chat.get("messages", []):
            message["imported_assistant_identity"] = dict(identity) if message.get("role") == "assistant" else None
    return parsed


def _account_import_message_batches(chats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for chat_index, chat in enumerate(chats):
        messages = chat.get("messages") if isinstance(chat.get("messages"), list) else []
        chunk_count = max(1, (len(messages) + ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE - 1) // ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE)
        for chunk_index in range(chunk_count):
            fingerprint = str(chat.get("source_fingerprint") or "")
            batch_chat = dict(chat)
            start = chunk_index * ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE
            batch_chat["messages"] = messages[start:start + ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE]
            batches.append({
                "chat_index": chat_index,
                "chunk_index": chunk_index,
                "source_fingerprint": fingerprint,
                "batch_id": f"scan-{fingerprint[:16]}-{chunk_index}",
                "chat": batch_chat,
            })
    return batches


def _append_compression_summary(chat: dict[str, Any], summary: str | None) -> dict[str, Any]:
    if not isinstance(summary, str) or not summary.strip():
        return chat
    result = dict(chat)
    result["messages"] = [*chat.get("messages", []), {
        "role": "system",
        "content": summary,
        "created_at": None,
        "source_message_id": None,
        "provider_metadata": {"import_type": COMPRESSION_SUMMARY_CATEGORY},
        "imported_assistant_identity": None,
    }]
    return result


def _read_import_zip_text(raw: bytes, required_name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.startswith("__MACOSX/") and "/._" not in name and not name.startswith("._")
        ]
        resolved = required_name if required_name in names else next((name for name in names if Path(name).name == required_name), None)
        if resolved is None:
            raise OpenMatesConfigError(f"Import archive is missing {required_name}")
        return archive.read(resolved).decode("utf-8")


def _decrypt_openmates_encrypted_zip(payload: bytes, password: str | None) -> bytes:
    if not payload.startswith(ENCRYPTED_ACCOUNT_EXPORT_MAGIC):
        return payload
    if not password:
        raise OpenMatesConfigError("OpenMates encrypted export requires a password")
    header_length_end = payload.find(b"\n", len(ENCRYPTED_ACCOUNT_EXPORT_MAGIC))
    if header_length_end < 0:
        raise OpenMatesConfigError("OpenMates encrypted export has an invalid header")
    try:
        header_length = int(payload[len(ENCRYPTED_ACCOUNT_EXPORT_MAGIC):header_length_end].decode("utf-8"))
        header_start = header_length_end + 1
        header_end = header_start + header_length
        header = json.loads(payload[header_start:header_end].decode("utf-8"))
        if header.get("magic") != "OMZIP1" or header.get("cipher") != "aes-256-gcm" or header.get("kdf") != "scrypt":
            raise OpenMatesConfigError("OpenMates encrypted export uses an unsupported encryption format")
        salt = base64.b64decode(str(header.get("salt") or ""))
        iv = base64.b64decode(str(header.get("iv") or ""))
        tag = base64.b64decode(str(header.get("tag") or ""))
        key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=ENCRYPTED_ACCOUNT_EXPORT_KEY_BYTES)
        return AESGCM(key).decrypt(iv, payload[header_end:] + tag, None)
    except OpenMatesConfigError:
        raise
    except Exception as exc:
        raise OpenMatesConfigError(f"OpenMates encrypted export could not be decrypted: {exc}") from exc


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


def _chatgpt_timestamp(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value)))


def _opencode_timestamp(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value) / 1000))


def _chatgpt_message_content(content: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text_parts: list[str] = []
    asset_count = 0
    for part in parts:
        if isinstance(part, str) and part.strip():
            text_parts.append(part)
        elif isinstance(part, dict) and part.get("asset_pointer"):
            asset_count += 1
    if not parts and isinstance(content.get("content"), str):
        text_parts.append(str(content["content"]))
    return "\n".join(text_parts), {"content_type": str(content.get("content_type") or "unknown"), "asset_count": asset_count}


def _chatgpt_active_nodes(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        raise OpenMatesConfigError("ChatGPT conversation is missing mapping")
    current_node = str(conversation.get("current_node") or "")
    if current_node in mapping:
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        node_id = current_node
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            if not isinstance(node, dict):
                break
            ordered.append(node)
            node_id = str(node.get("parent") or "")
        return list(reversed(ordered))
    nodes = [node for node in mapping.values() if isinstance(node, dict)]
    return sorted(nodes, key=lambda node: ((node.get("message") or {}).get("create_time") if isinstance(node.get("message"), dict) else 0) or 0)


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


def _normalize_object_slug(value: str) -> str:
    ascii_value = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_value.strip().lower().replace("'", ""))
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    slug = normalized[:MAX_OBJECT_SLUG_LENGTH].rstrip("-")
    if not slug:
        raise OpenMatesConfigError("Object slug must contain at least one letter or number.")
    return slug


def _object_slug_lookup_hash(slug: str, lookup_key: bytes) -> str:
    index_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"", info=SLUG_LOOKUP_HASH_INFO).derive(lookup_key)
    return hmac.new(index_key, slug.encode("utf-8"), hashlib.sha256).hexdigest()


def _encrypted_object_slug_metadata(value: str, *, encryption_key: bytes, lookup_key: bytes) -> dict[str, str]:
    slug = _normalize_object_slug(value)
    return {
        "slug": slug,
        "encrypted_slug": _encrypt_aes_gcm_text(slug, encryption_key),
        "slug_lookup_hash": _object_slug_lookup_hash(slug, lookup_key),
    }


def _decrypt_object_slug(encrypted_slug: Any, encryption_key: bytes) -> str:
    if not isinstance(encrypted_slug, str):
        return ""
    return _decrypt_aes_gcm_text(encrypted_slug, encryption_key) or ""


def _object_slug_matches(slug: Any, query: str) -> bool:
    if not isinstance(slug, str) or not slug:
        return False
    try:
        return _normalize_object_slug(slug) == _normalize_object_slug(query)
    except OpenMatesConfigError:
        return False


def _build_task_create_input(master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise OpenMatesConfigError("Task title is required")
    task_key = os.urandom(32)
    now = int(time.time())
    assignee_type, assignee_hash = _task_assignee(payload.get("assign") or payload.get("assignee"))
    external_chat = _normalize_external_chat_context(
        payload.get("external_chat", payload.get("externalChat")),
        title=payload.get("external_chat_title", payload.get("externalChatTitle")),
    )
    primary_chat_id = payload.get("chat_id") or payload.get("primary_chat_id") or None
    if primary_chat_id and external_chat:
        raise OpenMatesConfigError("A task cannot use both native chat and external chat context")
    project_ids = _string_list(payload.get("project_ids") or payload.get("linked_project_ids") or [])
    labels = _normalize_task_labels(payload.get("labels") if "labels" in payload else payload.get("tags"))
    status = str(payload.get("status") or "todo")
    slug_metadata = _encrypted_object_slug_metadata(
        str(payload.get("slug") or title),
        encryption_key=task_key,
        lookup_key=master_key,
    )
    task: dict[str, Any] = {
        "task_id": str(payload.get("task_id") or uuid.uuid4()),
        "version": 1,
        "encrypted_task_key": _encrypt_aes_gcm_bytes(task_key, master_key),
        "encrypted_slug": slug_metadata["encrypted_slug"],
        "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
        "encrypted_title": _encrypt_aes_gcm_text(title, task_key),
        "encrypted_description": _encrypt_aes_gcm_text(str(payload.get("description") or ""), task_key),
        "encrypted_labels": _encrypt_aes_gcm_text(json.dumps(labels), task_key),
        "encrypted_tags": _encrypt_aes_gcm_text(json.dumps(labels), task_key),
        "label_hashes": _task_label_hashes(master_key, labels),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text(json.dumps(project_ids), task_key),
        "status": status,
        "assignee_type": assignee_type,
        "assignee_hash": assignee_hash,
        "primary_chat_id": primary_chat_id,
        "linked_project_ids": project_ids,
        "plan_id": payload.get("plan_id") or payload.get("plan") or None,
        "due_at": payload.get("due_at"),
        "priority": _normalize_task_priority(payload.get("priority")) or 0,
        "position": int(payload.get("position") or now),
        "created_at": int(payload.get("created_at") or now),
        "updated_at": int(payload.get("updated_at") or now),
    }
    if external_chat:
        task.update({
            "external_chat_provider": external_chat["provider"],
            "external_chat_lookup_hash": _external_chat_lookup_hash(master_key, external_chat),
            "encrypted_external_chat_id": _encrypt_aes_gcm_text(external_chat["id"], task_key),
            "encrypted_external_chat_title": _encrypt_aes_gcm_text(external_chat["title"], task_key),
        })
    if assignee_type == "ai":
        task["plaintext_title"] = title
        task["plaintext_description"] = str(payload.get("description") or "")
    return task


def _canonicalize_task_payload(client: OpenMates, payload: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
    result = dict(payload)
    chat_value = result.get("chat_id") if "chat_id" in result else result.get("primary_chat_id")
    if chat_value and result.get("external_chat", result.get("externalChat")) is not None:
        raise OpenMatesConfigError("A task cannot use both native chat and external chat context")
    if isinstance(chat_value, str) and chat_value:
        resolved_chat_id = _resolve_chat_id(client, chat_value)
        if "chat_id" in result:
            result["chat_id"] = resolved_chat_id
        else:
            result["primary_chat_id"] = resolved_chat_id
    if "project_ids" in result or "linked_project_ids" in result:
        key = "project_ids" if "project_ids" in result else "linked_project_ids"
        result[key] = [
            _resolve_project_id(client, project_id, personal=not bool(team_id), team_id=team_id)
            for project_id in _string_list(result.get(key) or [])
        ]
    plan_value = result.get("plan_id") if "plan_id" in result else result.get("plan")
    if isinstance(plan_value, str) and plan_value and not team_id:
        resolved_plan_id = _resolve_plan_id(client, plan_value)
        if "plan_id" in result:
            result["plan_id"] = resolved_plan_id
        else:
            result["plan"] = resolved_plan_id
    return result


def _build_task_update_input(task: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    task_key = _task_key_from_record(task.get("encrypted") if isinstance(task.get("encrypted"), dict) else task, master_key)
    patch: dict[str, Any] = {"version": int(task["version"]), "updated_at": int(time.time())}
    if "title" in payload:
        patch["encrypted_title"] = _encrypt_aes_gcm_text(str(payload.get("title") or ""), task_key)
    if "description" in payload:
        patch["encrypted_description"] = _encrypt_aes_gcm_text(str(payload.get("description") or ""), task_key)
    if "slug" in payload:
        slug_metadata = _encrypted_object_slug_metadata(str(payload.get("slug") or ""), encryption_key=task_key, lookup_key=master_key)
        patch["encrypted_slug"] = slug_metadata["encrypted_slug"]
        patch["slug_lookup_hash"] = slug_metadata["slug_lookup_hash"]
    if "status" in payload:
        patch["status"] = payload.get("status")
    if "assign" in payload or "assignee" in payload:
        assignee_type, assignee_hash = _task_assignee(payload.get("assign") or payload.get("assignee"))
        patch["assignee_type"] = assignee_type
        patch["assignee_hash"] = assignee_hash
    external_chat_supplied = "external_chat" in payload or "externalChat" in payload
    external_chat = _normalize_external_chat_context(
        payload.get("external_chat", payload.get("externalChat")),
        title=payload.get("external_chat_title", payload.get("externalChatTitle")),
    ) if external_chat_supplied else None
    native_chat_supplied = "chat_id" in payload or "primary_chat_id" in payload
    native_chat_id = payload.get("chat_id") if "chat_id" in payload else payload.get("primary_chat_id")
    if native_chat_id and external_chat:
        raise OpenMatesConfigError("A task cannot use both native chat and external chat context")
    if native_chat_supplied:
        patch.update({
            "primary_chat_id": native_chat_id,
            "external_chat_provider": None,
            "external_chat_lookup_hash": None,
            "encrypted_external_chat_id": None,
            "encrypted_external_chat_title": None,
        })
    if external_chat:
        patch.update({
            "primary_chat_id": None,
            "external_chat_provider": external_chat["provider"],
            "external_chat_lookup_hash": _external_chat_lookup_hash(master_key, external_chat),
            "encrypted_external_chat_id": _encrypt_aes_gcm_text(external_chat["id"], task_key),
            "encrypted_external_chat_title": _encrypt_aes_gcm_text(external_chat["title"], task_key),
        })
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
        "slug": _decrypt_object_slug(record.get("encrypted_slug"), task_key),
        "title": _decrypt_aes_gcm_text(str(record.get("encrypted_title") or ""), task_key) or "(untitled task)",
        "description": _decrypt_aes_gcm_text(str(record.get("encrypted_description") or ""), task_key) or "",
        "labels": labels,
        "tags": labels,
        "latest_instruction": _decrypt_aes_gcm_text(str(record.get("encrypted_latest_instruction") or ""), task_key) or "",
        "status": record.get("status"),
        "assignee_type": record.get("assignee_type"),
        "assignee_hash": record.get("assignee_hash"),
        "primary_chat_id": record.get("primary_chat_id"),
        "external_chat": {
            "provider": record["external_chat_provider"],
            "id": _decrypt_aes_gcm_text(record["encrypted_external_chat_id"], task_key) or "",
            "title": _decrypt_aes_gcm_text(str(record.get("encrypted_external_chat_title") or ""), task_key) or "",
        } if record.get("external_chat_provider") and isinstance(record.get("encrypted_external_chat_id"), str) else None,
        "linked_project_ids": linked_project_ids or _string_list(record.get("linked_project_ids") or []),
        "plan_id": record.get("plan_id"),
        "due_at": record.get("due_at"),
        "priority": int(record.get("priority") or 0),
        "priority_level": _task_priority_level(record.get("priority")),
        "position": int(record.get("position") or 0),
        "queue_state": record.get("queue_state") or "none",
        "blocked_reason_code": record.get("blocked_reason_code"),
        "blocked_reason": _decrypt_aes_gcm_text(str(record.get("encrypted_blocked_reason") or ""), task_key) or "",
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


def _plan_key_from_record(record: dict[str, Any], master_key: bytes) -> bytes:
    wrappers = record.get("key_wrappers") if isinstance(record.get("key_wrappers"), list) else []
    encrypted_plan_key = next(
        (wrapper.get("encrypted_plan_key") for wrapper in wrappers if isinstance(wrapper, dict) and wrapper.get("key_type") == "master" and isinstance(wrapper.get("encrypted_plan_key"), str)),
        None,
    )
    if not isinstance(encrypted_plan_key, str):
        raise OpenMatesConfigError(f"Plan {record.get('plan_id')} is missing a master plan key wrapper")
    plan_key = _decrypt_aes_gcm_bytes(encrypted_plan_key, master_key)
    if plan_key is None:
        raise OpenMatesConfigError(f"Failed to decrypt plan key for {record.get('plan_id')}")
    return plan_key


def _build_plan_create_input(client: OpenMates, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise OpenMatesConfigError("Plan title is required")
    goal = payload.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise OpenMatesConfigError("Plan goal is required")
    master_key = client._get_master_key()
    plan_key = os.urandom(32)
    now = int(time.time())
    linked_project_ids = [_resolve_project_id(client, project_id) for project_id in _string_list(payload.get("linked_project_ids") or payload.get("linkedProjectIds") or [])]
    primary_chat_raw = payload.get("primary_chat_id") or payload.get("primaryChatId") or None
    primary_chat_id = _resolve_chat_id(client, primary_chat_raw) if isinstance(primary_chat_raw, str) and primary_chat_raw else None
    primary_chat_key = payload.get("_primary_chat_key") if isinstance(payload.get("_primary_chat_key"), bytes) else None
    slug_metadata = _encrypted_object_slug_metadata(
        str(payload.get("slug") or title),
        encryption_key=plan_key,
        lookup_key=master_key,
    )
    return {
        "plan_id": str(payload.get("plan_id") or uuid.uuid4()),
        "version": 1,
        "encrypted_slug": slug_metadata["encrypted_slug"],
        "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
        "encrypted_title": _encrypt_aes_gcm_text(title, plan_key),
        "encrypted_goal": _encrypt_aes_gcm_text(goal, plan_key),
        "encrypted_scope_in": _encrypt_aes_gcm_text(str(payload.get("scope_in") or payload.get("scopeIn") or ""), plan_key),
        "encrypted_scope_out": _encrypt_aes_gcm_text(str(payload.get("scope_out") or payload.get("scopeOut") or ""), plan_key),
        "encrypted_user_flows": _encrypt_aes_gcm_text(_serialize_plan_user_flows(payload.get("user_flows") if "user_flows" in payload else payload.get("userFlows")), plan_key) if ("user_flows" in payload or "userFlows" in payload) else None,
        "encrypted_assumptions": _encrypt_aes_gcm_text(str(payload.get("assumptions") or ""), plan_key),
        "encrypted_open_questions": _encrypt_aes_gcm_text(str(payload.get("open_questions") or payload.get("openQuestions") or ""), plan_key),
        "encrypted_constraints": _encrypt_aes_gcm_text(str(payload.get("constraints") or ""), plan_key),
        "encrypted_decisions": _encrypt_aes_gcm_text(str(payload.get("decisions") or ""), plan_key),
        "encrypted_risks": _encrypt_aes_gcm_text(str(payload.get("risks") or ""), plan_key),
        "encrypted_reference_patterns": _encrypt_aes_gcm_text(str(payload.get("reference_patterns") or payload.get("referencePatterns") or ""), plan_key),
        "encrypted_context": _encrypt_aes_gcm_text(str(payload.get("context") or ""), plan_key),
        "encrypted_linked_project_ids": _encrypt_aes_gcm_text(json.dumps(linked_project_ids), plan_key),
        "status": payload.get("status") or "draft",
        "primary_chat_id": primary_chat_id,
        "linked_project_ids": linked_project_ids,
        "planner_focus_id": payload.get("planner_focus_id") or payload.get("plannerFocusId"),
        "created_at": int(payload.get("created_at") or now),
        "updated_at": int(payload.get("updated_at") or now),
        "key_wrappers": _build_plan_key_wrappers(client, plan_key, primary_chat_id=primary_chat_id if isinstance(primary_chat_id, str) else None, primary_chat_key=primary_chat_key, linked_project_ids=linked_project_ids, created_at=now),
    }


def _decrypt_plan_record(record: dict[str, Any], master_key: bytes) -> dict[str, Any]:
    plan_key = _plan_key_from_record(record, master_key)
    linked_project_ids = _json_string_list(_decrypt_aes_gcm_text(str(record.get("encrypted_linked_project_ids") or ""), plan_key)) or _string_list(record.get("linked_project_ids") or [])
    return {
        "plan_id": record.get("plan_id"),
        "short_id": _derive_plan_short_id(record),
        "slug": _decrypt_object_slug(record.get("encrypted_slug"), plan_key),
        "title": _decrypt_aes_gcm_text(str(record.get("encrypted_title") or ""), plan_key) or "(untitled plan)",
        "goal": _decrypt_aes_gcm_text(str(record.get("encrypted_goal") or ""), plan_key) or "",
        "scope_in": _decrypt_aes_gcm_text(str(record.get("encrypted_scope_in") or ""), plan_key) or "",
        "scope_out": _decrypt_aes_gcm_text(str(record.get("encrypted_scope_out") or ""), plan_key) or "",
        "user_flows": _parse_plan_user_flows(_decrypt_aes_gcm_text(str(record.get("encrypted_user_flows") or ""), plan_key) or ""),
        "assumptions": _decrypt_aes_gcm_text(str(record.get("encrypted_assumptions") or ""), plan_key) or "",
        "open_questions": _decrypt_aes_gcm_text(str(record.get("encrypted_open_questions") or ""), plan_key) or "",
        "constraints": _decrypt_aes_gcm_text(str(record.get("encrypted_constraints") or ""), plan_key) or "",
        "decisions": _decrypt_aes_gcm_text(str(record.get("encrypted_decisions") or ""), plan_key) or "",
        "risks": _decrypt_aes_gcm_text(str(record.get("encrypted_risks") or ""), plan_key) or "",
        "reference_patterns": _decrypt_aes_gcm_text(str(record.get("encrypted_reference_patterns") or ""), plan_key) or "",
        "context": _decrypt_aes_gcm_text(str(record.get("encrypted_context") or ""), plan_key) or "",
        "status": record.get("status"),
        "primary_chat_id": record.get("primary_chat_id"),
        "linked_project_ids": linked_project_ids,
        "planner_focus_id": record.get("planner_focus_id"),
        "version": int(record.get("version") or 1),
        "created_at": int(record.get("created_at") or 0),
        "updated_at": int(record.get("updated_at") or 0),
        "completed_at": record.get("completed_at"),
        "encrypted": record,
    }


def _build_plan_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    source = plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan
    plan_key = _plan_key_from_record(source, master_key)
    client = payload.get("_client") if isinstance(payload.get("_client"), OpenMates) else None
    patch: dict[str, Any] = {"version": int(plan.get("version") or source.get("version") or 1), "updated_at": int(time.time())}
    text_fields = {
        "title": "encrypted_title",
        "goal": "encrypted_goal",
        "scope_in": "encrypted_scope_in",
        "scopeIn": "encrypted_scope_in",
        "scope_out": "encrypted_scope_out",
        "scopeOut": "encrypted_scope_out",
        "user_flows": "encrypted_user_flows",
        "userFlows": "encrypted_user_flows",
        "assumptions": "encrypted_assumptions",
        "open_questions": "encrypted_open_questions",
        "openQuestions": "encrypted_open_questions",
        "constraints": "encrypted_constraints",
        "decisions": "encrypted_decisions",
        "risks": "encrypted_risks",
        "reference_patterns": "encrypted_reference_patterns",
        "referencePatterns": "encrypted_reference_patterns",
        "context": "encrypted_context",
    }
    for public_name, storage_name in text_fields.items():
        if public_name in payload:
            value = _serialize_plan_user_flows(payload.get(public_name)) if public_name in {"user_flows", "userFlows"} else str(payload.get(public_name) or "")
            patch[storage_name] = _encrypt_aes_gcm_text(value, plan_key)
    if "slug" in payload:
        slug_metadata = _encrypted_object_slug_metadata(str(payload.get("slug") or ""), encryption_key=plan_key, lookup_key=master_key)
        patch["encrypted_slug"] = slug_metadata["encrypted_slug"]
        patch["slug_lookup_hash"] = slug_metadata["slug_lookup_hash"]
    if "status" in payload:
        patch["status"] = payload.get("status")
    linked_project_ids = _string_list(plan.get("linked_project_ids") or [])
    primary_chat_id = plan.get("primary_chat_id") if isinstance(plan.get("primary_chat_id"), str) else None
    linked_changed = "linked_project_ids" in payload or "linkedProjectIds" in payload
    primary_changed = "primary_chat_id" in payload or "primaryChatId" in payload
    if linked_changed:
        linked_project_ids = _string_list(payload.get("linked_project_ids") or payload.get("linkedProjectIds") or [])
        if client is not None:
            linked_project_ids = [_resolve_project_id(client, project_id) for project_id in linked_project_ids]
        patch["linked_project_ids"] = linked_project_ids
        patch["encrypted_linked_project_ids"] = _encrypt_aes_gcm_text(json.dumps(linked_project_ids), plan_key)
    if primary_changed:
        raw_primary_chat_id = payload.get("primary_chat_id") if "primary_chat_id" in payload else payload.get("primaryChatId")
        primary_chat_id = _resolve_chat_id(client, raw_primary_chat_id) if client is not None and isinstance(raw_primary_chat_id, str) and raw_primary_chat_id else raw_primary_chat_id
        patch["primary_chat_id"] = primary_chat_id
    if client is not None and (linked_changed or primary_changed):
        patch["key_wrappers"] = _build_plan_key_wrappers(client=client, plan_key=plan_key, primary_chat_id=primary_chat_id if isinstance(primary_chat_id, str) else None, linked_project_ids=linked_project_ids, created_at=patch["updated_at"])
    return {key: value for key, value in patch.items() if value is not None}


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "encrypted"}


def _plan_child_value(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload.get(name)
    return None


def _omit_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _decrypt_plan_child_text(record: dict[str, Any], plan_key: bytes, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        return ""
    return _decrypt_aes_gcm_text(value, plan_key) or ""


def _public_plan_criterion(record: dict[str, Any], plan_key: bytes) -> dict[str, Any]:
    return {
        "criterion_id": record.get("criterion_id"),
        "text": _decrypt_plan_child_text(record, plan_key, "encrypted_text"),
        "type": record.get("type"),
        "status": record.get("status"),
        "required": record.get("required"),
        "linked_task_ids": _string_list(record.get("linked_task_ids") or []),
        "verification_ids": _string_list(record.get("verification_ids") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _public_plan_assumption(record: dict[str, Any], plan_key: bytes) -> dict[str, Any]:
    return {
        "assumption_id": record.get("assumption_id"),
        "text": _decrypt_plan_child_text(record, plan_key, "encrypted_text"),
        "category": record.get("category"),
        "status": record.get("status"),
        "required_before": record.get("required_before"),
        "linked_sub_chat_id": record.get("linked_sub_chat_id"),
        "linked_task_id": record.get("linked_task_id"),
        "linked_criterion_ids": _string_list(record.get("linked_criterion_ids") or []),
        "source_count": record.get("source_count"),
        "corrected_text": _decrypt_plan_child_text(record, plan_key, "encrypted_corrected_text"),
        "evidence_summary": _decrypt_plan_child_text(record, plan_key, "encrypted_evidence_summary"),
        "blocker_reason": _decrypt_plan_child_text(record, plan_key, "encrypted_blocker_reason"),
        "waiver_reason": _decrypt_plan_child_text(record, plan_key, "encrypted_waiver_reason"),
        "sources": _decrypt_plan_child_text(record, plan_key, "encrypted_sources"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _public_plan_reference_pattern(record: dict[str, Any], plan_key: bytes) -> dict[str, Any]:
    return {
        "pattern_id": record.get("pattern_id"),
        "title": _decrypt_plan_child_text(record, plan_key, "encrypted_title") or "(untitled pattern)",
        "description": _decrypt_plan_child_text(record, plan_key, "encrypted_description"),
        "category": record.get("category"),
        "status": record.get("status"),
        "required_before": record.get("required_before"),
        "source_count": record.get("source_count"),
        "linked_task_ids": _string_list(record.get("linked_task_ids") or []),
        "linked_check_ids": _string_list(record.get("linked_check_ids") or []),
        "sources": _decrypt_plan_child_text(record, plan_key, "encrypted_sources"),
        "match_rules": _decrypt_plan_child_text(record, plan_key, "encrypted_match_rules"),
        "anti_patterns": _decrypt_plan_child_text(record, plan_key, "encrypted_anti_patterns"),
        "evidence_summary": _decrypt_plan_child_text(record, plan_key, "encrypted_evidence_summary"),
        "waiver_reason": _decrypt_plan_child_text(record, plan_key, "encrypted_waiver_reason"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _public_plan_verification(record: dict[str, Any], plan_key: bytes) -> dict[str, Any]:
    return {
        "verification_id": record.get("verification_id"),
        "kind": record.get("kind"),
        "phase": record.get("phase"),
        "status": record.get("status"),
        "required_for_done": record.get("required_for_done"),
        "covers": _string_list(record.get("covers") or []),
        "source_hash": record.get("source_hash"),
        "threshold": record.get("threshold"),
        "score": record.get("score"),
        "confidence": record.get("confidence"),
        "linked_task_id": record.get("linked_task_id"),
        "run_id": record.get("run_id"),
        "lifecycle_status": record.get("lifecycle_status"),
        "linked_sub_chat_id": record.get("linked_sub_chat_id"),
        "source_embed_id": record.get("source_embed_id"),
        "runner_kind": record.get("runner_kind"),
        "description": _decrypt_plan_child_text(record, plan_key, "encrypted_description"),
        "command": _decrypt_plan_child_text(record, plan_key, "encrypted_command"),
        "evaluation_prompt": _decrypt_plan_child_text(record, plan_key, "encrypted_evaluation_prompt"),
        "evaluator_instructions": _decrypt_plan_child_text(record, plan_key, "encrypted_evaluator_instructions"),
        "expected_result": _decrypt_plan_child_text(record, plan_key, "encrypted_expected_result"),
        "source_path": _decrypt_plan_child_text(record, plan_key, "encrypted_source_path"),
        "red_phase_reason": _decrypt_plan_child_text(record, plan_key, "encrypted_red_phase_reason"),
        "result_summary": _decrypt_plan_child_text(record, plan_key, "encrypted_result_summary"),
        "required_fixes": _decrypt_plan_child_text(record, plan_key, "encrypted_required_fixes"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _public_plan_learning(record: dict[str, Any], plan_key: bytes) -> dict[str, Any]:
    return {
        "learning_id": record.get("learning_id"),
        "type": record.get("type"),
        "target_kind": record.get("target_kind"),
        "status": record.get("status"),
        "severity": record.get("severity"),
        "confidence": record.get("confidence"),
        "linked_task_ids": _string_list(record.get("linked_task_ids") or []),
        "linked_check_ids": _string_list(record.get("linked_check_ids") or []),
        "applied_task_id": record.get("applied_task_id"),
        "title": _decrypt_plan_child_text(record, plan_key, "encrypted_title") or "(untitled learning)",
        "observation": _decrypt_plan_child_text(record, plan_key, "encrypted_observation"),
        "root_cause": _decrypt_plan_child_text(record, plan_key, "encrypted_root_cause"),
        "suggested_change": _decrypt_plan_child_text(record, plan_key, "encrypted_suggested_change"),
        "evidence_summary": _decrypt_plan_child_text(record, plan_key, "encrypted_evidence_summary"),
        "task_draft": _decrypt_plan_child_text(record, plan_key, "encrypted_task_draft"),
        "rejection_reason": _decrypt_plan_child_text(record, plan_key, "encrypted_rejection_reason"),
        "version": record.get("version"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _build_plan_criterion_create_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    now = int(time.time())
    return _omit_none({
        "criterion_id": str(_plan_child_value(payload, "criterion_id", "criterionId") or uuid.uuid4()),
        "encrypted_text": _encrypt_aes_gcm_text(str(_plan_child_value(payload, "text") or ""), plan_key),
        "type": _plan_child_value(payload, "type"),
        "status": _plan_child_value(payload, "status"),
        "required": _plan_child_value(payload, "required"),
        "linked_task_ids": _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or []),
        "verification_ids": _string_list(_plan_child_value(payload, "verification_ids", "verificationIds") or []),
        "created_at": now,
        "updated_at": now,
    })


def _build_plan_criterion_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    for public_name, storage_name in (("status", "status"), ("required", "required")):
        if public_name in payload:
            patch[storage_name] = payload.get(public_name)
    if "linked_task_ids" in payload or "linkedTaskIds" in payload:
        patch["linked_task_ids"] = _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or [])
    if "verification_ids" in payload or "verificationIds" in payload:
        patch["verification_ids"] = _string_list(_plan_child_value(payload, "verification_ids", "verificationIds") or [])
    for public_name, storage_name in (("evidence", "encrypted_evidence"), ("coverage_note", "encrypted_coverage_note"), ("coverageNote", "encrypted_coverage_note"), ("waiver_reason", "encrypted_waiver_reason"), ("waiverReason", "encrypted_waiver_reason")):
        if public_name in payload:
            patch[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return patch


def _serialize_assumption_proof_inputs(value: Any) -> str:
    if not isinstance(value, list) or not value:
        raise OpenMatesConfigError("proof_inputs must contain at least one typed proof")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in {"embed", "file", "url"}:
            raise OpenMatesConfigError("proof_inputs entries must use embed, file, or url kinds")
        kind = str(item["kind"])
        if kind == "embed":
            embed_id = str(item.get("embed_id") or item.get("embedId") or "").strip()
            if not embed_id:
                raise OpenMatesConfigError("embed proof requires embed_id")
            normalized.append({"kind": kind, "embed_id": embed_id})
        elif kind == "url":
            url = str(item.get("url") or "")
            if urlparse(url).scheme != "https":
                raise OpenMatesConfigError("URL proof requires HTTPS")
            normalized.append({"kind": kind, "url": url})
        else:
            path = str(item.get("path") or "")
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise OpenMatesConfigError("file proof path must be repository-relative")
            entry: dict[str, Any] = {"kind": kind, "path": path}
            for source, target in (("start_line", "start_line"), ("startLine", "start_line"), ("end_line", "end_line"), ("endLine", "end_line")):
                if source in item:
                    if not isinstance(item[source], int) or item[source] < 1:
                        raise OpenMatesConfigError(f"file proof {source} must be a positive integer")
                    entry[target] = item[source]
            if entry.get("end_line", 0) < entry.get("start_line", 1):
                raise OpenMatesConfigError("file proof end_line must not precede start_line")
            normalized.append(entry)
    return json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def _build_plan_assumption_create_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    now = int(time.time())
    output = {
        "assumption_id": str(_plan_child_value(payload, "assumption_id", "assumptionId") or uuid.uuid4()),
        "encrypted_text": _encrypt_aes_gcm_text(str(_plan_child_value(payload, "text") or ""), plan_key),
        "category": _plan_child_value(payload, "category"),
        "status": _plan_child_value(payload, "status"),
        "required_before": _plan_child_value(payload, "required_before", "requiredBefore"),
        "linked_sub_chat_id": _plan_child_value(payload, "linked_sub_chat_id", "linkedSubChatId"),
        "linked_task_id": _plan_child_value(payload, "linked_task_id", "linkedTaskId"),
        "linked_criterion_ids": _string_list(_plan_child_value(payload, "linked_criterion_ids", "linkedCriterionIds") or []),
        "source_count": _plan_child_value(payload, "source_count", "sourceCount"),
        "created_at": now,
        "updated_at": now,
    }
    if "proof_inputs" in payload or "proofInputs" in payload:
        output["encrypted_sources"] = _encrypt_aes_gcm_text(_serialize_assumption_proof_inputs(payload.get("proof_inputs") or payload.get("proofInputs")), plan_key)
    for public_name, storage_name in (("corrected_text", "encrypted_corrected_text"), ("correctedText", "encrypted_corrected_text"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("blocker_reason", "encrypted_blocker_reason"), ("blockerReason", "encrypted_blocker_reason"), ("waiver_reason", "encrypted_waiver_reason"), ("waiverReason", "encrypted_waiver_reason"), ("sources", "encrypted_sources")):
        if public_name in payload:
            output[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return _omit_none(output)


def _build_plan_assumption_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    for public_name, storage_name in (("category", "category"), ("status", "status"), ("required_before", "required_before"), ("requiredBefore", "required_before"), ("linked_sub_chat_id", "linked_sub_chat_id"), ("linkedSubChatId", "linked_sub_chat_id"), ("linked_task_id", "linked_task_id"), ("linkedTaskId", "linked_task_id"), ("source_count", "source_count"), ("sourceCount", "source_count")):
        if public_name in payload:
            patch[storage_name] = payload.get(public_name)
    if "proof_inputs" in payload or "proofInputs" in payload:
        patch["encrypted_sources"] = _encrypt_aes_gcm_text(_serialize_assumption_proof_inputs(payload.get("proof_inputs") or payload.get("proofInputs")), plan_key)
    for public_name, storage_name in (("corrected_text", "encrypted_corrected_text"), ("correctedText", "encrypted_corrected_text"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("blocker_reason", "encrypted_blocker_reason"), ("blockerReason", "encrypted_blocker_reason"), ("waiver_reason", "encrypted_waiver_reason"), ("waiverReason", "encrypted_waiver_reason"), ("sources", "encrypted_sources")):
        if public_name in payload:
            patch[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return patch


def _build_plan_reference_pattern_create_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    now = int(time.time())
    output = {
        "pattern_id": str(_plan_child_value(payload, "pattern_id", "patternId") or uuid.uuid4()),
        "encrypted_title": _encrypt_aes_gcm_text(str(_plan_child_value(payload, "title") or ""), plan_key),
        "category": _plan_child_value(payload, "category"),
        "status": _plan_child_value(payload, "status"),
        "required_before": _plan_child_value(payload, "required_before", "requiredBefore"),
        "source_count": _plan_child_value(payload, "source_count", "sourceCount"),
        "linked_task_ids": _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or []),
        "linked_check_ids": _string_list(_plan_child_value(payload, "linked_check_ids", "linkedCheckIds") or []),
        "created_at": now,
        "updated_at": now,
    }
    for public_name, storage_name in (("description", "encrypted_description"), ("sources", "encrypted_sources"), ("match_rules", "encrypted_match_rules"), ("matchRules", "encrypted_match_rules"), ("anti_patterns", "encrypted_anti_patterns"), ("antiPatterns", "encrypted_anti_patterns"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("waiver_reason", "encrypted_waiver_reason"), ("waiverReason", "encrypted_waiver_reason")):
        if public_name in payload:
            output[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return _omit_none(output)


def _build_plan_reference_pattern_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    for public_name, storage_name in (("category", "category"), ("status", "status"), ("required_before", "required_before"), ("requiredBefore", "required_before"), ("source_count", "source_count"), ("sourceCount", "source_count")):
        if public_name in payload:
            patch[storage_name] = payload.get(public_name)
    if "linked_task_ids" in payload or "linkedTaskIds" in payload:
        patch["linked_task_ids"] = _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or [])
    if "linked_check_ids" in payload or "linkedCheckIds" in payload:
        patch["linked_check_ids"] = _string_list(_plan_child_value(payload, "linked_check_ids", "linkedCheckIds") or [])
    for public_name, storage_name in (("description", "encrypted_description"), ("sources", "encrypted_sources"), ("match_rules", "encrypted_match_rules"), ("matchRules", "encrypted_match_rules"), ("anti_patterns", "encrypted_anti_patterns"), ("antiPatterns", "encrypted_anti_patterns"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("waiver_reason", "encrypted_waiver_reason"), ("waiverReason", "encrypted_waiver_reason")):
        if public_name in payload:
            patch[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return patch


def _build_plan_verification_create_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    now = int(time.time())
    output = {
        "verification_id": str(_plan_child_value(payload, "verification_id", "verificationId") or uuid.uuid4()),
        "kind": _plan_child_value(payload, "kind"),
        "phase": _plan_child_value(payload, "phase"),
        "status": _plan_child_value(payload, "status") or "pending",
        "required_for_done": _plan_child_value(payload, "required_for_done", "requiredForDone"),
        "covers": _string_list(_plan_child_value(payload, "covers") or []),
        "threshold": _plan_child_value(payload, "threshold"),
        "score": _plan_child_value(payload, "score"),
        "confidence": _plan_child_value(payload, "confidence"),
        "linked_task_id": _plan_child_value(payload, "linked_task_id", "linkedTaskId"),
        "run_id": _plan_child_value(payload, "run_id", "runId"),
        "created_at": now,
        "updated_at": now,
    }
    for public_name, storage_name in (("description", "encrypted_description"), ("command", "encrypted_command"), ("evaluation_prompt", "encrypted_evaluation_prompt"), ("evaluationPrompt", "encrypted_evaluation_prompt"), ("evaluator_instructions", "encrypted_evaluator_instructions"), ("evaluatorInstructions", "encrypted_evaluator_instructions"), ("expected_result", "encrypted_expected_result"), ("expectedResult", "encrypted_expected_result"), ("source_path", "encrypted_source_path"), ("sourcePath", "encrypted_source_path"), ("red_phase_reason", "encrypted_red_phase_reason"), ("redPhaseReason", "encrypted_red_phase_reason")):
        if public_name in payload:
            output[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return _omit_none(output)


def _build_plan_verification_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    for public_name, storage_name in (("kind", "kind"), ("phase", "phase"), ("status", "status"), ("lifecycle_status", "lifecycle_status"), ("lifecycleStatus", "lifecycle_status"), ("required_for_done", "required_for_done"), ("requiredForDone", "required_for_done"), ("source_hash", "source_hash"), ("sourceHash", "source_hash"), ("threshold", "threshold"), ("score", "score"), ("confidence", "confidence"), ("linked_sub_chat_id", "linked_sub_chat_id"), ("linkedSubChatId", "linked_sub_chat_id"), ("source_embed_id", "source_embed_id"), ("sourceEmbedId", "source_embed_id"), ("runner_kind", "runner_kind"), ("runnerKind", "runner_kind")):
        if public_name in payload:
            patch[storage_name] = payload.get(public_name)
    if "covers" in payload:
        patch["covers"] = _string_list(payload.get("covers") or [])
    for public_name, storage_name in (("description", "encrypted_description"), ("command", "encrypted_command"), ("evaluation_prompt", "encrypted_evaluation_prompt"), ("evaluationPrompt", "encrypted_evaluation_prompt"), ("evaluator_instructions", "encrypted_evaluator_instructions"), ("evaluatorInstructions", "encrypted_evaluator_instructions"), ("expected_result", "encrypted_expected_result"), ("expectedResult", "encrypted_expected_result"), ("source_path", "encrypted_source_path"), ("sourcePath", "encrypted_source_path"), ("red_phase_reason", "encrypted_red_phase_reason"), ("redPhaseReason", "encrypted_red_phase_reason")):
        if public_name in payload:
            patch[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return patch


def _build_plan_verification_evidence_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    output = {
        "status": _plan_child_value(payload, "status"),
        "score": _plan_child_value(payload, "score"),
        "threshold": _plan_child_value(payload, "threshold"),
        "confidence": _plan_child_value(payload, "confidence"),
        "run_id": _plan_child_value(payload, "run_id", "runId"),
        "updated_at": int(time.time()),
    }
    for public_name, storage_name in (("result_summary", "encrypted_result_summary"), ("resultSummary", "encrypted_result_summary"), ("required_fixes", "encrypted_required_fixes"), ("requiredFixes", "encrypted_required_fixes")):
        if public_name in payload:
            output[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return _omit_none(output)


def _build_plan_learning_create_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    now = int(time.time())
    output = {
        "learning_id": str(_plan_child_value(payload, "learning_id", "learningId") or uuid.uuid4()),
        "type": _plan_child_value(payload, "type"),
        "target_kind": _plan_child_value(payload, "target_kind", "targetKind"),
        "status": _plan_child_value(payload, "status") or "draft",
        "severity": _plan_child_value(payload, "severity") or "medium",
        "confidence": _plan_child_value(payload, "confidence") or "medium",
        "linked_task_ids": _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or []),
        "linked_check_ids": _string_list(_plan_child_value(payload, "linked_check_ids", "linkedCheckIds") or []),
        "encrypted_title": _encrypt_aes_gcm_text(str(_plan_child_value(payload, "title") or ""), plan_key),
        "created_at": now,
        "updated_at": now,
    }
    for public_name, storage_name in (("observation", "encrypted_observation"), ("root_cause", "encrypted_root_cause"), ("rootCause", "encrypted_root_cause"), ("suggested_change", "encrypted_suggested_change"), ("suggestedChange", "encrypted_suggested_change"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("task_draft", "encrypted_task_draft"), ("taskDraft", "encrypted_task_draft"), ("rejection_reason", "encrypted_rejection_reason"), ("rejectionReason", "encrypted_rejection_reason")):
        if public_name in payload:
            output[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return _omit_none(output)


def _build_plan_learning_update_input(plan: dict[str, Any], master_key: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    plan_key = _plan_key_from_record(plan.get("encrypted") if isinstance(plan.get("encrypted"), dict) else plan, master_key)
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    for public_name, storage_name in (("status", "status"), ("severity", "severity"), ("confidence", "confidence"), ("applied_task_id", "applied_task_id"), ("appliedTaskId", "applied_task_id")):
        if public_name in payload:
            patch[storage_name] = payload.get(public_name)
    if "linked_task_ids" in payload or "linkedTaskIds" in payload:
        patch["linked_task_ids"] = _string_list(_plan_child_value(payload, "linked_task_ids", "linkedTaskIds") or [])
    if "linked_check_ids" in payload or "linkedCheckIds" in payload:
        patch["linked_check_ids"] = _string_list(_plan_child_value(payload, "linked_check_ids", "linkedCheckIds") or [])
    for public_name, storage_name in (("title", "encrypted_title"), ("observation", "encrypted_observation"), ("root_cause", "encrypted_root_cause"), ("rootCause", "encrypted_root_cause"), ("suggested_change", "encrypted_suggested_change"), ("suggestedChange", "encrypted_suggested_change"), ("evidence_summary", "encrypted_evidence_summary"), ("evidenceSummary", "encrypted_evidence_summary"), ("task_draft", "encrypted_task_draft"), ("taskDraft", "encrypted_task_draft"), ("rejection_reason", "encrypted_rejection_reason"), ("rejectionReason", "encrypted_rejection_reason")):
        if public_name in payload:
            patch[storage_name] = _encrypt_aes_gcm_text(str(payload.get(public_name) or ""), plan_key)
    return patch


def _derive_plan_short_id(record: dict[str, Any]) -> str:
    source = str(record.get("plan_id") or f"{record.get('created_at', '')}-{record.get('updated_at', '')}")
    return f"PLAN-{int(hashlib.sha256(source.encode('utf-8')).hexdigest()[:4], 16) % 10000}"


def _build_project_create_input(wrapping_key: bytes, payload: dict[str, Any], team_id: str | None = None) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise OpenMatesConfigError("Project name is required")
    project_key = os.urandom(32)
    now = int(time.time())
    slug_metadata = _encrypted_object_slug_metadata(
        str(payload.get("slug") or name),
        encryption_key=project_key,
        lookup_key=wrapping_key,
    )
    result = {
        "project_id": str(payload.get("project_id") or uuid.uuid4()),
        "encrypted_project_key": None if team_id else _encrypt_aes_gcm_bytes(project_key, wrapping_key),
        "encrypted_slug": slug_metadata["encrypted_slug"],
        "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
        "encrypted_name": _encrypt_aes_gcm_text(name, project_key),
        "encrypted_description": _encrypt_aes_gcm_text(str(payload.get("description") or ""), project_key),
        "encrypted_icon": _encrypt_aes_gcm_text(str(payload.get("icon") or "folder"), project_key),
        "encrypted_color": _encrypt_aes_gcm_text(str(payload.get("color") or "default"), project_key),
        "pinned": payload.get("pinned") is True,
        "archived": payload.get("archived") is True,
        "created_at": now,
        "updated_at": now,
        "last_opened_at": now,
    }
    result["key_wrappers"] = [{
        "key_type": "team",
        "hashed_team_id": hashlib.sha256(team_id.encode("utf-8")).hexdigest(),
        "team_key_epoch": 1,
        "encrypted_project_key": _encrypt_aes_gcm_bytes(project_key, wrapping_key),
        "wrapper_version": 1,
        "created_at": now,
    }] if team_id else []
    return result


def _decrypt_project_record(record: dict[str, Any], master_key: bytes) -> dict[str, Any]:
    encrypted_project_key = record.get("encrypted_project_key")
    if not isinstance(encrypted_project_key, str):
        raise OpenMatesConfigError(f"Project {record.get('project_id')} is missing encrypted project key")
    project_key = _decrypt_aes_gcm_bytes(encrypted_project_key, master_key)
    if project_key is None:
        raise OpenMatesConfigError(f"Failed to decrypt Project key for {record.get('project_id')}")
    return _decrypt_project_record_with_key(record, project_key)


def _decrypt_project_record_with_key(record: dict[str, Any], project_key: bytes) -> dict[str, Any]:
    return {
        "project_id": record.get("project_id"),
        "slug": _decrypt_object_slug(record.get("encrypted_slug"), project_key),
        "name": _decrypt_aes_gcm_text(str(record.get("encrypted_name") or ""), project_key) or "(untitled project)",
        "description": _decrypt_aes_gcm_text(str(record.get("encrypted_description") or ""), project_key) or "",
        "icon": _decrypt_aes_gcm_text(str(record.get("encrypted_icon") or ""), project_key) or "",
        "color": _decrypt_aes_gcm_text(str(record.get("encrypted_color") or ""), project_key) or "",
        "pinned": record.get("pinned") is True,
        "archived": record.get("archived") is True,
        "version": record.get("version"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "last_opened_at": record.get("last_opened_at"),
        "encrypted": record,
    }


def _public_project(project: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in project.items() if key != "encrypted"}


def _build_project_update_input(
    client: OpenMates,
    update: dict[str, Any],
    *,
    personal: bool = True,
    team_id: str | None = None,
) -> dict[str, Any]:
    project_id = str(update.get("project_id") or update.get("projectId") or "")
    resolved_project_id = _resolve_project_id(client, project_id, personal=personal, team_id=team_id)
    project_key = _resolve_project_key(client, resolved_project_id, personal=personal, team_id=team_id)
    patch_input = dict(update.get("patch") or {})
    patch: dict[str, Any] = {"updated_at": int(time.time())}
    if "name" in patch_input:
        patch["encrypted_name"] = _encrypt_aes_gcm_text(str(patch_input.get("name") or ""), project_key)
    if "description" in patch_input:
        patch["encrypted_description"] = _encrypt_aes_gcm_text(str(patch_input.get("description") or ""), project_key)
    if "icon" in patch_input:
        patch["encrypted_icon"] = _encrypt_aes_gcm_text(str(patch_input.get("icon") or ""), project_key)
    if "color" in patch_input:
        patch["encrypted_color"] = _encrypt_aes_gcm_text(str(patch_input.get("color") or ""), project_key)
    if "slug" in patch_input:
        wrapping_key = _project_wrapping_key(client, team_id)
        slug_metadata = _encrypted_object_slug_metadata(str(patch_input.get("slug") or ""), encryption_key=project_key, lookup_key=wrapping_key)
        patch["encrypted_slug"] = slug_metadata["encrypted_slug"]
        patch["slug_lookup_hash"] = slug_metadata["slug_lookup_hash"]
    if "pinned" in patch_input:
        patch["pinned"] = patch_input.get("pinned") is True
    if "archived" in patch_input:
        patch["archived"] = patch_input.get("archived") is True
    return {"project_id": resolved_project_id, "patch": patch}


def _append_unique_id(existing: list[str], item_id: str) -> list[str]:
    return existing if item_id in existing else [*existing, item_id]


def _remove_id(existing: list[str], item_id: str) -> list[str]:
    return [existing_id for existing_id in existing if existing_id != item_id]


def _find_plan(plans: list[dict[str, Any]], plan_id: str) -> dict[str, Any]:
    for plan in plans:
        if plan.get("plan_id") == plan_id:
            return plan
    slug_matches = [plan for plan in plans if _object_slug_matches(plan.get("slug"), plan_id)]
    if len(slug_matches) > 1:
        raise OpenMatesConfigError(f"Plan slug '{plan_id}' is ambiguous. Use the full plan ID")
    if slug_matches:
        return slug_matches[0]
    short_id_matches = [plan for plan in plans if str(plan.get("short_id") or "").upper() == plan_id.upper()]
    if len(short_id_matches) > 1:
        raise OpenMatesConfigError(f"Plan '{plan_id}' is ambiguous. Use the full plan ID")
    if short_id_matches:
        return short_id_matches[0]
    matches = [plan for plan in plans if str(plan.get("plan_id") or "").startswith(plan_id)]
    if len(matches) > 1:
        raise OpenMatesConfigError(f"Plan '{plan_id}' is ambiguous. Use the full plan ID")
    if not matches:
        raise OpenMatesConfigError(f"Plan '{plan_id}' was not found")
    return matches[0]


def _resolve_plan_id(client: OpenMates, plan_id: str) -> str:
    if _is_uuid(plan_id):
        return plan_id
    return str(_find_plan(client.plans.list(active_only=False), plan_id).get("plan_id"))


def _find_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task.get("task_id") == task_id:
            return task
    slug_matches = [task for task in tasks if _object_slug_matches(task.get("slug"), task_id)]
    if len(slug_matches) > 1:
        raise OpenMatesConfigError(f"Task slug '{task_id}' is ambiguous. Use the full task ID.")
    if slug_matches:
        return slug_matches[0]
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


def _normalize_external_chat_context(value: Any, *, title: Any = None) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        provider, separator, chat_id = value.partition(":")
        provider = provider.strip().lower()
        chat_id = chat_id.strip()
        if not separator or not provider or not chat_id:
            raise OpenMatesConfigError("external_chat must use provider:id")
        context_title = title
    elif isinstance(value, dict):
        provider = str(value.get("provider") or "").strip().lower()
        chat_id = str(value.get("id") or "").strip()
        context_title = value.get("title") if title is None else title
        if not provider or not chat_id:
            raise OpenMatesConfigError("external_chat requires provider and id")
    else:
        raise OpenMatesConfigError("external_chat must be provider:id or a mapping")
    if provider != EXTERNAL_CHAT_PROVIDER:
        raise OpenMatesConfigError("Only opencode is supported as an external chat provider")
    return {"provider": EXTERNAL_CHAT_PROVIDER, "id": chat_id, "title": str(context_title or "")}


def _external_chat_lookup_hash(master_key: bytes, context: dict[str, str]) -> str:
    index_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=EXTERNAL_CHAT_INDEX_INFO,
    ).derive(master_key)
    value = f"{context['provider']}\x00{context['id']}".encode("utf-8")
    return hmac.new(index_key, value, hashlib.sha256).hexdigest()


def _normalize_blocked_reason_code(value: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", value.strip().lower())
    if normalized not in BLOCKED_REASON_CODES:
        raise OpenMatesConfigError(
            f"Unknown blocked reason code '{value}'. Expected one of: {', '.join(BLOCKED_REASON_CODES)}"
        )
    return normalized


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


def _serialize_plan_user_flows(value: Any) -> str:
    if not isinstance(value, list):
        raise OpenMatesConfigError("Plan user_flows must be a structured array")
    for flow in value:
        if not isinstance(flow, dict) or not all(isinstance(flow.get(field), str) and flow[field] for field in ("flow_id", "title", "expected_outcome")):
            raise OpenMatesConfigError("Each Plan user flow requires flow_id, title, and expected_outcome")
        steps = flow.get("steps")
        if not isinstance(steps, list) or any(not isinstance(step, dict) or not isinstance(step.get("step_id"), str) or not isinstance(step.get("text"), str) for step in steps):
            raise OpenMatesConfigError("Each Plan user flow requires ordered steps with step_id and text")
        for step in steps:
            references = step.get("references", [])
            if not isinstance(references, list):
                raise OpenMatesConfigError("Plan user flow references must be an array")
            for reference in references:
                _validate_plan_evidence_reference(reference)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _validate_plan_evidence_reference(reference: Any) -> None:
    if not isinstance(reference, dict) or reference.get("kind") not in {"embed", "file", "url"}:
        raise OpenMatesConfigError("Plan evidence references must be embed, file, or URL records")
    kind = reference["kind"]
    if kind == "embed" and not isinstance(reference.get("embed_id"), str):
        raise OpenMatesConfigError("Plan embed references require embed_id")
    if kind == "file":
        path = reference.get("path")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
            raise OpenMatesConfigError("Plan file references require a repository-relative path")
    if kind == "url" and (not isinstance(reference.get("url"), str) or not reference["url"].startswith("https://")):
        raise OpenMatesConfigError("Plan URL references must use HTTPS")
    start = reference.get("start_line")
    end = reference.get("end_line")
    if start is not None and (not isinstance(start, int) or isinstance(start, bool) or start < 1):
        raise OpenMatesConfigError("Plan evidence start_line must be a positive integer")
    if end is not None and (not isinstance(end, int) or isinstance(end, bool) or end < (start or 1)):
        raise OpenMatesConfigError("Plan evidence end_line must be greater than or equal to start_line")


def _parse_plan_user_flows(value: str) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise OpenMatesConfigError("Plan user_flows ciphertext does not contain JSON") from exc
    _serialize_plan_user_flows(parsed)
    return parsed


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
        "projection_kind": record.get("projection_kind"),
        "workflow_id": record.get("workflow_id"),
        "workflow_run_id": record.get("workflow_run_id"),
        "trigger_id": record.get("trigger_id"),
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
        "scheduled_at": record.get("scheduled_at"),
        "priority": int(record.get("priority") or 0),
        "priority_level": _task_priority_level(record.get("priority")),
        "position": int(record.get("position") or 0),
        "queue_state": str(record.get("run_status") or "workflow"),
        "blocked_reason_code": record.get("blocked_reason_code") or record.get("blocked_reason"),
        "ai_execution_state": None,
        "read_only": True,
        "can_cancel": bool(record.get("can_cancel")),
        "can_delete": bool(record.get("can_delete")),
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


def _normalize_ideabucket_processing_times(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_times = value
    elif isinstance(value, str):
        raw_times = value.split(",")
    else:
        raw_times = list(IDEABUCKET_DEFAULT_PROCESSING_TIMES)
    times = sorted({str(item).strip() for item in raw_times if str(item).strip()}, key=_ideabucket_time_to_minutes)
    if len(times) < 1 or len(times) > 3:
        raise OpenMatesConfigError("IdeaBucket processing_times must include one to three HH:MM values")
    for processing_time in times:
        if not IDEABUCKET_PROCESSING_TIME_PATTERN.match(processing_time):
            raise OpenMatesConfigError(f"Invalid IdeaBucket processing time '{processing_time}'. Expected HH:MM in 24-hour format")
    return times


def _ideabucket_time_to_minutes(value: str) -> int:
    match = IDEABUCKET_PROCESSING_TIME_PATTERN.match(value)
    if not match:
        return 24 * 60
    return int(match.group(1)) * 60 + int(match.group(2))


def _next_ideabucket_scheduled_send_at(now_seconds: int, processing_times: list[str]) -> int:
    now = time.localtime(now_seconds)
    candidates = []
    for processing_time in processing_times:
        hour, minute = [int(part) for part in processing_time.split(":")]
        candidate = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, -1, -1, -1)))
        if candidate <= now_seconds:
            tomorrow = time.localtime(now_seconds + 24 * 60 * 60)
            candidate = int(time.mktime((tomorrow.tm_year, tomorrow.tm_mon, tomorrow.tm_mday, hour, minute, 0, -1, -1, -1)))
        candidates.append(candidate)
    return min(candidates)


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
                for value in [chat.get("title"), chat.get("chat_summary"), chat.get("category"), chat.get("slug"), chat.get("id")]
                if isinstance(value, str)
            ).lower()
        ]
        return matches[offset:] if limit == 0 else matches[offset : offset + limit]

    def load(self, chat_id: str) -> dict[str, Any]:
        return self._client._decrypt_loaded_chat_payload(self._client._get(f"/v1/sdk/chats/{_quote(_resolve_chat_id(self._client, chat_id))}"))

    def add_to_project(
        self,
        chat_id: str,
        project_id: str,
        *,
        folder: str | None = None,
    ) -> dict[str, Any]:
        resolved_project_id = _resolve_project_id(self._client, project_id)
        project_key = _resolve_project_key(self._client, resolved_project_id)
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else None
        if not isinstance(chat, dict):
            raise OpenMatesConfigError("Loaded chat payload did not include chat metadata for Project linking")
        target_id = str(chat.get("id") or chat_id)
        display_name = str(chat.get("title") or target_id)
        return _create_encrypted_project_item(
            self._client,
            resolved_project_id,
            project_key,
            item_type="chat",
            target_id=target_id,
            display_name=display_name,
            folder=folder,
            metadata={
                "storage": "save_only_in_openmates",
                "source": "sdk_add_to_project",
            },
        )

    def remove_from_project(self, chat_id: str, project_id: str) -> dict[str, Any]:
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else None
        target_id = str(chat.get("id") if isinstance(chat, dict) and chat.get("id") else chat_id)
        return _delete_project_item_by_target(self._client, _resolve_project_id(self._client, project_id), "chat", target_id)

    def messages(
        self,
        *,
        chat_id: str,
        direction: str = "latest",
        limit: int = 30,
        before_timestamp: int | None = None,
        before_message_id: str | None = None,
        after_timestamp: int | None = None,
        after_message_id: str | None = None,
        anchor_message_id: str | None = None,
        respect_compression_boundary: bool = True,
        all: bool = False,
    ) -> dict[str, Any]:
        if all:
            loaded = self.load(chat_id)
            chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else None
            if not isinstance(chat, dict):
                raise OpenMatesConfigError("Saved chat payload did not include chat metadata")
            messages = _normalize_loaded_chat_messages(loaded)
            return {
                "chat": chat,
                "messages": messages,
                "has_more_before": False,
                "has_more_after": False,
                "start_cursor": {"created_at": messages[0]["created_at"], "message_id": messages[0]["id"]} if messages else None,
                "end_cursor": {"created_at": messages[-1]["created_at"], "message_id": messages[-1]["id"]} if messages else None,
                "anchor_found": True,
                "server_message_count": len(messages),
            }
        query = {
            "direction": direction,
            "limit": limit,
            "before_timestamp": before_timestamp,
            "before_message_id": before_message_id,
            "after_timestamp": after_timestamp,
            "after_message_id": after_message_id,
            "anchor_message_id": anchor_message_id,
            "respect_compression_boundary": False if respect_compression_boundary is False else None,
        }
        path = f"/v1/sdk/chats/{_quote(_resolve_chat_id(self._client, chat_id))}/messages?{urlencode({key: value for key, value in query.items() if value is not None})}"
        loaded = self._client._decrypt_loaded_chat_payload(self._client._get(path))
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else None
        if not isinstance(chat, dict):
            raise OpenMatesConfigError("Saved chat payload did not include chat metadata")
        return {
            "chat": chat,
            "messages": _normalize_loaded_chat_messages(loaded),
            "has_more_before": loaded.get("has_more_before") is True,
            "has_more_after": loaded.get("has_more_after") is True,
            "start_cursor": loaded.get("start_cursor") if isinstance(loaded.get("start_cursor"), dict) else None,
            "end_cursor": loaded.get("end_cursor") if isinstance(loaded.get("end_cursor"), dict) else None,
            "anchor_found": loaded.get("anchor_found") is not False,
            "server_message_count": loaded.get("server_message_count") if isinstance(loaded.get("server_message_count"), int) else None,
        }

    def message_pages(self, *, chat_id: str, limit: int = 30, **kwargs: Any):
        direction = str(kwargs.pop("direction", "latest"))
        before_timestamp = kwargs.pop("before_timestamp", None)
        before_message_id = kwargs.pop("before_message_id", None)
        while True:
            page = self.messages(
                chat_id=chat_id,
                direction=direction,
                limit=limit,
                before_timestamp=before_timestamp,
                before_message_id=before_message_id,
                **kwargs,
            )
            yield page
            start_cursor = page.get("start_cursor") if isinstance(page.get("start_cursor"), dict) else None
            if page.get("has_more_before") is not True or not start_cursor:
                break
            direction = "before"
            before_timestamp = start_cursor.get("created_at")
            before_message_id = start_cursor.get("message_id")

    def fork(self, *, chat_id: str, from_message_id: str, title: str | None = None) -> dict[str, Any]:
        loaded, chat, _chat_key = self._load_personal_encrypted_chat(chat_id)
        messages = _normalize_loaded_chat_messages(loaded)
        boundary_index = _find_message_boundary_index(messages, from_message_id)
        new_chat_id = str(uuid.uuid4())
        new_chat_key = os.urandom(32)
        now = int(time.time())
        id_map: dict[str, str] = {}
        encrypted_messages = []
        for message in messages[: boundary_index + 1]:
            new_message_id = str(uuid.uuid4())
            id_map[message["id"]] = new_message_id
            raw = message.get("raw") if isinstance(message.get("raw"), dict) else {}
            encrypted_message: dict[str, Any] = {
                "client_message_id": new_message_id,
                "message_id": new_message_id,
                "chat_id": new_chat_id,
                "encrypted_content": _encrypt_aes_gcm_text(str(message.get("content") or ""), new_chat_key),
                "encrypted_sender_name": _encrypt_aes_gcm_text(str(message.get("sender_name") or _default_sender_name(str(message.get("role") or "user"))), new_chat_key),
                "role": str(message.get("role") or "unknown"),
                "created_at": int(message.get("created_at") or now),
                "updated_at": _numeric_seconds(raw.get("updated_at")) or int(message.get("created_at") or now),
            }
            old_user_message_id = raw.get("user_message_id")
            if isinstance(old_user_message_id, str) and old_user_message_id in id_map:
                encrypted_message["user_message_id"] = id_map[old_user_message_id]
            if isinstance(message.get("category"), str):
                encrypted_message["encrypted_category"] = _encrypt_aes_gcm_text(message["category"], new_chat_key)
            if isinstance(message.get("model_name"), str):
                encrypted_message["encrypted_model_name"] = _encrypt_aes_gcm_text(message["model_name"], new_chat_key)
            encrypted_messages.append(encrypted_message)
        master_key = self._client._get_master_key()
        slug_metadata = _encrypted_object_slug_metadata(
            title or f"fork-of-{chat.get('slug') or chat.get('title') or chat.get('id')}",
            encryption_key=new_chat_key,
            lookup_key=master_key,
        )
        source_chat_id = str(chat.get("id") or _resolve_chat_id(self._client, chat_id))
        return self._client._post(
            f"/v1/sdk/chats/{_quote(source_chat_id)}/fork",
            {
                "protocol_version": 1,
                "from_message_id": from_message_id,
                "new_chat_id": new_chat_id,
                "expected_source_messages_v": int(chat.get("messages_v") or len(messages)),
                "encrypted_chat_metadata": {
                    "id": new_chat_id,
                    "encrypted_title": _encrypt_aes_gcm_text(title or f"Fork of {chat.get('title') or chat.get('id')}", new_chat_key),
                    "encrypted_slug": slug_metadata["encrypted_slug"],
                    "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
                    "encrypted_chat_key": _encrypt_aes_gcm_bytes(new_chat_key, master_key),
                    "created_at": now,
                    "updated_at": now,
                },
                "encrypted_messages": encrypted_messages,
            },
        )

    def rewind(
        self,
        *,
        chat_id: str,
        to_message_id: str,
        send: str | None = None,
        dry_run: bool = False,
        confirm_destructive: bool = False,
    ) -> dict[str, Any]:
        if not dry_run:
            _require_confirmed(confirm_destructive, "Rewinding a chat")
        loaded, chat, _chat_key = self._load_personal_encrypted_chat(chat_id)
        messages = _normalize_loaded_chat_messages(loaded)
        _find_message_boundary_index(messages, to_message_id)
        result = self._client._post(
            f"/v1/sdk/chats/{_quote(str(chat.get('id') or _resolve_chat_id(self._client, chat_id)))}/rewind",
            {
                "protocol_version": 1,
                "to_message_id": to_message_id,
                "expected_messages_v": int(chat.get("messages_v") or len(messages)),
                "dry_run": dry_run,
                "confirm_destructive": confirm_destructive,
            },
        )
        if send and not dry_run:
            result["response"] = self.send(send, save_to_account=True, chat_id=chat_id).raw
        return result

    def retry(self, *, chat_id: str, dry_run: bool = False, confirm_destructive: bool = False) -> dict[str, Any]:
        if not dry_run:
            _require_confirmed(confirm_destructive, "Retrying a chat")
        loaded, _chat, _chat_key = self._load_personal_encrypted_chat(chat_id)
        messages = _normalize_loaded_chat_messages(loaded)
        retry_index = _find_retryable_user_message_index(messages)
        if retry_index < 0:
            raise OpenMatesConfigError("No retryable user message found for this chat")
        if retry_index == 0:
            raise OpenMatesConfigError("Cannot retry a chat whose first message is the failed user turn")
        return self.rewind(
            chat_id=chat_id,
            to_message_id=messages[retry_index - 1]["id"],
            send=str(messages[retry_index].get("content") or ""),
            dry_run=dry_run,
            confirm_destructive=confirm_destructive,
        )

    def send(
        self,
        message: str,
        *,
        history: Any = None,
        save_to_account: bool | None = None,
        focus_mode: dict[str, str] | None = None,
        memory_ids: list[str] | None = None,
        model: str | None = None,
        chat_id: str | None = None,
        slug: str | None = None,
        title: str | None = None,
        goal: str | None = None,
        goal_title: str | None = None,
        team_id: str | None = None,
        sender_name: str | None = None,
        team_member_mentions: list[str] | None = None,
        connected_account_directory: list[dict[str, Any]] | None = None,
        connected_account_token_ref_inputs: list[dict[str, Any]] | None = None,
        recovery_poll_interval_seconds: float = DEFAULT_RECOVERY_POLL_INTERVAL_SECONDS,
        recovery_timeout_seconds: float = DEFAULT_RECOVERY_TIMEOUT_SECONDS,
    ) -> ChatResponse:
        normalized_history = _normalize_history(history)
        final_message = _rewrite_remember_message_references(message, normalized_history) if _has_remember_message_reference(message) else message
        normalized_goal = _normalize_optional_goal(goal)
        if normalized_goal and save_to_account is False:
            raise OpenMatesConfigError("Chat goals require a saved account chat. Omit save_to_account or set save_to_account=True.")
        if save_to_account is True or normalized_goal or team_id:
            return self._send_saved(
                final_message,
                history=normalized_history,
                focus_mode=focus_mode,
                memory_ids=memory_ids,
                model=model,
                chat_id=chat_id,
                slug=slug,
                title=title,
                goal=normalized_goal,
                goal_title=goal_title,
                team_id=team_id,
                sender_name=sender_name,
                team_member_mentions=team_member_mentions,
                connected_account_directory=connected_account_directory,
                connected_account_token_ref_inputs=connected_account_token_ref_inputs,
                recovery_poll_interval_seconds=recovery_poll_interval_seconds,
                recovery_timeout_seconds=recovery_timeout_seconds,
            )
        try:
            data = self._client._post(
                "/v1/sdk/chats",
                {
                    "message": final_message,
                    "history": normalized_history,
                    "save_to_account": bool(save_to_account),
                    "focus_mode": focus_mode,
                    "memory_ids": memory_ids or [],
                    "model": model,
                    "connected_account_directory": connected_account_directory or [],
                    "connected_account_token_ref_inputs": connected_account_token_ref_inputs or [],
                },
            )
            response = data.get("response") or {}
            if model and "model_name" not in data and "modelName" not in data:
                data = {**data, "model_name": model}
            return ChatResponse(content=response.get("content"), raw=data)
        except OpenMatesApiError as error:
            if error.status_code != 401:
                raise
            result = self._client._run_app_skill(
                "ai",
                "ask",
                {
                    "messages": [*normalized_history, {"role": "user", "content": final_message}],
                    "stream": False,
                    "apps_enabled": True,
                    "is_incognito": True,
                    "model": model,
                },
            )
            return ChatResponse(
                content=_app_skill_chat_content(result),
                raw={"model_name": model, "result": result},
            )

    def _send_saved(
        self,
        message: str,
        *,
        history: Any,
        focus_mode: dict[str, str] | None,
        memory_ids: list[str] | None,
        model: str | None,
        chat_id: str | None,
        slug: str | None,
        title: str | None,
        connected_account_directory: list[dict[str, Any]] | None,
        connected_account_token_ref_inputs: list[dict[str, Any]] | None,
        goal: str | None,
        goal_title: str | None,
        team_id: str | None,
        sender_name: str | None,
        team_member_mentions: list[str] | None,
        recovery_poll_interval_seconds: float,
        recovery_timeout_seconds: float,
    ) -> ChatResponse:
        master_key = self._client._get_master_key()
        normalized_team_id = team_id.strip() if isinstance(team_id, str) and team_id.strip() else None
        wrapping_key = (
            _team_key_from_record(self._client, self._client.teams.get(normalized_team_id))
            if normalized_team_id
            else master_key
        )
        session = self._client._get_sdk_session()
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        if not user.get("id"):
            raise OpenMatesConfigError("SDK session did not include the authenticated user identity")

        saved_chat_id = _resolve_chat_id(self._client, chat_id) if chat_id else str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        created_at = int(time.time())
        expected_messages_v = 0
        encrypted_chat_metadata = None
        loaded_messages: list[dict[str, Any]] = []
        if chat_id:
            if normalized_team_id:
                raise OpenMatesConfigError("Sending to an existing Team chat is not supported yet")
            loaded = self.load(saved_chat_id)
            chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else {}
            loaded_messages = _normalize_loaded_chat_messages(loaded)
            encrypted_chat_key = chat.get("encrypted_chat_key")
            if not isinstance(encrypted_chat_key, str):
                raise OpenMatesConfigError("Saved chat does not include encrypted chat key material")
            chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, master_key)
            if chat_key is None:
                raise OpenMatesConfigError("Unable to decrypt saved chat key material")
            expected_messages_v = int(chat.get("messages_v") or 0)
        else:
            chat_key = os.urandom(32)
            encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, wrapping_key)
            slug_metadata = _encrypted_object_slug_metadata(slug or title or message, encryption_key=chat_key, lookup_key=wrapping_key)
            encrypted_chat_metadata = {
                "encrypted_title": _encrypt_aes_gcm_text(title or ("New team chat" if normalized_team_id else message[:80]), chat_key),
                "encrypted_slug": slug_metadata["encrypted_slug"],
                "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
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
        rememberable_messages = loaded_messages or normalized_history
        final_message = _rewrite_remember_message_references(message, rememberable_messages) if _has_remember_message_reference(message) else message
        if encrypted_chat_metadata is not None and title is None and final_message != message:
            encrypted_chat_metadata["encrypted_title"] = _encrypt_aes_gcm_text(final_message[:80], chat_key)
        inference_history = [
            *normalized_history,
            {"role": "user", "content": final_message, **({"name": sender_name} if sender_name else {})},
        ]
        team_ai_invocation = (
            {"history": inference_history}
            if normalized_team_id and "@openmates" in final_message.casefold()
            else None
        )
        inference_request = {
            "messages": team_ai_invocation["history"] if team_ai_invocation else ([] if normalized_team_id else inference_history),
            "model": model,
            "focus_mode": focus_mode,
            "memory_ids": memory_ids or [],
        }
        payload = {
            "message": None if normalized_team_id else final_message,
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
                "encrypted_content": _encrypt_aes_gcm_text(final_message, chat_key),
                "encrypted_sender_name": _encrypt_aes_gcm_text(sender_name or "User", chat_key),
                "role": "user",
                "created_at": created_at,
                "updated_at": created_at,
            },
            "encrypted_chat_metadata": encrypted_chat_metadata,
            "inference_request": inference_request,
            "team_id": normalized_team_id,
            "team_ai_invocation": team_ai_invocation,
            "team_member_mentions": team_member_mentions or [],
            "connected_account_directory": connected_account_directory or [],
            "connected_account_token_ref_inputs": connected_account_token_ref_inputs or [],
        }
        data = self._client._post("/v1/sdk/chats", payload)
        task_id = data.get("task_id")
        if normalized_team_id and team_ai_invocation is None and not task_id:
            return ChatResponse(content=None, raw=data)
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
        plan = None
        if goal:
            plan_payload = _build_plan_create_input(
                self._client,
                {
                    "title": _normalize_optional_goal(goal_title) or title or goal,
                    "goal": goal,
                    "primary_chat_id": saved_chat_id,
                    "_primary_chat_key": chat_key,
                    "status": "draft",
                },
            )
            plan_record = self._client._post("/v1/user-plans", plan_payload).get("plan", {})
            plan = _public_plan(_decrypt_plan_record(plan_record, master_key)) if isinstance(plan_record, dict) and plan_record else None
        raw = {**data, "terminal": terminal}
        if plan is not None:
            raw["plan"] = plan
        return ChatResponse(content=recovered["content"], raw=raw, plan=plan)

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
        resolved_chat_id = _resolve_chat_id(self._client, chat_id)
        return self._client._post(f"/v1/sdk/chats/{_quote(resolved_chat_id)}/export", {"format": format or "json", "payload": self.load(resolved_chat_id)})

    def delete(self, chat_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a chat")
        return self._client._delete(f"/v1/sdk/chats/{_quote(_resolve_chat_id(self._client, chat_id))}")

    def share(self, chat_id: str, *, expires: int | None = None, password: str | None = None) -> dict[str, Any]:
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else {}
        encrypted_chat_key = chat.get("encrypted_chat_key") if isinstance(chat, dict) else None
        if not isinstance(encrypted_chat_key, str):
            raise OpenMatesConfigError("Chat does not include an encrypted chat key")
        chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, self._client._get_master_key())
        if chat_key is None:
            raise OpenMatesConfigError("Unable to decrypt chat key for share link")
        resolved_chat_id = str(chat.get("id") or _resolve_chat_id(self._client, chat_id))
        blob = _generate_share_blob("chat", resolved_chat_id, chat_key, expires=expires, password=password)
        return {"url": f"{self._client._web_origin()}/share/chat/{resolved_chat_id}#key={blob}"}

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

    def _load_personal_encrypted_chat(self, chat_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        loaded = self.load(chat_id)
        chat = loaded.get("chat") if isinstance(loaded.get("chat"), dict) else None
        if not isinstance(chat, dict):
            raise OpenMatesConfigError("Saved chat payload did not include chat metadata")
        if chat.get("hashed_team_id") or chat.get("team_id") or chat.get("shared_chat_id"):
            raise OpenMatesConfigError("Only personal saved chats are supported for fork, rewind, and retry")
        encrypted_chat_key = chat.get("encrypted_chat_key")
        if not isinstance(encrypted_chat_key, str):
            raise OpenMatesConfigError("Saved chat does not include encrypted chat key material")
        chat_key = _decrypt_aes_gcm_bytes(encrypted_chat_key, self._client._get_master_key())
        if chat_key is None:
            raise OpenMatesConfigError("Unable to decrypt saved chat key material")
        return loaded, chat, chat_key


def _normalize_loaded_chat_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    normalized = []
    for entry in raw_messages:
        raw = json.loads(entry) if isinstance(entry, str) else dict(entry)
        message_id = raw.get("client_message_id") or raw.get("message_id") or raw.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise OpenMatesConfigError("Loaded chat message is missing a stable message id")
        content = raw.get("content") if isinstance(raw.get("content"), str) else ""
        normalized.append({
            "id": message_id,
            "role": raw.get("role") if isinstance(raw.get("role"), str) else "unknown",
            "content": content,
            "sender_name": raw.get("sender_name") if isinstance(raw.get("sender_name"), str) else None,
            "category": raw.get("category") if isinstance(raw.get("category"), str) else None,
            "model_name": raw.get("model_name") if isinstance(raw.get("model_name"), str) else None,
            "created_at": _numeric_seconds(raw.get("created_at")) or 0,
            "preview": " ".join(content.split())[:120],
            "raw": raw,
        })
    return sorted(normalized, key=lambda message: int(message.get("created_at") or 0))


def _find_message_boundary_index(messages: list[dict[str, Any]], message_id: str) -> int:
    for index, message in enumerate(messages):
        current_id = message.get("id")
        if isinstance(current_id, str) and (current_id == message_id or current_id.startswith(message_id)):
            return index
    raise OpenMatesConfigError(f"Message '{message_id}' was not found in the chat")


def _find_retryable_user_message_index(messages: list[dict[str, Any]]) -> int:
    has_later_assistant = False
    for index in range(len(messages) - 1, -1, -1):
        role = str(messages[index].get("role") or "").lower()
        if role == "assistant":
            has_later_assistant = True
        if role == "user" and not has_later_assistant:
            return index
    return -1


def _numeric_seconds(value: Any) -> int | None:
    if isinstance(value, (int, float)) and math.isfinite(value):
        parsed = int(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(float(value))
        except ValueError:
            return None
    else:
        return None
    return parsed // 1000 if parsed > 10_000_000_000 else parsed


def _default_sender_name(role: str) -> str:
    if role == "assistant":
        return "Assistant"
    if role == "system":
        return "System"
    return "User"


class OpenMatesIdeaBucket:
    """IdeaBucket SDK namespace using the existing OpenMates package."""

    def __init__(self, client: OpenMates):
        self._client = client

    def settings(self) -> dict[str, Any]:
        data = self._client.memories.list(app_id=IDEABUCKET_APP_ID, item_type=IDEABUCKET_SETTINGS_ITEM_TYPE)
        memories = data.get("memories") if isinstance(data.get("memories"), list) else []
        entry = memories[0] if memories else None
        if not isinstance(entry, dict):
            return self._normalize_settings(None, None, None)
        item_data = entry.get("data") if isinstance(entry.get("data"), dict) else None
        return self._normalize_settings(
            item_data,
            str(entry.get("id")) if entry.get("id") else None,
            int(entry.get("item_version")) if isinstance(entry.get("item_version"), int) else None,
        )

    def save_settings(self, input_data: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        settings = self._normalize_settings(
            {
                "processing_prompt": input_data.get("processingPrompt") or input_data.get("processing_prompt") or current["processingPrompt"],
                "processing_times": input_data.get("processingTimes") or input_data.get("processing_times") or current["processingTimes"],
            },
            current.get("entryId"),
            current.get("itemVersion"),
        )
        item_version = int(settings.get("itemVersion") or 0) + 1 if settings.get("entryId") else 1
        result = self._client.memories.create({
            "id": settings.get("entryId"),
            "appId": IDEABUCKET_APP_ID,
            "itemType": IDEABUCKET_SETTINGS_ITEM_TYPE,
            "itemVersion": item_version,
            "data": self._settings_to_memory_value(settings),
        })
        return {**settings, "entryId": str(result.get("id") or settings.get("entryId") or ""), "itemVersion": item_version, "source": "account"}

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

    def _normalize_settings(self, data: dict[str, Any] | None, entry_id: str | None, item_version: int | None) -> dict[str, Any]:
        raw_prompt = data.get("processing_prompt") if isinstance(data, dict) else None
        processing_prompt = raw_prompt.strip() if isinstance(raw_prompt, str) and raw_prompt.strip() else IDEABUCKET_DEFAULT_PROCESSING_PROMPT
        return {
            "processingPrompt": processing_prompt,
            "processingTimes": _normalize_ideabucket_processing_times(data.get("processing_times") if isinstance(data, dict) else None),
            "entryId": entry_id,
            "itemVersion": item_version,
            "source": "account" if entry_id else "default",
        }

    def _settings_to_memory_value(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "processing_prompt": settings["processingPrompt"],
            "processing_times": ",".join(settings["processingTimes"]),
        }

    def _build_encrypted_add_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        idea_text = str(payload.get("text") or "").strip()
        if not idea_text:
            raise OpenMatesConfigError("IdeaBucket add requires non-empty text")
        now = int(time.time())
        bucket_id = str(payload.get("bucket_id") or payload.get("bucketId") or datetime_utc_date(now))
        settings = self.settings() if payload.get("prompt") is None or (payload.get("scheduled_send_at") is None and payload.get("scheduledSendAt") is None) else None
        scheduled_send_at = int(payload.get("scheduled_send_at") or payload.get("scheduledSendAt") or (_next_ideabucket_scheduled_send_at(now, settings["processingTimes"]) if settings and settings.get("source") == "account" else default_ideabucket_scheduled_send_at(now)))
        chat_id = str(payload.get("chat_id") or payload.get("chatId") or uuid.uuid4())
        prompt = str(payload.get("prompt") or (settings["processingPrompt"] if settings else IDEABUCKET_DEFAULT_PROCESSING_PROMPT))
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
        chat_key = os.urandom(32)
        encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
        return {
            "chat_id": chat_id,
            "encrypted_draft_md": _encrypt_aes_gcm_text(markdown, master_key),
            "encrypted_draft_preview": _encrypt_aes_gcm_text(preview, master_key),
            "ideabucket": True,
            "ideabucket_processing_window_id": bucket_id,
            "ideabucket_processing_version": now,
            "encrypted_chat_key": encrypted_chat_key,
            "scheduled_send_at": scheduled_send_at,
            "server_vault_encrypted_processing_payload": _encrypt_aes_gcm_text(server_payload, master_key),
            "client_encrypted_future_user_message": _encrypt_aes_gcm_text(markdown, chat_key),
            "client_encrypted_ideabucket_system_event": _encrypt_aes_gcm_text(json.dumps({
                "type": "ideabucket_triggered_send",
                "bucket_id": bucket_id,
                "processing_window_id": bucket_id,
                "source": "openmates_pip_sdk",
            }, separators=(",", ":")), chat_key),
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


class _PlanEncryptedFieldFacade:
    def __init__(self, plans: "OpenMatesPlans", field: str):
        self._plans = plans
        self._field = field.removeprefix("encrypted_")

    def add(self, plan_id: str, value: str) -> dict[str, Any]:
        return self._plans.update(plan_id, {self._field: value})

    def update(self, plan_id: str, value: str) -> dict[str, Any]:
        return self._plans.update(plan_id, {self._field: value})

    def set(self, plan_id: str, value: str) -> dict[str, Any]:
        return self.update(plan_id, value)

    def remove(self, plan_id: str) -> dict[str, Any]:
        return self._plans.update(plan_id, {self._field: ""})

    def clear(self, plan_id: str) -> dict[str, Any]:
        return self.remove(plan_id)

    def answer(self, plan_id: str, value: str) -> dict[str, Any]:
        return self.update(plan_id, value)

    def supersede(self, plan_id: str, value: str) -> dict[str, Any]:
        return self.update(plan_id, value)


class _PlanUserFlowsFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def set(self, plan_id: str, value: list[dict[str, Any]]) -> dict[str, Any]:
        return self._plans.update(plan_id, {"user_flows": value})

    def update(self, plan_id: str, value: list[dict[str, Any]]) -> dict[str, Any]:
        return self.set(plan_id, value)

    def clear(self, plan_id: str) -> dict[str, Any]:
        return self.set(plan_id, [])


class _PlanSuccessCriteriaFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def add(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_criterion(plan_id, payload)

    def update(self, plan_id: str, criterion_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_criterion(plan_id, criterion_id, payload)

    def remove(self, plan_id: str, criterion_id: str) -> dict[str, Any]:
        return self._plans.delete_criterion(plan_id, criterion_id)


class _PlanChecksFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def add(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_verification(plan_id, payload)

    def update(self, plan_id: str, check_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_verification(plan_id, check_id, payload)

    def remove(self, plan_id: str, check_id: str) -> dict[str, Any]:
        return self._plans.delete_verification(plan_id, check_id)

    def add_evidence(self, plan_id: str, check_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.add_verification_evidence(plan_id, check_id, payload)

    def get_run(self, plan_id: str, check_id: str, run_id: str) -> dict[str, Any]:
        return self._plans.get_verification_run(plan_id, check_id, run_id)


class _PlanAssumptionsFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def add(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_assumption(plan_id, payload)

    def update(self, plan_id: str, assumption_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_assumption(plan_id, assumption_id, payload)

    def check(self, plan_id: str, assumption_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {**(payload or {})}
        request.setdefault("status", "checking")
        return self._plans.update_assumption(plan_id, assumption_id, request)

    def waive(self, plan_id: str, assumption_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_assumption(plan_id, assumption_id, {**payload, "status": "waived"})

    def remove(self, plan_id: str, assumption_id: str) -> dict[str, Any]:
        return self._plans.delete_assumption(plan_id, assumption_id)


class _PlanReferencePatternsFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def add(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_reference_pattern(plan_id, payload)

    def update(self, plan_id: str, pattern_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_reference_pattern(plan_id, pattern_id, payload)

    def inspect(self, plan_id: str, pattern_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {**(payload or {})}
        request.setdefault("status", "inspected")
        return self._plans.update_reference_pattern(plan_id, pattern_id, request)

    def waive(self, plan_id: str, pattern_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_reference_pattern(plan_id, pattern_id, {**payload, "status": "waived"})

    def remove(self, plan_id: str, pattern_id: str) -> dict[str, Any]:
        return self._plans.delete_reference_pattern(plan_id, pattern_id)


class _PlanLearningsFacade:
    def __init__(self, plans: "OpenMatesPlans"):
        self._plans = plans

    def list(self, plan_id: str) -> list[dict[str, Any]]:
        return self._plans.list_learnings(plan_id)

    def show(self, plan_id: str, learning_id: str) -> dict[str, Any]:
        for learning in self._plans.list_learnings(plan_id):
            if learning.get("learning_id") == learning_id:
                return learning
        raise OpenMatesApiError(404, {"detail": "Plan learning not found"})

    def create(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_learning(plan_id, payload)

    def update(self, plan_id: str, learning_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.update_learning(plan_id, learning_id, payload)

    def remove(self, plan_id: str, learning_id: str) -> dict[str, Any]:
        return self._plans.delete_learning(plan_id, learning_id)

    def create_tasks(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plans.create_learning_tasks(plan_id, payload)


class _PlanTasksFacade:
    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, plan_id: str) -> list[dict[str, Any]]:
        return self._client.tasks.list(plan_id=plan_id)

    def add(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.tasks.create({**payload, "plan_id": plan_id})

    def update(self, plan_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.tasks.edit(task_id, payload, plan_id=plan_id)

    def remove(self, plan_id: str, task_id: str) -> dict[str, Any]:
        return self._client.tasks.delete(task_id, confirmed=True, plan_id=plan_id)


class OpenMatesPlans:
    """Cleartext user plans SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client
        self.goal = _PlanEncryptedFieldFacade(self, "encrypted_goal")
        self.tasks = _PlanTasksFacade(client)
        self.success_criteria = _PlanSuccessCriteriaFacade(self)
        self.user_flows = _PlanUserFlowsFacade(self)
        self.checks = _PlanChecksFacade(self)
        self.scope_in = _PlanEncryptedFieldFacade(self, "encrypted_scope_in")
        self.scope_out = _PlanEncryptedFieldFacade(self, "encrypted_scope_out")
        self.assumptions = _PlanAssumptionsFacade(self)
        self.open_questions = _PlanEncryptedFieldFacade(self, "encrypted_open_questions")
        self.constraints = _PlanEncryptedFieldFacade(self, "encrypted_constraints")
        self.decisions = _PlanEncryptedFieldFacade(self, "encrypted_decisions")
        self.risks = _PlanEncryptedFieldFacade(self, "encrypted_risks")
        self.reference_patterns = _PlanReferencePatternsFacade(self)
        self.learnings = _PlanLearningsFacade(self)
        self.context = type("PlanContextFacade", (), {"artifacts": _PlanEncryptedFieldFacade(self, "encrypted_context")})()
        self.activity = type("PlanActivityFacade", (), {"list": lambda _self, plan_id, limit=None: self.history(plan_id, limit=limit)})()
        self.dependencies = _WorkDependenciesFacade(client, "plan")
        self.revisions = _PlanRevisionsFacade(self)
        self.review = _PlanReviewFacade(self)
        self.approval = _PlanApprovalFacade(self)

    def list(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        active_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        return [_public_plan(_decrypt_plan_record(plan, self._client._get_master_key())) for plan in self._list_raw(status=status, chat_id=chat_id, project_id=project_id, active_only=active_only)]

    def _list_raw(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        active_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        resolved_chat_id = _resolve_chat_id(self._client, chat_id) if isinstance(chat_id, str) and chat_id else chat_id
        resolved_project_id = _resolve_project_id(self._client, project_id) if isinstance(project_id, str) and project_id else project_id
        return self._client._get(
            _with_query(
                "/v1/user-plans",
                status=status,
                chat_id=resolved_chat_id,
                project_id=resolved_project_id,
                active_only=active_only,
            )
        ).get("plans", [])

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._client._post("/v1/user-plans", _build_plan_create_input(self._client, payload)).get("plan", {})
        return _public_plan(_decrypt_plan_record(plan, self._client._get_master_key()))

    def show(self, plan_id: str) -> dict[str, Any]:
        return _public_plan(_decrypt_plan_record(self._get_raw_plan(plan_id), self._client._get_master_key()))

    def _get_raw_plan(self, plan_id: str) -> dict[str, Any]:
        if not _is_uuid(plan_id):
            return self._find_raw_plan_by_selector(plan_id)
        try:
            plan = self._client._get(f"/v1/user-plans/{_quote(plan_id)}").get("plan")
            if not isinstance(plan, dict):
                raise OpenMatesApiError(500, {"detail": "User plan response missing plan"})
            return plan
        except OpenMatesApiError as exc:
            if exc.status_code != 404:
                raise
        return self._find_raw_plan_by_selector(plan_id)

    def _find_raw_plan_by_selector(self, plan_id: str) -> dict[str, Any]:
        raw_plans = self._list_raw(active_only=False)
        master_key = self._client._get_master_key()
        public_plan = _find_plan([_public_plan(_decrypt_plan_record(plan, master_key)) for plan in raw_plans], plan_id)
        public_plan_id = public_plan.get("plan_id")
        for plan in raw_plans:
            if plan.get("plan_id") == public_plan_id:
                return plan
        raise OpenMatesConfigError(f"Plan '{plan_id}' was not found")

    def update(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        existing = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan = self._client._patch(f"/v1/user-plans/{_quote(str(existing['plan_id']))}", _build_plan_update_input(existing, master_key, {**payload, "_client": self._client})).get("plan", {})
        return _public_plan(_decrypt_plan_record(plan, master_key))

    def add_to_project(
        self,
        plan_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        plan = self._get_raw_plan(plan_id)
        master_key = self._client._get_master_key()
        plan_key = _plan_key_from_record(plan, master_key)
        linked_project_ids = _json_string_list(_decrypt_aes_gcm_text(str(plan.get("encrypted_linked_project_ids") or ""), plan_key)) or _string_list(plan.get("linked_project_ids") or [])
        updated_project_ids = _append_unique_id(linked_project_ids, _resolve_project_id(self._client, project_id))
        patch = {
            "version": plan.get("version"),
            "updated_at": int(time.time()),
            "linked_project_ids": updated_project_ids,
            "encrypted_linked_project_ids": _encrypt_aes_gcm_text(json.dumps(updated_project_ids), plan_key),
            "key_wrappers": _build_plan_key_wrappers(
                self._client,
                plan_key,
                primary_chat_id=plan.get("primary_chat_id") if isinstance(plan.get("primary_chat_id"), str) else None,
                linked_project_ids=updated_project_ids,
                created_at=int(time.time()),
            ),
        }
        updated = self._client._patch(f"/v1/user-plans/{_quote(str(plan.get('plan_id')))}", patch).get("plan", {})
        return _public_plan(_decrypt_plan_record(updated, master_key))

    def remove_from_project(
        self,
        plan_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        plan = self._get_raw_plan(plan_id)
        master_key = self._client._get_master_key()
        plan_key = _plan_key_from_record(plan, master_key)
        linked_project_ids = _json_string_list(_decrypt_aes_gcm_text(str(plan.get("encrypted_linked_project_ids") or ""), plan_key)) or _string_list(plan.get("linked_project_ids") or [])
        updated_project_ids = _remove_id(linked_project_ids, _resolve_project_id(self._client, project_id))
        patch = {
            "version": plan.get("version"),
            "updated_at": int(time.time()),
            "linked_project_ids": updated_project_ids,
            "encrypted_linked_project_ids": _encrypt_aes_gcm_text(json.dumps(updated_project_ids), plan_key),
            "key_wrappers": _build_plan_key_wrappers(
                self._client,
                plan_key,
                primary_chat_id=plan.get("primary_chat_id") if isinstance(plan.get("primary_chat_id"), str) else None,
                linked_project_ids=updated_project_ids,
                created_at=int(time.time()),
            ),
        }
        updated = self._client._patch(f"/v1/user-plans/{_quote(str(plan.get('plan_id')))}", patch).get("plan", {})
        return _public_plan(_decrypt_plan_record(updated, master_key))

    def history(self, plan_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        resolved_plan_id = _resolve_plan_id(self._client, plan_id)
        query = f"?limit={limit}" if limit is not None else ""
        return self._client._get(f"/v1/user-plans/{_quote(resolved_plan_id)}/history{query}").get("entries", [])

    def restore(self, plan_id: str, *, entry_id: str, state: str = "after") -> dict[str, Any]:
        return self._client._post(
            f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/restore",
            {"entry_id": entry_id, "state": state},
        )

    def ask(
        self,
        instruction: str,
        *,
            create: dict[str, Any] | None = None,
            update: dict[str, Any] | None = None,
            updates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        planned_create = None
        if create is None and update is None and not updates:
            planned_create = self._client._post("/v1/user-plans/ask/plan", {"instruction": instruction}).get("proposed_plan")
        encrypted_updates = None
        if updates:
            encrypted_updates = []
            for item in updates:
                plan_id = str(item.get("plan_id") or item.get("planId") or "")
                existing = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
                encrypted_updates.append({"plan_id": existing["plan_id"], "patch": _build_plan_update_input(existing, master_key, {**dict(item.get("patch") or {}), "_client": self._client})})
        request_payload: dict[str, Any] = {"instruction": instruction}
        if create is not None or planned_create is not None:
            request_payload["encrypted_create"] = _build_plan_create_input(self._client, create or planned_create or {"title": instruction})
        if update is not None:
            plan_id = str(update.get("plan_id") or update.get("planId") or "")
            existing = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
            request_payload["encrypted_update"] = {"plan_id": existing["plan_id"], "patch": _build_plan_update_input(existing, master_key, {**dict(update.get("patch") or {}), "_client": self._client})}
        if encrypted_updates is not None:
            request_payload["encrypted_updates"] = encrypted_updates
        response = self._client._post("/v1/user-plans/ask", request_payload)
        records = response.get("plans") if isinstance(response.get("plans"), list) else [response.get("plan")] if isinstance(response.get("plan"), dict) else []
        plans = [_public_plan(_decrypt_plan_record(plan, master_key)) for plan in records if isinstance(plan, dict)]
        return {**response, "plan": plans[0] if len(plans) == 1 else None, "plans": plans}

    def activate(self, plan_id: str, *, chat_id: str | None = None) -> dict[str, Any]:
        request_payload = {"chat_id": _resolve_chat_id(self._client, chat_id)} if chat_id is not None else {}
        if isinstance(request_payload.get("chat_id"), str):
            existing = self._get_raw_plan(plan_id)
            master_key = self._client._get_master_key()
            plan_key = _plan_key_from_record(existing, master_key)
            linked_project_ids = _json_string_list(_decrypt_aes_gcm_text(str(existing.get("encrypted_linked_project_ids") or ""), plan_key)) or _string_list(existing.get("linked_project_ids") or [])
            request_payload["key_wrappers"] = _build_plan_key_wrappers(
                self._client,
                plan_key,
                primary_chat_id=request_payload["chat_id"],
                linked_project_ids=linked_project_ids,
                created_at=int(request_payload.get("updated_at") or time.time()),
            )
        plan = self._client._post(f"/v1/user-plans/{_quote(str(existing.get('plan_id')) if 'existing' in locals() else _resolve_plan_id(self._client, plan_id))}/activate", request_payload).get("plan", {})
        if "primary_chat_id" not in plan and isinstance(request_payload.get("chat_id"), str):
            plan = {**plan, "primary_chat_id": request_payload["chat_id"]}
        return _public_plan(_decrypt_plan_record(plan, self._client._get_master_key()))

    def attach(self, plan_id: str, *, chat_id: str | None = None) -> dict[str, Any]:
        return self.activate(plan_id, chat_id=chat_id)

    def start(self, plan_id: str) -> dict[str, Any]:
        return self.update(plan_id, {"status": "executing"})

    def resume(self, plan_id: str) -> dict[str, Any]:
        return self.update(plan_id, {"status": "active"})

    def complete(self, plan_id: str) -> dict[str, Any]:
        existing = self._get_raw_plan(plan_id)
        plan = self._client._post(f"/v1/user-plans/{_quote(str(existing.get('plan_id')))}/complete", {"version": existing.get("version")}).get("plan", {})
        if not plan:
            plan = self._get_raw_plan(plan_id)
        return _public_plan(_decrypt_plan_record(plan, self._client._get_master_key()))

    def delete(self, plan_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Plan deletion")
        existing = self._get_raw_plan(plan_id)
        return self._client._delete(f"/v1/user-plans/{_quote(str(existing.get('plan_id')))}?version={_quote(str(existing.get('version')))}")

    def create_criterion(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        criterion = self._client._post(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/criteria", _build_plan_criterion_create_input(plan, master_key, payload)).get("criterion", {})
        return _public_plan_criterion(criterion, _plan_key_from_record(plan["encrypted"], master_key))

    def list_criteria(self, plan_id: str) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan_key = _plan_key_from_record(plan["encrypted"], master_key)
        return [_public_plan_criterion(criterion, plan_key) for criterion in self._client._get(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/criteria").get("criteria", [])]

    def update_criterion(self, plan_id: str, criterion_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        criterion = self._client._patch(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/criteria/{_quote(criterion_id)}", _build_plan_criterion_update_input(plan, master_key, payload)).get("criterion", {})
        return _public_plan_criterion(criterion, _plan_key_from_record(plan["encrypted"], master_key))

    def delete_criterion(self, plan_id: str, criterion_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/criteria/{_quote(criterion_id)}")

    def create_verification(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        verification = self._client._post(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/verification", _build_plan_verification_create_input(plan, master_key, payload)).get("verification", {})
        return _public_plan_verification(verification, _plan_key_from_record(plan["encrypted"], master_key))

    def list_verifications(self, plan_id: str) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan_key = _plan_key_from_record(plan["encrypted"], master_key)
        return [_public_plan_verification(verification, plan_key) for verification in self._client._get(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/verification").get("verifications", [])]

    def update_verification(self, plan_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        verification = self._client._patch(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/verification/{_quote(verification_id)}", _build_plan_verification_update_input(plan, master_key, payload)).get("verification", {})
        return _public_plan_verification(verification, _plan_key_from_record(plan["encrypted"], master_key))

    def delete_verification(self, plan_id: str, verification_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/verification/{_quote(verification_id)}")

    def create_assumption(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        assumption = self._client._post(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/assumptions", _build_plan_assumption_create_input(plan, master_key, payload)).get("assumption", {})
        return _public_plan_assumption(assumption, _plan_key_from_record(plan["encrypted"], master_key))

    def list_assumptions(self, plan_id: str) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan_key = _plan_key_from_record(plan["encrypted"], master_key)
        return [_public_plan_assumption(assumption, plan_key) for assumption in self._client._get(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/assumptions").get("assumptions", [])]

    def update_assumption(self, plan_id: str, assumption_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        assumption = self._client._patch(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/assumptions/{_quote(assumption_id)}", _build_plan_assumption_update_input(plan, master_key, payload)).get("assumption", {})
        return _public_plan_assumption(assumption, _plan_key_from_record(plan["encrypted"], master_key))

    def delete_assumption(self, plan_id: str, assumption_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/assumptions/{_quote(assumption_id)}")

    def create_reference_pattern(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        pattern = self._client._post(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/reference-patterns", _build_plan_reference_pattern_create_input(plan, master_key, payload)).get("reference_pattern", {})
        return _public_plan_reference_pattern(pattern, _plan_key_from_record(plan["encrypted"], master_key))

    def list_reference_patterns(self, plan_id: str) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan_key = _plan_key_from_record(plan["encrypted"], master_key)
        return [_public_plan_reference_pattern(pattern, plan_key) for pattern in self._client._get(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/reference-patterns").get("reference_patterns", [])]

    def update_reference_pattern(self, plan_id: str, pattern_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        pattern = self._client._patch(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/reference-patterns/{_quote(pattern_id)}", _build_plan_reference_pattern_update_input(plan, master_key, payload)).get("reference_pattern", {})
        return _public_plan_reference_pattern(pattern, _plan_key_from_record(plan["encrypted"], master_key))

    def delete_reference_pattern(self, plan_id: str, pattern_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/reference-patterns/{_quote(pattern_id)}")

    def create_learning(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        learning = self._client._post(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/learnings", _build_plan_learning_create_input(plan, master_key, payload)).get("learning", {})
        return _public_plan_learning(learning, _plan_key_from_record(plan["encrypted"], master_key))

    def list_learnings(self, plan_id: str) -> list[dict[str, Any]]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        plan_key = _plan_key_from_record(plan["encrypted"], master_key)
        return [_public_plan_learning(learning, plan_key) for learning in self._client._get(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/learnings").get("learnings", [])]

    def update_learning(self, plan_id: str, learning_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        learning = self._client._patch(f"/v1/user-plans/{_quote(str(plan['plan_id']))}/learnings/{_quote(learning_id)}", _build_plan_learning_update_input(plan, master_key, payload)).get("learning", {})
        return _public_plan_learning(learning, _plan_key_from_record(plan["encrypted"], master_key))

    def delete_learning(self, plan_id: str, learning_id: str) -> dict[str, Any]:
        return self._client._delete(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/learnings/{_quote(learning_id)}")

    def create_learning_tasks(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/learnings/create-tasks", payload)

    def add_verification_evidence(self, plan_id: str, verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        plan = _decrypt_plan_record(self._get_raw_plan(plan_id), master_key)
        verification = self._client._post(
            f"/v1/user-plans/{_quote(str(plan['plan_id']))}/verification/{_quote(verification_id)}/evidence",
            _build_plan_verification_evidence_input(plan, master_key, payload),
        ).get("verification", {})
        return _public_plan_verification(verification, _plan_key_from_record(plan["encrypted"], master_key))

    def get_verification_run(self, plan_id: str, verification_id: str, run_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/user-plans/{_quote(_resolve_plan_id(self._client, plan_id))}/verification/{_quote(verification_id)}/runs/{_quote(run_id)}")


class OpenMatesTasks:
    """Cleartext user tasks SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client
        self.dependencies = _WorkDependenciesFacade(client, "task")

    def list(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        plan_id: str | None = None,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        external_chat: str | dict[str, Any] | None = None,
        priority: str | int | None = None,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            _public_task(task)
            for task in self._list_internal(status=status, chat_id=chat_id, project_id=project_id, plan_id=plan_id, labels=labels, tags=tags, external_chat=external_chat, priority=priority, team_id=team_id)
        ]

    def _list_raw(
        self,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        plan_id: str | None = None,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        external_chat: str | dict[str, Any] | None = None,
        priority: str | int | None = None,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]:
        label_values = labels if labels is not None else tags
        external_chat_context = _normalize_external_chat_context(external_chat) if external_chat is not None else None
        master_key = self._client._get_master_key() if label_values or external_chat_context else None
        label_hashes = _task_label_hashes(master_key, _normalize_task_labels(label_values)) if label_values and master_key else None
        resolved_chat_id = _resolve_chat_id(self._client, chat_id) if isinstance(chat_id, str) and chat_id else chat_id
        resolved_project_id = (
            _resolve_project_id(self._client, project_id, personal=not bool(team_id), team_id=team_id)
            if isinstance(project_id, str) and project_id
            else project_id
        )
        resolved_plan_id = _resolve_plan_id(self._client, plan_id) if isinstance(plan_id, str) and plan_id and not team_id else plan_id
        return self._client._get(
            _with_query(
                "/v1/user-tasks",
                status=status,
                chat_id=resolved_chat_id,
                project_id=resolved_project_id,
                plan_id=resolved_plan_id,
                label_hash=label_hashes,
                external_chat_provider=external_chat_context["provider"] if external_chat_context else None,
                external_chat_lookup_hash=_external_chat_lookup_hash(master_key, external_chat_context) if external_chat_context and master_key else None,
                priority=_normalize_task_priority(priority),
                team_id=team_id,
            )
        ).get("tasks", [])

    def show(self, task_id: str, **filters: Any) -> dict[str, Any]:
        return _public_task(self._resolve(task_id, filters))

    def history(self, task_id: str, *, limit: int | None = None, **filters: Any) -> list[dict[str, Any]]:
        task = self._resolve(task_id, filters)
        query = f"?limit={limit}" if limit is not None else ""
        return self._client._get(f"/v1/user-tasks/{_quote(str(task['task_id']))}/history{query}").get("entries", [])

    def restore(self, task_id: str, *, entry_id: str, state: str = "after", **filters: Any) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        return self._client._post(
            f"/v1/user-tasks/{_quote(str(task['task_id']))}/restore",
            {"entry_id": entry_id, "state": state},
        )

    def ask(
        self,
        instruction: str,
        *,
            create: dict[str, Any] | None = None,
            creates: list[dict[str, Any]] | None = None,
            update: dict[str, Any] | None = None,
            updates: list[dict[str, Any]] | None = None,
            exact_delete: dict[str, Any] | None = None,
            exact_deletes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        planned_creates: list[dict[str, Any]] = []
        if create is None and not creates and update is None and not updates and exact_delete is None and exact_deletes is None:
            planned_creates = self._client._post("/v1/user-tasks/ask/plan", {"instruction": instruction}).get("proposed_tasks", [])
        create_payloads = creates if creates is not None else [create] if create is not None else planned_creates
        encrypted_creates = [_build_task_create_input(master_key, _canonicalize_task_payload(self._client, item)) for item in create_payloads if isinstance(item, dict)]
        payload: dict[str, Any] = {"instruction": instruction}
        if create is not None and encrypted_creates:
            payload["encrypted_create"] = encrypted_creates[0]
        if creates is not None or planned_creates:
            payload["encrypted_creates"] = encrypted_creates
        if update is not None:
            task_id = str(update.get("task_id") or update.get("taskId") or "")
            task = self._resolve(task_id, dict(update.get("filters") or {}))
            update_team_id = (update.get("filters") or {}).get("team_id")
            payload["encrypted_update"] = {"task_id": task["task_id"], "patch": _build_task_update_input(task, master_key, _canonicalize_task_payload(self._client, dict(update.get("patch") or {}), team_id=update_team_id))}
        if updates is not None:
            payload["encrypted_updates"] = []
            for item in updates:
                task_id = str(item.get("task_id") or item.get("taskId") or "")
                task = self._resolve(task_id, dict(item.get("filters") or {}))
                item_team_id = (item.get("filters") or {}).get("team_id")
                payload["encrypted_updates"].append({"task_id": task["task_id"], "patch": _build_task_update_input(task, master_key, _canonicalize_task_payload(self._client, dict(item.get("patch") or {}), team_id=item_team_id))})
        if exact_delete is not None:
            payload["exact_delete"] = exact_delete
        if exact_deletes is not None:
            payload["exact_deletes"] = exact_deletes
        response = self._client._post("/v1/user-tasks/ask", payload)
        records = response.get("tasks") if isinstance(response.get("tasks"), list) else [response.get("task")] if isinstance(response.get("task"), dict) else []
        tasks = [_public_task(_decrypt_task_record(task, master_key)) for task in records if isinstance(task, dict)]
        return {**response, "task": tasks[0] if len(tasks) == 1 else None, "tasks": tasks}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        created = self._create_raw(_build_task_create_input(master_key, _canonicalize_task_payload(self._client, payload)))
        return _public_task(_decrypt_task_record(created, master_key))

    def _create_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client._post("/v1/user-tasks", payload).get("task", {})

    def update(self, task_id: str, payload: dict[str, Any], **filters: Any) -> dict[str, Any]:
        return self.edit(task_id, payload, **filters)

    def _update_raw(self, task_id: str, payload: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        return self._client._patch(_with_query(f"/v1/user-tasks/{_quote(task_id)}", team_id=team_id), payload).get("task", {})

    def edit(self, task_id: str, payload: dict[str, Any], **filters: Any) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        master_key = self._client._get_master_key()
        for attempt in range(2):
            try:
                updated = self._update_raw(
                    str(task["task_id"]),
                    _build_task_update_input(task, master_key, _canonicalize_task_payload(self._client, payload, team_id=filters.get("team_id"))),
                    team_id=filters.get("team_id"),
                )
                return _public_task(_decrypt_task_record(updated, master_key))
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task update retry failed unexpectedly")

    def add_to_project(
        self,
        task_id: str,
        project_id: str,
        **filters: Any,
    ) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        master_key = self._client._get_master_key()
        team_id = filters.get("team_id")
        updated = self._update_raw(str(task["task_id"]), _build_task_update_input(task, master_key, {
            "linked_project_ids": _append_unique_id(
                _string_list(task.get("linked_project_ids") or []),
                _resolve_project_id(self._client, project_id, personal=not bool(team_id), team_id=team_id),
            ),
        }), team_id=team_id)
        return _public_task(_decrypt_task_record(updated, master_key))

    def remove_from_project(
        self,
        task_id: str,
        project_id: str,
        **filters: Any,
    ) -> dict[str, Any]:
        task = self._resolve(task_id, filters)
        master_key = self._client._get_master_key()
        team_id = filters.get("team_id")
        updated = self._update_raw(str(task["task_id"]), _build_task_update_input(task, master_key, {
            "linked_project_ids": _remove_id(
                _string_list(task.get("linked_project_ids") or []),
                _resolve_project_id(self._client, project_id, personal=not bool(team_id), team_id=team_id),
            ),
        }), team_id=team_id)
        return _public_task(_decrypt_task_record(updated, master_key))

    def start_ai(self, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.start(task_id, **(payload or {}))

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
                    "team_id": filters.get("team_id"),
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
                return self._client._delete(_with_query(
                    f"/v1/user-tasks/{_quote(str(task['task_id']))}",
                    version=task["version"],
                    team_id=filters.get("team_id"),
                ))
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

    def block(self, task_id: str, reason: str, *, reason_text: str | None = None, **filters: Any) -> dict[str, Any]:
        return self._action_by_id(
            task_id,
            "block",
            {
                "blocked_reason_code": _normalize_blocked_reason_code(reason),
                "_reason_text": reason_text,
            },
            filters,
        )

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
                updated = self._client._post("/v1/user-tasks/reorder", {
                    "moves": [{**move, "task_id": task["task_id"], "version": task["version"]}],
                    "team_id": filters.get("team_id"),
                }).get("tasks", [])
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
                request_patch = dict(patch)
                reason_text = request_patch.pop("_reason_text", None)
                if reason_text is not None:
                    request_patch["encrypted_blocked_reason"] = _encrypt_aes_gcm_text(
                        reason_text,
                        _task_key_from_record(task.get("encrypted") if isinstance(task.get("encrypted"), dict) else task, self._client._get_master_key()),
                    )
                updated = self._action_raw(
                    str(task["task_id"]),
                    action,
                    {"version": task["version"], "team_id": filters.get("team_id"), **request_patch},
                )
                return _public_task(_decrypt_task_record(updated, self._client._get_master_key()))
            except OpenMatesApiError as exc:
                if attempt > 0 or not _is_task_version_conflict(exc):
                    raise
                time.sleep(1)
                task = self._resolve(task_id, filters)
        raise OpenMatesConfigError("Task action retry failed unexpectedly")

    def _list_internal(self, **filters: Any) -> list[dict[str, Any]]:
        records = [task for task in self._list_raw(**filters) if isinstance(task, dict)]
        decrypted: list[dict[str, Any]] = []
        master_key: bytes | None = None
        for task in records:
            if task.get("source") == "workflow_run":
                decrypted.append(_workflow_projection_task(task))
                continue
            if master_key is None:
                master_key = self._client._get_master_key()
            decrypted.append(_decrypt_task_record(task, master_key))
        return decrypted

    def _resolve(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return _find_task(self._list_internal(**filters), task_id)


class OpenMatesHistory:
    """Workspace change history SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, *, object_type: str | None = None, object_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if object_type:
            params["object_type"] = object_type
        if object_id:
            params["object_id"] = object_id
        if limit is not None:
            params["limit"] = str(limit)
        query = f"?{urlencode(params)}" if params else ""
        return self._client._get(f"/v1/workspace/history{query}").get("change_sets", [])

    def show(self, change_set_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/workspace/history/{_quote(change_set_id)}")

    def undo(self, change_set_id: str) -> dict[str, Any]:
        return self._client._post(f"/v1/workspace/history/{_quote(change_set_id)}/undo", {})


class OpenMatesProjects:
    """Cleartext Project source SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self, *, personal: bool = False, team_id: str | None = None, include_archived: bool | None = None) -> list[dict[str, Any]]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        wrapping_key = _project_wrapping_key(self._client, context_team_id)
        records = self._client._get(_with_query(
            "/v1/projects",
            include_archived="true" if include_archived else "false" if include_archived is not None else None,
            team_id=context_team_id,
        )).get("projects", [])
        return [
            _public_project(_decrypt_project_record_with_key(
                project,
                _project_key_from_record(project, wrapping_key, context_team_id),
            ))
            for project in records
            if isinstance(project, dict)
        ]

    def show(self, project_id: str, *, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        resolved_project_id = _resolve_project_id(self._client, project_id, personal=personal, team_id=context_team_id)
        response = self._client._get(_with_query(f"/v1/projects/{_quote(resolved_project_id)}", team_id=context_team_id))
        project = response.get("project")
        if not isinstance(project, dict):
            raise OpenMatesApiError(404, {"detail": "Project not found"})
        key = _project_key_from_record(project, _project_wrapping_key(self._client, context_team_id), context_team_id)
        return _public_project(_decrypt_project_record_with_key(project, key))

    def create(self, payload: dict[str, Any], *, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        wrapping_key = _project_wrapping_key(self._client, context_team_id)
        encrypted = _build_project_create_input(wrapping_key, payload, context_team_id)
        project_key = _project_key_from_record(encrypted, wrapping_key, context_team_id)
        project = self._client._post(_with_query("/v1/projects", team_id=context_team_id), encrypted).get("project", {})
        return _public_project(_decrypt_project_record_with_key(project, project_key))

    def update(self, project_id: str, payload: dict[str, Any], *, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        built = _build_project_update_input(
            self._client,
            {"project_id": project_id, "patch": payload},
            personal=personal,
            team_id=context_team_id,
        )
        project_key = _resolve_project_key(self._client, built["project_id"], personal=personal, team_id=context_team_id)
        project = self._client._patch(
            _with_query(f"/v1/projects/{_quote(built['project_id'])}", team_id=context_team_id),
            built["patch"],
        ).get("project", {})
        return _public_project(_decrypt_project_record_with_key(project, project_key))

    def archive(self, project_id: str, *, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        return self.update(project_id, {"archived": True}, personal=personal, team_id=team_id)

    def unarchive(self, project_id: str, *, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        return self.update(project_id, {"archived": False}, personal=personal, team_id=team_id)

    def delete(self, project_id: str, *, confirmed: bool, personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        _require_confirmed(confirmed, "Project delete")
        context_team_id = _project_context(personal=personal, team_id=team_id)
        resolved_project_id = _resolve_project_id(self._client, project_id, personal=personal, team_id=context_team_id)
        response = self._client._delete(_with_query(
            f"/v1/projects/{_quote(resolved_project_id)}",
            confirmation_project_id=resolved_project_id,
            team_id=context_team_id,
        ))
        return {"deleted": response.get("deleted") is True}

    def history(self, project_id: str, *, limit: int | None = None, personal: bool = False, team_id: str | None = None) -> list[dict[str, Any]]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        resolved_project_id = _resolve_project_id(self._client, project_id, personal=personal, team_id=context_team_id)
        query = f"?limit={limit}" if limit is not None else ""
        return self._client._get(_with_query(f"/v1/projects/{_quote(resolved_project_id)}/history{query}", team_id=context_team_id)).get("entries", [])

    def restore(self, project_id: str, *, entry_id: str, state: str = "after", personal: bool = False, team_id: str | None = None) -> dict[str, Any]:
        context_team_id = _project_context(personal=personal, team_id=team_id)
        resolved_project_id = _resolve_project_id(self._client, project_id, personal=personal, team_id=context_team_id)
        return self._client._post(
            _with_query(f"/v1/projects/{_quote(resolved_project_id)}/restore", team_id=context_team_id),
            {"entry_id": entry_id, "state": state},
        )

    def ask(
        self,
        instruction: str,
        *,
            create: dict[str, Any] | None = None,
            update: dict[str, Any] | None = None,
            updates: list[dict[str, Any]] | None = None,
            exact_delete: dict[str, Any] | None = None,
            exact_deletes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        planned_create = None
        if create is None and update is None and not updates and exact_delete is None and exact_deletes is None:
            planned_create = self._client._post("/v1/projects/ask/plan", {"instruction": instruction}).get("proposed_project")
        payload: dict[str, Any] = {"instruction": instruction}
        if create is not None or planned_create is not None:
            payload["encrypted_create"] = _build_project_create_input(master_key, create or planned_create or {"name": instruction})
        if update is not None:
            payload["encrypted_update"] = _build_project_update_input(self._client, update)
        if updates is not None:
            payload["encrypted_updates"] = [_build_project_update_input(self._client, item) for item in updates]
        if exact_delete is not None:
            payload["exact_delete"] = exact_delete
        if exact_deletes is not None:
            payload["exact_deletes"] = exact_deletes
        response = self._client._post("/v1/projects/ask", payload)
        records = response.get("projects") if isinstance(response.get("projects"), list) else [response.get("project")] if isinstance(response.get("project"), dict) else []
        projects = [_public_project(_decrypt_project_record(project, master_key)) for project in records if isinstance(project, dict)]
        return {**response, "project": projects[0] if len(projects) == 1 else None, "projects": projects}


class OpenMatesWorkflows:
    """Server-side workflow SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def list(self) -> list[dict[str, Any]]:
        return [self._decrypt_slug(workflow) for workflow in self._client._get("/v1/workflows").get("workflows", [])]

    def temporary(self) -> list[dict[str, Any]]:
        return [self._decrypt_slug(workflow) for workflow in self._client._get("/v1/workflows/temporary").get("workflows", [])]

    def _decrypt_slug(self, workflow: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(workflow, dict):
            return workflow
        public_workflow = {key: value for key, value in workflow.items() if key not in {"encrypted_slug", "slug_lookup_hash"}}
        if isinstance(workflow.get("encrypted_slug"), str):
            public_workflow["slug"] = _decrypt_object_slug(workflow["encrypted_slug"], self._client._get_master_key())
        return public_workflow

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
        return {**response, "workflow": self._decrypt_slug(response["workflow"])}

    def update_from_yaml(self, workflow_id: str, source: str) -> dict[str, Any]:
        response = _workflow_resource_request(self._client, "POST", workflow_id, "/yaml", {"source": source})
        if not isinstance(response.get("workflow"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing workflow"})
        if not isinstance(response.get("validation"), dict):
            raise OpenMatesApiError(500, {"detail": "Workflow YAML response missing validation"})
        return {**response, "workflow": self._decrypt_slug(response["workflow"])}

    def history(self, workflow_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = f"?limit={limit}" if limit is not None else ""
        return _workflow_resource_request(self._client, "GET", workflow_id, f"/history{query}").get("entries", [])

    def restore(self, workflow_id: str, *, entry_id: str, state: str = "after") -> dict[str, Any]:
        return _workflow_resource_request(self._client, "POST", workflow_id, "/restore", {"entry_id": entry_id, "state": state})

    def ask(
        self,
        instruction: str,
        *,
        create: dict[str, Any] | None = None,
        exact_update: dict[str, Any] | None = None,
        exact_action: dict[str, Any] | None = None,
        selected_object_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"instruction": instruction}
        if create is not None:
            payload["create"] = create
        if exact_update is not None:
            payload["exact_update"] = exact_update
        if exact_action is not None:
            payload["exact_action"] = exact_action
        if selected_object_id is not None:
            payload["selected_object_id"] = _resolve_workflow_id(self._client, selected_object_id)
        return self._client._post("/v1/workflows/ask", payload)

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
            payload["selected_workflow_id"] = _resolve_workflow_id(self._client, selected_workflow_id)
        if selected_project_id is not None:
            payload["selected_project_id"] = _resolve_project_id(self._client, selected_project_id)
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
        return self._decrypt_slug(_workflow_resource_request(self._client, "GET", workflow_id).get("workflow", {}))

    def add_to_project(
        self,
        workflow_id: str,
        project_id: str,
        *,
        folder: str | None = None,
    ) -> dict[str, Any]:
        resolved_project_id = _resolve_project_id(self._client, project_id)
        project_key = _resolve_project_key(self._client, resolved_project_id)
        workflow = self.get(workflow_id)
        target_id = str(workflow.get("id") or workflow_id)
        display_name = str(workflow.get("title") or target_id)
        return _create_encrypted_project_item(
            self._client,
            resolved_project_id,
            project_key,
            item_type="workflow",
            target_id=target_id,
            display_name=display_name,
            folder=folder,
            metadata={
                "storage": "save_only_in_openmates",
                "source": "sdk_add_to_project",
            },
        )

    def remove_from_project(self, workflow_id: str, project_id: str) -> dict[str, Any]:
        workflow = self.get(workflow_id)
        target_id = str(workflow.get("id") or workflow_id)
        return _delete_project_item_by_target(self._client, _resolve_project_id(self._client, project_id), "workflow", target_id)

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
        slug: str | None = None,
        source_chat_id: str | None = None,
        created_by_assistant: bool = False,
        auto_delete_at: int | None = None,
    ) -> dict[str, Any]:
        master_key = self._client._get_master_key()
        slug_metadata = _encrypted_object_slug_metadata(slug or title, encryption_key=master_key, lookup_key=master_key)
        payload = {
            "title": title,
            "encrypted_slug": slug_metadata["encrypted_slug"],
            "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
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
            payload["source_chat_id"] = _resolve_chat_id(self._client, source_chat_id)
        if auto_delete_at is not None:
            payload["auto_delete_at"] = auto_delete_at
        return self._decrypt_slug(self._client._post(
            "/v1/workflows",
            payload,
        ).get("workflow", {}))

    def update(
        self,
        workflow_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        graph: dict[str, Any] | None = None,
        enabled: bool | None = None,
        run_content_retention: str | None = None,
        slug: str | None = None,
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
        if slug is not None:
            master_key = self._client._get_master_key()
            slug_metadata = _encrypted_object_slug_metadata(slug, encryption_key=master_key, lookup_key=master_key)
            payload["encrypted_slug"] = slug_metadata["encrypted_slug"]
            payload["slug_lookup_hash"] = slug_metadata["slug_lookup_hash"]
        return self._decrypt_slug(_workflow_resource_request(self._client, "PATCH", workflow_id, "", payload).get("workflow", {}))

    def enable(self, workflow_id: str) -> dict[str, Any]:
        return self._decrypt_slug(_workflow_resource_request(self._client, "POST", workflow_id, "/enable", {}).get("workflow", {}))

    def disable(self, workflow_id: str) -> dict[str, Any]:
        return self._decrypt_slug(_workflow_resource_request(self._client, "POST", workflow_id, "/disable", {}).get("workflow", {}))

    def delete(self, workflow_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        _require_confirmed(confirmed, "Deleting a workflow")
        return _workflow_resource_request(self._client, "DELETE", workflow_id)

    def keep(self, workflow_id: str) -> dict[str, Any]:
        return self._decrypt_slug(_workflow_resource_request(self._client, "POST", workflow_id, "/keep", {}).get("workflow", {}))

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
        return _workflow_resource_request(
            self._client,
            "POST",
            workflow_id,
            "/run",
            {"mode": mode, "input": input_data or {}},
            extra_headers={"Idempotency-Key": idempotency_key},
        ).get("run", {})

    def runs(self, workflow_id: str) -> list[dict[str, Any]]:
        return _workflow_resource_request(self._client, "GET", workflow_id, "/runs").get("runs", [])

    def run_detail(self, workflow_id: str, run_id: str) -> dict[str, Any]:
        return _workflow_resource_request(self._client, "GET", workflow_id, f"/runs/{_quote(run_id)}").get("run", {})

    def step_test(
        self,
        workflow_id: str,
        step_id: str,
        *,
        input_data: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        response = _workflow_resource_request(
            self._client,
            "POST",
            workflow_id,
            f"/steps/{_quote(step_id)}/test",
            {"input": input_data or {}, "confirmed": confirmed},
        )
        run = response.get("run")
        if not isinstance(run, dict):
            raise OpenMatesApiError(500, {"detail": "Workflow response missing run"})
        return run

    def cancel_run(self, workflow_id: str, run_id: str) -> dict[str, Any]:
        result = _workflow_resource_request(self._client, "POST", workflow_id, f"/runs/{_quote(run_id)}/cancel", {})
        if result.get("status") not in {"cancellation_requested", "cancelled"}:
            raise OpenMatesApiError(500, {"detail": "Workflow response has invalid cancellation status"})
        return result

    def respond(self, workflow_id: str, run_id: str, step_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        response = _workflow_resource_request(
            self._client,
            "POST",
            workflow_id,
            f"/runs/{_quote(run_id)}/respond",
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
        return _workflow_resource_request(
            self._client,
            "PUT",
            workflow_id,
            "/template-projection",
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
        return _workflow_resource_request(self._client, "POST", workflow_id, "/template-projection/revoke", {})

    def unrevoke_template_projection(self, workflow_id: str) -> dict[str, Any]:
        return _workflow_resource_request(self._client, "POST", workflow_id, "/template-projection/unrevoke", {})

    def complete_imported_binding(
        self,
        workflow_id: str,
        *,
        binding_type: str,
        node_id: str,
    ) -> dict[str, Any]:
        return _workflow_resource_request(
            self._client,
            "POST",
            workflow_id,
            "/binding-requirements/complete",
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
        return self._decrypt_slug(workflow)


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

    def download_export(self, *, accept_partial: bool = False, **options: Any) -> dict[str, Any]:
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

    def parse_claude_import(self, payload: bytes | str, source_name: str = "claude-export", source: str = "claude") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            if raw[:2] == b"PK":
                conversations = json.loads(_read_import_zip_text(raw, "conversations.json"))
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
        return _finalize_account_import({"chats": chats, "skipped_domains": []}, "claude", source)

    def parse_chatgpt_import(self, payload: bytes | str, source_name: str = "chatgpt-export", source: str = "chatgpt") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            if raw[:2] == b"PK":
                conversations = json.loads(_read_import_zip_text(raw, "conversations.json"))
            else:
                conversations = json.loads(raw.decode("utf-8"))
        except OpenMatesConfigError:
            raise
        except Exception as exc:
            raise OpenMatesConfigError(f"ChatGPT export could not be parsed: {exc}") from exc
        if isinstance(conversations, dict) and isinstance(conversations.get("conversations"), list):
            conversations = conversations["conversations"]
        if not isinstance(conversations, list):
            raise OpenMatesConfigError("ChatGPT export conversations must be an array")
        chats: list[dict[str, Any]] = []
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            source_chat_id = str(conversation.get("conversation_id") or conversation.get("id") or "")
            if not source_chat_id:
                raise OpenMatesConfigError("ChatGPT conversation is missing id")
            messages: list[dict[str, Any]] = []
            for node in _chatgpt_active_nodes(conversation):
                raw_message = node.get("message")
                if not isinstance(raw_message, dict):
                    continue
                author = raw_message.get("author") if isinstance(raw_message.get("author"), dict) else {}
                role = str(author.get("role") or "")
                if role not in {"user", "assistant", "system"}:
                    continue
                content = raw_message.get("content")
                if not isinstance(content, dict):
                    continue
                text, metadata = _chatgpt_message_content(content)
                if not text.strip():
                    continue
                messages.append({
                    "role": role,
                    "content": text,
                    "created_at": _chatgpt_timestamp(raw_message.get("create_time")),
                    "source_message_id": raw_message.get("id") if isinstance(raw_message.get("id"), str) else None,
                    "provider_metadata": metadata,
                })
            chats.append({
                "provider": "chatgpt",
                "source_chat_id": source_chat_id,
                "source_fingerprint": _account_import_fingerprint("chatgpt", source_chat_id, messages),
                "title": conversation.get("title") if isinstance(conversation.get("title"), str) else None,
                "created_at": _chatgpt_timestamp(conversation.get("create_time")),
                "updated_at": _chatgpt_timestamp(conversation.get("update_time")),
                "messages": messages,
                "embeds": [],
                "uploads": [],
                "provider_labels": ["chatgpt"],
                "source_metadata": {"source_name": source_name, "message_count": len(messages)},
            })
        return _finalize_account_import({"chats": chats, "skipped_domains": []}, "chatgpt", source)

    def parse_opencode_import(self, payload: bytes | str, source_name: str = "opencode-session.json", source: str = "opencode") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            transcript = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise OpenMatesConfigError(f"OpenCode transcript export could not be parsed: {exc}") from exc
        if not isinstance(transcript, dict):
            raise OpenMatesConfigError("OpenCode transcript export must be an object")
        info = transcript.get("info")
        raw_messages = transcript.get("messages")
        if not isinstance(info, dict) or not isinstance(raw_messages, list) or not info.get("id"):
            raise OpenMatesConfigError("OpenCode transcript export is missing info.id or messages")

        messages: list[dict[str, Any]] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            message_info = item.get("info") if isinstance(item.get("info"), dict) else {}
            role = str(message_info.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            parts = [part for part in item.get("parts", []) if isinstance(part, dict)] if isinstance(item.get("parts"), list) else []
            text_parts = [part for part in parts if part.get("type") == "text" and part.get("ignored") is not True and isinstance(part.get("text"), str)]
            content = "\n".join(str(part["text"]) for part in text_parts if str(part["text"]).strip())
            if content.strip():
                message_time = message_info.get("time") if isinstance(message_info.get("time"), dict) else {}
                messages.append({
                    "role": role,
                    "content": content,
                    "created_at": _opencode_timestamp(message_time.get("created")),
                    "source_message_id": message_info.get("id") if isinstance(message_info.get("id"), str) else None,
                    "provider_metadata": {"part_types": [str(part.get("type") or "unknown") for part in parts], "text_part_count": len(text_parts)},
                })
        source_chat_id = str(info["id"])
        session_time = info.get("time") if isinstance(info.get("time"), dict) else {}
        chat = {
            "provider": "opencode",
            "source_chat_id": source_chat_id,
            "source_fingerprint": _account_import_fingerprint("opencode", source_chat_id, messages),
            "title": info.get("title") if isinstance(info.get("title"), str) else None,
            "created_at": _opencode_timestamp(session_time.get("created")),
            "updated_at": _opencode_timestamp(session_time.get("updated")),
            "messages": messages,
            "embeds": [],
            "uploads": [],
            "provider_labels": ["opencode"],
            "source_metadata": {"source_name": source_name, "message_count": len(messages)},
        }
        return _finalize_account_import({"chats": [chat], "skipped_domains": []}, "opencode", source)

    def parse_openmates_import(self, payload: bytes | str, source_name: str = "openmates-export.zip", password: str | None = None, source: str = "openmates") -> dict[str, Any]:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            with zipfile.ZipFile(io.BytesIO(_decrypt_openmates_encrypted_zip(raw, password))) as archive:  # type: ignore[name-defined]
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
        return _finalize_account_import({"chats": chats, "skipped_domains": skipped}, "openmates", source)

    def parse_generic_import(self, payload: bytes | str, source: str, source_name: str = "generic-transcript.json") -> dict[str, Any]:
        if source not in {"gemini", "other"}:
            raise OpenMatesConfigError("Generic account import source must be gemini or other")
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise OpenMatesConfigError(f"Generic role/content transcript could not be parsed: {exc}") from exc
        raw_chats = decoded if isinstance(decoded, list) else [decoded]
        if not raw_chats or any(not isinstance(chat, dict) or not isinstance(chat.get("messages"), list) for chat in raw_chats):
            raise OpenMatesConfigError("Generic role/content transcript must contain chat objects with messages arrays")
        chats: list[dict[str, Any]] = []
        for chat_index, raw_chat in enumerate(raw_chats):
            allowed_chat_fields = {"id", "title", "created_at", "updated_at", "messages"}
            unknown_chat_fields = sorted(set(raw_chat) - allowed_chat_fields)
            if unknown_chat_fields:
                raise OpenMatesConfigError(f"Generic role/content transcript contains unknown chat fields: {', '.join(unknown_chat_fields)}")
            raw_messages = raw_chat["messages"]
            if not raw_messages:
                raise OpenMatesConfigError("Generic role/content transcript messages must not be empty")
            messages: list[dict[str, Any]] = []
            for message_index, raw_message in enumerate(raw_messages):
                if not isinstance(raw_message, dict) or "role" not in raw_message or "content" not in raw_message:
                    raise OpenMatesConfigError(f"Generic role/content message {message_index + 1} requires role and content")
                allowed_message_fields = {"id", "role", "content", "created_at"}
                unknown_message_fields = sorted(set(raw_message) - allowed_message_fields)
                if unknown_message_fields:
                    raise OpenMatesConfigError(f"Generic role/content message {message_index + 1} contains unknown fields: {', '.join(unknown_message_fields)}")
                role = raw_message["role"]
                content = raw_message["content"]
                if role not in {"user", "assistant", "system"} or not isinstance(content, str) or not content.strip():
                    raise OpenMatesConfigError(f"Generic role/content message {message_index + 1} has invalid role or content")
                messages.append({
                    "role": role,
                    "content": content,
                    "created_at": raw_message.get("created_at") if isinstance(raw_message.get("created_at"), str) else None,
                    "source_message_id": raw_message.get("id") if isinstance(raw_message.get("id"), str) else None,
                    "provider_metadata": {},
                })
            source_chat_id = str(raw_chat.get("id") or f"generic-chat-{chat_index + 1}")
            chats.append({
                "provider": source,
                "source_chat_id": source_chat_id,
                "source_fingerprint": _account_import_fingerprint("generic", source_chat_id, messages),
                "title": raw_chat.get("title") if isinstance(raw_chat.get("title"), str) else None,
                "created_at": raw_chat.get("created_at") if isinstance(raw_chat.get("created_at"), str) else None,
                "updated_at": raw_chat.get("updated_at") if isinstance(raw_chat.get("updated_at"), str) else None,
                "messages": messages,
                "embeds": [],
                "uploads": [],
                "provider_labels": [source, "generic"],
                "source_metadata": {"source_name": source_name, "message_count": len(messages)},
            })
        return _finalize_account_import({"chats": chats, "skipped_domains": []}, "generic", source)

    def preview_import(self, *, source: str, chats: list[dict[str, Any]] | None = None, chat_count: int | None = None, source_fingerprints: list[str] | None = None, estimated_tokens: int = 0, estimated_tokens_by_chat: list[int] | None = None, estimated_bytes: int = 0) -> dict[str, Any]:
        selected_chats = chats or []
        return self._client._post("/v1/account-imports/preview", {
            "source": source,
            **({"parser_format": selected_chats[0].get("parser_format")} if selected_chats and selected_chats[0].get("parser_format") else {}),
            "chat_count": chat_count if chat_count is not None else len(selected_chats),
            "source_fingerprints": source_fingerprints if source_fingerprints is not None else [str(chat.get("source_fingerprint") or "") for chat in selected_chats],
            "estimated_tokens": estimated_tokens,
            "estimated_tokens_by_chat": estimated_tokens_by_chat if estimated_tokens_by_chat is not None else [(sum(len(str(message.get("content") or "")) for message in chat.get("messages", [])) + 3) // 4 for chat in selected_chats],
            "estimated_bytes": estimated_bytes,
        })

    def confirm_import(self, import_id: str, selected_fingerprints: list[str]) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/confirm", {"selected_fingerprints": selected_fingerprints})

    def scan_import(self, import_id: str, chats: list[dict[str, Any]], *, sequence: int = 0, final_batch: bool = True, batch_id: str | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/scan", {
            "batch_id": batch_id or f"scan-{sequence}",
            "sequence": sequence,
            "final_batch": final_batch,
            "chats": chats,
        })

    def import_status(self, import_id: str) -> dict[str, Any]:
        return self._client._get(f"/v1/account-imports/{quote(import_id, safe='')}/status")

    def compress_import(self, import_id: str, *, sanitized_messages: list[dict[str, Any]], scan_sequence: int, source_fingerprint: str, prior_summary: str | None = None, sequence: int = 0, final_batch: bool = True, batch_id: str | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/compress", {
            "batch_id": batch_id or f"compress-{sequence}",
            "sequence": sequence,
            "final_batch": final_batch,
            "scan_sequence": scan_sequence,
            "source_fingerprint": source_fingerprint,
            "sanitized_messages": sanitized_messages,
            **({"prior_summary": prior_summary} if prior_summary is not None else {}),
        })

    def persist_import(self, import_id: str, chats: list[dict[str, Any]]) -> dict[str, Any]:
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
                identity = message.get("imported_assistant_identity") if role == "assistant" and isinstance(message.get("imported_assistant_identity"), dict) else None
                metadata = message.get("provider_metadata") if isinstance(message.get("provider_metadata"), dict) else {}
                is_compression_summary = metadata.get("import_type") == COMPRESSION_SUMMARY_CATEGORY
                row = {
                    "message_id": message_id,
                    "role": role,
                    "encrypted_content": _encrypt_aes_gcm_text(str(message.get("content") or ""), chat_key),
                    "encrypted_sender_name": _encrypt_aes_gcm_text(str(identity.get("sender_name")) if identity else "AI assistant" if role == "assistant" else "System" if role == "system" else "User", chat_key),
                    "created_at": _parse_import_timestamp(message.get("created_at")),
                    "updated_at": int(time.time()),
                }
                if identity:
                    row["encrypted_category"] = _encrypt_aes_gcm_text(str(identity["category"]), chat_key)
                    row["encrypted_model_name"] = _encrypt_aes_gcm_text(str(identity["model_name"]), chat_key)
                elif is_compression_summary:
                    row["encrypted_category"] = _encrypt_aes_gcm_text(COMPRESSION_SUMMARY_CATEGORY, chat_key)
                    row["encrypted_model_name"] = _encrypt_aes_gcm_text(str(chat.get("selected_source") or "other"), chat_key)
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

    def complete_import(self, import_id: str, *, imported_chat_ids: list[str], source_fingerprints: list[str], record_counts: dict[str, int], client_failures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._client._post(f"/v1/account-imports/{quote(import_id, safe='')}/complete", {
            "imported_chat_ids": imported_chat_ids,
            "source_fingerprints": source_fingerprints,
            "encrypted_record_counts": record_counts,
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
        selected_fingerprints = [str(chat.get("source_fingerprint") or "") for chat in selected_chats]
        confirmation = self.confirm_import(import_id, selected_fingerprints)
        initial_status = self.import_status(import_id)
        if int(initial_status.get("last_scan_sequence", -1)) != -1 or int(initial_status.get("last_compression_sequence", -1)) != -1:
            raise OpenMatesConfigError("Resuming this import requires the client-held sanitized batch state.")
        batches = _account_import_message_batches(selected_chats)
        sanitized_chats = [{**chat, "messages": []} for chat in selected_chats]
        sanitized_batches: list[dict[str, Any]] = []
        scan: dict[str, Any] = {}
        for sequence, batch in enumerate(batches):
            scan = self.scan_import(
                import_id,
                [batch["chat"]],
                sequence=sequence,
                final_batch=sequence == len(batches) - 1,
                batch_id=batch["batch_id"],
            )
            if scan.get("status") != "acknowledged" or scan.get("sequence") != sequence or scan.get("batch_id") != batch["batch_id"] or not isinstance(scan.get("chats"), list):
                raise OpenMatesConfigError("Account import scan batch was not acknowledged at the expected cursor.")
            if not scan["chats"]:
                raise OpenMatesConfigError("Account import scan omitted the sanitized batch.")
            sanitized_messages = scan["chats"][0].get("messages", [])
            sanitized_chats[batch["chat_index"]]["messages"].extend(sanitized_messages)
            sanitized_batches.append({
                "messages": sanitized_messages,
                "scan_sequence": sequence,
                "source_fingerprint": batch["source_fingerprint"],
                "chat_index": batch["chat_index"],
                "chunk_index": batch["chunk_index"],
            })
        post_scan_status = self.import_status(import_id)
        if int(post_scan_status.get("last_scan_sequence", -1)) != len(batches) - 1:
            raise OpenMatesConfigError("Account import scan status cursor did not advance as expected.")
        summaries: dict[str, str] = {}
        compression: dict[str, Any] = {}
        for sequence, batch in enumerate(sanitized_batches):
            final_chat_batch = sequence + 1 == len(sanitized_batches) or sanitized_batches[sequence + 1]["source_fingerprint"] != batch["source_fingerprint"]
            compression = self.compress_import(
                import_id,
                sanitized_messages=batch["messages"],
                scan_sequence=batch["scan_sequence"],
                source_fingerprint=batch["source_fingerprint"],
                prior_summary=summaries.get(batch["source_fingerprint"]),
                sequence=sequence,
                final_batch=final_chat_batch,
                batch_id=f"compress-{batch['source_fingerprint'][:16]}-{batch['chunk_index']}",
            )
            if compression.get("status") != "acknowledged" or compression.get("sequence") != sequence:
                raise OpenMatesConfigError("Account import compression was not acknowledged at the expected cursor.")
            if isinstance(compression.get("summary"), str) and compression["summary"].strip():
                summaries[batch["source_fingerprint"]] = compression["summary"]
        post_compression_status = self.import_status(import_id)
        if int(post_compression_status.get("last_compression_sequence", -1)) != len(sanitized_batches) - 1:
            raise OpenMatesConfigError("Account import compression status cursor did not advance as expected.")
        persisted_chats = [_append_compression_summary(chat, summaries.get(str(chat.get("source_fingerprint") or ""))) for chat in sanitized_chats]
        persistence = self.persist_import(import_id, persisted_chats)
        complete = self.complete_import(
            import_id,
            imported_chat_ids=[str(item) for item in persistence.get("imported_chat_ids", [])] if isinstance(persistence.get("imported_chat_ids"), list) else [],
            source_fingerprints=[str(chat.get("source_fingerprint") or "") for chat in persisted_chats],
            record_counts=persistence.get("encrypted_record_counts") if isinstance(persistence.get("encrypted_record_counts"), dict) else {"chats": 0, "messages": 0},
            client_failures=persistence.get("failures") if isinstance(persistence.get("failures"), list) else [],
        )
        return {"source": parsed.get("source"), "parsed": parsed, "preview": preview, "import_id": import_id, "confirmation": confirmation, "initial_status": initial_status, "post_scan_status": post_scan_status, "scan": scan, "compression": compression, "post_compression_status": post_compression_status, "persistence": persistence, "complete": complete}

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

    def set_model_defaults(
        self,
        *,
        default_ai_model_simple: str | None = None,
        default_ai_model_complex: str | None = None,
        default_ai_model_most_demanding: str | None = None,
    ) -> dict[str, Any]:
        defaults: AiModelDefaults = {
            "default_ai_model_simple": default_ai_model_simple,
            "default_ai_model_complex": default_ai_model_complex,
            "default_ai_model_most_demanding": default_ai_model_most_demanding,
        }
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
    def usage_overview(self, **query: Any) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/billing/usage/overview", **query))
    def usage_details(self, *, type: str, identifier: str, year_month: str) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/billing/usage/details", type=type, identifier=identifier, year_month=year_month))
    def chat_total(self, chat_id: str) -> dict[str, Any]: return self._client._get(_with_query("/v1/sdk/billing/usage/chat-total", chat_id=chat_id))
    def usage_summaries(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/summaries")
    def usage_daily(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/usage/daily")
    def usage_export(self, *, months: int | None = None) -> dict[str, Any]: return self._client._get_raw(_with_query("/v1/sdk/billing/usage/export", months=months))
    def create_bank_transfer_order(self, credits: int, *, email_encryption_key: str | None = None) -> dict[str, Any]: return self._client._post("/v1/sdk/billing/bank-transfer-orders", {"credits_amount": credits, "currency": "eur", "email_encryption_key": email_encryption_key})
    def bank_transfer_status(self, order_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/billing/bank-transfer-orders/{_quote(order_id)}")
    def list_bank_transfer_orders(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/bank-transfer-orders")
    def list_invoices(self) -> dict[str, Any]: return self._client._get("/v1/sdk/billing/invoices")
    def download_invoice(self, invoice_id: str) -> dict[str, Any]: return self._client._get_raw(f"/v1/sdk/billing/invoices/{_quote(invoice_id)}/download")
    def download_credit_note(self, invoice_id: str) -> dict[str, Any]: return self._client._get_raw(f"/v1/sdk/billing/invoices/{_quote(invoice_id)}/credit-note/download")
    def request_refund(self, invoice_id: str, *, confirmed: bool = False, email_encryption_key: str | None = None) -> dict[str, Any]:
        _require_confirmed(confirmed, "Requesting an invoice refund")
        return self._client._post("/v1/sdk/billing/refund", {"invoice_id": invoice_id, "email_encryption_key": email_encryption_key})
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


class OpenMatesWikipedia:
    def __init__(self, client: OpenMates): self._client = client
    def search(self, query: str, *, language: str | None = "en", limit: int | None = None) -> dict[str, Any]:
        return self._client._get(_with_query("/v1/wikipedia/search", query=query, language=language or "en", limit=limit))
    def summary(self, title: str, *, language: str | None = "en") -> dict[str, Any]:
        return self._client._get(_with_query("/v1/wikipedia/summary", title=title, language=language or "en"))


class OpenMatesEmbeds:
    def __init__(self, client: OpenMates):
        self._client = client
        self.preview = OpenMatesEmbedPreview(client)
    def show(self, embed_id: str) -> dict[str, Any]: return self._client._get(f"/v1/sdk/embeds/{_quote(embed_id)}")
    def add_to_project(self, embed_id: str, project_id: str, *, folder: str | None = None) -> dict[str, Any]:
        project_key = _resolve_project_key(self._client, project_id)
        return _create_encrypted_project_item(
            self._client,
            project_id,
            project_key,
            item_type="embed",
            target_id=embed_id,
            display_name=embed_id,
            folder=folder,
            metadata={
                "storage": "save_only_in_openmates",
                "source": "sdk_add_to_project",
            },
        )
    def remove_from_project(self, embed_id: str, project_id: str) -> dict[str, Any]:
        return _delete_project_item_by_target(self._client, project_id, "embed", embed_id)
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


class OpenMatesFinance:
    """Finance SDK namespace for connected-account-only Finance skills."""

    def __init__(self, client: OpenMates):
        self._client = client

    def check_accounts(
        self,
        input_data: dict[str, Any],
        *,
        connected_account_token_ref_inputs: list[dict[str, Any]] | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        prompt_injection_protection: bool | None = False,
    ) -> dict[str, Any]:
        return self._client.run_connected_account_skill(
            "finance",
            "check_accounts",
            input_data,
            connected_account_token_ref_inputs=connected_account_token_ref_inputs,
            chat_id=chat_id,
            message_id=message_id,
            prompt_injection_protection=prompt_injection_protection,
        )


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

    def create_plain(self, payload: dict[str, Any] | None = None, *, team_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        input_payload = {**(payload or {}), **kwargs}
        if team_id is not None:
            input_payload["team_id"] = team_id
        profile = _generated_team_profile_image_metadata(input_payload.get("profile") if isinstance(input_payload.get("profile"), dict) else None)
        result = self._client._post("/v1/teams", _build_team_plain_create_payload(self._client, input_payload))
        return {**dict(result.get("team") or result), "profile_image_metadata": profile}

    def update(self, team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._client._patch(f"/v1/teams/{_quote(team_id)}", payload)
        return dict(result.get("team") or result)

    def update_generated_profile_image(self, team_id: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        input_payload = {**(payload or {}), **kwargs}
        profile = _generated_team_profile_image_metadata(input_payload)
        team_key = _team_key_from_record(self._client, self.get(team_id))
        result = self._client._patch(
            f"/v1/teams/{_quote(team_id)}",
            {
                "encrypted_profile_image_metadata": _encrypt_aes_gcm_text(json.dumps(profile), team_key),
                "updated_at": int(time.time()),
            },
        )
        return {**dict(result.get("team") or result), "profile_image_metadata": profile}

    def get_profile_image(self, team_id: str) -> dict[str, Any]:
        return self._client._get_raw(f"/v1/teams/{_quote(team_id)}/profile-image")

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
