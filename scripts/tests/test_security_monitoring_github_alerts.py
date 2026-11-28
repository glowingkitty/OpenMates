"""Contracts for GitHub Dependabot and secret scanning alerts in the daily report.

Synthetic alerts only (example packages, fake alert numbers); no network.
"""

# contract-test-file: infrastructure
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import security_monitoring_fakes as fx  # noqa: E402 - tests dir added above

from security_monitoring import dispatch, github_alerts, health  # noqa: E402
from security_monitoring.sources.fetch import FetchError  # noqa: E402
from security_monitoring.state import Store  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("DRY_RUN", "SECURITY_MONITORING_DIR", "SECURITY_REPORTING_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def cfg(tmp_path):
    return fx.settings(tmp_path)


@pytest.fixture
def store(cfg):
    opened = Store.open(cfg.state_db)
    yield opened
    opened.close()


def _dependabot(number, cve, name, severity, manifest, ecosystem="npm", scope="runtime"):
    return {"number": number, "security_advisory": {"cve_id": cve, "ghsa_id": f"GHSA-{number:04d}-xxxx-yyyy", "summary": "example flaw"},
            "security_vulnerability": {"severity": severity, "package": {"ecosystem": ecosystem, "name": name},
                                       "first_patched_version": {"identifier": "2.0.0"}},
            "dependency": {"manifest_path": manifest, "scope": scope, "package": {"ecosystem": ecosystem, "name": name}}}


SECRET = {"number": 7, "secret_type": "example_token", "secret_type_display_name": "Example Token", "validity": "unknown",
          "secret": "never-copied-value", "created_at": "2026-11-01T00:00:00Z"}


def _fetch(dependabot, secrets, locations=None):
    def fetch(url, options=None):
        if "/dependabot/alerts" in url:
            return dependabot
        if url.endswith("secret-scanning/alerts?state=open&per_page=100"):
            return secrets
        if "/locations" in url:
            return locations or [{"type": "commit", "details": {"path": "docs/example.yml", "start_line": 3}}]
        raise AssertionError(url)
    return fetch


# Spec coverage: security-monitoring.github-alerts.every-alert-listed
# contract-test: infrastructure
def test_every_dependabot_alert_is_listed_once_per_advisory_with_our_verdict(cfg, store):
    store.record_verdict("CVE-2026-0101|npm:example-kit", "fp", "not_affected", "not_reachable",
                         {"reachability": "The vulnerable handler is never registered."}, "triage-1", fx.NOW)
    alerts = [_dependabot(1, "CVE-2026-0101", "example-kit", "critical", "apps/web/package.json", scope="development"),
              _dependabot(2, "CVE-2026-0101", "example-kit", "critical", "pnpm-lock.yaml"),
              _dependabot(3, "CVE-2026-0102", "example-lib", "low", "pnpm-lock.yaml")]
    snapshot = github_alerts.run(dispatch.Dispatcher(settings=cfg, store=store, deps=fx.World().deps(),
                                                     notifier=fx.notifier(cfg, store, fx.Channels()), now=fx.NOW),
                                 fetch=_fetch(alerts, []))
    assert snapshot["dependabot_total"] == 3 and len(snapshot["dependabot"]) == 2
    critical = snapshot["dependabot"][0]
    assert critical["numbers"] == [1, 2] and critical["severity"] == "critical"
    assert critical["where"] == ["apps/web/package.json (development)", "pnpm-lock.yaml (runtime)"]
    assert critical["state"] == "not affected (not_reachable)" and "never registered" in critical["reachability"]
    assert snapshot["dependabot"][1]["state"] == "not in our scans yet"
    rendered = health.render_digest(health.digest_data(store, fx.NOW))
    text = "\n".join(f"{label}: {value}" for label, value in rendered.lines)
    assert "Dependabot 3 open (critical 2, low 1) in 2 advisories" in text
    assert "[CRITICAL] npm:example-kit CVE-2026-0101" in text and "alerts #1, #2" in text


# Spec coverage: security-monitoring.github-alerts.every-alert-listed
# contract-test: infrastructure
def test_secret_alerts_carry_classification_and_never_the_secret(cfg, store):
    (cfg.state_dir / github_alerts.VERDICTS_FILE).write_text(json.dumps({"7": {"verdict": "false_positive", "reason": "test label"}}))
    channels = fx.Channels()
    dispatcher = dispatch.Dispatcher(settings=cfg, store=store, deps=fx.World().deps(), notifier=fx.notifier(cfg, store, channels), now=fx.NOW)
    snapshot = github_alerts.run(dispatcher, fetch=_fetch([], [SECRET]))
    assert snapshot["secrets"][0]["verdict"] == "false_positive"
    assert snapshot["secrets"][0]["locations"] == ["docs/example.yml:3"]
    assert "never-copied-value" not in store.get_meta(github_alerts.META_KEY)
    assert channels.email == []


# Spec coverage: security-monitoring.github-alerts.every-alert-listed
# contract-test: infrastructure
@pytest.mark.parametrize("validity,verdict", [("active", None), ("unknown", "real_live")])
def test_possibly_live_secret_emails_at_once(cfg, store, validity, verdict):
    if verdict:
        (cfg.state_dir / github_alerts.VERDICTS_FILE).write_text(json.dumps({"7": {"verdict": verdict, "reason": "ours"}}))
    channels = fx.Channels()
    dispatcher = dispatch.Dispatcher(settings=cfg, store=store, deps=fx.World().deps(), notifier=fx.notifier(cfg, store, channels), now=fx.NOW)
    github_alerts.run(dispatcher, fetch=_fetch([], [{**SECRET, "validity": validity}]))
    assert len(channels.email) == 1 and "may be a live secret" in json.dumps(channels.email[0])


# Spec coverage: security-monitoring.github-alerts.every-alert-listed
# contract-test: infrastructure
def test_unavailable_github_api_is_reported_not_hidden(cfg, store):
    def failing(url, options=None):
        raise FetchError("gh_failed")
    snapshot = github_alerts.collect(store, cfg.state_dir, failing)
    lines = github_alerts.digest_lines(snapshot)
    assert [label for label, _ in lines].count("Not checked") == 2


# Spec coverage: security-monitoring.github-alerts.every-alert-listed
# contract-test: infrastructure
def test_invalid_verdict_file_fails_loudly(cfg, store):
    (cfg.state_dir / github_alerts.VERDICTS_FILE).write_text(json.dumps({"7": {"verdict": "maybe"}}))
    with pytest.raises(ValueError):
        github_alerts.collect(store, cfg.state_dir, _fetch([], [SECRET]))
