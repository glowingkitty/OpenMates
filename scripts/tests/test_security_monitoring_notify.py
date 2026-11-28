"""Contracts for deterministic security notifications, the content boundary and the digest.

Email and Task creation are captured in memory (no Discord security channel, owner decision 21 Nov). Addresses are RFC 5737
/ RFC 3849 documentation values; tokens are synthetic placeholders.
"""

# contract-test-file: infrastructure
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import security_monitoring_fakes as fx  # noqa: E402 - tests dir added above

from security_monitoring import health, notify  # noqa: E402
from security_monitoring.state import Store  # noqa: E402

SYNTHETIC_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


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


def _advisory(store: Store, outcome: str, **details):
    incident_id, _ = store.open_incident("advisory", f"advisory:x:{outcome}", outcome, {
        "advisory_ids": ["CVE-2026-31337"], "assets": [{"name": "linux-image", "version": "6.8.0-100", "environments": ["dev", "prod"]}],
        "environments": ["dev", "prod"], "outcome": outcome, "evidence_summary": "running kernel older than installed kernel",
        "reachability": "local", "exploitability": "local privilege escalation", "blast_radius": "host root",
        "host_roles": ["dev", "core (prod)"], "manual_actions": [], "automatic_actions": {"summary": "no automatic fix possible"}, **details,
    }, fx.NOW)
    return store.incident(incident_id)


# Monitoring coverage: security-monitoring.notifications.deterministic-dual-channel
# contract-test: infrastructure
def test_urgent_kernel_verdict_sends_its_own_email_once(cfg, store):
    channels = fx.Channels()
    sender = fx.notifier(cfg, store, channels)
    incident = _advisory(store, "urgent")
    assert sender.notify(incident, fx.NOW) == {"email": "sent"}
    assert sender.notify(incident, fx.NOW + timedelta(hours=1)) == {"email": "already_sent"}
    assert len(channels.email) == 1
    text = channels.email[0]["text"]
    for expected in ("CVE-2026-31337", "dev, prod", "URGENT", "running kernel older", "no automatic fix possible",
                     "Patch and reboot the dev server", "Patch and reboot the core (prod) server"):
        assert expected in text
    assert "https://nvd.nist.gov/vuln/detail/CVE-2026-31337" in text


# Monitoring coverage: security-monitoring.notifications.deterministic-dual-channel
# contract-test: infrastructure
def test_fix_soon_creates_task_without_immediate_email(cfg, store):
    channels = fx.Channels()
    fx.notifier(cfg, store, channels).notify(_advisory(store, "affected_fix_soon"), fx.NOW)
    assert len(channels.tasks) == 1 and channels.email == []


# Monitoring coverage: security-monitoring.notifications.deterministic-dual-channel
# contract-test: infrastructure
@pytest.mark.parametrize("outcome", ["affected_low", "not_affected"])
def test_low_and_not_affected_are_digest_only(cfg, store, outcome):
    channels = fx.Channels()
    assert fx.notifier(cfg, store, channels).notify(_advisory(store, outcome), fx.NOW) == {}
    assert channels.email == [] and channels.tasks == []


# Monitoring coverage: security-monitoring.health.no-silent-failure
# contract-test: infrastructure
def test_non_urgent_health_waits_for_daily_email_and_never_uses_discord(cfg, store):
    channels = fx.Channels()
    world = fx.World(stale=["preview"])
    fx.run(cfg, world, store, channels)
    assert {row["channel"] for row in store.notifications()} <= {"email", "task"}
    signals = {i["details"]["signal"] for i in store.unresolved_incidents("health")}
    assert "stale_host_report" in signals and "notification_channel_unavailable" not in signals
    assert channels.email == []


# Monitoring coverage: security-monitoring.content.boundary
# contract-test: infrastructure
def test_rendered_messages_contain_no_addresses_hosts_or_secrets(cfg, store):
    hostile = (f"login from 192.0.2.44:2222 and 198.51.100.7/24 via 2001:db8::17 and 2001:0db8:0000:0000:0000:0000:0000:0001 "
               f"host db-1.example.internal ip-192-0-2-9.ec2 static.203.0.113.5.clients.your-server.de "
               f"API_TOKEN={SYNTHETIC_TOKEN} key {SYNTHETIC_TOKEN} see https://evil.example/x and https://osv.dev/vulnerability/GHSA-x "
               f"@everyone -----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----")
    incident_id, _ = store.open_incident("intrusion", "intrusion:upload:k:1", "critical", {
        "role": "upload", "signal_kind": "unknown_key_login", "change_id": "deadbeefcafe",
        "safe_detail": f"user=root fingerprint=SHA256:{'Ab1' * 14}x file=/root/.ssh/authorized_keys {hostile}"}, fx.NOW)
    rendered = notify.render_incident(store.incident(incident_id))
    email = rendered.email_payload()
    for output in (email["text"], email["html"]):
        for leaked in ("192.0.2.", "198.51.100.", "203.0.113.", "2001:db8", "2001:0db8", "example.internal", "your-server.de",
                       SYNTHETIC_TOKEN, "evil.example", "PRIVATE KEY", "@everyone"):
            assert leaked not in output
        assert "SHA256:" in output and "upload" in output
        assert "authorized_keys" in output.replace("\\_", "_")
    assert "https://osv.dev/vulnerability/GHSA-x" in email["text"]


