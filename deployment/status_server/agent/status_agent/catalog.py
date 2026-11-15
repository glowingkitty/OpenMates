"""Public components, checks and external providers of status.openmates.org.

This catalog is the single mapping between internal check keys (Gatus endpoint
keys) and what the public page shows. Only names and descriptions written here
are ever published: no hostnames, error texts or internal identifiers.

Gatus endpoint keys follow Gatus' rule ``<group>_<name>`` with spaces and dots
replaced by ``-``; ``deployment/status_server/gatus/config.yaml`` must define a
check for every key below (``scripts/tests/test_status_server_config.py``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    """One Gatus endpoint, its expected result interval and alert label."""

    key: str
    alert_name: str
    interval_s: int

    @property
    def stale_after_s(self) -> int:
        """A check with no new result for 3 intervals (plus slack) is treated as down."""
        return self.interval_s * 3 + 120


@dataclass(frozen=True)
class Component:
    """One public component and the checks that decide its status."""

    id: str
    name: str
    description: str
    checks: tuple[Check, ...]


@dataclass(frozen=True)
class Provider:
    """One external provider shown in the providers overview."""

    id: str
    name: str
    category: str
    status_page: str
    check: Check


MINUTE = 60
AI_WORKERS = Check("openmates_ai-workers", "AI workers", MINUTE)

COMPONENTS: tuple[Component, ...] = (
    Component("web_app", "Web app", "openmates.org and the web app", (
        Check("openmates_web-app", "Web app (openmates.org)", MINUTE),
        Check("openmates_web-app-shell", "Web app (app.openmates.org)", MINUTE),
        Check("openmates_link-previews", "Link previews", MINUTE),
    )),
    Component("api", "API", "REST and WebSocket API", (
        Check("openmates_api", "API", MINUTE),
    )),
    Component("ai_chat", "AI chat", "Sending a message and receiving an AI answer", (
        AI_WORKERS,
        Check("synthetic_chat-without-account", "AI chat without account", 5 * MINUTE),
        Check("synthetic_chat-with-account", "AI chat with account", 5 * MINUTE),
    )),
    # Voice has no free end-to-end check: a real call costs speech credits. It
    # depends on the AI workers and on Mistral AI speech input, so it shows the
    # worse of those two checks.
    Component("voice", "Voice", "Voice calls and speech input", (
        AI_WORKERS,
        Check("providers_mistral", "Provider Mistral AI", 5 * MINUTE),
    )),
    Component("apps", "Apps and skills", "App skills such as web search", (
        Check("synthetic_skill-web-search", "App skill: web search", 30 * MINUTE),
    )),
    Component("uploads", "Uploads", "File and image uploads", (
        Check("openmates_uploads", "Uploads", MINUTE),
    )),
)

PROVIDER_INTERVAL_S = 5 * MINUTE


def _provider(provider_id: str, name: str, category: str, status_page: str) -> Provider:
    return Provider(provider_id, name, category, status_page,
                    Check(f"providers_{provider_id}", f"Provider {name}", PROVIDER_INTERVAL_S))


PROVIDERS: tuple[Provider, ...] = (
    _provider("openai", "OpenAI", "AI models", "https://status.openai.com"),
    _provider("anthropic", "Anthropic", "AI models", "https://status.claude.com"),
    _provider("google-cloud", "Google Cloud (Gemini)", "AI models", "https://status.cloud.google.com"),
    _provider("mistral", "Mistral AI", "AI models", "https://status.mistral.ai"),
    _provider("groq", "Groq", "AI models", "https://groqstatus.com"),
    _provider("cerebras", "Cerebras", "AI models", "https://status.cerebras.ai"),
    _provider("stripe", "Stripe", "Payments", "https://www.stripestatus.com"),
    _provider("brevo", "Brevo", "Email", "https://status.brevo.com"),
    _provider("vercel", "Vercel", "Web hosting", "https://www.vercel-status.com"),
)


def all_checks() -> tuple[Check, ...]:
    """Every distinct check that the agent reads from Gatus and alerts on."""
    checks: dict[str, Check] = {}
    for check in [c for component in COMPONENTS for c in component.checks] + [p.check for p in PROVIDERS]:
        checks.setdefault(check.key, check)
    return tuple(checks.values())


# Gatus external endpoints: results pushed by the agent's probes. Gatus' list
# route omits them, so the agent reads each by key (gatus.fetch_statuses).
EXTERNAL_KEYS: tuple[str, ...] = (
    "synthetic_chat-without-account",
    "synthetic_chat-with-account",
    "synthetic_skill-web-search",
    "providers_google-cloud",
)
