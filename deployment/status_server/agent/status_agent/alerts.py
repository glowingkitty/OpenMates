"""Escalating outage alerts for the external status monitor.

Pure decision logic: given the recent check results of every monitored check and
the persisted alert state, decide which notifications to send now. Delivery
(Discord, email) and storage live elsewhere so this module is fully unit-tested.

Policy (specification ``architecture.external-status-monitoring``):
- A check is confirmed down after ``FAILURES_TO_ALERT`` failed results in a row,
  or when its newest result is older than its stale limit (the checker stopped).
- The first notification goes out once a check is confirmed down.
- Reminders follow at 15 minutes and 1 hour after that first notification, then
  every 3 hours, each saying how long the check has been down.
- One "resolved" notification goes out on the first successful result after a
  notification was sent. Failures that recover before confirmation stay silent.
- State survives restarts, so a restart never repeats a notification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

FAILURES_TO_ALERT = 2
FIRST_REMINDERS_S = (15 * 60, 60 * 60)
LATER_REMINDER_EVERY_S = 3 * 60 * 60

NotificationKind = Literal["down", "still_down", "resolved"]


@dataclass(frozen=True)
class CheckResult:
    """One result of a check: Unix timestamp in seconds and pass/fail."""

    timestamp: float
    success: bool


@dataclass(frozen=True)
class CheckSnapshot:
    """Recent results of one check, oldest first, plus its stale limit."""

    key: str
    name: str
    results: tuple[CheckResult, ...]
    stale_after_s: float


@dataclass
class OpenAlert:
    """Persisted state of one confirmed outage."""

    down_since: float
    notified_at: float
    reminders_sent: int = 0

    def to_json(self) -> dict[str, float | int]:
        return {"down_since": self.down_since, "notified_at": self.notified_at,
                "reminders_sent": self.reminders_sent}

    @classmethod
    def from_json(cls, data: dict[str, float | int]) -> "OpenAlert":
        return cls(down_since=float(data["down_since"]), notified_at=float(data["notified_at"]),
                   reminders_sent=int(data["reminders_sent"]))


@dataclass(frozen=True)
class Notification:
    """One message to deliver for one check."""

    kind: NotificationKind
    key: str
    name: str
    down_since: float
    duration_s: float


@dataclass
class Evaluation:
    """Notifications to send now and the alert state to persist afterwards."""

    notifications: list[Notification] = field(default_factory=list)
    state: dict[str, OpenAlert] = field(default_factory=dict)


def reminder_due_at(alert: OpenAlert) -> float:
    """Return when the next "still down" reminder for ``alert`` is due."""
    sent = alert.reminders_sent
    if sent < len(FIRST_REMINDERS_S):
        return alert.notified_at + FIRST_REMINDERS_S[sent]
    later = sent - len(FIRST_REMINDERS_S) + 1
    return alert.notified_at + FIRST_REMINDERS_S[-1] + later * LATER_REMINDER_EVERY_S


def _confirmed_down_since(snapshot: CheckSnapshot, now: float) -> float | None:
    """Return when the current confirmed outage started, or None when not down."""
    results = snapshot.results
    if not results:
        return None
    newest = results[-1]
    if now - newest.timestamp > snapshot.stale_after_s:
        # The checker stopped reporting: treat silence as an outage that began
        # when the next result was due.
        return newest.timestamp + snapshot.stale_after_s
    failing: list[CheckResult] = []
    for result in reversed(results):
        if result.success:
            break
        failing.append(result)
    if len(failing) < FAILURES_TO_ALERT:
        return None
    return failing[-1].timestamp


def evaluate(snapshots: Iterable[CheckSnapshot], state: dict[str, OpenAlert], now: float) -> Evaluation:
    """Decide which notifications to send at ``now`` and return the new state.

    Checks missing from ``snapshots`` keep their state untouched, so removing a
    check from one poll (e.g. a partial API response) never fakes a recovery.
    """
    evaluation = Evaluation(state=dict(state))
    for snapshot in snapshots:
        down_since = _confirmed_down_since(snapshot, now)
        alert = evaluation.state.get(snapshot.key)
        if down_since is None:
            if alert is not None and snapshot.results and snapshot.results[-1].success:
                evaluation.notifications.append(Notification(
                    "resolved", snapshot.key, snapshot.name, alert.down_since,
                    snapshot.results[-1].timestamp - alert.down_since))
                del evaluation.state[snapshot.key]
            continue
        if alert is None:
            evaluation.state[snapshot.key] = OpenAlert(down_since=down_since, notified_at=now)
            evaluation.notifications.append(Notification(
                "down", snapshot.key, snapshot.name, down_since, now - down_since))
            continue
        if now >= reminder_due_at(alert):
            alert.reminders_sent += 1
            evaluation.notifications.append(Notification(
                "still_down", snapshot.key, snapshot.name, alert.down_since, now - alert.down_since))
    return evaluation


def format_duration(seconds: float) -> str:
    """Human duration such as "4 minutes", "1 hour 5 minutes" or "2 days 3 hours"."""
    minutes = max(0, int(seconds // 60))
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)

    def unit(value: int, name: str) -> str:
        return f"{value} {name}{'' if value == 1 else 's'}"

    if days:
        return unit(days, "day") + (f" {unit(hours, 'hour')}" if hours else "")
    if hours:
        return unit(hours, "hour") + (f" {unit(mins, 'minute')}" if mins else "")
    return unit(mins, "minute") if mins else "less than a minute"


def message_line(notification: Notification) -> str:
    """One plain sentence for Discord and email."""
    duration = format_duration(notification.duration_s)
    if notification.kind == "down":
        return f"DOWN: {notification.name} is failing (confirmed by 2 checks in a row, down for {duration})."
    if notification.kind == "still_down":
        return f"STILL DOWN: {notification.name} has been down for {duration}."
    return f"RESOLVED: {notification.name} is working again after {duration}."
