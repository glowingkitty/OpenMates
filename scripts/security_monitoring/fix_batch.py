"""Daily patch/minor security fix lane (autofix.guarded-dev-only, owner decision 21 Nov).

Once a day every open fix-soon or low advisory whose triage verdict proposes a
dependency bump within the current major line (patch or minor; for 0.x the
current minor line) is grouped per package. One guarded fix chat per package
bumps to the highest of the proposed fixed versions, so it covers all open
advisories of that package, but only once that version has been public for 7
days (release_age.select_fix_version). It reuses the urgent fix runner: same
skill, tool allowlist, path guard, isolated CI, dev-only deploy, smoke check and
private transcript.

Everything the lane does not fix on its own (major bumps, image bumps, code
changes, items without a proposed fix, versions younger than 7 days) becomes one
line per package that the daily email lists under "Needs a decision" or
"Waiting".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import TYPE_CHECKING, Any, Callable, Mapping

from security_monitoring import release_age
from security_monitoring.config import is_forbidden_path
from security_monitoring.state import parse_utc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from security_monitoring.dispatch import Dispatcher

BATCH_OUTCOMES = frozenset({"affected_fix_soon", "affected_low"})
BUMP_ECOSYSTEMS = frozenset({"npm", "PyPI", "crates.io"})
DECISIONS_META_KEY = "fix_batch:last_plan"
_ADVISORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,80}")

AgeCheck = Callable[[str, str, str, str, datetime], tuple[bool, str]]


@dataclass
class Group:
    """All open advisories of one package that a single bump can fix."""

    ecosystem: str
    package: str
    from_version: str
    target_version: str
    incident_ids: list[str] = field(default_factory=list)
    advisory_ids: list[str] = field(default_factory=list)
    target_files: set[str] = field(default_factory=set)
    environments: set[str] = field(default_factory=set)
    identities: list[str] = field(default_factory=list)
    mitigation: str | None = None


@dataclass
class Plan:
    ready: list[Group] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def as_meta(self, now: datetime) -> str:
        return json.dumps({"at": now.isoformat(), "ready": [f"{g.ecosystem}:{g.package} {g.from_version} -> {g.target_version}" for g in self.ready],
                           "waiting": self.waiting, "decisions": self.decisions}, sort_keys=True)


def is_patch_or_minor(current: str, target: str) -> bool:
    """True when target is above current on the same major line (same minor line for 0.x)."""
    cur, tgt = release_age.version_key(current)[0], release_age.version_key(target)[0]
    if not cur or not tgt or release_age.version_key(target) <= release_age.version_key(current):
        return False
    if cur[0] != tgt[0]:
        return False
    return cur[0] != 0 or (len(cur) > 1 and len(tgt) > 1 and cur[1] == tgt[1])


def _ecosystem(identity: str, package: str) -> str | None:
    """The ecosystem of `package` from an observation identity `<advisory>|<eco>:<name>,...`."""
    _, _, assets = identity.partition("|")
    for item in assets.split(","):
        eco, _, name = item.partition(":")
        if name.lower() == package.lower():
            return eco
    return None


def default_age_check(ecosystem: str, package: str, current: str, target: str, now: datetime) -> tuple[bool, str]:
    """(ok, reason) for taking `target` under the 7-day rule; lookup failures wait."""
    try:
        decision = release_age.select_fix_version(ecosystem, package, current, [target], actively_exploited=False, now=now)
    except release_age.RegistryLookupError as error:
        return False, f"release age could not be checked ({error})"
    if decision.mode == "immediate" and decision.version == target:
        return True, decision.reasons[0]
    return False, decision.reasons[0] if decision.reasons else "fixed version is younger than 7 days"


def plan_batch(store: Any, now: datetime, age_check: AgeCheck = default_age_check) -> Plan:
    """Group open fix-soon/low advisories into ready bumps, waiting bumps and decision lines."""
    groups: dict[tuple[str, str], Group] = {}
    undecided: dict[str, set[str]] = {}
    reviewed: dict[str, tuple[str, list[str], set[str]]] = {}  # package -> (fix class, targets, identities)
    os_packages: set[str] = set()
    for incident in store.unresolved_incidents("advisory"):
        details = incident.get("details") or {}
        if details.get("outcome") not in BATCH_OUTCOMES:
            continue
        identity = incident["incident_key"].split(":", 1)[1].rsplit(":", 1)[0]
        latest = store.latest_verdict(identity)
        fix = (latest or {}).get("verdict", {}).get("proposed_fix") if latest else None
        label = identity.partition("|")[2] or identity
        if not fix and label.startswith("ubuntu:"):
            os_packages.add(identity)
            continue
        if not fix:
            undecided.setdefault(f"{label}: no automatic fix proposed (code change or vendor update)", set()).add(identity)
            continue
        package, current, target = fix.get("package"), fix.get("from_version"), fix.get("target_version")
        if fix.get("fix_class") != "dependency_bump" or not (package and current and target):
            entry = reviewed.setdefault(package or label, (str(fix.get("fix_class") or "fix"), [], set()))
            entry[1].extend([target] if target else [])
            entry[2].add(identity)
            continue
        ecosystem = _ecosystem(identity, package)
        if ecosystem not in BUMP_ECOSYSTEMS:
            undecided.setdefault(f"{ecosystem or '?'}:{package}: not a registry dependency, handled by OS or image updates", set()).add(identity)
            continue
        if not is_patch_or_minor(current, target):
            undecided.setdefault(f"{ecosystem}:{package} {current} -> {target}: major upgrade needs a decision", set()).add(identity)
            continue
        if any(is_forbidden_path(path) for path in fix.get("target_files") or []):
            undecided.setdefault(f"{ecosystem}:{package}: fix touches a protected path, apply manually", set()).add(identity)
            continue
        group = groups.setdefault((ecosystem, package.lower()), Group(ecosystem, package, current, target))
        if release_age.version_key(target) > release_age.version_key(group.target_version):
            group.target_version = target
        group.incident_ids.append(incident["incident_id"])
        group.identities.append(identity)
        group.advisory_ids.extend(a for a in details.get("advisory_ids", []) if _ADVISORY_ID.fullmatch(a) and a not in group.advisory_ids)
        group.target_files.update(fix.get("target_files") or [])
        group.environments.update(details.get("environments") or [])
        group.mitigation = group.mitigation or fix.get("mitigation")
    for package, (fix_class, targets, ids) in reviewed.items():
        highest = max(targets, key=release_age.version_key) if targets else "a fixed version"
        undecided[f"{package}: {fix_class.replace('_', ' ')} to {highest} needs a reviewed upgrade"] = ids
    if os_packages:
        undecided["OS packages: installed by automatic OS security updates and the reboot windows"] = os_packages
    plan = Plan(decisions=sorted(f"{line} ({_count(ids)})" for line, ids in undecided.items()))
    for group in sorted(groups.values(), key=lambda g: (g.ecosystem, g.package.lower())):
        ok, reason = age_check(group.ecosystem, group.package, group.from_version, group.target_version, now)
        if ok:
            plan.ready.append(group)
        else:
            plan.waiting.append(f"{group.ecosystem}:{group.package} {group.from_version} -> {group.target_version}: {reason}")
    return plan


def _count(ids: set[str]) -> str:
    return f"{len(ids)} advisor{'y' if len(ids) == 1 else 'ies'}"


def batch_request(group: Group) -> dict[str, Any]:
    """Fix request in the same shape as the urgent lane, covering every advisory of the package."""
    return {
        "incident_id": group.incident_ids[0],
        "incident_ids": group.incident_ids[:20],
        "lane": "daily_patch_minor",
        "advisory_ids": group.advisory_ids[:8],
        "observation_identity": group.identities[0],
        "fix_class": "dependency_bump",
        "target_files": sorted(group.target_files),
        "package": group.package,
        "ecosystem": group.ecosystem,
        "from_version": group.from_version,
        "target_version": group.target_version,
        "mitigation": group.mitigation,
        "environments": sorted(group.environments),
        "actively_exploited": False,
        "release_age_required": True,
    }


def paused(settings: Any, now: datetime) -> bool:
    if not settings.fix_batch_paused_until:
        return False
    return now < parse_utc(settings.fix_batch_paused_until).astimezone(timezone.utc)


def run_batch(dispatcher: "Dispatcher", age_check: AgeCheck = default_age_check) -> dict[str, Any]:
    """Plan and run the daily lane through the dispatcher's guarded fix runner and health alerts."""
    settings, store, now = dispatcher.settings, dispatcher.store, dispatcher.now
    plan = plan_batch(store, now, age_check)
    if not settings.dry_run:
        store.set_meta(DECISIONS_META_KEY, plan.as_meta(now))
    summary: dict[str, Any] = {"ready": len(plan.ready), "waiting": plan.waiting, "decisions": plan.decisions, "fixes": {}}
    hold = settings.dry_run or settings.no_agents or paused(settings, now)
    for group in plan.ready:
        label = f"{group.ecosystem}:{group.package} -> {group.target_version}"
        if hold:
            dispatcher.plan(f"would start a guarded patch/minor fix chat for {label} ({_count(set(group.incident_ids))})")
            continue
        if store.agent_runs_on("fix", now) >= settings.autofixes_per_day:
            summary["limit_reached"] = True
            break
        run_id = f"fix-batch-{group.ecosystem}-{re.sub(r'[^A-Za-z0-9_-]', '_', group.package)}-{now.strftime('%Y%m%dT%H%M%SZ')}"
        store.record_agent_run(run_id, "fix", now)
        outcome = dispatcher.deps.run_fix(settings=settings, request=batch_request(group), transcript_id=run_id)
        store.finish_agent_run(run_id, outcome.status, datetime.now(timezone.utc),
                               {"reason": outcome.reason, "commit": outcome.commit, "forbidden_files": list(outcome.forbidden_files), "lane": "daily"})
        summary["fixes"][label] = outcome.status
        for incident_id in group.incident_ids:
            store.update_incident(incident_id, details={"automatic_actions": outcome.automatic_actions()}, now=now)
        _report_outcome(dispatcher, group, label, outcome, run_id)
    return summary


