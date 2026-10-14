"""Safety and capture assertions for the real isolated newsletter E2E probe."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.scripts import probe_newsletter_delivery as probe
from backend.shared.python_utils.openmates_event_registry import load_openmates_events


@pytest.mark.parametrize(
    "missing",
    [
        "CI",
        "OPENMATES_CI_ISOLATED",
        "OPENMATES_CI_MAIL_CAPTURE",
        "CMS_URL",
        "SERVER_ENVIRONMENT",
    ],
)
# contract-test: supporting surface=rest_api assertions=newsletter.lifecycle.double-opt-in,newsletter.campaign.eligible-idempotent-delivery
def test_probe_fails_before_reading_account_or_opening_transport(monkeypatch, missing):
    for name, value in {
        "CI": "true",
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055",
        "SERVER_ENVIRONMENT": "development",
        "PROBE_EMAIL": "ci-newsletter@example.com",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    attempts = []
    monkeypatch.setattr(probe, "_admin", lambda: attempts.append(True))
    with pytest.raises(RuntimeError, match="isolated CI"):
        asyncio.run(probe.main())
    assert not attempts


# contract-test: supporting surface=rest_api assertions=newsletter.lifecycle.double-opt-in,newsletter.campaign.eligible-idempotent-delivery
def test_probe_requires_dedicated_disposable_recipient(monkeypatch):
    for name, value in {
        "CI": "true",
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055",
        "SERVER_ENVIRONMENT": "development",
        "PROBE_EMAIL": "ordinary@gmail.com",
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="example.com"):
        probe._require_isolation()


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout
def test_fixture_reuses_public_registry_copy_and_authored_assets_at_current_dates():
    registry = load_openmates_events(
        Path(__file__).resolve().parents[2] / "shared/events/openmates_events.yml"
    )
    run_at = datetime(2030, 1, 4, 9, 0, tzinfo=timezone.utc)
    manifest = probe._fixture_manifest(registry, run_at)
    assert len(manifest["_events"]) == 2
    assert all(
        datetime.fromisoformat(event["starts_at"]) > run_at
        for event in manifest["_events"]
    )
    for event in manifest["_events"]:
        original = next(
            item for item in registry["events"] if item["id"] == event["id"]
        )
        assert event["localized_content"] == original["localized_content"]
        assert event["assets"] == original["assets"]
        assert event["starts_at"] != original["starts_at"]
    assert manifest["campaign_assets"] == registry["campaign"]["assets"]


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout
def test_registry_fixture_reads_verified_source_mount_without_image_copy(monkeypatch, tmp_path):
    import yaml

    for name, value in {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development",
        "PROBE_EMAIL": "ci-registry@example.com",
    }.items():
        monkeypatch.setenv(name, value)
    registry = load_openmates_events(
        Path(__file__).resolve().parents[2] / "shared/events/openmates_events.yml"
    )
    registry["events"][0]["localized_content"]["en"]["title"] = "Candidate source fixture"
    candidate_registry = tmp_path / "shared/events/openmates_events.yml"
    candidate_registry.parent.mkdir(parents=True)
    candidate_registry.write_text(yaml.safe_dump(registry))
    assert probe.CI_REGISTRY_PATH == Path("/shared/events/openmates_events.yml")
    monkeypatch.setattr(probe, "CI_REGISTRY_PATH", candidate_registry)
    assert probe._load_registry_fixture()["events"][0]["localized_content"]["en"]["title"] == "Candidate source fixture"
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE")
    with pytest.raises(RuntimeError, match="isolated CI"):
        probe._load_registry_fixture()


def _capture():
    hosted = "https://landing.dev.openmates.org/newsletter-assets/known.jpg"
    url = "https://api.dev.openmates.org/v1/newsletter/unsubscribe/one-click/synthetic-token-000000001"
    return {
        "message": {
            "HTML": f'<img src="{hosted}"><p>Öffentliche Events</p>',
            "Text": "Öffentliche Events",
        },
        "headers": {
            "List-Unsubscribe": [f"<{url}>"],
            "List-Unsubscribe-Post": ["List-Unsubscribe=One-Click"],
            "X-OpenMates-Email-Type": ["newsletter"],
        },
        "expected_images": [hosted],
        "expected_copy": ["Öffentliche Events"],
        "one_click_url": url,
    }


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout,newsletter.lifecycle.unsubscribe-resubscribe
def test_capture_assertions_preserve_localized_text_and_persistent_header():
    payload = _capture()
    receipt = probe._validate_capture(**payload)
    assert receipt["hosted_images"] == 1
    assert receipt["html_bytes"] == len(payload["message"]["HTML"].encode("utf-8"))


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout
@pytest.mark.parametrize("markup,expected", [
    ('<p>Join the monthly <a><mark>Open</mark><span>Mates</span></a> video call.</p>', 'Join the monthly OpenMates video call.'),
    ('<p><mark>Open</mark><span>Mates</span> Monthly Community Hour</p>', 'OpenMates Monthly Community Hour'),
    ('<p><b>One</b> <i>two</i>.</p>', 'One two.'),
    ('<p>Übersicht <strong>für</strong>\n alle</p>', 'Übersicht für alle'),
    ('<head><style>Hidden styles</style></head><p>First<br>line</p>\n <div> Second <b>paragraph</b>.</div>', 'First\nline\nSecond paragraph.'),
])
def test_plain_text_preserves_inline_spaces_and_block_boundaries(markup, expected):
    from backend.core.api.app.services.email_template import html_to_plain_text

    assert html_to_plain_text(markup) == expected


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout,newsletter.lifecycle.unsubscribe-resubscribe
@pytest.mark.parametrize("language", ["en", "de"])
def test_real_render_capture_preserves_complete_localized_titles_and_summaries(language):
    from backend.core.api.app.services.email_template import EmailTemplateService, html_to_plain_text
    from backend.scripts import send_newsletter
    from backend.shared.python_utils.newsletter_assets import newsletter_image_url

    registry = load_openmates_events(Path(__file__).resolve().parents[2] / "shared/events/openmates_events.yml")
    manifest = probe._fixture_manifest(registry, datetime(2030, 1, 4, 9, 0, tzinfo=timezone.utc))
    context = send_newsletter.build_context(manifest, language, "", probe.BASE_URL, None, False)
    rendered = EmailTemplateService(object()).render_template("newsletter", context, language)
    payload = _capture()
    payload["message"] = {"HTML": rendered, "Text": html_to_plain_text(rendered)}
    header = manifest["campaign_assets"]["header"][language]
    sources = [header["path"], header["mobile_path"]] + [event["assets"]["card"][language]["path"] for event in manifest["_events"]]
    payload["expected_images"] = [newsletter_image_url(source, probe.BASE_URL) for source in sources]
    payload["expected_copy"] = [
        event["localized_content"][language][field]
        for event in manifest["_events"]
        for field in ("title", "summary")
    ]
    receipt = probe._validate_capture(**payload)
    assert receipt["hosted_images"] == len(sources)
    assert receipt["html_bytes"] <= probe.HTML_MAX_BYTES


@pytest.mark.parametrize(
    "defect",
    [
        "oversize",
        "inline_image",
        "missing_asset",
        "plain_text",
        "header_token",
        "header_type",
    ],
)
# contract-test: supporting surface=rest_api assertions=newsletter.campaign.accessible-event-layout,newsletter.lifecycle.unsubscribe-resubscribe
def test_capture_rejects_material_newsletter_regressions(defect):
    payload = _capture()
    if defect == "oversize":
        payload["message"]["HTML"] += "ü" * (probe.HTML_MAX_BYTES // 2)
    elif defect == "inline_image":
        payload["message"]["HTML"] += (
            '<img src="data:image/png;base64,' + "A" * 5000 + '">'
        )
    elif defect == "missing_asset":
        payload["message"]["HTML"] = "<p>Öffentliche Events</p>"
    elif defect == "plain_text":
        payload["message"]["Text"] = ""
    elif defect == "header_token":
        payload["headers"]["List-Unsubscribe"] = [
            "<https://example.org/temporary-token>"
        ]
    elif defect == "header_type":
        payload["headers"]["X-OpenMates-Email-Type"] = ["newsletter-confirmed"]
    with pytest.raises(AssertionError):
        probe._validate_capture(**payload)
