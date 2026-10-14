"""Capture a real newsletter broadcast only in the disposable CI Mailpit stack.

Public registry copy/images supply a deterministic current-dated campaign. The
confirmed subscriber, persistent unsubscribe token, delivery reservation, MJML,
localized text, headers and SMTP transport all use production code paths.
"""

from __future__ import annotations

import asyncio
import copy
import html
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

BASE_URL = "https://app.dev.openmates.org"
HTML_MAX_BYTES = 80 * 1024
CI_REGISTRY_PATH = Path("/shared/events/openmates_events.yml")


def _load_registry_fixture() -> dict:
    """Use the verified candidate source mount, including on cached runtimes."""
    from backend.shared.python_utils.openmates_event_registry import load_openmates_events

    _require_isolation()
    return load_openmates_events(CI_REGISTRY_PATH)


def _require_isolation() -> str:
    required = {
        "CI": "true",
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055",
        "SERVER_ENVIRONMENT": "development",
    }
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError(
            "Newsletter delivery probe requires isolated CI Mailpit stack"
        )
    email = os.getenv("PROBE_EMAIL", "").lower()
    if not re.fullmatch(r"ci-[a-z0-9+._-]+@example\.com", email):
        raise RuntimeError(
            "Newsletter delivery probe requires a fresh CI example.com recipient"
        )
    return email


def _fixture_manifest(registry: dict, run_at: datetime) -> dict:
    from backend.shared.python_utils.events_newsletter_generator import (
        build_events_preview_manifest,
    )

    fixture = copy.deepcopy(registry)
    selected = []
    titles = set()
    # Real public copy and authored assets, with dates moved into this run's
    # window so a long-lived regression never depends on old event dates.
    for event in fixture["events"]:
        title = event["localized_content"]["en"]["title"]
        if event["status"] != "published" or title in titles:
            continue
        titles.add(title)
        starts = run_at + timedelta(days=len(selected) + 1)
        event.update(
            starts_at=starts.isoformat(),
            ends_at=(starts + timedelta(hours=1)).isoformat(),
        )
        selected.append(event)
        if len(selected) == 2:
            break
    if len(selected) != 2:
        raise AssertionError(
            "Registry must supply two distinct authored event fixtures"
        )
    fixture["events"] = selected
    manifest = build_events_preview_manifest(fixture, run_at)
    manifest["slug"] = "ci-newsletter-delivery-" + uuid.uuid4().hex
    manifest["subject"] = {
        lang: f"CI newsletter delivery {manifest['slug']} {lang}"
        for lang in ("en", "de")
    }
    return manifest


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str):
        self.parts.append(data)


def _normalized(value: str) -> str:
    return " ".join(html.unescape(value).split())


def _validate_capture(
    message: dict,
    headers: dict,
    *,
    expected_images: list[str],
    expected_copy: list[str],
    one_click_url: str,
) -> dict:
    body = message.get("HTML") or ""
    text = message.get("Text") or ""
    size = len(body.encode("utf-8"))
    if not body or size > HTML_MAX_BYTES:
        raise AssertionError(
            "Newsletter captured HTML exceeded its 80 KiB budget or was empty"
        )
    inline_images = re.findall(r'data:image/[^\s"\'<>]+', body, re.IGNORECASE)
    if any(len(image) > 4096 for image in inline_images):
        raise AssertionError("Newsletter still contains a large inline image")
    if not all(url in html.unescape(body) for url in expected_images):
        raise AssertionError(
            "Newsletter lost an authored hosted header or event-card URL"
        )
    parser = _VisibleText()
    parser.feed(body)
    visible = _normalized("".join(parser.parts))
    if not text or not all(
        _normalized(copy_text) in visible
        and _normalized(copy_text) in _normalized(text)
        for copy_text in expected_copy
    ):
        raise AssertionError(
            "Newsletter lost localized event copy in HTML or plain text"
        )
    lowered = {
        key.lower(): value if isinstance(value, list) else [value]
        for key, value in headers.items()
    }
    if (
        lowered.get("list-unsubscribe") != [f"<{one_click_url}>"]
        or lowered.get("list-unsubscribe-post") != ["List-Unsubscribe=One-Click"]
        or lowered.get("x-openmates-email-type") != ["newsletter"]
    ):
        raise AssertionError(
            "Newsletter did not advertise the subscriber's persistent one-click route"
        )
    return {"html_bytes": size, "hosted_images": len(expected_images)}


