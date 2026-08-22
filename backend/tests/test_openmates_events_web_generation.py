"""OpenMates public web event generation tests.

The chat sidebar, event SEO pages, sitemap, and hash-based event embeds consume
frontend static data. This guard keeps that generated web bundle aligned with
the shared event registry that also drives the events newsletter.
"""

from __future__ import annotations

from backend.shared.python_utils.openmates_event_registry import load_openmates_events
from scripts.generate_openmates_events import OUTPUT_TS, STATIC_ASSET_DIR, generate


# contract-test: direct surface=gui.web assertions=newsletter.campaign.accessible-event-layout
def test_web_openmates_events_are_generated_from_shared_registry() -> None:
    before = OUTPUT_TS.read_text(encoding="utf-8")
    generated_paths = generate()
    after = OUTPUT_TS.read_text(encoding="utf-8")

    assert after == before
    assert OUTPUT_TS in generated_paths

    registry = load_openmates_events()
    for event in registry["events"]:
        content = event["localized_content"]["en"]
        static_image = STATIC_ASSET_DIR / f"{event['slug']}.jpg"
        assert event["slug"] in after
        assert content["title"] in after
        assert f"/event-assets/openmates/{event['slug']}.jpg" in after
        assert static_image.exists()
