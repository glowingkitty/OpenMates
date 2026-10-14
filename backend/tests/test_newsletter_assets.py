"""Newsletter publication, clipping, and delivery admission regression tests."""

import json
from pathlib import Path
from types import SimpleNamespace
import sys
from types import ModuleType

import pytest
from PIL import Image

from backend.core.api.app.services.email.mjml_processor import embed_images
from backend.shared.python_utils.newsletter_assets import (
    ASSET_MAP_PATH, NEWSLETTER_HTML_MAX_BYTES, newsletter_image_url,
    validate_newsletter_html_size,
)
from backend.scripts import send_newsletter
from scripts.publish_newsletter_assets import STATIC_DIR, publish_sources

REPO_ROOT = Path(__file__).resolve().parents[2]


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_publication_compresses_deduplicates_and_survives_transient_source_removal(tmp_path):
    source_dir = tmp_path / "campaign"
    source_dir.mkdir()
    image = Image.new("RGB", (1600, 800), "red")
    for name in ("header.png", "second.png"):
        image.save(source_dir / name)
    index = publish_sources(["campaign/header.png", "campaign/second.png"], repo_root=tmp_path)
    assert index["assets"]["campaign/header.png"] == index["assets"]["campaign/second.png"]
    asset = index["assets"]["campaign/header.png"]
    with Image.open(tmp_path / STATIC_DIR / asset["filename"]) as compressed:
        assert compressed.format == "JPEG"
        assert compressed.size == (1200, 600)
    (source_dir / "header.png").unlink()
    url = newsletter_image_url("campaign/header.png", "https://openmates.org", repo_root=tmp_path)
    assert url == "https://openmates.org/newsletter-assets/" + asset["filename"]


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
@pytest.mark.parametrize("source", ["../private.png", "/etc/private.png", "http://127.0.0.1/image.png", "https://evil.test/image.png", "data:image/png;base64,AAAA"])
def test_untrusted_image_sources_are_rejected(source):
    with pytest.raises(ValueError):
        newsletter_image_url(source, "https://openmates.org")


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_missing_or_corrupt_publication_blocks_rendering(tmp_path):
    path = tmp_path / ASSET_MAP_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "assets": {}}))
    with pytest.raises(ValueError, match="no published asset"):
        newsletter_image_url("campaign/missing.png", "https://openmates.org", repo_root=tmp_path)
    path.write_text(json.dumps({"schema_version": 1, "assets": {"campaign/missing.png": {"filename": "../private.jpg", "size_bytes": 30}}}))
    with pytest.raises(ValueError, match="invalid public image"):
        newsletter_image_url("campaign/missing.png", "https://openmates.org", repo_root=tmp_path)


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_bundled_index_assets_exist_on_website():
    index = json.loads((REPO_ROOT / ASSET_MAP_PATH).read_text())
    for asset in index["assets"].values():
        path = REPO_ROOT / STATIC_DIR / asset["filename"]
        assert path.stat().st_size == asset["size_bytes"]


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_remote_png_stays_hosted_and_never_enters_local_embedding(tmp_path):
    tag = '<mj-image width="600px" src="https://openmates.org/newsletter-assets/header.png" />'
    assert embed_images(str(tmp_path), tag) == tag


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_size_guard_counts_utf8_bytes_and_keeps_provider_buffer():
    validate_newsletter_html_size("x" * NEWSLETTER_HTML_MAX_BYTES)
    with pytest.raises(ValueError, match="maximum is 81920"):
        validate_newsletter_html_size("x" * (NEWSLETTER_HTML_MAX_BYTES + 1))
    with pytest.raises(ValueError):
        validate_newsletter_html_size("ü" * (NEWSLETTER_HTML_MAX_BYTES // 2 + 1))


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
async def test_real_recipient_without_persistent_token_is_blocked(monkeypatch):
    monkeypatch.setattr(send_newsletter, "load_body_text", lambda *_: "Body")
    assert await send_newsletter.send_one(
        None, None, {"slug": "campaign", "subject": {"en": "Title"}},
        "real-subscriber", "subscriber@example.test", "en", False,
        "https://openmates.org", None, is_registered=True,
    ) is False


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
@pytest.mark.parametrize("registered", [True, False])
def test_one_click_context_uses_persistent_token_for_all_subscribers(registered, monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    manifest = {"slug": "campaign", "kind": "announcements", "subject": {"en": "Title"}, "title": {"en": "Title"}}
    context = send_newsletter.build_context(
        manifest, "en", "Body", "https://app.dev.openmates.org",
        "https://app.dev.openmates.org/#settings/newsletter/unsubscribe/token",
        False, registered, "synthetic-token-0000000001",
    )
    assert context["unsubscribe_one_click_url"] == "https://api.dev.openmates.org/v1/newsletter/unsubscribe/one-click/synthetic-token-0000000001"
    assert bool(context["manage_settings_url"]) == registered
    assert bool(context["unsubscribe_url"]) != registered


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
async def test_explicit_test_to_rejects_unallowlisted_ordinary_mailbox_before_service_work(monkeypatch):
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.setenv("OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST", "")

    def fail_manifest(*_args):
        raise AssertionError("Unapproved test delivery must stop before loading campaign/services")

    monkeypatch.setattr(send_newsletter, "load_broadcast_manifest", fail_manifest)
    args = SimpleNamespace(events_preview=False, test_to="ordinary.person@gmail.com", dry_run=False, render_to=None)
    assert await send_newsletter.run(args) == 2


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
def test_preview_approval_is_exact_and_ci_capture_uses_no_live_transport(monkeypatch):
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)
    monkeypatch.setenv("OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST", "approved@gmail.com")
    send_newsletter._require_preview_recipient("approved@gmail.com")
    with pytest.raises(ValueError, match="test_recipient_not_allowlisted"):
        send_newsletter._require_preview_recipient("approved+alias@gmail.com")
    monkeypatch.setenv("OPENMATES_CI_MAIL_CAPTURE", "1")
    send_newsletter._require_preview_recipient("captured@example.test")


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
@pytest.mark.parametrize("subscriber_id", ["test:approved@gmail.com", "preview:approved@gmail.com", "events-preview:approved@gmail.com", "real-subscriber"])
async def test_sender_stamps_trusted_preview_audience(subscriber_id, monkeypatch):
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)
    monkeypatch.setenv("OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST", "approved@gmail.com")
    monkeypatch.setattr(send_newsletter, "load_body_text", lambda *_: "Body")
    monkeypatch.setattr(send_newsletter, "render_body_html", lambda *_: "<p>Body</p>")
    captured = {}

    async def capture_delivery(**kwargs):
        captured.update(kwargs)
        return True, "sent"

    module = ModuleType("backend.core.api.app.services.email_delivery_guard")
    module.send_email_once = capture_delivery
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert await send_newsletter.send_one(
        None, None, {"slug": "campaign", "kind": "announcements", "subject": {"en": "Title"}},
        subscriber_id, "approved@gmail.com", "en", False, "https://openmates.org", None,
        unsubscribe_token="synthetic-token-0000000001",
    ) is True
    expected = "user" if subscriber_id == "real-subscriber" else "test"
    assert captured["context"]["_email_audience"] == expected