def _admin() -> httpx.Client:
    client = httpx.Client(base_url="http://cms:8055", timeout=20)
    response = client.post(
        "/auth/login",
        json={
            "email": os.environ["DATABASE_ADMIN_EMAIL"],
            "password": os.environ["DATABASE_ADMIN_PASSWORD"],
            "mode": "json",
        },
    )
    response.raise_for_status()
    client.headers["Authorization"] = (
        "Bearer " + response.json()["data"]["access_token"]
    )
    return client


async def _captured(
    mailpit: httpx.Client, *, recipient: str, subject: str
) -> tuple[dict, dict]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        listing = mailpit.get("/api/v1/messages", params={"limit": 100})
        listing.raise_for_status()
        matching = [
            item
            for item in listing.json().get("messages", [])
            if item.get("Subject") == subject
            and any(
                address.get("Address", "").lower() == recipient
                for address in item.get("To", [])
            )
        ]
        if len(matching) > 1:
            raise AssertionError("Newsletter capture was duplicated")
        if matching:
            message_id = matching[0]["ID"]
            message = mailpit.get(f"/api/v1/message/{message_id}")
            headers = mailpit.get(f"/api/v1/message/{message_id}/headers")
            message.raise_for_status()
            headers.raise_for_status()
            return message.json(), headers.json()
        await asyncio.sleep(0.5)
    raise AssertionError("Newsletter did not reach the isolated Mailpit recipient")


