"""Integration health from production's public ``/v1/health`` (alerts only).

Production's own health tasks check each configured provider, app and external
service with our credentials (for example Stripe or Brevo). Those transitions
used to be posted to Discord by the backend once per change. The status agent
now reads the same sanitized public summary every minute and runs it through
the escalation policy, so these alerts repeat and resolve like every other
check. Production stops its own posts with ``OPENMATES_HEALTH_ALERTS_DELEGATED``.

These checks feed alerts only. The public page shows providers from their
official status pages instead, because ``/v1/health`` names internal services.
"""

from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from typing import Any

from .alerts import CheckResult, CheckSnapshot

SECTIONS = {"providers": "AI provider", "apps": "App", "external_services": "Service"}
# Matches the backend policy: unconfigured or skipped items never alert.
OBSERVED_STATUSES = {"healthy", "unhealthy", "degraded"}
IGNORED_ERRORS = {"missing_credentials", "not_configured"}
KEEP_RESULTS = 10
STALE_AFTER_S = 15 * 60
TIMEOUT_S = 15


def confirmation_interval(key: str) -> int:
    """Allow a backend probe to refresh before counting a repeated cached failure."""
    if key.startswith("integration_providers_"):
        return 1800
    if key == "integration_external_services_sightengine":
        return 7200
    return 60


def fetch_health(api_url: str) -> Any:
    """GET the public health summary; raises OSError/ValueError on failure."""
    request = urllib.request.Request(f"{api_url}/v1/health", headers={"User-Agent": "openmates-status-monitor/1"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def observations(payload: Any) -> dict[str, tuple[str, bool]]:
    """Map ``integration_<section>_<id>`` to (alert name, healthy) for alertable items."""
    found: dict[str, tuple[str, bool]] = {}
    if not isinstance(payload, dict):
        return found
    for section, label in SECTIONS.items():
        items = payload.get(section)
        if not isinstance(items, dict):
            continue
        for item_id, item in items.items():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            if status not in OBSERVED_STATUSES or str(item.get("last_error") or "") in IGNORED_ERRORS:
                continue
            found[f"integration_{section}_{item_id}"] = (f"{label} {item_id} (production health check)",
                                                         status == "healthy")
    return found


class IntegrationTracker:
    """Recent results per integration item, kept in memory between ticks."""

    def __init__(self) -> None:
        self.results: dict[str, list[CheckResult]] = defaultdict(list)
        self.names: dict[str, str] = {}

    def record(self, payload: Any, now: float) -> None:
        for key, (name, healthy) in observations(payload).items():
            self.names[key] = name
            series = self.results[key]
            series.append(CheckResult(now, healthy))
            del series[:-KEEP_RESULTS]

    def snapshots(self) -> list[CheckSnapshot]:
        return [CheckSnapshot(key, self.names[key], tuple(series), STALE_AFTER_S)
                for key, series in self.results.items() if series]
