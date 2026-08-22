"""Deterministic events newsletter payload helpers.

These pure functions turn the shared public event registry into an internal
campaign payload. They intentionally avoid Directus, email-provider, and
subscriber reads so tests can prove event selection and link fallback without
risking a real broadcast.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from base64 import b64encode
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from PIL import Image

NEWSLETTER_WINDOW_DAYS = 28
EVENTS_CATEGORY = "openmates_events"
SUPPORTED_LANGUAGES = ("en", "de")
REPO_ROOT = Path(os.getenv("OPENMATES_REPO_ROOT", Path(__file__).resolve().parents[3]))
EMAIL_CARD_MAX_WIDTH = 640
EMAIL_CARD_JPEG_QUALITY = 78
EMAIL_CONTENT_MAX_WIDTH = 520
EMAIL_BODY_FONT_SIZE = 16
EMAIL_HEADING_FONT_SIZE = 30
EMAIL_EVENT_TITLE_FONT_SIZE = 18


def select_events_for_newsletter(
    events: list[dict[str, Any]],
    run_at: datetime,
    *,
    window_days: int = NEWSLETTER_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Select published events starting within [run_at, run_at + window)."""

    if run_at.tzinfo is None:
        raise ValueError("run_at must include timezone information")
    window_end = run_at + timedelta(days=window_days)
    selected = []
    for event in events:
        starts_at = datetime.fromisoformat(str(event["starts_at"]))
        if starts_at.tzinfo is None:
            raise ValueError(f"event starts_at must include timezone: {event.get('id')}")
        if event.get("status") == "published" and run_at <= starts_at < window_end:
            selected.append(event)
    return sorted(selected, key=lambda item: (item["starts_at"], item["id"]))


def resolve_event_destination(
    event: dict[str, Any],
    *,
    is_openmates_url_live: Callable[[str], bool] | None = None,
) -> str:
    """Return the live OpenMates URL when available, otherwise the Luma URL."""

    openmates_url = str(event.get("openmates_url") or "").strip()
    if openmates_url and is_openmates_url_live and is_openmates_url_live(openmates_url):
        return openmates_url

    luma_url = str(event.get("luma_url") or "").strip()
    parsed = urlparse(luma_url)
    if parsed.scheme == "https" and parsed.netloc == "luma.com" and parsed.path.strip("/"):
        return luma_url
    raise ValueError(f"No usable destination for event: {event.get('id') or event.get('slug')}")


