"""Events newsletter rendering contract tests.

These tests prove the OpenMates events campaign uses the shared YAML registry,
renders accessible text and event links, embeds optimized email-safe images, and
passes through the existing newsletter template context instead of introducing a
parallel email delivery stack.
"""

from __future__ import annotations

from base64 import b64decode
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend.core.api.app.services.email.html_processor import process_brand_name
from backend.shared.python_utils.events_newsletter_generator import (
    build_events_email_html,
    build_events_preview_manifest,
    select_events_for_newsletter,
)
from backend.shared.python_utils.openmates_event_registry import load_openmates_events
from backend.scripts import send_newsletter

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_AT = datetime.fromisoformat("2026-08-20T12:00:00+02:00")
BASE_URL = "https://app.dev.openmates.org"


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout,newsletter.campaign.event-link-fallback
def test_events_newsletter_html_contains_all_registry_events_without_local_paths() -> None:
    registry = load_openmates_events()
    selected_events = select_events_for_newsletter(registry["events"], RUN_AT)

    html = build_events_email_html(selected_events, "en", base_url=BASE_URL)

    assert html.count("data:image/jpeg;base64,") == len(selected_events)
    assert "shared/events/assets" not in html
    assert "Our first ever online meetup" in html
    assert "free webinars" in html
    assert "Hope to see you at the upcoming events" in html
    assert "newsletter sent every 2 weeks" not in html
    assert "Upcoming events" in html
    assert "max-width:520px;width:100%" in html
    assert "font-size:16px" in html
    assert "font-size:18px" in html
    assert "border-bottom" not in html
    assert "background-color:#ff553b" not in html
    for event in selected_events:
        content = event["localized_content"]["en"]
        assert content["title"] in html
        assert content["summary"] in html
        assert f"{BASE_URL}/#embed-id={event['id']}" in html
        assert f"{BASE_URL}/events/{event['slug']}" not in html
        assert event["luma_url"] in html


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_events_newsletter_context_uses_existing_newsletter_template(monkeypatch) -> None:
    monkeypatch.setattr(send_newsletter, "REPO_ROOT", REPO_ROOT)
    manifest = build_events_preview_manifest(load_openmates_events(), RUN_AT)

    english_context = send_newsletter.build_context(
        manifest,
        "en",
        "",
        BASE_URL,
        f"{BASE_URL}/#settings/newsletter/unsubscribe/PREVIEW-TOKEN",
        darkmode=False,
        is_registered=True,
    )

    context = send_newsletter.build_context(
        manifest,
        "de",
        "",
        BASE_URL,
        f"{BASE_URL}/#settings/newsletter/unsubscribe/PREVIEW-TOKEN",
        darkmode=False,
        is_registered=True,
    )

    assert context["newsletter_header_image_src"].startswith("data:image/png;base64,")
    assert context["newsletter_header_mobile_image_src"].startswith("data:image/png;base64,")
    assert context["newsletter_header_image_alt"] == "Roter OpenMates Events Newsletter Header"
    assert context["newsletter_header_image_width"] == "600px"
    assert context["newsletter_header_mobile_image_width"] == "390px"
    assert context["newsletter_content_padding"] == "0 24px 20px 24px"
    assert context["hide_email_brand_header"] is True
    assert context["is_events_newsletter"] is True
    assert "Kommende OpenMates Events" in context["newsletter_title"]
    assert "Auf Luma anmelden" in context["newsletter_content"]
    assert "kostenlose Webinare" in context["newsletter_content"]
    assert "Wir hoffen, dich bei den kommenden Events zu sehen" in context["newsletter_content"]
    assert "für die nächsten 4 Wochen" not in context["newsletter_content"]
    assert context["cta_url"] is None
    assert context["manage_settings_url"] == f"{BASE_URL}/#settings/newsletter"
    assert english_context["newsletter_header_image_src"] != context["newsletter_header_image_src"]

    image_data = context["newsletter_header_image_src"].split(",", 1)[1]
    with Image.open(BytesIO(b64decode(image_data))) as image:
        assert image.size == (1155, 322)

    mobile_image_data = context["newsletter_header_mobile_image_src"].split(",", 1)[1]
    with Image.open(BytesIO(b64decode(mobile_image_data))) as image:
        assert image.size == (780, 258)


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_brand_name_processor_leaves_html_title_plain() -> None:
    html = "<html><head><title>Upcoming OpenMates events</title></head><body><p>OpenMates</p></body></html>"

    processed = process_brand_name(html)

    assert "<title>Upcoming OpenMates events</title>" in processed
    assert '<body><p><a href="https://openmates.org"' in processed
