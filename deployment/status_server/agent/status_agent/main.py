"""Status agent main loop: probes, alerts and public page data.

Runs next to Gatus on the status server. Every minute it reads all check
results from Gatus, evaluates the escalation policy, delivers notifications,
and writes ``status.json`` for the public page. Synthetic probes run on their
own schedule in worker threads and push their results into Gatus.

Gatus read failures are retained as checker diagnostics.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import gatus, integrations, probes
from .alerts import OpenAlert
from .catalog import COMPONENTS, EXTERNAL_KEYS, all_checks
from .notify import Channels, deliver_uptime
from .page_data import History, Incident, build, update_incidents
from .uptime import Observation, Store

LOG = logging.getLogger("status_agent")
TICK_S = 60
SELF_CHECK_KEY = "monitor_status-checker"
CHECK_SERVICES = {check.key: component.name for component in reversed(COMPONENTS) for check in component.checks
                  if not check.key.startswith("providers_")}
SYNTHETIC_CHECKER_ERRORS = {"http_401", "http_403", "http_429"}


@dataclass(frozen=True)
class Settings:
    gatus_url: str
    external_token: str
    api_url: str
    monitor_token: str
    monitor_api_key: str
    synthetic_probes: bool
    state_dir: Path
    public_dir: Path
    channels: Channels

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            gatus_url=env.get("GATUS_URL", "http://gatus:8080"),
            external_token=env["GATUS_EXTERNAL_TOKEN"],
            api_url=env.get("PROD_API_URL", "https://api.openmates.org").rstrip("/"),
            monitor_token=env.get("MONITOR_PROBE_TOKEN", ""),
            monitor_api_key=env.get("MONITOR_API_KEY", ""),
            # Off only for image smoke tests in CI, which must not send real chats.
            synthetic_probes=env.get("SYNTHETIC_PROBES", "on") != "off",
            state_dir=Path(env.get("STATE_DIR", "/var/lib/status-agent")),
            public_dir=Path(env.get("PUBLIC_DATA_DIR", "/srv/data")),
            channels=Channels(
                discord_webhook_url=env.get("DISCORD_WEBHOOK_URL", ""),
                brevo_api_key=env.get("BREVO_API_KEY", ""),
                email_to=env.get("ALERT_EMAIL_TO", ""),
                email_from=env.get("ALERT_EMAIL_FROM", "noreply@openmates.org"),
                environment_label=env.get("ENVIRONMENT_LABEL", "OpenMates production"),
                status_page_url=env.get("STATUS_PAGE_URL", "https://status.openmates.org"),
            ),
        )


@dataclass
class Schedule:
    """One probe: what to run, which Gatus key it reports to, and how often."""

    key: str
    run: Callable[[], probes.ProbeResult]
    every_s: int
    retry_s: int
    next_at: float = 0.0
    running: Future | None = None


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_schedules(settings: Settings) -> list[Schedule]:
    schedules = [Schedule("providers_google-cloud", probes.google_cloud_status, every_s=300, retry_s=300)]
    if not settings.synthetic_probes:
        return schedules
    schedules.append(Schedule("synthetic_chat-without-account",
                              lambda: probes.chat_without_account(settings.api_url, settings.monitor_token),
                              every_s=300, retry_s=300))
    if settings.monitor_api_key:
        schedules += [
            Schedule("synthetic_chat-with-account",
                     lambda: probes.chat_with_account(settings.api_url, settings.monitor_api_key),
                     every_s=300, retry_s=300),
            # Every 30 minutes; a failure is re-checked after 5 minutes so two
            # failures in a row confirm an outage quickly.
            Schedule("synthetic_skill-web-search",
                     lambda: probes.skill_web_search(settings.api_url, settings.monitor_api_key),
                     every_s=1800, retry_s=300),
        ]
    return schedules


class Agent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="probe")
        self.schedules = build_schedules(settings)
        state_dir = settings.state_dir
        self.uptime = Store(state_dir / "uptime.sqlite3")
        self.history_path = state_dir / "history.json"
        self.incidents_path = state_dir / "incidents.json"
        self.history = History.from_json(dict(read_json(self.history_path, {})))
        self.incidents = [Incident.from_json(i) for i in list(read_json(self.incidents_path, []))]
    def run_probes(self, now: float) -> None:
        for schedule in self.schedules:
            if schedule.running is not None:
                if not schedule.running.done():
                    continue
                result: probes.ProbeResult = schedule.running.result()
                schedule.running = None
                schedule.next_at = now + (schedule.every_s if result.success else schedule.retry_s)
                try:
                    gatus.push_external(self.settings.gatus_url, schedule.key, self.settings.external_token,
                                        result.success, result.error, result.duration_s)
                except gatus.GatusError as exc:
                    LOG.error("probe %s result not stored: %s", schedule.key, exc)
            if schedule.running is None and now >= schedule.next_at:
                schedule.running = self.pool.submit(schedule.run)

    def tick(self, now: float) -> None:
        self.run_probes(now)
        observations = []
        try:
            results = gatus.fetch_statuses(self.settings.gatus_url, EXTERNAL_KEYS)
        except gatus.GatusError as exc:
            LOG.error("%s", exc)
            results = {}
            observations.append(Observation("Status checker", SELF_CHECK_KEY, now, "checker", str(exc)))

        latest = {}
        public_alerts = {}
        for check in all_checks():
            series = results.get(check.key, ())
            if not series:
                continue
            service = CHECK_SERVICES.get(check.key, check.alert_name)
            self.history.add(check.key, series)
            outcome = None
            for result in series:
                error = result.error or ", ".join(result.failed_conditions) or "Probe condition failed"
                provider_unavailable = check.key.startswith("providers_") and (
                    (result.error and result.error != "provider_outage")
                    or any(condition.startswith("[STATUS]") for condition in result.failed_conditions)
                    or not (result.error or result.failed_conditions)
                )
                synthetic_misconfigured = check.key.startswith("synthetic_") and error in SYNTHETIC_CHECKER_ERRORS
                previous_outcome = outcome
                outcome = "up" if result.success else "checker" if provider_unavailable or synthetic_misconfigured else "down"
                # Old history is useful for tracking short incidents, but only
                # current checks can open or remind about a live incident.
                observations.append(Observation(service, check.key, result.timestamp,
                                                outcome, "" if result.success else error,
                                                notify=now - result.timestamp <= check.stale_after_s,
                                                max_gap=check.stale_after_s))
            last = series[-1]
            if now - last.timestamp > check.stale_after_s:
                observations.append(Observation(service, f"{check.key} freshness", now, "checker",
                                                "No current probe result"))
                continue
            if (outcome == previous_outcome == "down"
                    and last.timestamp - series[-2].timestamp <= check.stale_after_s):
                public_alerts[check.key] = OpenAlert(series[-2].timestamp, now)
            if outcome != "checker":
                latest[check.key] = last

        try:
            payload = integrations.fetch_health(self.settings.api_url)
            if not isinstance(payload, dict) or not all(isinstance(payload.get(key), dict) for key in integrations.SECTIONS):
                raise ValueError("Incomplete production health summary")
            for key, (name, healthy) in integrations.observations(payload).items():
                # The host monitor checks real email send and account outcomes.
                if key != "integration_external_services_brevo":
                    observations.append(Observation(name, key, now, "up" if healthy else "down",
                                                    "" if healthy else "Production health reports a failure",
                                                    min_interval=integrations.confirmation_interval(key),
                                                    max_gap=integrations.confirmation_interval(key) + 180))
        except (OSError, ValueError) as exc:
            LOG.warning("production health summary unavailable: %s", type(exc).__name__)
            observations.append(Observation("Production health summary", "integration health", now,
                                            "checker", type(exc).__name__))
        self.uptime.record(observations, now, self.send_uptime)
        self.history.prune(now)
        if results:
            self.incidents = update_incidents(self.incidents, public_alerts, now, known_checks=set(latest))
        write_json_atomic(self.history_path, self.history.to_json())
        write_json_atomic(self.incidents_path, [i.to_json() for i in self.incidents])
        if results:
            document = build(latest, public_alerts, self.history, self.incidents, now)
            count, seconds = self.uptime.short_blips(now - 86400, now)
            document["short_blips_24h"] = {"count": count, "seconds": seconds}
            write_json_atomic(self.settings.public_dir / "status.json", document)

    def send_uptime(self, message: str) -> bool:
        if deliver_uptime(message, self.settings.channels):
            return True
        LOG.error("Could not deliver an uptime notice")
        return False

    def run_forever(self) -> None:
        while True:
            started = time.time()
            self.tick(started)
            time.sleep(max(1.0, TICK_S - (time.time() - started)))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Agent(Settings.from_env()).run_forever()


if __name__ == "__main__":
    main()
