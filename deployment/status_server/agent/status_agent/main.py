"""Status agent main loop: probes, alerts and public page data.

Runs next to Gatus on the status server. Every minute it reads all check
results from Gatus, evaluates the escalation policy, delivers notifications,
and writes ``status.json`` for the public page. Synthetic probes run on their
own schedule in worker threads and push their results into Gatus.

If Gatus itself cannot be read, the agent treats that as a check named
"Status checker" and alerts on it with the same policy.
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
from .alerts import CheckResult, CheckSnapshot, OpenAlert, evaluate
from .catalog import EXTERNAL_KEYS, all_checks
from .notify import Channels, deliver
from .page_data import History, Incident, build, update_incidents

LOG = logging.getLogger("status_agent")
TICK_S = 60
SELF_CHECK_KEY = "monitor_status-checker"
SELF_CHECK = CheckSnapshot(SELF_CHECK_KEY, "Status checker", (), TICK_S * 3)


@dataclass(frozen=True)
class Settings:
    gatus_url: str
    external_token: str
    api_url: str
    monitor_token: str
    monitor_api_key: str
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
    schedules = [Schedule("synthetic_chat-without-account",
                          lambda: probes.chat_without_account(settings.api_url, settings.monitor_token),
                          every_s=300, retry_s=300),
                 Schedule("providers_google-cloud", probes.google_cloud_status, every_s=300, retry_s=300)]
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
        self.alerts_path = state_dir / "alerts.json"
        self.history_path = state_dir / "history.json"
        self.incidents_path = state_dir / "incidents.json"
        self.alerts = {k: OpenAlert.from_json(v) for k, v in dict(read_json(self.alerts_path, {})).items()}
        self.history = History.from_json(dict(read_json(self.history_path, {})))
        self.incidents = [Incident.from_json(i) for i in list(read_json(self.incidents_path, []))]
        self.self_results: list[CheckResult] = []
        self.integrations = integrations.IntegrationTracker()

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
        try:
            results = gatus.fetch_statuses(self.settings.gatus_url, EXTERNAL_KEYS)
            self.self_results.append(CheckResult(now, True))
        except gatus.GatusError as exc:
            LOG.error("%s", exc)
            results = {}
            self.self_results.append(CheckResult(now, False))
        self.self_results = self.self_results[-10:]
        snapshots = [CheckSnapshot(SELF_CHECK_KEY, SELF_CHECK.name, tuple(self.self_results), SELF_CHECK.stale_after_s)]
        for check in all_checks():
            if check.key in results:
                snapshots.append(CheckSnapshot(check.key, check.alert_name, results[check.key], check.stale_after_s))
                self.history.add(check.key, results[check.key])
        try:
            self.integrations.record(integrations.fetch_health(self.settings.api_url), now)
        except (OSError, ValueError) as exc:
            # The API check itself reports an unreachable API; no extra alert here.
            LOG.warning("production health summary unavailable: %s", type(exc).__name__)
        snapshots += self.integrations.snapshots()
        evaluation = evaluate(snapshots, self.alerts, now)
        failures = deliver(evaluation.notifications, self.settings.channels)
        for failure in failures:
            LOG.error("alert delivery: %s", failure)
        self.alerts = evaluation.state
        self.history.prune(now)
        public_alerts = {k: v for k, v in self.alerts.items()
                         if k != SELF_CHECK_KEY and not k.startswith("integration_")}
        self.incidents = update_incidents(self.incidents, public_alerts, now)
        latest = {k: v[-1] for k, v in results.items() if v}
        write_json_atomic(self.alerts_path, {k: v.to_json() for k, v in self.alerts.items()})
        write_json_atomic(self.history_path, self.history.to_json())
        write_json_atomic(self.incidents_path, [i.to_json() for i in self.incidents])
        if results:
            write_json_atomic(self.settings.public_dir / "status.json",
                              build(latest, public_alerts, self.history, self.incidents, now))

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
