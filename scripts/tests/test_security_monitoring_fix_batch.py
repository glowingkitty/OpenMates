"""Contracts for the daily patch/minor security fix lane (owner decision 21 Nov).

Registry ages, the fix chat and email are faked; nothing leaves the process.
"""

# contract-test-file: infrastructure
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import security_monitoring_fakes as fx  # noqa: E402 - tests dir added above

from security_monitoring import autofix, dispatch, fix_batch, health  # noqa: E402
from security_monitoring.state import Store  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("DRY_RUN", "SECURITY_MONITORING_DIR", "SECURITY_REPORTING_DIR", "SECURITY_MONITORING_FIX_BATCH_PAUSED_UNTIL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def cfg(tmp_path):
    return fx.settings(tmp_path)


@pytest.fixture
def store(cfg):
    opened = Store.open(cfg.state_db)
    yield opened
    opened.close()


def _open(store: Store, advisory: str, asset: str, outcome: str, fix: dict | None) -> str:
    identity = f"{advisory}|{asset}"
    store.record_verdict(identity, "fp", outcome, None, {"observation_identity": identity, "proposed_fix": fix}, "triage-1", fx.NOW)
    incident_id, _ = store.open_incident("advisory", f"advisory:{identity}:fp", outcome, {
        "advisory_ids": [advisory], "outcome": outcome, "environments": ["dev", "prod"]}, fx.NOW)
    return incident_id


def _bump(package: str, current: str, target: str, path: str = "backend/core/api/requirements.txt", fix_class: str = "dependency_bump") -> dict:
    return {"fix_class": fix_class, "package": package, "from_version": current, "target_version": target, "target_files": [path], "mitigation": None}


def _old_enough(eco, name, current, target, now):
    return True, f"{target} is 9.0 days old"


def _seed(store: Store) -> None:
    _open(store, "CVE-2026-1001", "PyPI:opentelemetry-api", "affected_fix_soon", _bump("opentelemetry-api", "1.40.0", "1.45.1"))
    _open(store, "CVE-2026-1002", "PyPI:opentelemetry-api", "affected_low", _bump("opentelemetry-api", "1.40.0", "1.45.2"))
    _open(store, "GHSA-aaaa-bbbb-cccc", "docker:example/cms", "affected_fix_soon",
          _bump("example/cms", "11.5", "12.1.0", "backend/core/cms/Dockerfile", "image_digest_bump"))
    _open(store, "CVE-2026-1003", "npm:big-lib", "affected_fix_soon", _bump("big-lib", "2.4.0", "3.0.1", "frontend/package.json"))
    _open(store, "CVE-2026-1004", "npm:tool-cli", "affected_fix_soon", None)


# Spec coverage: security-monitoring.autofix.guarded-dev-only
# contract-test: infrastructure
def test_plan_groups_one_package_and_lists_majors_images_and_unfixable_as_decisions(store):
    _seed(store)
    plan = fix_batch.plan_batch(store, fx.NOW, _old_enough)
    # Both opentelemetry advisories go into one bump to the highest proposed version.
    assert [(g.package, g.target_version, len(g.incident_ids)) for g in plan.ready] == [("opentelemetry-api", "1.45.2", 2)]
    decisions = "\n".join(plan.decisions)
    assert "big-lib 2.4.0 -> 3.0.1: major upgrade needs a decision" in decisions
    assert "example/cms: image digest bump to 12.1.0 needs a reviewed upgrade (1 advisory)" in decisions
    assert "no automatic fix proposed" in decisions and len(plan.decisions) == 3


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_fixed_version_younger_than_7_days_waits(store):
    _seed(store)
    plan = fix_batch.plan_batch(store, fx.NOW, lambda *a: (False, "only 4.0 days old (<7 days)"))
    assert plan.ready == [] and plan.waiting == ["PyPI:opentelemetry-api 1.40.0 -> 1.45.2: only 4.0 days old (<7 days)"]


# Spec coverage: security-monitoring.autofix.guarded-dev-only
# contract-test: infrastructure
@pytest.mark.parametrize(("current", "target", "expected"), [
    ("1.40.0", "1.45.2", True), ("1.40.0", "1.40.1", True), ("1.40.0", "2.0.0", False),
    ("0.4.1", "0.4.9", True), ("0.4.1", "0.5.0", False), ("1.2.0", "1.1.9", False),
])
def test_patch_or_minor_respects_semver_lines(current, target, expected):
    assert fix_batch.is_patch_or_minor(current, target) is expected


def _dispatcher(cfg, store, world, channels):
    return dispatch.Dispatcher(settings=cfg, store=store, deps=world.deps(), notifier=fx.notifier(cfg, store, channels), now=fx.NOW)


# Spec coverage: security-monitoring.autofix.guarded-dev-only
# contract-test: infrastructure
def test_batch_runs_one_guarded_fix_and_records_it_on_every_incident(cfg, store):
    _seed(store)
    world = fx.World(fix_outcome=autofix.FixOutcome("deployed", commit="abc1234def", dev_deploy="deployed", changed_files=("backend/core/api/requirements.txt",)))
    summary = fix_batch.run_batch(_dispatcher(cfg, store, world, fx.Channels()), _old_enough)
    assert summary["fixes"] == {"PyPI:opentelemetry-api -> 1.45.2": "deployed"}
    request = world.fix_calls[0]
    assert request["lane"] == "daily_patch_minor" and request["release_age_required"] and not request["actively_exploited"]
    assert sorted(request["advisory_ids"]) == ["CVE-2026-1001", "CVE-2026-1002"] and len(request["incident_ids"]) == 2
    otel = [i for i in store.unresolved_incidents("advisory") if "opentelemetry" in i["incident_key"]]
    assert all(i["details"]["automatic_actions"]["commit"] == "abc1234def" for i in otel)
    # The digest lists what the lane will not change on its own.
    text = health.render_digest(health.digest_data(store, fx.NOW + timedelta(hours=1))).email_payload()["text"]
    assert "NEEDS A DECISION" in text and "major upgrade needs a decision" in text


# Spec coverage: security-monitoring.health.no-silent-failure
# contract-test: infrastructure
def test_refused_fix_waits_for_digest_and_guard_violation_emails_now(cfg, store):
    _seed(store)
    channels = fx.Channels()
    refused = fx.World(fix_outcome=autofix.FixOutcome("refused", "other"))
    fix_batch.run_batch(_dispatcher(cfg, store, refused, channels), _old_enough)
    signals = {i["details"]["signal"] for i in store.unresolved_incidents("health")}
    assert "fix_batch_not_applied" in signals and channels.email == []
    violation = fx.World(fix_outcome=autofix.FixOutcome("guard_violation", "forbidden_path_in_deployed_commit", commit="abc1234", revert_required=True))
    later = dispatch.Dispatcher(settings=replace(cfg, autofixes_per_day=5), store=store, deps=violation.deps(),
                                notifier=fx.notifier(cfg, store, channels), now=fx.NOW + timedelta(days=1))
    fix_batch.run_batch(later, _old_enough)
    assert len(channels.email) == 1 and "guard violation" in channels.email[0]["text"]


# Spec coverage: security-monitoring.autofix.guarded-dev-only
# contract-test: infrastructure
def test_pause_and_daily_limit_hold_the_lane(cfg, store):
    _seed(store)
    world = fx.World()
    held = fix_batch.run_batch(_dispatcher(replace(cfg, fix_batch_paused_until="2026-11-24T00:00:00Z"), store, world, fx.Channels()), _old_enough)
    assert world.fix_calls == [] and held["ready"] == 1
    for n in range(3):
        store.record_agent_run(f"fix-urgent-{n}", "fix", fx.NOW)
    limited = fix_batch.run_batch(_dispatcher(cfg, store, world, fx.Channels()), _old_enough)
    assert world.fix_calls == [] and limited.get("limit_reached")


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_exploited_prod_os_flaw_asks_once_for_an_early_reboot(cfg, store):
    kernel = fx.asset("linux-image-generic", "6.8.0-100", ecosystem="ubuntu", kind="kernel", environments=("prod",), exposure="internal")
    world = fx.World(observations=[fx.observation("CVE-2026-0099", assets=(kernel,), severity="critical", known_exploited=True)])
    asked: list[tuple[str, str]] = []
    channels = fx.Channels()
    for hour in range(3):
        deps = replace(world.deps(), ask_operator=lambda q, r: asked.append((q, r)) or True)
        dispatch.run_hourly(cfg, deps=deps, store=store, notifier=fx.notifier(cfg, store, channels), now=fx.NOW + timedelta(hours=hour))
    # One question for the whole incident, never a reboot: production waits for the answer or Sunday.
    assert len(asked) == 1 and "before Sunday" in asked[0][0]
    assert len(asked[0][0]) + len(asked[0][1]) < 120
