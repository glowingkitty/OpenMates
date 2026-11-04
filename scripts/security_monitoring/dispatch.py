"""Hourly security watcher pipeline (triage.no-repeat-dispatch, health.no-silent-failure).

host reports -> inventory -> sources (since the last successful run) -> matcher
(with recorded not-affected fingerprints) -> persist + security-reporting ledger
-> no-repeat dispatch -> one batched read-only triage chat -> verdicts ->
guarded dev-only fix for urgent verdicts -> deterministic notifications.

An observation is triage-eligible only when its disposition is `triage` and it
was never dispatched, or its material fingerprint differs from the last
dispatched one (the diffed reason is recorded). Operator inaction never
re-dispatches; open incidents carry forward in the digest instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from security_monitoring import autofix, notify, records, triage
from security_monitoring.config import Settings, dotenv_value, git_head
from security_monitoring.models import Inventory, Observation, TriageVerdict
from security_monitoring.state import Store, utc

HOST_ROLE_FOR_ENV = {"prod": "core (prod)", "upload": "upload", "preview": "preview", "dev": "dev"}


@dataclass
class Deps:
    """Lane interfaces; tests inject fakes, production uses default_deps()."""

    load_host_reports: Callable[[Path], dict[str, Any]]
    load_previous_host_reports: Callable[[Path], dict[str, Any]]
    stale_roles: Callable[[Mapping[str, Any], datetime], list[str]]
    intrusion_signals: Callable[[Any, Any, Mapping[str, set[str]]], list[dict[str, str]]]
    load_expected_keys: Callable[[Path], dict[str, set[str]]]
    ssh_context: Callable[[Any], dict[str, Any]]
    build_inventory: Callable[[Path, Mapping[str, Any], datetime], Inventory]
    collect: Callable[..., tuple[list[Any], list[Any]]]
    match: Callable[..., list[Observation]]
    run_triage: Callable[..., triage.TriageResult] = triage.run_triage
    run_fix: Callable[..., autofix.FixOutcome] = autofix.run_fix
    report_scan: Callable[..., Any] | None = None
    seed_expected_keys: Callable[[Path, Any], tuple[dict[str, set[str]], list[dict[str, str]]]] | None = None


def default_deps() -> Deps:
    from security_monitoring import host_reports, inventory, matcher, sources

    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from security_scan_reporting import report_scan

    return Deps(
        load_host_reports=host_reports.load_latest,
        load_previous_host_reports=host_reports.load_previous,
        stale_roles=host_reports.stale_roles,
        intrusion_signals=host_reports.intrusion_signals,
        load_expected_keys=host_reports.load_expected_keys,
        ssh_context=host_reports.ssh_context,
        build_inventory=inventory.build_inventory,
        collect=sources.collect,
        match=matcher.match,
        report_scan=report_scan,
        seed_expected_keys=host_reports.seed_expected_keys,
    )


@dataclass
class RunReport:
    run_id: str
    outcome: str = "running"
    planned: list[str] = field(default_factory=list)
    eligible: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    triage_status: str | None = None
    verdicts: dict[str, str] = field(default_factory=dict)
    fixes: dict[str, str] = field(default_factory=dict)
    incidents_opened: list[str] = field(default_factory=list)
    notifications: dict[str, dict[str, str]] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    deferred: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "eligible": len(self.eligible), "queued": len(self.queued), "triage_status": self.triage_status,
            "verdicts": self.verdicts, "fixes": self.fixes, "incidents_opened": self.incidents_opened,
            "failed_sources": self.failed_sources, "coverage_gaps": self.coverage_gaps, "deferred": self.deferred,
        }


class Dispatcher:
    def __init__(self, *, settings: Settings, store: Store, deps: Deps, notifier: notify.Notifier, now: datetime):
        self.settings = settings
        self.store = store
        self.deps = deps
        self.notifier = notifier
        self.now = now.astimezone(timezone.utc)
        self.run_id = f"run-{self.now.strftime('%Y%m%dT%H%M%SZ')}"
        self.report = RunReport(self.run_id)

    # -- helpers --------------------------------------------------------
    def plan(self, message: str) -> None:
        self.report.planned.append(message)

    def raise_health(self, key: str, signal: str, summary: str, *, checklist: list[str] | None = None,
                     advisory_ids: list[str] | None = None, resolve_after_notify: bool = False) -> str:
        incident_id, created = self.store.open_incident(
            "health", f"health:{key}", "high",
            {"signal": signal, "summary": summary, "checklist": checklist or [], "advisory_ids": advisory_ids or []}, self.now,
        )
        if created:
            self.report.incidents_opened.append(incident_id)
        self._notify(incident_id)
        if resolve_after_notify:
            self.store.resolve_incident_key(f"health:{key}", self.now)
        return incident_id

    def _notify(self, incident_id: str) -> None:
        incident = self.store.incident(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        self.report.notifications[incident_id] = self.notifier.notify(incident, self.now)

    # -- pipeline -------------------------------------------------------
    def run(self) -> RunReport:
        self.store.start_run(self.run_id, self.now)
        self._check_watcher_gap()
        reports = self.deps.load_host_reports(self.settings.hosts_dir)
        self._host_health(reports)
        inventory = self.deps.build_inventory(self.settings.project_root, reports, self.now)
        since = self.store.last_successful_run_started() or self.now - timedelta(hours=self.settings.first_run_lookback_hours)
        items, statuses = self.deps.collect(since=since, now=self.now, inventory=inventory)
        status_dicts = [_status_dict(status) for status in statuses]
        self._source_health(status_dicts)
        observations = self.deps.match(items, inventory, self.store.not_affected_fingerprints())
        self._persist(observations)
        self._report_ledger(observations, status_dicts)
        batch = self._select_batch(observations)
        if batch:
            self._dispatch(batch, inventory, reports)
        self._retry_undelivered()
        self._channel_health()
        failed_sources = [s for s in status_dicts if not s["ok"] and s["supported"]]
        self.report.failed_sources = [f"{s['name']}:{s.get('error_code') or 'failed'}" for s in failed_sources]
        self.report.coverage_gaps = [f"{s['name']}:{s.get('error_code') or 'unsupported'}" for s in status_dicts if not s["supported"]]
        self.report.outcome = "incomplete" if failed_sources or not inventory.complete else "complete"
        self.store.finish_run(self.run_id, datetime.now(timezone.utc) if not self.settings.dry_run else self.now,
                              self.report.outcome, status_dicts,
                              {**self.report.summary(), "inventory_complete": inventory.complete,
                               "incomplete_sources": list(inventory.incomplete_sources), "stale_hosts": list(inventory.stale_hosts)})
        return self.report

    def _check_watcher_gap(self) -> None:
        last = self.store.last_run_started(excluding=self.run_id)
        if last and self.now - last > timedelta(hours=self.settings.watcher_stale_hours):
            hours = int((self.now - last).total_seconds() // 3600)
            self.raise_health("watcher_gap", "watcher_not_running",
                              f"The hourly security watcher did not run for {hours} hours before this run.",
                              checklist=["Check the dev-host crontab block 'OpenMates security monitoring'"],
                              resolve_after_notify=True)

    def _host_health(self, reports: Mapping[str, Any]) -> None:
        stale = set(self.deps.stale_roles(reports, self.now))
        for role in sorted(stale):
            self.raise_health(f"stale_host:{role}", "stale_host_report",
                              f"No accepted host report from the {role} server in the last 36 hours.",
                              checklist=[f"Check the host reporter service on the {role} server"])
        self.store.resolve_incidents_with_prefix("health:stale_host:", {f"health:stale_host:{r}" for r in stale}, self.now)
        previous = self.deps.load_previous_host_reports(self.settings.hosts_dir)
        expected = self.deps.load_expected_keys(self.settings.expected_ssh_file)
        for role, current in sorted(reports.items()):
            if current is None:
                continue
            signals: list[dict[str, str]] = []
            if self.deps.seed_expected_keys is not None and not self.settings.dry_run:
                expected, seeded = self.deps.seed_expected_keys(self.settings.expected_ssh_file, current)
                signals.extend(seeded)
            signals.extend(self.deps.intrusion_signals(previous.get(role), current, expected))
            for signal in signals:
                key = f"intrusion:{signal['role']}:{signal['kind']}:{signal['change_id']}"
                incident_id, created = self.store.open_incident(
                    "intrusion", key, "critical",
                    {"role": signal["role"], "signal_kind": signal["kind"], "change_id": signal["change_id"][:16],
                     "safe_detail": signal.get("safe_detail", "")}, self.now,
                )
                if created:
                    self.report.incidents_opened.append(incident_id)
                self._notify(incident_id)

    def _source_health(self, statuses: list[dict[str, Any]]) -> None:
        # Unsupported sources (supported=False) are a standing coverage gap shown in
        # the digest, not an hourly alert; only failures of supported sources alert.
        failing = {status["name"] for status in statuses if not status["ok"] and status["supported"]}
        for status in statuses:
            if status["name"] in failing:
                self.raise_health(f"source:{status['name']}", "source_failed",
                                  f"Source {status['name']} failed ({status.get('error_code') or 'unknown'}); coverage is incomplete.")
        self.store.resolve_incidents_with_prefix("health:source:", {f"health:source:{name}" for name in failing}, self.now)

    def _persist(self, observations: list[Observation]) -> None:
        for observation in observations:
            facts = records.material_facts(observation)
            self.store.upsert_observation(
                observation.identity, observation.material_fingerprint, observation.disposition,
                observation.suppression_reason, {"facts": facts, "observation": records.observation_to_record(observation)}, self.now,
            )

    def _report_ledger(self, observations: list[Observation], statuses: list[dict[str, Any]]) -> None:
        if self.deps.report_scan is None:
            return
        findings = records.ledger_findings(observations)
        failed = [status for status in statuses if not status["ok"] and status["supported"]]
        gaps = [status for status in statuses if not status["supported"]]
        outcome = "incomplete" if failed else ("findings" if findings else "no_new_findings")
        self.deps.report_scan(
            project_root=self.settings.project_root, source="security_monitoring", findings=findings, outcome=outcome,
            subject_commit=git_head(self.settings.project_root),
            coverage={"expected_and_completed_stages": {"sources": [len(statuses), len(statuses) - len(failed)]},
                      "sanitized_failure_codes": sorted({f"{s['name']}:{s.get('error_code') or 'failed'}" for s in failed}
                                                        | {f"unsupported:{s['name']}" for s in gaps})},
            inventory={"missing_required_data": sorted({s["name"] for s in failed})},
            dry_run=self.settings.dry_run,
        )

    # -- no-repeat dispatch --------------------------------------------
    def _select_batch(self, observations: list[Observation]) -> list[tuple[Observation, str]]:
        for observation in observations:
            if observation.disposition != "triage":
                continue
            latest = self.store.latest_dispatch(observation.identity)
            facts = records.material_facts(observation)
            record = {"facts": facts, "observation": records.observation_to_record(observation)}
            if latest is None:
                self.store.queue_dispatch(observation.identity, observation.material_fingerprint, "new observation", record, self.now)
            elif latest["material_fingerprint"] != observation.material_fingerprint:
                done = self.store.last_completed_dispatch(observation.identity) or latest
                reason = records.material_change_reason(done["facts"].get("facts"), facts)
                self.store.queue_dispatch(observation.identity, observation.material_fingerprint, reason, record, self.now)
            # Same fingerprint already dispatched: operator inaction never re-dispatches.
        pending = self.store.dispatches_with_status("queued") + [
            row for row in self.store.dispatches_with_status("failed") if row["attempts"] < self.settings.triage_max_attempts
        ]
        batch: list[tuple[Observation, str]] = []
        seen: set[str] = set()
        for row in pending:
            if row["identity"] in seen:
                continue
            current = self.store.observation(row["identity"])
            if current is None or current["material_fingerprint"] != row["material_fingerprint"]:
                continue  # superseded by a newer fingerprint row
            if current["disposition"] != "triage":
                continue
            seen.add(row["identity"])
            batch.append((records.observation_from_record(row["facts"]["observation"]), row["reason"]))
        batch.sort(key=lambda entry: records.triage_priority(entry[0]))
        self.report.eligible = [observation.identity for observation, _ in batch]
        limit = self.settings.triage_max_batch
        # The remainder keeps status 'queued' and is taken by the next run; that is
        # backlog, not a re-dispatch, so no attempt is counted for it.
        self.report.deferred = max(0, len(batch) - limit)
        if self.report.deferred:
            self.plan(f"{self.report.deferred} lower-priority observation(s) stay queued for the next run (batch cap {limit})")
        return batch[:limit]

    def _dispatch(self, batch: list[tuple[Observation, str]], inventory: Inventory, reports: Mapping[str, Any]) -> None:
        identities = [observation.identity for observation, _ in batch]
        keys = [(observation.identity, observation.material_fingerprint) for observation, _ in batch]
        urgent_pending = [o for o, _ in batch if records.is_urgent_candidate(o)]
        if self.settings.no_agents:
            self.report.queued = identities
            self.plan(f"--no-agents: {len(batch)} observation(s) stay queued for triage")
            return
        if self.store.agent_runs_on("triage", self.now) >= self.settings.triage_runs_per_day:
            self.report.queued = identities
            self.report.triage_status = "limit_exhausted"
            if urgent_pending:
                self.raise_health(f"limit:triage:{self.now.date().isoformat()}", "triage_limit_exhausted",
                                  "Daily triage limit reached while critical or known-exploited observations wait.",
                                  advisory_ids=[o.advisory.advisory_id for o in urgent_pending][:8],
                                  checklist=["Raise SECURITY_MONITORING_TRIAGE_RUNS_PER_DAY or triage manually"])
            return
        lease_ttl = timedelta(seconds=self.settings.triage_timeout_seconds + 300)
        if not self.store.acquire_lease(self.run_id, self.now, lease_ttl):
            self.report.queued = identities
            self.report.triage_status = "lease_held"
            self.plan(f"triage lease held: {len(batch)} observation(s) wait for the next run")
            return
        try:
            self._run_triage(batch, keys, inventory, reports)
        finally:
            self.store.release_lease(self.run_id)

    def _run_triage(self, batch: list[tuple[Observation, str]], keys: list[tuple[str, str]], inventory: Inventory, reports: Mapping[str, Any]) -> None:
        if self.settings.dry_run:
            self.report.triage_status = "dry_run"
            self.plan(f"would launch one triage chat for {len(batch)} observation(s): " + ", ".join(o.advisory.advisory_id for o, _ in batch[:10]))
            return
        self.store.set_dispatch_status(keys, "running", self.run_id, self.now, count_attempt=True)
        agent_run_id = f"triage-{self.run_id}"
        self.store.record_agent_run(agent_run_id, "triage", self.now)
        ssh_contexts = {role: self.deps.ssh_context(report) for role, report in reports.items() if report is not None}
        role_env = {"core": "prod", "upload": "upload", "preview": "preview"}
        ssh_by_env = {role_env.get(role, role): context for role, context in ssh_contexts.items()}
        summary = {"complete": inventory.complete, "incomplete_sources": list(inventory.incomplete_sources),
                   "stale_hosts": list(inventory.stale_hosts), "generated_at": inventory.generated_at}
        result = self.deps.run_triage(settings=self.settings, run_id=agent_run_id, observations=batch,
                                      inventory_summary=summary, ssh_contexts=ssh_by_env)
        self.report.triage_status = result.status
        self.store.finish_agent_run(agent_run_id, result.status, datetime.now(timezone.utc), {"error_code": result.error_code})
        if result.status != "ok":
            self.store.set_dispatch_status(keys, "failed", agent_run_id, self.now)
            self.raise_health(f"triage_failed:{agent_run_id}", "triage_failed",
                              f"Triage chat failed ({result.error_code}); {len(batch)} observation(s) remain untriaged, none marked not affected.",
                              advisory_ids=[o.advisory.advisory_id for o, _ in batch][:8],
                              checklist=["Inspect the private triage transcript on the dev server", "Triage the listed advisories manually if the next run fails again"])
            return
        by_identity = {observation.identity: (observation, reason) for observation, reason in batch}
        for verdict in result.verdicts:
            observation, reason = by_identity[verdict.observation_identity]
            self._apply_verdict(observation, reason, verdict, agent_run_id)
        self.store.set_dispatch_status(keys, "done", agent_run_id, self.now)

    # -- verdicts, fixes, incidents ------------------------------------
    def _apply_verdict(self, observation: Observation, reason: str, verdict: TriageVerdict, agent_run_id: str) -> None:
        verdict_dict = triage.verdict_to_dict(verdict)
        self.store.record_verdict(observation.identity, observation.material_fingerprint, verdict.outcome,
                                  verdict.not_affected_reason, verdict_dict, agent_run_id, self.now)
        self.report.verdicts[observation.identity] = verdict.outcome
        key = f"advisory:{observation.identity}:{observation.material_fingerprint}"
        self.store.resolve_incidents_with_prefix(f"advisory:{observation.identity}:", {key}, self.now)
        if verdict.outcome == "not_affected":
            return
        details = self._advisory_details(observation, reason, verdict)
        incident_id, created = self.store.open_incident("advisory", key, verdict.outcome, details, self.now)
        if created:
            self.report.incidents_opened.append(incident_id)
        if verdict.outcome == "urgent":
            self._maybe_fix(incident_id, observation, verdict)
        self._notify(incident_id)

    def _advisory_details(self, observation: Observation, reason: str, verdict: TriageVerdict) -> dict[str, Any]:
        environments = sorted(set(verdict.environments_assessed) | {e for a in observation.assets for e in a.environments})
        host_roles = sorted({HOST_ROLE_FOR_ENV[e] for a in observation.assets if a.kind in ("os_package", "kernel")
                             for e in a.environments if e in HOST_ROLE_FOR_ENV})
        image_actions = sorted({f"Update the {e} server image" for a in observation.assets if a.kind == "container_image"
                                for e in a.environments if e in ("upload", "preview")})
        return {
            "advisory_ids": [observation.advisory.advisory_id, *observation.advisory.aliases][:8],
            "assets": [{"name": a.name, "version": a.version, "environments": list(a.environments)} for a in observation.assets][:10],
            "environments": environments,
            "outcome": verdict.outcome,
            "dispatch_reason": reason,
            "evidence_summary": verdict.evidence_summary,
            "reachability": verdict.reachability,
            "exploitability": verdict.exploitability,
            "blast_radius": verdict.blast_radius,
            "host_roles": host_roles,
            "manual_actions": [*image_actions, *verdict.manual_actions],
            "automatic_actions": {"summary": "no automatic fix possible"},
        }

    def _maybe_fix(self, incident_id: str, observation: Observation, verdict: TriageVerdict) -> None:
        eligible, why = triage.fix_is_auto_eligible(verdict)
        if not eligible:
            if why == "forbidden_target_path":
                self._downgrade(incident_id, "automatic fix refused: the change would touch a protected path")
            else:
                self.store.update_incident(incident_id, details={"automatic_actions": {"summary": f"no automatic fix possible ({why})"}}, now=self.now)
            return
        if self.settings.dry_run or self.settings.no_agents:
            self.plan(f"would start a guarded fix chat for {observation.advisory.advisory_id}")
            return
        if self.store.agent_runs_on("fix", self.now) >= self.settings.autofixes_per_day:
            self.store.update_incident(incident_id, details={"automatic_actions": {"summary": "auto-fix daily limit reached; fix not attempted"}}, now=self.now)
            self.raise_health(f"limit:fix:{self.now.date().isoformat()}", "fix_limit_exhausted",
                              "Daily auto-fix limit reached with urgent work pending.",
                              advisory_ids=[observation.advisory.advisory_id],
                              checklist=["Apply the urgent fix manually or raise SECURITY_MONITORING_AUTOFIXES_PER_DAY"])
            return
        request = autofix.fix_request(verdict, incident_id, observation.assets,
                                      [observation.advisory.advisory_id, *observation.advisory.aliases],
                                      known_exploited=observation.advisory.known_exploited)
        fix_run_id = f"fix-{incident_id}-{self.now.strftime('%Y%m%dT%H%M%SZ')}"
        self.store.record_agent_run(fix_run_id, "fix", self.now)
        outcome = self.deps.run_fix(settings=self.settings, request=request)
        self.store.finish_agent_run(fix_run_id, outcome.status, datetime.now(timezone.utc),
                                    {"reason": outcome.reason, "commit": outcome.commit, "forbidden_files": list(outcome.forbidden_files)})
        self.report.fixes[incident_id] = outcome.status
        self.store.update_incident(incident_id, details={"automatic_actions": outcome.automatic_actions()}, now=self.now)
        if outcome.status == "refused" and outcome.reason in {"forbidden_target_path", "forbidden_path_required"}:
            self._downgrade(incident_id, "automatic fix refused: the change would touch a protected path")
        elif outcome.status in {"guard_violation", "smoke_failed", "failed"}:
            summary = {
                "guard_violation": f"Auto-fix guard violation ({outcome.reason}); the vulnerability is still open.",
                "smoke_failed": "Dev smoke failed after the auto-fix was deployed; a manual revert is required and the vulnerability is still open.",
                "failed": f"Auto-fix failed ({outcome.reason}); the vulnerability is still open.",
            }[outcome.status]
            checklist = ["Revert the auto-fix commit on dev via a reviewed session deploy"] if outcome.revert_required else []
            self.raise_health(f"fix:{incident_id}:{outcome.status}", f"fix_{outcome.status}", summary,
                              advisory_ids=[observation.advisory.advisory_id],
                              checklist=checklist + ["Apply the urgent fix manually"])

    def _downgrade(self, incident_id: str, summary: str) -> None:
        incident = self.store.incident(incident_id)
        actions = list((incident or {}).get("details", {}).get("manual_actions", []))
        actions.insert(0, "Apply the proposed fix manually (protected path)")
        self.store.update_incident(incident_id, severity="affected_fix_soon", now=self.now, details={
            "outcome": "affected_fix_soon", "downgraded_from": "urgent", "manual_actions": actions,
            "automatic_actions": {"summary": summary},
        })

    def _retry_undelivered(self) -> None:
        """Carry forward: deliver missing channels of unresolved incidents, never re-send delivered ones."""
        for incident in self.store.unresolved_incidents():
            if incident["incident_id"] in self.report.notifications:
                continue
            outcomes = self.notifier.notify(incident, self.now)
            if any(state not in {"already_sent"} for state in outcomes.values()):
                self.report.notifications[incident["incident_id"]] = outcomes

    def _channel_health(self) -> None:
        for channel in sorted(self.notifier.unavailable_channels):
            key = f"health:channel_unavailable:{channel}"
            incident_id, created = self.store.open_incident(
                "health", key, "high",
                {"signal": "notification_channel_unavailable", "summary": f"Security notifications cannot use {channel}: not configured.",
                 "checklist": [f"Configure {notify.DISCORD_WEBHOOK_ENV} in the dev-host .env" if channel == "discord" else "Configure the security email destination"]},
                self.now,
            )
            if created:
                self.report.incidents_opened.append(incident_id)
                # Deliver on the remaining channels only; the unavailable one is recorded again harmlessly.
                self.notifier.notify(self.store.incident(incident_id) or {}, self.now)


def _status_dict(status: Any) -> dict[str, Any]:
    if isinstance(status, Mapping):
        return {"name": str(status["name"]), "ok": bool(status["ok"]), "error_code": status.get("error_code"),
                "item_count": int(status.get("item_count") or 0), "supported": bool(status.get("supported", True))}
    return {"name": str(status.name), "ok": bool(status.ok), "error_code": status.error_code,
            "item_count": int(status.item_count or 0), "supported": bool(getattr(status, "supported", True))}


def build_notifier(settings: Settings, store: Store, **overrides: Any) -> notify.Notifier:
    webhook = dotenv_value(settings.project_root, notify.DISCORD_WEBHOOK_ENV)
    return notify.Notifier(store=store, ledger_path=settings.delivery_ledger, webhook_url=webhook, dry_run=settings.dry_run, **overrides)


def run_hourly(settings: Settings, *, deps: Deps | None = None, store: Store | None = None,
               notifier: notify.Notifier | None = None, now: datetime | None = None) -> RunReport:
    owned = store is None
    store = store or Store.open(settings.state_db, dry_run=settings.dry_run)
    try:
        dispatcher = Dispatcher(settings=settings, store=store, deps=deps or default_deps(),
                                notifier=notifier or build_notifier(settings, store), now=now or datetime.now(timezone.utc))
        report = dispatcher.run()
        if dispatcher.notifier.planned:
            report.planned.extend(f"would notify {p['channel']}: {p['title']}" for p in dispatcher.notifier.planned)
        return report
    finally:
        if owned:
            store.close()


__all__ = ["Deps", "Dispatcher", "RunReport", "build_notifier", "default_deps", "run_hourly", "utc"]
