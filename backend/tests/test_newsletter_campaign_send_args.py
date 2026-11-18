"""Admin campaign preview and send pass complete send_newsletter arguments.

A hand-built argparse.Namespace in the campaign service lacked --events-preview
and --run-at, so every admin preview and broadcast crashed with AttributeError
before any email was sent (TASK-427). The service now starts from the parser's
own defaults; this test fails if run() ever reads an option the service omits.
"""

from __future__ import annotations

import contextlib
import inspect
import re

import pytest

from backend.core.api.app.services import newsletter_campaign_service as service_module
from backend.scripts import send_newsletter

CAMPAIGN = {
    "id": "campaign-1",
    "slug": "email-delivery-check",
    "status": "draft",
    "approved_at": "2026-11-15T00:00:00Z",
    "mode": "email_only",
    "body_markdown": {"en": "Hello"},
}


class _FakeDirectus:
    async def update_item(self, collection, item_id, data, admin_required=False):
        return {**CAMPAIGN, **data}


def _attributes_read_by_sender() -> set[str]:
    source = inspect.getsource(send_newsletter)
    return set(re.findall(r"\bargs\.([a-z_]+)\b", source))


@pytest.fixture
def captured(monkeypatch):
    calls = []

    async def fake_run(args):
        calls.append(args)
        return 0

    service = service_module.NewsletterCampaignService(_FakeDirectus())

    async def fake_get(slug):
        return dict(CAMPAIGN)

    monkeypatch.setattr(service, "get_by_slug", fake_get)
    monkeypatch.setattr(service, "_legacy_files", lambda campaign: contextlib.nullcontext())
    monkeypatch.setattr(send_newsletter, "run", fake_run)
    return service, calls


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.campaign.review-window
async def test_preview_passes_every_argument_the_sender_reads(captured):
    service, calls = captured
    result = await service.send_preview("email-delivery-check", "admin@example.org")

    assert result["sent_langs"] == ["en"]
    (args,) = calls
    missing = _attributes_read_by_sender() - set(vars(args))
    assert not missing, f"send_newsletter.run reads options the preview omits: {sorted(missing)}"
    assert args.test_to == "admin@example.org"
    assert args.send is False
    assert args.events_preview is False


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.campaign.eligible-idempotent-delivery,newsletter.campaign.review-window
async def test_send_now_passes_every_argument_the_sender_reads(captured):
    service, calls = captured
    await service.send_campaign_now("email-delivery-check", simulate=True)

    (args,) = calls
    missing = _attributes_read_by_sender() - set(vars(args))
    assert not missing, f"send_newsletter.run reads options the broadcast omits: {sorted(missing)}"
    assert args.send is True
    assert args.resume is True
    assert args.simulate is True
    assert args.non_interactive_approved is True


# contract-test: supporting surface=rest_api assertions=newsletter.campaign.review-window
def test_programmatic_args_rejects_unknown_options():
    with pytest.raises(ValueError, match="no_such_option"):
        send_newsletter.programmatic_args(no_such_option=True)
