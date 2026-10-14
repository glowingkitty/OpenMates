"""Events newsletter rendering contract tests.

These tests prove the OpenMates events campaign uses the shared YAML registry,
renders accessible text and event links, references optimized hosted images, and
passes through the existing newsletter template context instead of introducing a
parallel email delivery stack.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image
from lxml import html as lxml_html

from backend.core.api.app.services.email.html_processor import process_brand_name
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.shared.python_utils.newsletter_assets import NEWSLETTER_HTML_MAX_BYTES
from backend.shared.python_utils.events_newsletter_generator import (
    build_events_email_html,
    build_events_preview_manifest,
    select_events_for_newsletter,
)
from backend.shared.python_utils.openmates_event_registry import load_openmates_events
from backend.scripts import send_newsletter

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_AT = datetime.fromisoformat("2026-09-16T12:00:00+02:00")
BASE_URL = "https://app.dev.openmates.org"


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout,newsletter.campaign.event-link-fallback
def test_events_newsletter_html_contains_all_registry_events_without_local_paths() -> None:
    registry = load_openmates_events()
    selected_events = select_events_for_newsletter(registry["events"], RUN_AT)

    html = build_events_email_html(selected_events, "en", base_url=BASE_URL)

    assert html.count("https://landing.dev.openmates.org/newsletter-assets/") == len(selected_events)
    assert "data:image" not in html
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

    assert context["newsletter_header_image_src"].startswith("https://landing.dev.openmates.org/newsletter-assets/")
    assert context["newsletter_header_mobile_image_src"].startswith("https://landing.dev.openmates.org/newsletter-assets/")
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

    public_dir = REPO_ROOT / "frontend/apps/website/static/newsletter-assets"
    with Image.open(public_dir / context["newsletter_header_image_src"].rsplit("/", 1)[1]) as image:
        assert image.size == (1155, 322)

    with Image.open(public_dir / context["newsletter_header_mobile_image_src"].rsplit("/", 1)[1]) as image:
        assert image.size == (780, 258)


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_brand_name_processor_leaves_html_title_plain() -> None:
    html = "<html><head><title>Upcoming OpenMates events</title></head><body><p>OpenMates</p></body></html>"

    processed = process_brand_name(html)

    assert "<title>Upcoming OpenMates events</title>" in processed
    assert '<body><p><a href="https://openmates.org"' in processed


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_full_localized_campaigns_remain_below_clipping_budget() -> None:
    manifest = build_events_preview_manifest(load_openmates_events(), RUN_AT)
    service = EmailTemplateService(object())
    for language in ("en", "de"):
        context = send_newsletter.build_context(
            manifest, language, "", BASE_URL, None, False, True,
        )
        rendered = service.render_template("newsletter", context, language)
        assert len(rendered.encode("utf-8")) < NEWSLETTER_HTML_MAX_BYTES
        # The shared footer may still embed its tiny generic brand logo.
        document = lxml_html.fromstring(rendered)
        embedded_images = document.xpath('//img[starts-with(@src, "data:image")]/@src')
        assert all(len(source) < 8192 for source in embedded_images)
        assert context["newsletter_header_image_src"] in rendered
        assert context["newsletter_header_mobile_image_src"] in rendered
        visible_text = document.text_content()
        for event in manifest["_events"]:
            assert event["localized_content"][language]["title"] in visible_text
            assert event["assets"]["card"][language]["alt"] in rendered
