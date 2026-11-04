"""Offline fakes for security monitoring orchestration tests.

No helper here launches claude, posts to Discord, sends email or creates a
Task; every external effect is captured in memory. Addresses use RFC 5737 and
RFC 3849 documentation ranges only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring import autofix, dispatch, notify, triage  # noqa: E402 - path set above
from security_monitoring.config import Settings  # noqa: E402 - path set above
from security_monitoring.models import AdvisoryItem, Asset, Inventory, Observation, ProposedFix, TriageVerdict  # noqa: E402
from security_monitoring.state import Store  # noqa: E402 - path set above
from security_report_delivery import SendResult  # noqa: E402 - path set above

NOW = datetime(2026, 11, 4, 10, 20, tzinfo=timezone.utc)


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    base = Settings(project_root=tmp_path / "repo", state_dir=tmp_path / "state", dev_smoke_command="true")
    return replace(base, **overrides)


def asset(name: str = "zod", version: str = "4.6.2", *, ecosystem: str = "npm", kind: str = "package",
          environments: tuple[str, ...] = ("prod", "dev"), exposure: str = "internet_facing") -> Asset:
    return Asset(kind=kind, ecosystem=ecosystem, name=name, version=version, environments=environments, exposure=exposure,
                 source_file="pnpm-lock.yaml")


def observation(advisory_id: str = "GHSA-2222-3333-4444", *, assets: tuple[Asset, ...] | None = None,
                severity: str = "high", known_exploited: bool = False, disposition: str = "triage",
                title: str = "zod parser issue", suppression_reason: str | None = None) -> Observation:
    assets = assets or (asset(),)
    item = AdvisoryItem(source="osv", advisory_id=advisory_id, aliases=("CVE-2026-0001",), title=title, severity=severity,
                        published_at="2026-11-01T00:00:00Z", modified_at="2026-11-01T00:00:00Z", known_exploited=known_exploited)
    identity = f"{advisory_id}|" + ",".join(sorted(a.identity for a in assets))
    material = json.dumps([sorted(a.identity for a in assets), severity, known_exploited], sort_keys=True)
    fingerprint = hashlib.sha256(material.encode()).hexdigest()[:16]
    return Observation(identity=identity, advisory=item, assets=assets, match_strength="version_range",
                       disposition=disposition, suppression_reason=suppression_reason, material_fingerprint=fingerprint)


def verdict_for(obs: Observation, outcome: str = "urgent", *, fix: ProposedFix | None = None, reason: str | None = None) -> TriageVerdict:
    return TriageVerdict(
        observation_identity=obs.identity, outcome=outcome,
        not_affected_reason=reason if outcome == "not_affected" else None,
        environments_assessed=("prod", "dev"), reachability="imported by the web app form parser",
        exploitability="internet-facing route, no auth", blast_radius="user form data",
        evidence_summary="pnpm-lock.yaml pins 4.6.2; parse() called in signup form", proposed_fix=fix,
        manual_actions=("Release to production via update-prod-server",) if outcome == "urgent" else (),
    )


def dependency_fix(target: str = "frontend/apps/web_app/package.json") -> ProposedFix:
    return ProposedFix(fix_class="dependency_bump", target_files=(target,), package="zod", from_version="4.6.2", target_version="4.6.6")


@dataclass
class World:
    """Mutable fake world: what sources return this hour and what triage answers."""

    observations: list[Observation] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=lambda: [{"name": "osv", "ok": True, "error_code": None, "item_count": 1}])
    stale: list[str] = field(default_factory=list)
    signals: list[dict[str, str]] = field(default_factory=list)
    reports: dict[str, Any] = field(default_factory=dict)
    verdict_outcome: str = "urgent"
    verdict_fix: ProposedFix | None = None
    triage_status: str = "ok"
    triage_calls: list[list[tuple[Observation, str]]] = field(default_factory=list)
    fix_calls: list[dict[str, Any]] = field(default_factory=list)
    fix_outcome: autofix.FixOutcome = field(default_factory=lambda: autofix.FixOutcome("deployed", commit="abc1234def", dev_deploy="deployed"))
    match_recorded: list[dict[str, str]] = field(default_factory=list)
    ledger_calls: list[dict[str, Any]] = field(default_factory=list)

    def match(self, items: Any, inventory: Inventory, recorded: dict[str, str]) -> list[Observation]:
        """Mimic the matcher contract: a still-valid not_affected verdict suppresses."""
        self.match_recorded.append(dict(recorded))
        out = []
        for obs in self.observations:
            if recorded.get(obs.identity) == obs.material_fingerprint:
                obs = replace(obs, disposition="suppressed_recorded_verdict", suppression_reason="recorded verdict: not affected")
            out.append(obs)
        return out

    def run_triage(self, *, settings: Settings, run_id: str, observations: list[tuple[Observation, str]], **_: Any) -> triage.TriageResult:
        self.triage_calls.append(list(observations))
        if self.triage_status != "ok":
            return triage.TriageResult("failed", self.triage_status)
        verdicts = tuple(verdict_for(obs, self.verdict_outcome, fix=self.verdict_fix,
                                     reason="vulnerable_code_not_present" if self.verdict_outcome == "not_affected" else None)
                         for obs, _ in observations)
        return triage.TriageResult("ok", None, verdicts)

    def run_fix(self, *, settings: Settings, request: dict[str, Any]) -> autofix.FixOutcome:
        self.fix_calls.append(dict(request))
        return self.fix_outcome

    def deps(self) -> dispatch.Deps:
        return dispatch.Deps(
            load_host_reports=lambda directory: dict(self.reports),
            load_previous_host_reports=lambda directory: {},
            stale_roles=lambda reports, now: list(self.stale),
            intrusion_signals=lambda previous, current, expected: list(self.signals),
            load_expected_keys=lambda path: {},
            ssh_context=lambda report: {"sshd_effective_settings": {"passwordauthentication": "no"}},
            build_inventory=lambda root, reports, now: Inventory(generated_at="2026-11-04T10:00:00Z", assets=()),
            collect=lambda **kwargs: ([], list(self.statuses)),
            match=self.match,
            run_triage=self.run_triage,
            run_fix=self.run_fix,
            report_scan=lambda **kwargs: self.ledger_calls.append(kwargs),
        )


@dataclass
class Channels:
    discord: list[dict[str, Any]] = field(default_factory=list)
    email: list[dict[str, str]] = field(default_factory=list)
    tasks: list[tuple[str, str]] = field(default_factory=list)

    def discord_post(self, url: str, payload: dict[str, Any]) -> dict[str, str]:
        self.discord.append(payload)
        return {"message_id": str(len(self.discord))}

    def email_sender(self, request: dict[str, str]) -> SendResult:
        self.email.append(request)
        return SendResult.accepted(f"msg-{len(self.email)}")

    def task_creator(self, title: str, description: str) -> str:
        self.tasks.append((title, description))
        return f"TASK-{len(self.tasks)}"


def notifier(cfg: Settings, store: Store, channels: Channels, *, webhook: str = "https://discord.example.invalid/webhook") -> notify.Notifier:
    return notify.Notifier(store=store, ledger_path=cfg.delivery_ledger, webhook_url=webhook, dry_run=cfg.dry_run,
                           discord_post=channels.discord_post, email_sender=channels.email_sender,
                           task_creator=channels.task_creator)


def run(cfg: Settings, world: World, store: Store, channels: Channels, now: datetime = NOW, **kwargs: Any) -> dispatch.RunReport:
    return dispatch.run_hourly(cfg, deps=world.deps(), store=store, notifier=notifier(cfg, store, channels, **kwargs), now=now)
