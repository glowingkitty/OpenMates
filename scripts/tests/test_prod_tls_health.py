"""Prod TLS certificate validity and expiry check (TASK-5089)."""

# contract-test-file: infrastructure

from __future__ import annotations

import ssl
from datetime import datetime, timedelta, timezone

from scripts import prod_tls_health as tls

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _cert(days_left: float) -> dict:
    return {"notAfter": (NOW + timedelta(days=days_left)).strftime("%b %d %H:%M:%S %Y GMT")}


def _resolve(addresses):
    return lambda host: list(addresses)


def test_fresh_certificate_on_every_edge_passes():
    result = tls.check_host("www.example.org", NOW, _resolve(["192.0.2.1", "192.0.2.2"]), lambda h, a: _cert(80))
    assert result["ok"] is True
    assert [r["address"] for r in result["addresses"]] == ["192.0.2.1", "192.0.2.2"]


def test_certificate_inside_renewal_window_fails_before_it_expires():
    result = tls.check_host("www.example.org", NOW, _resolve(["192.0.2.1"]), lambda h, a: _cert(tls.MIN_DAYS_LEFT - 1))
    assert result["ok"] is False
    assert "renewal looks stuck" in result["reason"]


def test_expired_certificate_on_one_stale_edge_fails_the_host():
    """The Feb 2026 www incident: some Vercel edges kept serving an expired certificate."""

    def fetch(host, address):
        if address == "192.0.2.2":
            err = ssl.SSLCertVerificationError("certificate verify failed")
            err.verify_message = "certificate has expired"
            raise err
        return _cert(80)

    result = tls.check_host("www.example.org", NOW, _resolve(["192.0.2.1", "192.0.2.2"]), fetch)
    assert result["ok"] is False
    assert "192.0.2.2" in result["reason"] and "certificate has expired" in result["reason"]
    assert "192.0.2.1" not in result["reason"]


def test_unreachable_and_unresolvable_hosts_fail():
    def refuse(host, address):
        raise ConnectionRefusedError

    def no_dns(host):
        raise OSError("nodename nor servname provided")

    assert tls.check_host("a.example.org", NOW, _resolve(["192.0.2.1"]), refuse)["ok"] is False
    assert tls.check_host("a.example.org", NOW, no_dns, refuse)["ok"] is False
    assert tls.check_host("a.example.org", NOW, _resolve([]), refuse)["ok"] is False


def test_evaluate_covers_all_public_prod_hosts():
    result = tls.evaluate(NOW, _resolve(["192.0.2.1"]), lambda h, a: _cert(60))
    assert result["ok"] is True
    assert set(result["checks"]) == {"openmates.org", "www.openmates.org", "app.openmates.org", "api.openmates.org"}


def test_alert_on_change_repeat_after_six_hours_and_recover_once():
    failing = {"ok": False, "checks": {"x": {"ok": False, "reason": "x: expired"}}}
    passing = {"ok": True, "checks": {}}
    assert tls.alert_decision(failing, {}, 1000.0) == "failure"
    assert tls.alert_decision(failing, {"ok": False, "last_alert_ts": 1000.0}, 1000.0 + 3600) is None
    assert tls.alert_decision(failing, {"ok": False, "last_alert_ts": 1000.0}, 1000.0 + 6 * 3600) == "failure"
    assert tls.alert_decision(passing, {"ok": False}, 0.0) == "recovery"
    assert tls.alert_decision(passing, {"ok": True}, 0.0) is None
    assert "x: expired" in tls.format_message(failing, "failure")


def test_dry_run_neither_posts_nor_saves_state(monkeypatch, tmp_path):
    monkeypatch.setattr(tls, "evaluate", lambda now: {"ok": False, "checked_at": NOW.isoformat(),
                                                      "checks": {"x": {"ok": False, "reason": "x"}}})
    monkeypatch.setattr(tls, "post_discord", lambda *a, **k: (_ for _ in ()).throw(AssertionError("posted")))
    state = tmp_path / "state.json"
    assert tls.run(dry_run=True, state_path=state) == 1
    assert not state.exists()
