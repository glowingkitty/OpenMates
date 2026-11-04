"""Deterministic security notifications (notifications.deterministic-dual-channel).

Messages are rendered only from structured incident records by fixed templates;
no agent writes or sends them. Every rendered string passes the content
boundary (content.boundary): bounded length, no IP addresses or internal host
names, no token-like secrets, and links only to allowlisted advisory origins.

Routing:
  urgent advisory, intrusion, health -> Discord + email immediately
  affected_fix_soon                  -> Discord immediately + OpenMates Task (+ digest)
  affected_low, not_affected         -> daily digest only
Each incident notifies once per channel (stable notification id per channel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import discord_webhook  # noqa: E402 - sibling script module, path set above
from security_report_delivery import (  # noqa: E402 - sibling script module, path set above
    SendResult,
    container_email_sender,
    deliver_notification,
    stable_notification_id,
)

from security_monitoring.state import Store  # noqa: E402 - package import after path setup

DISCORD_WEBHOOK_ENV = "DISCORD_WEBHOOK_SECURITY"
EMAIL_DESTINATION = "configured_destination"
DONE_STATES = {"sent", "created"}
TEXT_LIMIT = 300
DISCORD_LIMIT = 1900

ALLOWED_LINK_ORIGINS: tuple[str, ...] = (
    "https://osv.dev/",
    "https://github.com/advisories/",
    "https://nvd.nist.gov/",
    "https://ubuntu.com/security/",
    "https://www.cisa.gov/",
    "https://cisa.gov/",
)

# --- content boundary -------------------------------------------------------
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL)
_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}")
_KNOWN_TOKEN = re.compile(r"\b(?:gh[pousr]_|github_pat_|glpat-|xox[abpr]-|sk-|sk_live_|rk_live_|AKIA|ASIA|AIza)[A-Za-z0-9_\-]{8,}")
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_.-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|WEBHOOK|CREDENTIAL|AUTH)[A-Z0-9_.-]*)\s*[=:]\s*(\S+)"
)
_LONG_TOKEN = re.compile(r"(?<![\w:])(?:[A-Za-z0-9+/_-]{32,}={0,2})(?![\w])")
_HEX_ONLY = re.compile(r"[0-9a-fA-F]{7,64}")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?::\d{1,5})?(?![\w.])")
_IPV6 = re.compile(
    r"(?<![\w:])(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"  # full form
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?"  # compressed
    r"|::(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?(?:\d{1,3}(?:\.\d{1,3}){3})?"
    r"|(?:[0-9A-Fa-f]{1,4}:){5,6}(?:\d{1,3}\.){3}\d{1,3}"  # embedded IPv4
    r")(?:/\d{1,3})?(?![\w:])"
)
_IP_LIKE_HOST = re.compile(r"(?i)\b(?:(?:ip-|static\.)\d{1,3}(?:[-.]\d{1,3}){3}|\d{1,3}(?:-\d{1,3}){3})(?:\.[a-z0-9-]+)*\b")
_INTERNAL_HOST = re.compile(
    r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:internal|local|localdomain|lan|intra|intranet|corp|home\.arpa|your-server\.de)\b"
)
_MENTION = re.compile(r"@(everyone|here)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def allowlisted_link(url: str) -> bool:
    return any(url.startswith(origin) for origin in ALLOWED_LINK_ORIGINS) and "@" not in url


def _redact_long_token(match: re.Match[str]) -> str:
    token = match.group(0)
    # Commit SHAs and digests stay readable; mixed-alphabet long tokens do not.
    if _HEX_ONLY.fullmatch(token):
        return token
    mixed = any(c.isdigit() for c in token) and any(c.isupper() for c in token) and any(c.islower() for c in token)
    return "[redacted]" if mixed else token


def redact(value: object) -> str:
    """Apply the content boundary to one untrusted or record-derived string."""
    text = _CONTROL.sub(" ", str(value if value is not None else ""))
    text = _PRIVATE_KEY.sub("[redacted]", text)
    text = _URL.sub(lambda m: m.group(0) if allowlisted_link(m.group(0)) else "[link removed]", text)
    text = _JWT.sub("[redacted]", text)
    text = _KNOWN_TOKEN.sub("[redacted]", text)
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = _IPV6.sub("[address]", text)
    text = _IPV4.sub("[address]", text)
    text = _IP_LIKE_HOST.sub("[address]", text)
    text = _INTERNAL_HOST.sub("[host]", text)
    text = _LONG_TOKEN.sub(_redact_long_token, text)
    text = _MENTION.sub(r"@​\1", text)
    return text


def bounded(value: object, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(redact(value).split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "unknown"


def advisory_link(advisory_id: str) -> str | None:
    """Links are built from identifiers only, never from fetched source URLs."""
    value = advisory_id.strip()
    if re.fullmatch(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}", value):
        return f"https://github.com/advisories/{value}"
    if re.fullmatch(r"CVE-\d{4}-\d{4,}", value):
        return f"https://nvd.nist.gov/vuln/detail/{value}"
    if re.fullmatch(r"(?:OSV|PYSEC|RUSTSEC|GO|MAL)-[\w.-]{3,40}", value):
        return f"https://osv.dev/vulnerability/{value}"
    if re.fullmatch(r"USN-\d{3,5}-\d{1,3}", value):
        return f"https://ubuntu.com/security/notices/{value}"
    return None


# --- rendering --------------------------------------------------------------
@dataclass(frozen=True)
class Rendered:
    title: str
    lines: tuple[tuple[str, str], ...]
    checklist: tuple[str, ...]
    links: tuple[str, ...] = ()

    def discord_payload(self) -> dict[str, Any]:
        body = [f"**{_discord_escape(self.title)}**"]
        body += [f"{label}: {_discord_escape(value)}" for label, value in self.lines]
        if self.checklist:
            body.append("Operator checklist:")
            body += [f"- [ ] {_discord_escape(item)}" for item in self.checklist]
        body += [f"<{link}>" for link in self.links]
        content = "\n".join(body)
        if len(content) > DISCORD_LIMIT:
            content = content[: DISCORD_LIMIT - 1] + "…"
        return {"content": content, "allowed_mentions": {"parse": []}}

    def email_payload(self) -> dict[str, str]:
        text_lines = [self.title, ""] + [f"{label}: {value}" for label, value in self.lines]
        if self.checklist:
            text_lines += ["", "Operator checklist:"] + [f"[ ] {item}" for item in self.checklist]
        if self.links:
            text_lines += [""] + list(self.links)
        items = "".join(f"<li><b>{escape(label)}:</b> {escape(value)}</li>" for label, value in self.lines)
        checklist = "".join(f"<li>{escape(item)}</li>" for item in self.checklist)
        links = "".join(f'<li><a href="{escape(link, quote=True)}">{escape(link)}</a></li>' for link in self.links)
        html = (
            f"<!doctype html><html><body><h1>{escape(self.title)}</h1><ul>{items}</ul>"
            + (f"<h2>Operator checklist</h2><ul>{checklist}</ul>" if checklist else "")
            + (f"<h2>References</h2><ul>{links}</ul>" if links else "")
            + "</body></html>"
        )
        subject = self.title.replace("<", "").replace(">", "")[:200]
        return {"subject": subject, "text": "\n".join(text_lines), "html": html}


def _discord_escape(value: str) -> str:
    return re.sub(r"([*_~`|>\\])", r"\\\1", value)


def _join(values: Any, limit: int = 12) -> str:
    items = [bounded(item, 80) for item in (values or [])][:limit]
    return ", ".join(items) if items else "none"


def _assets_line(assets: list[dict[str, Any]]) -> str:
    parts = []
    for asset in assets[:10]:
        version = asset.get("version") or "*"
        envs = "/".join(str(env) for env in asset.get("environments") or [])
        parts.append(f"{asset.get('name')} {version} ({envs})")
    return bounded("; ".join(parts) or "none", 600)


OUTCOME_LABEL = {
    "urgent": "URGENT",
    "affected_fix_soon": "fix soon",
    "affected_low": "low",
    "not_affected": "not affected",
}


def render_incident(incident: dict[str, Any]) -> Rendered:
    kind = incident["kind"]
    details = incident.get("details") or {}
    if kind == "advisory":
        return _render_advisory(incident, details)
    if kind == "intrusion":
        return _render_intrusion(incident, details)
    return _render_health(incident, details)


def _render_advisory(incident: dict[str, Any], details: dict[str, Any]) -> Rendered:
    advisory_ids = [str(item) for item in details.get("advisory_ids") or []][:8]
    outcome = str(details.get("outcome", "unknown"))
    fix = details.get("automatic_actions") or {}
    if fix.get("commit"):
        automatic = f"fix commit {bounded(fix['commit'], 40)}; dev deploy {bounded(fix.get('dev_deploy', 'unknown'), 40)}"
    else:
        automatic = bounded(fix.get("summary") or "no automatic fix possible", 200)
    lines = [
        ("Advisory", _join(advisory_ids)),
        ("Affected", _assets_line(details.get("assets") or [])),
        ("Environments", _join(details.get("environments"))),
        ("Verdict", OUTCOME_LABEL.get(outcome, bounded(outcome, 40))),
        ("Evidence", bounded(details.get("evidence_summary"), 500)),
        ("Reachability", bounded(details.get("reachability"), 300)),
        ("Exploitability", bounded(details.get("exploitability"), 300)),
        ("Blast radius", bounded(details.get("blast_radius"), 300)),
        ("Automatic actions", automatic),
        ("Incident", bounded(incident["incident_id"], 80)),
    ]
    if details.get("dispatch_reason"):
        lines.insert(4, ("Triage reason", bounded(details["dispatch_reason"], 120)))
    checklist = tuple(bounded(item, 200) for item in operator_checklist(details))
    links = tuple(link for link in (advisory_link(item) for item in advisory_ids) if link)[:4]
    title = f"[Security] {OUTCOME_LABEL.get(outcome, 'advisory')}: {_join(advisory_ids, 3)}"
    return Rendered(bounded(title, 180), tuple(lines), checklist, links)


def operator_checklist(details: dict[str, Any]) -> list[str]:
    """Deterministic manual steps; production and host actions are never automatic."""
    items: list[str] = []
    environments = set(details.get("environments") or [])
    fix = details.get("automatic_actions") or {}
    if fix.get("commit") and fix.get("dev_deploy") == "deployed" and "prod" in environments:
        items.append("Release to production via update-prod-server")
    for role in details.get("host_roles") or []:
        items.append(f"Patch and reboot the {role} server")
    for secret_class in details.get("rotate_secret_classes") or []:
        items.append(f"Rotate {secret_class}")
    for action in details.get("manual_actions") or []:
        if action not in items:
            items.append(str(action))
    if fix.get("revert_required"):
        items.insert(0, "Revert the auto-fix commit on dev manually (dev smoke failed)")
    return items[:12] or ["Review the incident and acknowledge it with security_monitor.py acknowledge"]


def _render_intrusion(incident: dict[str, Any], details: dict[str, Any]) -> Rendered:
    lines = [
        ("Server role", bounded(details.get("role"), 40)),
        ("Signal", bounded(details.get("signal_kind"), 80)),
        ("Change", bounded(details.get("change_id"), 120)),
        ("Detail", bounded(details.get("safe_detail"), 300)),
        ("Incident", bounded(incident["incident_id"], 80)),
    ]
    checklist = (
        f"Verify the change on the {bounded(details.get('role'), 40)} server over your own SSH session",
        "If unexpected: isolate the server, rotate affected credentials, review auth logs",
        "If expected: update the expected key/config list and acknowledge the incident",
    )
    if details.get("signal_kind") == "baseline_seeded":
        return Rendered(f"[Security] SSH key baseline recorded for {bounded(details.get('role'), 40)}", tuple(lines),
                        ("Confirm the recorded keys are expected, then acknowledge the incident",))
    return Rendered(f"[Security] INTRUSION signal on {bounded(details.get('role'), 40)}", tuple(lines), checklist)


def _render_health(incident: dict[str, Any], details: dict[str, Any]) -> Rendered:
    lines = [
        ("Problem", bounded(details.get("summary"), 300)),
        ("Signal", bounded(details.get("signal"), 80)),
        ("Since", bounded(incident.get("opened_at"), 40)),
        ("Incident", bounded(incident["incident_id"], 80)),
    ]
    if details.get("advisory_ids"):
        lines.insert(1, ("Advisory", _join(details["advisory_ids"])))
    checklist = tuple(bounded(item, 200) for item in (details.get("checklist") or ["Check logs/security-monitoring/ on the dev server"]))
    return Rendered(f"[Security] Monitoring health: {bounded(details.get('signal'), 60)}", tuple(lines), checklist)


# --- routing and delivery ---------------------------------------------------
def channels_for(incident: dict[str, Any]) -> tuple[str, ...]:
    kind = incident["kind"]
    if kind in {"intrusion", "health"}:
        return ("discord", "email")
    outcome = (incident.get("details") or {}).get("outcome")
    if outcome == "urgent":
        return ("discord", "email")
    if outcome == "affected_fix_soon":
        return ("discord", "task")
    return ()


DiscordPost = Callable[[str, dict[str, Any]], "dict[str, str] | None"]
TaskCreator = Callable[[str, str], "str | None"]


def default_discord_post(url: str, payload: dict[str, Any]) -> dict[str, str] | None:
    return discord_webhook.post_message(webhook_url=url, payload=payload)


def default_task_creator(title: str, description: str) -> str | None:
    result = subprocess.run(
        ["openmates", "tasks", "create", "--title", title, "--description", description,
         "--label", "security", "--priority", "high", "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    task = payload.get("task", payload) if isinstance(payload, dict) else {}
    value = task.get("short_id") or task.get("id") if isinstance(task, dict) else None
    return str(value) if value else None


@dataclass
class Notifier:
    store: Store
    ledger_path: Path
    webhook_url: str
    dry_run: bool = False
    discord_post: DiscordPost = default_discord_post
    email_sender: Callable[[dict[str, str]], SendResult] | None = None
    task_creator: TaskCreator = default_task_creator
    planned: list[dict[str, str]] = field(default_factory=list)
    unavailable_channels: set[str] = field(default_factory=set)

    def notify(self, incident: dict[str, Any], now: datetime) -> dict[str, str]:
        """Deliver every routed channel not yet delivered for this incident."""
        rendered = render_incident(incident)
        outcomes: dict[str, str] = {}
        for channel in channels_for(incident):
            if self.store.notification_state(incident["incident_id"], channel) in DONE_STATES:
                outcomes[channel] = "already_sent"
                continue
            notification_id = stable_notification_id(f"security-monitoring-{channel}", "dev", incident["incident_id"])
            if self.dry_run:
                self.planned.append({"incident": incident["incident_id"], "channel": channel, "title": rendered.title})
                outcomes[channel] = "dry_run"
                continue
            state, reason = self._deliver(channel, notification_id, rendered, incident)
            if state == "unavailable":
                self.unavailable_channels.add(channel)
            self.store.record_notification(notification_id, incident["incident_id"], channel, state, reason, now)
            outcomes[channel] = state
        return outcomes

    def _deliver(self, channel: str, notification_id: str, rendered: Rendered, incident: dict[str, Any]) -> tuple[str, str | None]:
        if channel == "discord":
            if not self.webhook_url:
                return "unavailable", f"{DISCORD_WEBHOOK_ENV} is not configured"
            result = self.discord_post(self.webhook_url, rendered.discord_payload())
            return ("sent", None) if result and result.get("message_id") else ("failed", "discord_not_confirmed")
        if channel == "email":
            outcome = deliver_notification(
                ledger_path=self.ledger_path, notification_id=notification_id, payload=rendered.email_payload(),
                recipient=EMAIL_DESTINATION, sender=self.email_sender or container_email_sender(),
            )
            if outcome.state in {"accepted", "queued"}:
                return "sent", None
            return outcome.state, outcome.reason
        if channel == "task":
            description = rendered.email_payload()["text"][:4000]
            task_id = self.task_creator(rendered.title, description)
            return ("created", task_id) if task_id else ("failed", "task_create_failed")
        raise ValueError(f"unknown channel {channel}")
