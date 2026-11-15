"""Public page data, probes, Gatus parsing, notifications and config of the status server.

Covers deployment/status_server (agent package and Gatus config) without network access.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deployment/status_server/agent"))

from status_agent import catalog, gatus, integrations, notify, page_data, probes  # noqa: E402 - path set up above
from status_agent.alerts import CheckResult, Notification, OpenAlert  # noqa: E402 - path set up above

NOW = 1_700_000_000.0
PAGE = "external-status-monitoring.page.public-safe"
CONFIRM = "external-status-monitoring.alerts.confirmed-failures"
ESCALATE = "external-status-monitoring.alerts.escalation"


def _gatus_key(endpoint: dict, default_group: str = "") -> str:
    group = endpoint.get("group", default_group)
    raw = f"{group}_{endpoint['name']}"
    return "".join("-" if ch in " ./,#+&" else ch for ch in raw.lower())


def _ai_chat() -> catalog.Component:
    return next(c for c in catalog.COMPONENTS if c.id == "ai_chat")


# contract-test: direct surface=tooling assertions=external-status-monitoring.page.public-safe
def test_component_is_outage_only_when_every_check_is_down() -> None:
    component = _ai_chat()
    latest = {c.key: CheckResult(NOW, True) for c in component.checks}
    alerts = {component.checks[0].key: OpenAlert(NOW - 300, NOW - 240)}
    assert page_data.component_status(component, latest, {}) == "operational"
    assert page_data.component_status(component, latest, alerts) == "degraded"
    every = {c.key: OpenAlert(NOW - 300, NOW - 240) for c in component.checks}
    assert page_data.component_status(component, latest, every) == "outage"
    assert page_data.component_status(component, {}, {}) == "unknown"


# contract-test: direct surface=tooling assertions=external-status-monitoring.page.public-safe
def test_public_document_carries_no_internal_details() -> None:
    component = _ai_chat()
    alerts = {c.key: OpenAlert(NOW - 600, NOW - 540) for c in component.checks}
    history = page_data.History()
    history.add(component.checks[0].key, [CheckResult(NOW - 120, False), CheckResult(NOW - 60, True)])
    incidents = page_data.update_incidents([], alerts, NOW)
    document = page_data.build({}, alerts, history, incidents, NOW)
    text = json.dumps(document)
    assert document["overall"] == "outage"
    # The AI-worker check is shared, so Voice is affected too.
    assert sorted(i["component"] for i in document["incidents"]) == ["ai_chat", "voice"]
    for check in catalog.all_checks():
        assert check.key not in text
    for leak in ("api.openmates.org", "token", "Bearer", "http_", "localhost", "gatus"):
        assert leak not in text
    assert len(document["components"][0]["days"]) == page_data.HISTORY_DAYS
    # "All systems operational" only when every component has data and is up.
    partial = {c.key: CheckResult(NOW, True) for c in catalog.all_checks() if not c.key.startswith("synthetic_")}
    assert page_data.build(partial, {}, history, [], NOW)["overall"] == "unknown"
    every = {c.key: CheckResult(NOW, True) for c in catalog.all_checks()}
    assert page_data.build(every, {}, history, [], NOW)["overall"] == "operational"


# contract-test: direct surface=tooling assertions=external-status-monitoring.page.public-safe
def test_incident_resolves_when_component_recovers_and_history_dedups() -> None:
    component = _ai_chat()
    only_ai_chat = next(c.key for c in component.checks if c.key.startswith("synthetic_"))
    alerts = {only_ai_chat: OpenAlert(NOW - 600, NOW - 540)}
    incidents = page_data.update_incidents([], alerts, NOW)
    incidents = page_data.update_incidents(incidents, alerts, NOW + 60)
    assert len(incidents) == 1 and incidents[0].resolved_at is None
    incidents = page_data.update_incidents(incidents, {}, NOW + 120)
    assert incidents[0].resolved_at == NOW + 120
    history = page_data.History()
    results = [CheckResult(NOW - 60, True), CheckResult(NOW, False)]
    history.add("k", results)
    history.add("k", results)
    restored = page_data.History.from_json(json.loads(json.dumps(history.to_json())))
    counts = restored.days["k"][page_data.day_of(NOW)]
    assert (counts.total, counts.ok) == (2, 1)


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_gatus_statuses_parse_nanosecond_timestamps_oldest_first() -> None:
    payload = [{"key": "openmates_api", "results": [
        {"timestamp": "2026-11-14T10:01:00.123456789Z", "success": False},
        {"timestamp": "2026-11-14T10:00:00Z", "success": True}]}]
    parsed = gatus.parse_statuses(payload)["openmates_api"]
    assert [r.success for r in parsed] == [True, False]
    assert parsed[1].timestamp - parsed[0].timestamp == pytest.approx(60.123456, abs=1e-6)


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_every_catalog_check_exists_in_gatus_config() -> None:
    config = yaml.safe_load((ROOT / "deployment/status_server/gatus/config.yaml").read_text(encoding="utf-8"))
    keys = {_gatus_key(e) for e in config.get("endpoints", [])}
    keys |= {_gatus_key(e) for e in config.get("external-endpoints", [])}
    missing = [c.key for c in catalog.all_checks() if c.key not in keys]
    assert missing == []
    external = {_gatus_key(e) for e in config.get("external-endpoints", [])}
    assert external == set(catalog.EXTERNAL_KEYS)
    assert "alerting" not in config


def _response(status: int, body: object) -> probes.HttpResponse:
    return probes.HttpResponse(status, json.dumps(body).encode())


# contract-test: direct surface=tooling assertions=external-status-monitoring.probes.no-billing
def test_anonymous_probe_sends_monitor_token_and_cheapest_model() -> None:
    sent: list[tuple[str, dict, dict]] = []

    def post(url: str, payload: dict, headers: dict, timeout: float) -> probes.HttpResponse:
        sent.append((url, payload, headers))
        return _response(200, {"status": "completed", "assistant": "pong"})

    result = probes.chat_without_account("https://api.example.org", "probe-token", post)
    assert result.success and result.error == ""
    url, payload, headers = sent[0]
    assert url.endswith("/v1/anonymous/chat/stream")
    assert headers == {probes.MONITOR_HEADER: "probe-token"}
    assert payload["plaintext_message"].startswith(probes.MODEL_MENTION)


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_probe_failures_reduce_to_public_error_classes() -> None:
    def status(code: int, body: object):
        return lambda *_: _response(code, body)

    assert probes.chat_without_account("u", "t", status(503, {})).error == "http_503"
    assert probes.chat_without_account("u", "t", status(200, {"status": "failed"})).error == "not_completed"
    assert probes.chat_with_account("u", "k", status(200, {"choices": []})).error == "empty_answer"
    ok = {"choices": [{"message": {"content": "pong"}}]}
    assert probes.chat_with_account("u", "k", status(200, ok)).success
    placeholder = {"choices": [{"message": {"content": probes.EMPTY_REPLY_PLACEHOLDER + " later."}}]}
    assert probes.chat_with_account("u", "k", status(200, placeholder)).error == "empty_answer"
    search = {"choices": [{"message": {"content": "Headline.", "embeds": [
        {"type": "app_skill_use", "metadata": {"app_id": "web", "skill_id": "search"}}]}}]}
    assert probes.skill_web_search("u", "k", status(200, search)).success
    assert probes.skill_web_search("u", "k", status(200, ok)).error == "skill_not_used"

    def broken(*_: object) -> probes.HttpResponse:
        raise TimeoutError

    assert probes.chat_with_account("u", "k", broken).error == "timeout"


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_google_cloud_feed_fails_only_on_open_high_ai_incident() -> None:
    gemini = {"severity": "high", "end": None, "affected_products": [{"title": "Vertex Gemini API"}]}
    assert probes.google_cloud_ai_incident_open([gemini])
    assert not probes.google_cloud_ai_incident_open([dict(gemini, end="2026-11-01T00:00:00Z")])
    assert not probes.google_cloud_ai_incident_open([dict(gemini, severity="low")])
    assert not probes.google_cloud_ai_incident_open([dict(gemini, affected_products=[{"title": "BigQuery"}])])


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.confirmed-failures
def test_integration_items_skip_unconfigured_and_track_health() -> None:
    payload = {"providers": {"stripe": {"status": "unhealthy"}, "fal": {"status": "not_configured"}},
               "apps": {"web": {"status": "healthy"}, "maps": {"status": "unhealthy",
                                                              "last_error": "missing_credentials"}}}
    tracker = integrations.IntegrationTracker()
    tracker.record(payload, NOW)
    snapshots = {s.key: s for s in tracker.snapshots()}
    assert set(snapshots) == {"integration_providers_stripe", "integration_apps_web"}
    assert snapshots["integration_providers_stripe"].results[-1].success is False


# contract-test: direct surface=tooling assertions=external-status-monitoring.alerts.escalation
def test_notification_batch_groups_checks_into_one_message() -> None:
    channels = notify.Channels("", "", "", "noreply@example.org", "Production", "https://status.example.org")
    batch = [Notification("down", f"k{i}", f"Check {i}", NOW - 300, 300) for i in range(5)]
    subject, body = notify.render(batch, channels)
    assert subject == "[Production] Outage: Check 0, Check 1, Check 2 and 2 more"
    assert body.count("\n") >= 6 and body.endswith("Status page: https://status.example.org")
    resolved = [Notification("resolved", "k0", "Check 0", NOW - 3600, 3600)]
    assert notify.render(resolved, channels)[0].startswith("[Production] Resolved:")
    assert notify.deliver([], channels) == []
    assert notify.deliver(resolved, channels) == ["discord: not configured", "email: not configured"]