# Monitoring coverage: security-monitoring.content.boundary
# contract-test: infrastructure
def test_boundary_keeps_versions_commits_and_advisory_ids():
    text = notify.bounded("kernel 6.8.0-137-generic commit 0123456789abcdef0123456789abcdef01234567 CVE-2026-1234 zod 4.6.6 10:00:00Z")
    assert "6.8.0-137-generic" in text and "0123456789abcdef0123456789abcdef01234567" in text
    assert "CVE-2026-1234" in text and "4.6.6" in text and "10:00:00Z" in text
    assert len(notify.bounded("x" * 5000, 100)) == 100


# Monitoring coverage: security-monitoring.content.boundary
# contract-test: infrastructure
def test_links_are_built_only_for_allowlisted_origins():
    assert notify.advisory_link("GHSA-2222-3333-4444") == "https://github.com/advisories/GHSA-2222-3333-4444"
    assert notify.advisory_link("USN-7000-1") == "https://ubuntu.com/security/notices/USN-7000-1"
    assert notify.advisory_link("javascript:alert(1)") is None
    assert notify.allowlisted_link("https://www.cisa.gov/known-exploited-vulnerabilities-catalog")
    assert not notify.allowlisted_link("https://osv.dev.evil.example/")


# Monitoring coverage: security-monitoring.ssh.vulnerability-and-intrusion
# contract-test: infrastructure
def test_intrusion_signal_alerts_immediately_once_without_triage(cfg, store):
    world = fx.World(reports={"upload": object()}, signals=[{"role": "upload", "kind": "unknown_key_login",
                     "change_id": "c" * 64, "safe_detail": "user=root fingerprint=SHA256:placeholder from 192.0.2.10"}])
    channels = fx.Channels()
    for hour in range(3):
        fx.run(cfg, world, store, channels, now=fx.NOW + timedelta(hours=hour))
    assert world.triage_calls == []
    assert len(channels.email) == 1
    assert "192.0.2.10" not in channels.email[0]["text"] and "upload" in channels.email[0]["subject"]


# Monitoring coverage: security-monitoring.health.no-silent-failure, security-monitoring.apple-packages.daily-report
# contract-test: infrastructure
def test_daily_digest_confirms_runs_coverage_and_carried_incidents(cfg, store):
    world = fx.World(observations=[fx.observation(disposition="suppressed_not_used", suppression_reason="not used: no Drupal or PHP")],
                     statuses=[{"name": "osv", "ok": True, "error_code": None, "item_count": 3},
                               {"name": "cisa_kev", "ok": False, "error_code": "timeout", "item_count": 0}])
    channels = fx.Channels()
    for hour in range(3):
        fx.run(cfg, world, store, channels, now=fx.NOW + timedelta(hours=hour))
    sender = fx.notifier(cfg, store, channels)
    apple_packages = [("Update available", "github.com/example/swift-sodium 0.9.1 → 0.10.0")]
    result = health.run_digest(cfg, store, sender, now=fx.NOW + timedelta(hours=3), sender=channels.email_sender,
                               apple_packages=apple_packages)
    assert result["digest"] == "accepted"
    text = channels.email[-1]["text"]
    assert "Update available: github.com/example/swift-sodium 0.9.1 → 0.10.0" in text
    assert "3/24" in text and "Sources failed: cisa_kev" in text
    assert "not used: no Drupal or PHP: 1" in text
    assert text.index("NEW since last email") < text.index("STILL OPEN") < text.index("Watcher runs")
    assert "New: [high] source_failed" in text
    sent = len(channels.email)
    again = health.run_digest(cfg, store, sender, now=fx.NOW + timedelta(hours=3), sender=channels.email_sender,
                              apple_packages=apple_packages)
    assert again["digest"] == "accepted" and len(channels.email) == sent  # same daily id: never sent twice


# Monitoring coverage: security-monitoring.health.no-silent-failure
# contract-test: infrastructure
def test_digest_job_alerts_when_watcher_stopped(cfg, store):
    channels = fx.Channels()
    fx.run(cfg, fx.World(), store, channels)
    result = health.run_digest(cfg, store, fx.notifier(cfg, store, channels), now=fx.NOW + timedelta(hours=3), sender=channels.email_sender)
    assert result["watcher_alert"] == {"email": "sent"}