def _report_outcome(dispatcher: "Dispatcher", group: Group, label: str, outcome: Any, run_id: str) -> None:
    if outcome.status in {"deployed", "mitigation_deployed"}:
        return
    immediate = outcome.status in {"guard_violation", "smoke_failed"}
    summary = {
        "guard_violation": f"Daily auto-fix {label}: guard violation ({outcome.reason}); still open.",
        "smoke_failed": f"Daily auto-fix {label}: dev smoke failed after deploy; manual revert required, still open.",
    }.get(outcome.status, f"Daily auto-fix {label} {outcome.status} ({outcome.reason}); still open. Transcript {run_id}.")
    checklist = ["Revert the auto-fix commit on dev via a reviewed session deploy"] if outcome.revert_required else []
    dispatcher.raise_health(f"fix_batch:{group.ecosystem}:{group.package.lower()}:{dispatcher.now.date().isoformat()}",
                            f"fix_{outcome.status}" if immediate else "fix_batch_not_applied", summary,
                            advisory_ids=group.advisory_ids[:8],
                            checklist=checklist + ["Read the private fix transcript on the dev server and apply the bump manually"])


def last_plan(store: Any) -> Mapping[str, Any] | None:
    raw = store.get_meta(DECISIONS_META_KEY)
    return json.loads(raw) if raw else None