async def _probe_feedback(
    admin: httpx.Client, directus, secrets, email: str, cleanup: list[str]
) -> None:
    from backend.core.api.app.services.email_delivery_feedback import (
        COLLECTION,
        classify_event,
        email_recipient_allowed,
        reconcile_events,
        transition,
        update_suppression_if_version,
    )

    digest = hashlib.sha256(email.encode()).hexdigest()
    row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"email-feedback:development:{digest}"))

    def state() -> list[dict]:
        response = admin.get(
            f"/items/{COLLECTION}", params={"filter[id][_eq]": row_id, "limit": 2}
        )
        response.raise_for_status()
        return response.json()["data"]

    if state():
        raise AssertionError(
            "Newsletter feedback probe requires a fresh recipient state"
        )
    prior_health = await directus.health_event.get_last_status(
        "external", "email-delivery-development"
    )
    if prior_health and prior_health["new_status"] != "healthy":
        raise AssertionError(
            "Newsletter feedback probe must not alter an existing operator incident"
        )
    if not await email_recipient_allowed(
        email, secrets_manager=secrets, directus=directus
    ):
        raise AssertionError(
            "Newsletter feedback fixture was unexpectedly suppressed before the probe"
        )
    cleanup.append(row_id)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
        seconds=10
    )
    event = {
        "event": "hardBounce",
        "reason": "552 5.2.2 mailbox full",
        "email": email,
        "date": timestamp.isoformat(),
        "messageId": "ci-newsletter-" + uuid.uuid4().hex,
        "tags": ["environment:development", "email-type:newsletter", "audience:test"],
    }
    result = await reconcile_events(
        directus=directus, events=[event], environment="development"
    )
    blocked = state()
    if (
        result["changed"] != 1
        or len(blocked) != 1
        or blocked[0]["status"] != "temporary"
    ):
        raise AssertionError(
            "Newsletter feedback did not persist temporary mailbox-full suppression"
        )
    if await email_recipient_allowed(email, secrets_manager=secrets, directus=directus):
        raise AssertionError(
            "Newsletter feedback eligibility did not honor persisted suppression"
        )
    replay = await reconcile_events(
        directus=directus, events=[event], environment="development"
    )
    replay_state = state()
    if (
        replay["changed"] != 0
        or len(replay_state) != 1
        or replay_state[0]["version"] != blocked[0]["version"]
        or replay_state[0]["suppressed_until"] != blocked[0]["suppressed_until"]
    ):
        raise AssertionError(
            "Newsletter feedback replay extended or rewrote suppression"
        )
    delivered = {
        **event,
        "event": "delivered",
        "reason": "",
        "date": (timestamp + timedelta(seconds=1)).isoformat(),
    }
    recovery = await reconcile_events(
        directus=directus, events=[delivered], environment="development"
    )
    if recovery["changed"] != 1 or not await email_recipient_allowed(
        email, secrets_manager=secrets, directus=directus
    ):
        raise AssertionError(
            "Newsletter delivered feedback did not restore temporary delivery eligibility"
        )
    if not all(
        metric["environment"] == "development"
        and metric["email_type"] == "newsletter"
        and metric["audience"] == "test"
        for metric in result["metrics"] + recovery["metrics"]
    ):
        raise AssertionError(
            "Newsletter feedback lost environment/type/test metric separation"
        )
    recovered = state()[0]
    stale = transition(
        blocked[0],
        {
            **event,
            "date": (timestamp + timedelta(seconds=2)).isoformat(),
            "messageId": "stale-ci-feedback",
        },
        environment="development",
    )
    if (
        stale is None
        or await update_suppression_if_version(directus, stale, blocked[0]["version"])
        is not None
    ):
        raise AssertionError("Newsletter feedback accepted an obsolete state version")
    unchanged = state()[0]
    if unchanged["version"] != recovered["version"] or unchanged["status"] != "clear":
        raise AssertionError(
            "Obsolete newsletter feedback overwrote delivered eligibility"
        )
    candidates = [
        transition(
            recovered,
            {
                **event,
                "date": (timestamp + timedelta(seconds=offset)).isoformat(),
                "messageId": f"concurrent-ci-feedback-{offset}",
            },
            environment="development",
        )
        for offset in (3, 4)
    ]
    if any(candidate is None for candidate in candidates):
        raise AssertionError("Newsletter feedback concurrency fixtures were invalid")
    # The new atomic CMS endpoint is privileged even though it is internal.
    async with httpx.AsyncClient(base_url="http://cms:8055", timeout=10) as anonymous:
        rejected = await anonymous.post(
            "/email-delivery-feedback/",
            json={
                "id": row_id,
                "expected_version": recovered["version"],
                "data": candidates[0],
            },
        )
    if rejected.status_code not in (401, 403):
        raise AssertionError(
            "Newsletter feedback atomic endpoint accepted an unauthenticated caller"
        )
    writes = await asyncio.gather(
        *(
            update_suppression_if_version(directus, candidate, recovered["version"])
            for candidate in candidates
        )
    )
    if (
        sum(item is not None for item in writes) != 1
        or state()[0]["version"] != recovered["version"] + 1
    ):
        raise AssertionError(
            "Newsletter feedback atomic update permitted multiple concurrent winners"
        )
    final_delivery = {
        **delivered,
        "date": (timestamp + timedelta(seconds=5)).isoformat(),
    }
    await reconcile_events(
        directus=directus, events=[final_delivery], environment="development"
    )
    if not await email_recipient_allowed(
        email, secrets_manager=secrets, directus=directus
    ):
        raise AssertionError(
            "Newsletter feedback did not restore eligibility after concurrent failures"
        )
    # Classification only: a synthetic IP incident must not alter shared health.
    if (
        classify_event(
            {**event, "reason": "554 5.7.1 sending IP blocked using SpamCop"}
        )
        != "sender_rejection"
    ):
        raise AssertionError(
            "Newsletter feedback misclassified sender reputation as recipient invalidity"
        )


