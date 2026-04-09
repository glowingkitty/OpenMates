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

PAYMENT_SERVICE_IDS: Final[set[str]] = {"stripe", "polar", "invoiceninja"}
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


@dataclass(frozen=True)
class UserComponent:
    """A user-facing component on the status page, mapping to one or more service_ids."""
    name: str
    group: str
    service_ids: tuple[str, ...]

# Groups ordered as they appear on the status page
SERVICE_GROUPS: Final[tuple[tuple[str, tuple[UserComponent, ...]], ...]] = (
    ("Core Platform", (
        UserComponent("Web App", "Core Platform", ("web_app",)),
        UserComponent("API Server", "Core Platform", ("core_api",)),
        UserComponent("Upload Server", "Core Platform", ("upload_server",)),
        UserComponent("Preview Server", "Core Platform", ("preview_server",)),
    )),
    ("AI Providers", (
        UserComponent("Anthropic", "AI Providers", ("anthropic",)),
        UserComponent("OpenAI", "AI Providers", ("openai",)),
        UserComponent("Groq", "AI Providers", ("groq",)),
        UserComponent("Mistral", "AI Providers", ("mistral",)),
        UserComponent("Google", "AI Providers", ("google",)),
        UserComponent("Cerebras", "AI Providers", ("cerebras",)),
        UserComponent("Together", "AI Providers", ("together",)),
        UserComponent("OpenRouter", "AI Providers", ("openrouter",)),
        UserComponent("AWS Bedrock", "AI Providers", ("aws_bedrock",)),
    )),
    ("Search & Data", (
        UserComponent("Brave Search", "Search & Data", ("brave", "brave_search")),
        UserComponent("SerpAPI", "Search & Data", ("serpapi",)),
        UserComponent("Firecrawl", "Search & Data", ("firecrawl",)),
        UserComponent("Context7", "Search & Data", ("context7",)),
        UserComponent("YouTube", "Search & Data", ("youtube",)),
        UserComponent("Google Maps", "Search & Data", ("google_maps",)),
    )),
    ("Image & Media", (
        UserComponent("FAL (Flux)", "Image & Media", ("fal",)),
        UserComponent("Recraft", "Image & Media", ("recraft",)),
    )),
    ("Events & Health", (
        UserComponent("Doctolib", "Events & Health", ("doctolib",)),
        UserComponent("Meetup", "Events & Health", ("meetup",)),
        UserComponent("Luma Events", "Events & Health", ("luma",)),
    )),
    ("Travel", (
        UserComponent("Travelpayouts", "Travel", ("travelpayouts",)),
        UserComponent("Transitous", "Travel", ("transitous",)),
        UserComponent("FlightRadar24", "Travel", ("flightradar24",)),
    )),
    ("Payment", (
        UserComponent("Stripe", "Payment", ("stripe",)),
        UserComponent("Polar", "Payment", ("polar",)),
    )),
    ("Email & Moderation", (
        UserComponent("Brevo", "Email & Moderation", ("brevo",)),
        UserComponent("Sightengine", "Email & Moderation", ("sightengine",)),
    )),
)

# E2E test categories — pattern-based matching against spec file names
TEST_CATEGORIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("Chat", ("chat-flow", "chat-management", "chat-scroll", "chat-search", "daily-inspiration", "fork-conversation", "hidden-chats", "import-chats", "message-sync", "background-chat")),
    ("Payment", ("buy-credits", "saved-payment", "settings-buy-credits")),
    ("Signup", ("signup",)),
    ("Login", ("account-recovery", "backup-code", "multi-session", "recovery-key", "session-revoke")),
    ("Search & AI", ("code-generation", "focus-mode", "follow-up-suggestions")),
    ("Media & Embeds", ("audio-recording", "embed-", "file-attachment", "pdf-flow")),
    ("Settings", ("api-keys", "incognito", "language-settings", "location-security", "pii-detection", "default-model", "model-override", "mention-dropdown")),
    ("Reminders", ("reminder-",)),
    ("Accessibility", ("a11y-",)),
    ("Skills", ("skill-", "cli-skills")),
    ("CLI", ("cli-images", "cli-memories", "cli-pair", "cli-file")),
    ("Infrastructure", ("status-page", "app-load", "connection-resilience", "page-load", "share-chat", "share-embed", "not-found", "embed-json")),
)


def get_all_service_ids() -> set[str]:
    """Return all monitored service_ids across all groups."""
    ids: set[str] = set()
    for _, components in SERVICE_GROUPS:
        for comp in components:
            ids.update(comp.service_ids)
    return ids


def categorize_test(spec_name: str) -> str | None:
    """Return the category name for a spec file, or None if uncategorized."""
    name_lower = spec_name.lower()
    for category_name, patterns in TEST_CATEGORIES:
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return category_name
    return None
