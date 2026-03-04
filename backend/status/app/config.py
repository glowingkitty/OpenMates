"""
Status service configuration and monitored service definitions.
Architecture: Independent status VM with its own health storage/checking.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status service tests not added yet)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

ENV_PROD: Final[str] = "prod"
ENV_DEV: Final[str] = "dev"
VALID_ENVS: Final[set[str]] = {ENV_PROD, ENV_DEV}

STATUS_OPERATIONAL: Final[str] = "operational"
STATUS_DEGRADED: Final[str] = "degraded"
STATUS_DOWN: Final[str] = "down"
STATUS_UNKNOWN: Final[str] = "unknown"

GROUP_CORE: Final[str] = "core_platform"
GROUP_AI: Final[str] = "ai_providers"
GROUP_PAYMENT: Final[str] = "payment"
GROUP_EMAIL: Final[str] = "email"
GROUP_MODERATION: Final[str] = "content_moderation"
GROUP_SEARCH_DATA: Final[str] = "search_and_data"
GROUP_INFRA: Final[str] = "infrastructure"

DEFAULT_CHECK_INTERVAL_SECONDS: Final[int] = 60
EVENT_RETENTION_DAYS: Final[int] = 90
RESPONSE_RETENTION_DAYS: Final[int] = 30
HTTP_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True)
class MonitoredService:
    service_id: str
    service_name: str
    group_name: str
    is_shared_between_envs: bool = False


CORE_SERVICES: Final[tuple[MonitoredService, ...]] = (
    MonitoredService("web_app", "Web App", GROUP_CORE),
    MonitoredService("core_api", "Core API", GROUP_CORE),
    MonitoredService("upload_server", "Upload Server", GROUP_CORE, is_shared_between_envs=True),
    MonitoredService("preview_server", "Preview Server", GROUP_CORE, is_shared_between_envs=True),
)

PAYMENT_SERVICE_IDS: Final[set[str]] = {"stripe", "polar", "revolut", "invoiceninja"}
EMAIL_SERVICE_IDS: Final[set[str]] = {"brevo"}
MODERATION_SERVICE_IDS: Final[set[str]] = {"sightengine"}
SEARCH_DATA_SERVICE_IDS: Final[set[str]] = {"brave_search", "brave"}
INFRA_SERVICE_IDS: Final[set[str]] = {"vercel", "upload_server", "preview_server"}


def get_status_db_path() -> str:
    default_path = "/app/data/status.db"
    return os.getenv("STATUS_DB_PATH", default_path)


def get_check_interval_seconds() -> int:
    value = os.getenv("STATUS_CHECK_INTERVAL_SECONDS", str(DEFAULT_CHECK_INTERVAL_SECONDS))
    return max(30, int(value))


def get_base_urls() -> dict[str, dict[str, str]]:
    prod_web = os.getenv("PROD_WEB_URL", "https://openmates.org")
    prod_api = os.getenv("PROD_API_URL", "https://api.openmates.org")
    dev_web = os.getenv("DEV_WEB_URL", "https://dev.openmates.org")
    dev_api = os.getenv("DEV_API_URL", "https://api.dev.openmates.org")
    upload_url = os.getenv("UPLOAD_URL", "")
    preview_url = os.getenv("PREVIEW_URL", "")

    return {
        ENV_PROD: {
            "web_app": prod_web,
            "core_api": prod_api,
            "upload_server": upload_url,
            "preview_server": preview_url,
        },
        ENV_DEV: {
            "web_app": dev_web,
            "core_api": dev_api,
            "upload_server": upload_url,
            "preview_server": preview_url,
        },
    }


def get_group_for_external_service(service_id: str) -> str:
    if service_id in PAYMENT_SERVICE_IDS:
        return GROUP_PAYMENT
    if service_id in EMAIL_SERVICE_IDS:
        return GROUP_EMAIL
    if service_id in MODERATION_SERVICE_IDS:
        return GROUP_MODERATION
    if service_id in SEARCH_DATA_SERVICE_IDS:
        return GROUP_SEARCH_DATA
    if service_id in INFRA_SERVICE_IDS:
        return GROUP_INFRA
    return GROUP_INFRA
