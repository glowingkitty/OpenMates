"""Email HTML post-processing tests.

These tests pin behavior for the shared newsletter HTML processor used by
templated email sends. They focus on preserving plain-text head metadata while
still applying OpenMates brand styling to visible body copy.
"""

from __future__ import annotations

from backend.core.api.app.services.email.html_processor import process_brand_name


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_brand_name_processor_leaves_html_title_plain() -> None:
    html = '<html><head><title>Upcoming OpenMates events</title></head><body><p>OpenMates</p></body></html>'

    processed = process_brand_name(html)

    assert "<title>Upcoming OpenMates events</title>" in processed
    assert '<body><p><a href="https://openmates.org"' in processed


# contract-test: direct surface=cli assertions=newsletter.campaign.accessible-event-layout
def test_brand_name_processor_leaves_mjml_title_plain() -> None:
    mjml = '<mjml><mj-head><mj-title>Upcoming OpenMates events</mj-title></mj-head><mj-body><mj-text>OpenMates</mj-text></mj-body></mjml>'

    processed = process_brand_name(mjml)

    assert "<mj-title>Upcoming OpenMates events</mj-title>" in processed
    assert '<mj-text><a href="https://openmates.org"' in processed
