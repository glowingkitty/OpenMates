"""Validated task, result and control contracts for owner-scoped web browsing."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDLE_PAUSE_SECONDS = 120
IDLE_DELETE_SECONDS = 86400
RUNTIME_USD_PER_SECOND = Decimal(
    "0.000046"
)  # 2 vCPU / 4 GiB; E2B, reviewed 2026-10-26.
CUSTOMER_MULTIPLIER = Decimal(2)
SIGN_IN_NOTICE = (
    "You're signing in to a cloud browser. When you let AI continue, it can access "
    "information in this account. Relevant page content may be sent to our AI "
    "providers. Only sign in to accounts you're comfortable giving AI access to."
)


class BrowseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    task: str = Field(min_length=1, max_length=8000)
    start_url: str | None = Field(default=None, max_length=4096)
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    max_steps: int = Field(default=40, ge=1, le=80)
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_credits: int = Field(default=250, ge=1, le=5000)
    output_schema: dict[str, Any] | None = None

    @field_validator("task")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Provide a browsing task.")
        return value.strip()

    @field_validator("start_url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        p = urlsplit(value)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.port not in (None, 443)
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Use a public HTTPS URL without credentials.")
        return value

    @field_validator("session_id")
    @classmethod
    def canonical_session_id(cls, value: str | None) -> str | None:
        return str(UUID(value)) if value else None

    @field_validator("output_schema")
    @classmethod
    def bounded_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        encoded = json.dumps(value)
        if len(encoded) > 12000:
            raise ValueError("Output schema exceeds the size limit.")

        def check(node: Any, depth: int = 0) -> None:
            if depth > 12:
                raise ValueError("Output schema exceeds the depth limit.")
            if isinstance(node, dict):
                if any(key in node for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ValueError("Output schema references are not supported.")
                if any(key in node for key in ("pattern", "patternProperties")):
                    raise ValueError(
                        "Regular-expression output schemas are not supported."
                    )
                if len(node) > 64:
                    raise ValueError("The output schema contains too many fields.")
                for child in node.values():
                    check(child, depth + 1)
            elif isinstance(node, list):
                if len(node) > 64:
                    raise ValueError(
                        "The output schema contains too many alternatives."
                    )
                for child in node:
                    check(child, depth + 1)

        check(value)
        if value.get("type") not in ("object", "array"):
            raise ValueError("The output schema must describe an object or array.")
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError:
            raise ValueError("Provide a valid JSON output schema.") from None
        return value


class BrowseManualInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    kind: Literal["click", "type", "key", "scroll"]
    x: float | None = Field(default=None, ge=0, lt=1280, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, lt=800, allow_inf_nan=False)
    text: str | None = Field(default=None, max_length=2000, repr=False)
    key: (
        Literal[
            "Enter",
            "Tab",
            "Shift+Tab",
            "Backspace",
            "Escape",
            "ArrowDown",
            "ArrowUp",
            "Control+A",
        ]
        | None
    ) = None
    delta: int | None = Field(default=None, ge=-800, le=800)

    @model_validator(mode="after")
    def required_coordinates_or_value(self) -> "BrowseManualInput":
        required = {
            "click": ("x", "y"),
            "type": ("text",),
            "key": ("key",),
            "scroll": ("delta",),
        }[self.kind]
        if any(getattr(self, field) is None for field in required):
            raise ValueError("Provide the required browser input fields.")
        return self


class BrowseControl(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    operation: Literal["take_control", "resume", "stop", "close", "input", "sign_in"]
    action: BrowseManualInput | None = None
    sign_in_origin: str | None = Field(default=None, max_length=2048)


class BrowseResult(BaseModel):
    session_id: str
    run_id: str
    status: Literal[
        "completed",
        "needs_user",
        "no_results",
        "blocked",
        "failed",
        "cancelled",
        "budget_exceeded",
    ]
    reason: str | None = None
    url: str = ""
    title: str = ""
    data: dict[str, Any] | list[Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    observations: dict[str, Any] = Field(default_factory=dict)
    screenshot_ref: dict[str, Any] | None = None
    screenshot_base64: str | None = Field(default=None, repr=False)
    metrics: dict[str, Any] = Field(default_factory=dict)


class BrowseJob(BaseModel):
    session_id: str
    run_id: str
    task_id: str
    embed_id: str | None = None
    status: Literal["processing"] = "processing"
    dispatch_required: bool = Field(default=True, exclude=True, repr=False)


def browse_identity(
    request: BrowseRequest, user_id: str, chat_id: str, message_id: str
) -> BrowseJob:
    import uuid

    identity = json.dumps(
        [user_id, chat_id, message_id, request.model_dump()], sort_keys=True
    )
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
    return BrowseJob(
        session_id=request.session_id
        or str(uuid.uuid5(uuid.NAMESPACE_URL, "session:" + identity)),
        run_id=run_id,
        task_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "browse-job:" + run_id)),
    )


def owner_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


def charged_credits(supplier_usd: str | Decimal) -> int:
    from backend.shared.python_utils.billing_utils import floor_raw_credits

    return floor_raw_credits(
        Decimal(supplier_usd) * CUSTOMER_MULTIPLIER / Decimal("0.001")
    )


def session_lifecycle(record: dict[str, Any], now: float) -> str:
    if record["status"] in ("closed", "expired"):
        return record["status"]
    idle = max(0.0, now - float(record["last_activity"]))
    if idle >= IDLE_DELETE_SECONDS:
        return "expired"
    if not record.get("active_run") and idle >= IDLE_PAUSE_SECONDS:
        return "paused"
    return record["status"]