def build_events_campaign_payload(
    selected_events: list[dict[str, Any]],
    run_at: datetime,
    *,
    is_openmates_url_live: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Build the deterministic internal campaign payload for selected events."""

    if not selected_events:
        raise ValueError("Cannot build an events campaign without selected events")

    slug = f"openmates-events-{run_at.date().isoformat()}"
    body_markdown = {
        language: _build_language_body(selected_events, language, is_openmates_url_live)
        for language in SUPPORTED_LANGUAGES
    }
    payload: dict[str, Any] = {
        "slug": slug,
        "status": "draft",
        "mode": "email_only",
        "category": EVENTS_CATEGORY,
        "kind": "announcements",
        "demo_chat_category": "events",
        "timezone": "Europe/Berlin",
        "subject": {
            "en": "Upcoming OpenMates events",
            "de": "Kommende OpenMates Events",
        },
        "title": {
            "en": "Upcoming OpenMates events",
            "de": "Kommende OpenMates Events",
        },
        "subtitle": {
            "en": "Join our next webinars, meetup, and community hour.",
            "de": "Sei bei den nächsten Webinaren, dem Meetup und dem Community Call dabei.",
        },
        "cta_text": {
            "en": "See all events",
            "de": "Alle Events ansehen",
        },
        "cta_url": resolve_event_destination(selected_events[0], is_openmates_url_live=is_openmates_url_live),
        "body_markdown": body_markdown,
        "metadata": {
            "campaign_type": "openmates_events",
            "generated_at": run_at.isoformat(),
            "window_days": NEWSLETTER_WINDOW_DAYS,
            "event_ids": [event["id"] for event in selected_events],
            "email_event_links": {event["id"]: _event_app_fragment(event) for event in selected_events},
            "email_copy": {language: _labels(language) for language in SUPPORTED_LANGUAGES},
        },
    }
    payload["metadata"]["payload_hash"] = _payload_hash(payload)
    return payload


def build_events_email_html(
    selected_events: list[dict[str, Any]],
    language: str,
    *,
    base_url: str,
    is_openmates_url_live: Callable[[str], bool] | None = None,
    repo_root: Path | None = None,
) -> str:
    """Render the events newsletter body as email-safe HTML.

    The surrounding MJML, footer, unsubscribe handling, plain-text generation,
    and provider delivery stay in the existing newsletter email infrastructure.
    """

    if language not in SUPPORTED_LANGUAGES:
        language = "en"
    if not selected_events:
        raise ValueError("Cannot render events newsletter without selected events")

    labels = _labels(language)
    parts = [
        f'<div style="margin:0 auto;padding:0;background-color:#ffffff;color:#000000;font-family:Arial, Helvetica, sans-serif;max-width:{EMAIL_CONTENT_MAX_WIDTH}px;width:100%;">',
        f'<p style="font-size:{EMAIL_BODY_FONT_SIZE}px;line-height:1.35;margin:0 0 24px 0;color:#000000;font-weight:700;">{html.escape(labels["intro"])}</p>',
        f'<h2 style="font-size:{EMAIL_HEADING_FONT_SIZE}px;line-height:1.25;margin:0 0 16px 0;color:#000000;font-weight:800;">{html.escape(labels["heading"])}</h2>',
    ]
    for event in selected_events:
        parts.append(_event_card_html(event, language, labels, base_url, is_openmates_url_live, repo_root or REPO_ROOT))
    parts.append(f'<p style="font-size:16px;line-height:1.35;margin:28px 0 0 0;color:#000000;font-weight:700;">{html.escape(labels["closing_note"])}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def build_events_preview_manifest(
    registry: dict[str, Any],
    run_at: datetime,
    *,
    is_openmates_url_live: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Build a manifest-like object for send_newsletter.py events previews."""

    selected_events = select_events_for_newsletter(registry["events"], run_at)
    payload = build_events_campaign_payload(
        selected_events,
        run_at,
        is_openmates_url_live=is_openmates_url_live,
    )
    payload["_events"] = selected_events
    payload["campaign_assets"] = (registry.get("campaign") or {}).get("assets") or {}
    return payload


def _build_language_body(
    selected_events: list[dict[str, Any]],
    language: str,
    is_openmates_url_live: Callable[[str], bool] | None,
) -> str:
    intro = {
        "en": "Here are the next OpenMates events from the public event calendar.",
        "de": "Hier sind die nächsten OpenMates Events aus dem öffentlichen Eventkalender.",
    }[language]
    lines = [intro, ""]
    for event in selected_events:
        content = event["localized_content"][language]
        destination = resolve_event_destination(event, is_openmates_url_live=is_openmates_url_live)
        location = event.get("venue") or event.get("online_url") or destination
        lines.extend(
            [
                f"## {content['title']}",
                f"Event ID: {event['id']}",
                f"When: {event['starts_at']} ({event['timezone']})",
                f"Where: {location}",
                content["summary"],
                content["description"],
                f"Register: {destination}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _labels(language: str) -> dict[str, str]:
    return {
        "en": {
            "intro": "Our first ever online meetup, a new in person meetup and free webinars!",
            "heading": "Upcoming events",
            "closing_note": "Hope to see you at the upcoming events! And stay tuned for the next newsletter.",
            "when": "When",
            "where_online": "on",
            "where_venue": "at",
            "details": "Open event details",
            "register": "Register on Luma",
        },
        "de": {
            "intro": "Unser erstes Online-Meetup, ein neues Vor-Ort-Meetup und kostenlose Webinare!",
            "heading": "Kommende Events",
            "closing_note": "Wir hoffen, dich bei den kommenden Events zu sehen! Und freu dich auf den nächsten Newsletter.",
            "when": "Wann",
            "where_online": "auf",
            "where_venue": "bei",
            "details": "Eventdetails öffnen",
            "register": "Auf Luma anmelden",
        },
    }[language]


def _event_card_html(
    event: dict[str, Any],
    language: str,
    labels: dict[str, str],
    base_url: str,
    is_openmates_url_live: Callable[[str], bool] | None,
    repo_root: Path,
) -> str:
    content = event["localized_content"][language]
    title = html.escape(str(content["title"]))
    summary = html.escape(str(content["summary"]))
    date_line = html.escape(_format_event_time(event, language))
    location = html.escape(_format_event_location(event, language))
    location_prefix = html.escape(labels["where_venue"] if event.get("venue") else labels["where_online"])
    event_app_url = html.escape(_event_app_url(event, base_url), quote=True)
    register_url = html.escape(resolve_event_destination(event, is_openmates_url_live=is_openmates_url_live), quote=True)
    image_src = html.escape(_event_card_data_uri(event, language, repo_root), quote=True)
    image_alt = html.escape(str(event["assets"]["card"][language]["alt"]), quote=True)
    details_label = html.escape(labels["details"])
    register_label = html.escape(labels["register"])

    return f'''<section style="margin:0 0 34px 0;padding:0;background-color:#ffffff;color:#000000;">
  <p style="margin:0 0 16px 0;text-align:center;"><a href="{event_app_url}" style="display:inline-block;text-decoration:none;"><img src="{image_src}" alt="{image_alt}" width="672" style="max-width:100%;height:auto;display:block;border:0;border-radius:24px;" /></a></p>
  <h3 style="font-size:{EMAIL_EVENT_TITLE_FONT_SIZE}px;line-height:1.3;margin:0 0 8px 0;color:#000000;font-weight:800;">{title}</h3>
  <p style="font-size:{EMAIL_BODY_FONT_SIZE}px;line-height:1.35;margin:0 0 18px 0;color:#000000;font-weight:700;">{summary}</p>
  <p style="font-size:{EMAIL_BODY_FONT_SIZE}px;line-height:1.35;margin:0 0 14px 0;color:#000000;font-weight:800;">{date_line}<br />{location_prefix} {location}</p>
  <p style="font-size:15px;line-height:1.4;margin:0 0 6px 0;color:#000000;font-weight:700;"><a href="{event_app_url}" style="color:#4867CD;text-decoration:none;">{details_label}</a> &nbsp;|&nbsp; <a href="{register_url}" style="color:#4867CD;text-decoration:none;">{register_label}</a></p>
</section>'''


def _event_card_data_uri(event: dict[str, Any], language: str, repo_root: Path) -> str:
    asset = event["assets"]["card"][language]
    raw_path = Path(str(asset["path"]))
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(f"unsafe event card path: {raw_path}")
    path = repo_root / raw_path
    if not path.exists():
        raise FileNotFoundError(f"event card image missing: {path}")

    with Image.open(path) as image:
        converted = image.convert("RGB")
        if converted.width > EMAIL_CARD_MAX_WIDTH:
            ratio = EMAIL_CARD_MAX_WIDTH / converted.width
            converted = converted.resize((EMAIL_CARD_MAX_WIDTH, round(converted.height * ratio)), Image.Resampling.LANCZOS)
        output = BytesIO()
        converted.save(output, format="JPEG", quality=EMAIL_CARD_JPEG_QUALITY, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + b64encode(output.getvalue()).decode("ascii")


def _format_event_time(event: dict[str, Any], language: str) -> str:
    starts_at = _event_datetime(event, "starts_at")
    ends_at = _event_datetime(event, "ends_at")
    timezone_label = starts_at.strftime("%Z") or str(event["timezone"])
    if language == "de":
        date = starts_at.strftime("%d.%m.%Y")
        start_time = starts_at.strftime("%H:%M")
        end_time = ends_at.strftime("%H:%M")
    else:
        date = starts_at.strftime("%a, %b %-d, %Y")
        start_time = starts_at.strftime("%-I:%M %p")
        end_time = ends_at.strftime("%-I:%M %p")
    return f"{date}, {start_time} - {end_time} {timezone_label}"


def _format_event_location(event: dict[str, Any], language: str) -> str:
    if event.get("venue"):
        return str(event["venue"])
    if event.get("online_url"):
        parsed = urlparse(str(event["online_url"]))
        return parsed.netloc or str(event["online_url"])
    return str(event.get("luma_url") or "")


def _event_datetime(event: dict[str, Any], field: str) -> datetime:
    value = datetime.fromisoformat(str(event[field]))
    timezone_name = str(event.get("timezone") or "")
    if timezone_name:
        value = value.astimezone(ZoneInfo(timezone_name))
    return value


def _event_app_url(event: dict[str, Any], base_url: str) -> str:
    return f"{base_url.rstrip('/')}/{_event_app_fragment(event)}"


def _event_app_fragment(event: dict[str, Any]) -> str:
    event_id = quote(str(event["id"]), safe="-_")
    return f"#embed-id={event_id}"


def _payload_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