async def main() -> None:
    email = _require_isolation()
    # Suppress routine transport/service logs; the receipt exposes counts only.
    logging.basicConfig(level=logging.WARNING)
    from backend.scripts import send_newsletter
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.services.email_delivery_guard import (
        build_delivery_id,
        build_delivery_key,
    )
    from backend.core.api.app.utils.newsletter_utils import (
        hash_email,
        is_subscriber_allowed_for_category,
    )
    from backend.core.api.app.utils.newsletter_unsubscribe import (
        build_newsletter_one_click_url,
    )
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.python_utils.newsletter_assets import newsletter_image_url

    admin = _admin()
    directus = DirectusService()
    secrets = SecretsManager()
    mailpit = httpx.Client(base_url="http://mailpit:8025", timeout=10)
    delivery_ids = []
    suppression_ids = []
    captures = []
    try:
        response = admin.get(
            "/items/newsletter_subscribers",
            params={
                "filter[hashed_email][_eq]": hash_email(email),
                "filter[confirmed_at][_nnull]": "true",
                "fields": "id,confirmed_at,unsubscribe_token,categories,user_registration_status",
                "limit": 2,
            },
        )
        response.raise_for_status()
        rows = response.json()["data"]
        if len(rows) != 1 or not rows[0].get("unsubscribe_token"):
            raise AssertionError(
                "Newsletter probe needs one confirmed isolated subscriber with a persistent token"
            )
        subscriber = rows[0]
        if not is_subscriber_allowed_for_category(
            subscriber.get("categories"), "openmates_events"
        ):
            raise AssertionError(
                "Isolated subscriber did not consent to the events newsletter category"
            )
        token = subscriber["unsubscribe_token"]
        manifest = _fixture_manifest(
            _load_registry_fixture(), datetime.now(timezone.utc).replace(microsecond=0)
        )
        await secrets.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets)
        if email_service.selected_delivery_transport() != "ci_smtp":
            raise AssertionError("Newsletter probe must select isolated SMTP capture")
        await _probe_feedback(admin, directus, secrets, email, suppression_ids)
        for language in ("en", "de"):
            delivery_ids.append(
                build_delivery_id(
                    build_delivery_key(
                        email_type="newsletter",
                        campaign_key=manifest["slug"],
                        recipient_kind="newsletter_subscriber",
                        recipient_id=subscriber["id"],
                        stage=language,
                    )
                )
            )
            sent = await send_newsletter.send_one(
                directus,
                email_service,
                manifest,
                subscriber["id"],
                email,
                language,
                False,
                BASE_URL,
                send_newsletter.build_unsubscribe_url(token, BASE_URL),
                is_registered=subscriber.get("user_registration_status")
                == "registered",
                stage=language,
                unsubscribe_token=token,
            )
            if sent is not True:
                raise AssertionError(
                    "Newsletter production dispatcher rejected the isolated subscriber"
                )
            # The same reservation must prevent a second delivery.
            duplicate = await send_newsletter.send_one(
                directus,
                email_service,
                manifest,
                subscriber["id"],
                email,
                language,
                False,
                BASE_URL,
                send_newsletter.build_unsubscribe_url(token, BASE_URL),
                stage=language,
                unsubscribe_token=token,
            )
            if duplicate is not None:
                raise AssertionError(
                    "Newsletter reservation did not block duplicate dispatch"
                )
            message, headers = await _captured(
                mailpit, recipient=email, subject=manifest["subject"][language]
            )
            header = manifest["campaign_assets"]["header"][language]
            sources = [header["path"], header["mobile_path"]] + [
                event["assets"]["card"][language]["path"]
                for event in manifest["_events"]
            ]
            expected_images = [
                newsletter_image_url(source, BASE_URL) for source in sources
            ]
            expected_copy = [
                part
                for event in manifest["_events"]
                for part in (
                    event["localized_content"][language]["title"],
                    event["localized_content"][language]["summary"],
                )
            ]
            captures.append(
                _validate_capture(
                    message,
                    headers,
                    expected_images=expected_images,
                    expected_copy=expected_copy,
                    one_click_url=build_newsletter_one_click_url(token),
                )
            )
    finally:
        for row_id in suppression_ids:
            removed = admin.delete(f"/items/email_delivery_suppressions/{row_id}")
            if removed.status_code not in (200, 204, 404):
                raise RuntimeError(
                    "Could not remove disposable newsletter feedback state"
                )
        for row_id in delivery_ids:
            removed = admin.delete(f"/items/email_deliveries/{row_id}")
            if removed.status_code not in (200, 204, 404):
                raise RuntimeError(
                    "Could not remove disposable newsletter delivery reservation"
                )
        mailpit.close()
        admin.close()
        await directus.close()
        await secrets.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "languages": ["en", "de"],
                "captured": len(captures),
                "max_html_bytes": max(item["html_bytes"] for item in captures),
                "hosted_images": sum(item["hosted_images"] for item in captures),
                "one_click_headers": True,
                "feedback_replay_safe": True,
                "feedback_cas_safe": True,
                "feedback_recovery": True,
                "sender_reputation_classification": True,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
