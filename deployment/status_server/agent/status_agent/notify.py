"""Deliver alert notifications: Discord webhook first, Brevo email as backup.

Both channels are tried for every batch, so a Discord outage never hides an
alert. Delivery failures are returned (not raised) so the caller can log them
and still persist alert state; a failed batch is never re-sent as a duplicate.
Messages carry only public component names, durations and the page link.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Sequence

from .alerts import Notification, message_line

TIMEOUT_S = 15
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
DISCORD_LIMIT = 1900
MAX_LINES = 12


@dataclass(frozen=True)
class Channels:
    """Delivery configuration; empty values disable that channel."""

    discord_webhook_url: str
    brevo_api_key: str
    email_to: str
    email_from: str
    environment_label: str
    status_page_url: str


def render(notifications: Sequence[Notification], channels: Channels) -> tuple[str, str]:
    """Return (subject, body) for one batch of notifications."""
    kinds = {n.kind for n in notifications}
    if kinds == {"resolved"}:
        head = "Resolved"
    elif "down" in kinds:
        head = "Outage"
    else:
        head = "Still down"
    names = sorted({n.name for n in notifications})
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    subject = f"[{channels.environment_label}] {head}: {shown}"
    lines = [message_line(n) for n in notifications[:MAX_LINES]]
    if len(notifications) > MAX_LINES:
        lines.append(f"... and {len(notifications) - MAX_LINES} more checks.")
    body = "\n".join([subject, "", *lines, "", f"Status page: {channels.status_page_url}"])
    return subject, body


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> None:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              # Discord refuses the default Python-urllib agent.
                                              "User-Agent": "openmates-status-monitor/1", **headers})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        if response.status >= 300:
            raise OSError(f"HTTP {response.status}")


def deliver(notifications: Sequence[Notification], channels: Channels) -> list[str]:
    """Send one batch to every configured channel; return failure descriptions."""
    if not notifications:
        return []
    subject, body = render(notifications, channels)
    failures: list[str] = []
    if channels.discord_webhook_url:
        try:
            _post_json(channels.discord_webhook_url, {"content": body[:DISCORD_LIMIT]}, {})
        except OSError as exc:
            failures.append(f"discord: {type(exc).__name__}")
    else:
        failures.append("discord: not configured")
    if channels.brevo_api_key and channels.email_to:
        payload = {
            "sender": {"name": "OpenMates Status", "email": channels.email_from},
            "to": [{"email": channels.email_to}],
            "subject": subject,
            "textContent": body,
            "tags": ["status-monitor"],
        }
        try:
            _post_json(BREVO_URL, payload, {"api-key": channels.brevo_api_key, "accept": "application/json"})
        except OSError as exc:
            failures.append(f"email: {type(exc).__name__}")
    else:
        failures.append("email: not configured")
    return failures
