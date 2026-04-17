#!/usr/bin/env python3
"""
Send an OpenMates newsletter issue to confirmed subscribers.

The authoring workspace (openmates-marketing/) lives on the admin's dev
machine. Before sending, the admin runs ``publish_newsletter.py``, which
captures every file the dispatcher needs into the OpenMates repo:

    backend/newsletters/issues/<slug>.yml
        Email-level metadata: subject/subtitle/cta_text per language,
        category, body i18n key, video info, and ``sent_at`` (this script
        writes it after a successful broadcast to block double-sends).

    frontend/packages/ui/src/i18n/sources/demo_chats/<kind>_<slug>.yml
        Translation keys incl. the markdown body for the chat + email.

This script therefore only ever reads committed repo state — prod doesn't
need access to openmates-marketing/.

Three-step workflow on dev (mandatory order):

    1. --dry-run [--render-to <path>]
       Render a preview; no email sent.

    2. --test-to <email>
       One email via Brevo to a single address (no subscriber list,
       no sent_at write).

    3. --confirm-send
       Broadcast to every confirmed subscriber whose
       ``categories[<this issue's category>]`` is true. Prompts for a
       typed ``SEND`` confirmation, refuses piped stdin, and writes
       ``sent_at`` to the manifest so the next accidental re-run aborts.

Usage:
    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --slug <slug> --dry-run --render-to /tmp/preview.html --lang en

    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --slug <slug> --test-to testing@openmates.org --lang en

    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --slug <slug> --confirm-send
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml

sys.path.insert(0, "/app/backend")

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.newsletter_utils import (
    check_ignored_email,
    is_subscriber_allowed_for_category,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager

try:
    # markdown-it-py is required for body rendering.
    from markdown_it import MarkdownIt
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "markdown-it-py is required. Rebuild the api image (it is listed in requirements.txt)."
    ) from exc


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

REPO_ROOT = Path("/app")
ISSUES_DIR = REPO_ROOT / "backend" / "newsletters" / "issues"
I18N_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "demo_chats"
AUDIT_LOG_DIR = Path("/app/logs/newsletters")
SEND_DELAY_SECONDS = 0.5
CONFIRM_TOKEN = "SEND"
SUPPORTED_LANGS = ("en", "de")

# Hash parameter that triggers auto-play of the chat's header video in
# fullscreen (see ActiveChat.svelte hash routing → chatVideoFullscreenStore).
AUTOPLAY_VIDEO_PARAM = "autoplay-video"

# Where the pre-rendered intro thumbnails live on disk. Refresh with
# ``python /app/backend/scripts/newsletter_thumbnail.py``. The bytes are
# embedded directly into the email HTML as a ``data:image/jpeg;base64,...``
# URI so the image travels inside the message body — no external fetch
# (Apple Mail's tracker protection can't block it), no CID attachment
# (Brevo strips the ``contentId`` field so ``cid:`` references always break).
INTRO_THUMBNAIL_PATH_TEMPLATE = (
    "frontend/apps/web_app/static/newsletter-assets/intro-thumbnail-{lang}.jpg"
)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) >= 2 else local
    return f"{visible}***@{domain}"


def load_manifest(slug: str) -> Dict[str, Any]:
    path = ISSUES_DIR / f"{slug}.yml"
    if not path.exists():
        raise FileNotFoundError(
            f"Newsletter manifest not found: {path}. Run publish_newsletter.py first."
        )
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid manifest (not a mapping): {path}")

    required = ("slug", "kind", "category", "chat_id", "subject", "body_i18n_key")
    for field in required:
        if field not in manifest:
            raise ValueError(f"Manifest {path.name} missing required field: {field}")
    if manifest["kind"] not in ("announcements", "tips"):
        raise ValueError(f"Manifest kind must be announcements|tips (got {manifest['kind']!r})")
    return manifest


def load_body_text(manifest: Dict[str, Any], lang: str) -> Optional[str]:
    """Read the raw markdown body for the given language from the i18n YAML.

    We parse the committed YAML file directly (rather than going through
    TranslationService) because the script only needs two languages and a
    raw-string pass; no variable interpolation, no fallback-to-EN logic.
    """
    # body_i18n_key = "demo_chats.<kind>_<snake_slug>.message"
    body_key = manifest["body_i18n_key"]
    m = re.match(r"^demo_chats\.([a-z0-9_]+)\.message$", body_key)
    if not m:
        raise ValueError(f"Unexpected body_i18n_key format: {body_key}")
    snake_name = m.group(1)
    yml_path = I18N_DIR / f"{snake_name}.yml"
    if not yml_path.exists():
        raise FileNotFoundError(
            f"Demo chat i18n source not found: {yml_path}. Did publish_newsletter.py run?"
        )
    parsed = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
    message = (parsed.get("message") or {})
    if not isinstance(message, dict):
        return None
    value = message.get(lang)
    if value and value.strip():
        return value
    return None


def _video_link_for_manifest(manifest: Dict[str, Any], base_url: str) -> str:
    """Return the URL the video thumbnail should link to.

    Deep-links to the announcement/tip chat with ``&autoplay-video`` so the
    fullscreen video opens automatically on page load. Falls back to the
    newsletter landing page when no chat_id is set.
    """
    chat_id = manifest.get("chat_id")
    if chat_id:
        return f"{base_url.rstrip('/')}/#chat-id={chat_id}&{AUTOPLAY_VIDEO_PARAM}"
    return build_landing_url(manifest, base_url)


def _intro_thumbnail_path(lang: str) -> Path:
    """Disk path to the pre-rendered intro-video thumbnail for this language."""
    lang_upper = (lang or "en").upper()
    if lang_upper not in ("EN", "DE"):
        lang_upper = "EN"
    return REPO_ROOT / INTRO_THUMBNAIL_PATH_TEMPLATE.format(lang=lang_upper)


def _intro_thumbnail_data_uri(lang: str) -> Optional[str]:
    """Return a ``data:image/jpeg;base64,...`` URI for the intro thumbnail, or None."""
    path = _intro_thumbnail_path(lang)
    if not path.exists():
        logger.warning(
            f"Intro thumbnail missing: {path}. "
            "Run `python /app/backend/scripts/newsletter_thumbnail.py` to regenerate."
        )
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def render_body_html(
    body_md: str,
    video_url: str,
    thumbnail_data_uri: Optional[str],
    meta: Dict[str, Any],
    alt_text: str,
) -> str:
    """Render the markdown body and swap ``[video]`` for a clickable thumbnail.

    If the manifest has no video config (or the thumbnail failed to load),
    any ``[video]`` marker is dropped. If the body doesn't contain
    ``[video]``, the thumbnail is prepended so recipients still see the hero.
    """
    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
    body_html = md.render(body_md)

    video = meta.get("video") or {}
    if not video or not thumbnail_data_uri:
        return re.sub(r"<p>\s*\[video\]\s*</p>", "", body_html)

    safe_href = html.escape(video_url, quote=True)
    safe_alt = html.escape(alt_text, quote=True)
    # ``data:image/jpeg;base64,…`` embeds the bytes directly into the HTML so
    # the image ships inside the message body itself — no external request,
    # no CID attachment (Brevo drops the ``contentId`` field in transit).
    thumbnail_html = (
        f'<p><a href="{safe_href}" style="display:inline-block;text-decoration:none;">'
        f'<img src="{thumbnail_data_uri}" alt="{safe_alt}" width="900" '
        f'style="max-width:100%;height:auto;display:block;border:0;" /></a></p>'
    )

    # ``[video]`` on its own line becomes ``<p>[video]</p>`` after markdown-it;
    # swap that in place so the thumbnail sits where the author put it.
    placeholder_re = re.compile(r"<p>\s*\[video\]\s*</p>")
    if placeholder_re.search(body_html):
        return placeholder_re.sub(thumbnail_html, body_html, count=1)
    return thumbnail_html + "\n" + body_html


DEV_WEBAPP_BASE = "https://app.dev.openmates.org"
PROD_WEBAPP_BASE = "https://openmates.org"


def resolve_base_url(override: Optional[str] = None, for_test_send: bool = False) -> str:
    """Return the webapp origin that should appear in the rendered email.

    Precedence:
      1. ``override`` (explicit ``--base-url`` passed by the admin).
      2. ``for_test_send`` → the dev webapp (``app.dev.openmates.org``) so
         test emails always link to an environment that's safe to point at
         without leaking unreleased changes onto prod URLs.
      3. The deployed prod webapp (``openmates.org``) — used for broadcasts.
    """
    if override:
        base = override
    elif for_test_send:
        base = DEV_WEBAPP_BASE
    else:
        base = PROD_WEBAPP_BASE
    if not base.startswith("http"):
        base = f"https://{base}"
    return base.rstrip("/")


def build_landing_url(manifest: Dict[str, Any], base_url: str) -> str:
    """https://openmates.org/announcements/<slug> or .../tips/<slug>."""
    return f"{base_url.rstrip('/')}/{manifest['kind']}/{manifest['slug']}"


async def fetch_subscribers(directus: DirectusService) -> List[Dict[str, Any]]:
    """Fetch all confirmed newsletter subscribers.

    The ``confirmed_at`` filter is defence in depth even though only
    double-opt-in rows enter this collection. ``limit=-1`` disables the
    default Directus pagination so large lists don't silently truncate.
    """
    url = f"{directus.base_url}/items/newsletter_subscribers"
    params = {
        "fields": (
            "id,encrypted_email_address,hashed_email,language,darkmode,"
            "unsubscribe_token,confirmed_at,subscribed_at,user_registration_status,"
            "categories"
        ),
        "filter[confirmed_at][_nnull]": "true",
        "sort": "subscribed_at",
        "limit": "-1",
    }
    resp = await directus._make_api_request("GET", url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch subscribers: {resp.status_code} {resp.text[:500]}"
        )
    return resp.json().get("data", [])


def build_unsubscribe_url(token: Optional[str], base_url: str) -> Optional[str]:
    if not token:
        return None
    return f"{base_url}/#settings/newsletter/unsubscribe/{token}"


def prompt_confirmation(eligible_count: int, manifest: Dict[str, Any]) -> bool:
    if not sys.stdin.isatty():
        logger.error(
            "Refusing to broadcast: stdin is not a TTY. "
            "Use `docker exec -it api python ...` so the prompt is interactive; "
            "piped/automated input is not allowed."
        )
        return False
    print("\n" + "=" * 72)
    print(f"About to broadcast newsletter to {eligible_count} subscribers.")
    print(f"Category: {manifest['category']}  Kind: {manifest['kind']}  Slug: {manifest['slug']}")
    print("This will send REAL emails via Brevo and cannot be undone.")
    print("=" * 72)
    answer = input(f'Type "{CONFIRM_TOKEN}" in uppercase to proceed (anything else cancels): ').strip()
    return answer == CONFIRM_TOKEN


def open_audit_log(slug: str) -> Path:
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return AUDIT_LOG_DIR / f"{slug}-{ts}.jsonl"


def append_audit(path: Path, record: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def write_sent_at(slug: str, sent_at: str) -> None:
    """Persist the broadcast timestamp so a second run requires --resend-confirm."""
    path = ISSUES_DIR / f"{slug}.yml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    manifest["sent_at"] = sent_at
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")


async def check_landing_page_live(landing_url: str) -> bool:
    """HEAD the landing URL to confirm the page is deployed before we broadcast.

    Prevents the "forgot to deploy / PR not merged" footgun — recipients
    would otherwise click the email thumbnail and hit a 404 on prod.
    """
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(landing_url, allow_redirects=True) as resp:
                return resp.status == 200
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Landing-page check failed for {landing_url}: {exc}")
        return False


def build_context(
    manifest: Dict[str, Any],
    lang: str,
    body_md: str,
    base_url: str,
    unsubscribe_url: Optional[str],
    darkmode: bool,
    is_registered: bool = False,
) -> Dict[str, Any]:
    """Assemble the Jinja2 context for the newsletter.mjml template."""
    video = manifest.get("video") or {}
    video_url = _video_link_for_manifest(manifest, base_url)
    thumb_uri = _intro_thumbnail_data_uri(lang) if video.get("intro_fullscreen") else None
    subtitle = (manifest.get("subtitle") or {}).get(lang)
    # Alt text cannot contain the brand name — the MJML brand-name processor
    # rewrites "OpenMates" into nested HTML which mangles any attribute value.
    alt_text = "Watch the update video"
    body_html = render_body_html(body_md, video_url, thumb_uri, manifest, alt_text)
    cta_text = (manifest.get("cta_text") or {}).get(lang)
    # Registered users get a link to manage newsletter category toggles;
    # non-registered subscribers get a simple unsubscribe link.
    manage_settings_url = f"{base_url}/#settings/newsletter" if is_registered else None
    # CTA URL and shared-URL/footer links are hardcoded as prod URLs across
    # the template stack (manifest.cta_url, config_loader's imprint/privacy/
    # terms, brand-name processor). The renderer does a final string replace
    # of ``https://openmates.org`` → base_url when this key is set, so the
    # dev/prod split is honored without patching every call site.
    return {
        "newsletter_content": body_html,
        "newsletter_subtitle": subtitle,
        "cta_url": manifest.get("cta_url"),
        "cta_text": cta_text,
        "show_social_media": False,
        "manage_settings_url": manage_settings_url,
        "unsubscribe_url": unsubscribe_url if not is_registered else None,
        "darkmode": darkmode,
        "_base_url_override": base_url,
    }


async def send_one(
    email_template_service: EmailTemplateService,
    manifest: Dict[str, Any],
    recipient_email: str,
    recipient_lang: str,
    darkmode: bool,
    base_url: str,
    unsubscribe_url: Optional[str],
    is_registered: bool = False,
) -> bool:
    body_md = load_body_text(manifest, recipient_lang) or load_body_text(manifest, "en")
    if body_md is None:
        logger.error("No body text found for en — cannot send.")
        return False
    lang = recipient_lang if recipient_lang in SUPPORTED_LANGS else "en"
    subject = (manifest.get("subject") or {}).get(lang) or (manifest.get("subject") or {}).get("en")
    context = build_context(manifest, lang, body_md, base_url, unsubscribe_url, darkmode, is_registered)
    # Thumbnail is a ``data:`` URI inside the HTML (see _intro_thumbnail_data_uri)
    # — no attachment, no external fetch, nothing for a tracker-protection
    # shield to block.
    return await email_template_service.send_email(
        template="newsletter",
        recipient_email=recipient_email,
        context=context,
        subject=subject,
        lang=lang,
        attachments=None,
    )


async def run(args: argparse.Namespace) -> int:
    # ── Load manifest ────────────────────────────────────────────────────
    if not args.slug:
        logger.error("--slug is required (matches backend/newsletters/issues/<slug>.yml).")
        return 2
    manifest = load_manifest(args.slug)
    logger.info(f"Loaded manifest: {manifest['slug']} ({manifest['kind']}/{manifest['category']})")

    # ── Services ─────────────────────────────────────────────────────────
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    await encryption.initialize()
    email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

    base_url = resolve_base_url(
        override=args.base_url,
        for_test_send=bool(args.test_to) and not args.confirm_send,
    )
    landing_url = build_landing_url(manifest, base_url)
    logger.info(f"Base URL: {base_url}")
    logger.info(f"Landing URL: {landing_url}")

    # Thumbnails are rendered per-recipient in ``send_one`` so EN and DE users
    # receive the matching localized intro frame. Caching happens inside
    # ``build_thumbnail_attachment``.

    # ── Dry-run / render-only ────────────────────────────────────────────
    if args.dry_run or args.render_to:
        lang = args.lang or "en"
        body_md = load_body_text(manifest, lang) or load_body_text(manifest, "en")
        if body_md is None:
            logger.error("No body text found — publish_newsletter.py must populate the i18n YAML.")
            return 2
        fake_unsub = f"{base_url}/#settings/newsletter/unsubscribe/DRY-RUN-TOKEN"
        context = build_context(manifest, lang, body_md, base_url, fake_unsub, darkmode=False, is_registered=True)
        subject = (manifest.get("subject") or {}).get(lang) or (manifest.get("subject") or {}).get("en")
        html_out = email_template_service.render_template("newsletter", {**context, "_subject": subject}, lang)
        if args.render_to:
            out = Path(args.render_to).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html_out, encoding="utf-8")
            logger.info(f"Wrote preview HTML ({len(html_out)} chars) to {out}")
        if args.dry_run:
            logger.info("[DRY RUN] No emails sent. Re-run with --test-to <email> to test-send.")
        return 0

    # ── Test-to-self ─────────────────────────────────────────────────────
    if args.test_to:
        logger.info(f"Test-send to {_mask_email(args.test_to)} (no subscriber list access)")
        audit_path = open_audit_log(manifest["slug"])
        append_audit(
            audit_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "test",
                "slug": manifest["slug"],
                "recipient": args.test_to,  # audit log only, container-local
            },
        )
        lang = args.lang or "en"
        success = await send_one(
            email_template_service=email_template_service,
            manifest=manifest,
            recipient_email=args.test_to,
            recipient_lang=lang,
            darkmode=False,
            base_url=base_url,
            unsubscribe_url=f"{base_url}/#settings/newsletter/unsubscribe/TEST-TOKEN",
            is_registered=True,
        )
        logger.info("Test send: %s", "OK" if success else "FAILED")
        return 0 if success else 1

    # ── Real broadcast ───────────────────────────────────────────────────
    if not args.confirm_send:
        logger.error(
            "Refusing to broadcast without --confirm-send. "
            "Run with --dry-run, --test-to <email>, or --confirm-send."
        )
        return 2

    # Double-send guard: if the manifest already has sent_at, demand an explicit override.
    if manifest.get("sent_at") and not args.resend_confirm:
        logger.error(
            f"Issue {manifest['slug']} was already sent at {manifest['sent_at']}. "
            "Pass --resend-confirm to re-broadcast intentionally."
        )
        return 2

    # Landing-page live check (skippable only in dev, where the page may
    # not be deployed yet but the admin is iterating).
    env = os.getenv("SERVER_ENVIRONMENT", os.getenv("ENVIRONMENT", "production")).lower()
    is_dev = env in ("development", "dev", "test") or "localhost" in base_url
    if not is_dev:
        logger.info(f"Checking landing page liveness: {landing_url}")
        if not await check_landing_page_live(landing_url):
            logger.error(
                f"Landing page {landing_url} did not return 200. "
                "Deploy the page to prod before broadcasting — recipients will 404."
            )
            return 2

    subscribers = await fetch_subscribers(directus)
    if args.limit:
        subscribers = subscribers[: args.limit]
    if not subscribers:
        logger.warning("No subscribers found; nothing to send.")
        return 0

    # Pre-filter so the confirmation prompt shows the real eligible count.
    eligible = [
        s for s in subscribers
        if is_subscriber_allowed_for_category(s.get("categories"), manifest["category"])
    ]
    lang_breakdown: Dict[str, int] = {}
    registered_count = 0
    non_registered_count = 0
    for sub in eligible:
        lang_breakdown[sub.get("language", "en")] = lang_breakdown.get(sub.get("language", "en"), 0) + 1
        if sub.get("user_registration_status") == "signup_complete":
            registered_count += 1
        else:
            non_registered_count += 1

    print(f"\n{'=' * 52}")
    print(f"  Newsletter: {manifest['slug']}")
    print(f"  Category:   {manifest['category']}")
    print(f"  Total eligible: {len(eligible)}")
    print(f"{'=' * 52}")
    print(f"\n  Registered users (manage settings link): {registered_count}")
    print(f"  Non-registered subscribers (unsubscribe link): {non_registered_count}")
    print("\n  Language breakdown:")
    for lang_code, count in sorted(lang_breakdown.items(), key=lambda kv: -kv[1]):
        print(f"    {lang_code}: {count}")
    opted_out = len(subscribers) - len(eligible)
    if opted_out:
        print(f"\n  Skipping {opted_out} who opted out of '{manifest['category']}'")
    print()

    if not prompt_confirmation(len(eligible), manifest):
        logger.info("Broadcast cancelled by user.")
        return 0

    audit_path = open_audit_log(manifest["slug"])
    logger.info(f"Audit log: {audit_path}")

    stats = {
        "sent": 0,
        "failed": 0,
        "skipped_ignored": 0,
        "skipped_decrypt_failed": 0,
        "skipped_category_off": opted_out,
    }
    total = len(eligible)

    for idx, sub in enumerate(eligible, 1):
        sub_id = sub.get("id", "unknown")
        hashed_email = sub.get("hashed_email", "")
        encrypted_email = sub.get("encrypted_email_address", "")

        if hashed_email and await check_ignored_email(hashed_email, directus):
            stats["skipped_ignored"] += 1
            append_audit(
                audit_path,
                {"ts": datetime.now(timezone.utc).isoformat(), "subscriber_id": sub_id, "status": "skipped_ignored"},
            )
            continue

        try:
            email = await encryption.decrypt_newsletter_email(encrypted_email)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{idx}/{total}] decrypt failed for {sub_id}: {exc}")
            stats["skipped_decrypt_failed"] += 1
            append_audit(
                audit_path,
                {"ts": datetime.now(timezone.utc).isoformat(), "subscriber_id": sub_id, "status": "skipped_decrypt_failed"},
            )
            continue

        lang = sub.get("language", "en")
        unsub = build_unsubscribe_url(sub.get("unsubscribe_token"), base_url)
        darkmode = bool(sub.get("darkmode", False))
        is_registered = sub.get("user_registration_status") == "signup_complete"

        success = await send_one(
            email_template_service=email_template_service,
            manifest=manifest,
            recipient_email=email,
            recipient_lang=lang,
            darkmode=darkmode,
            base_url=base_url,
            unsubscribe_url=unsub,
            is_registered=is_registered,
        )

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "subscriber_id": sub_id,
            "lang": lang,
            "status": "sent" if success else "failed",
        }
        append_audit(audit_path, record)

        if success:
            stats["sent"] += 1
            logger.info(f"[{idx}/{total}] sent to {_mask_email(email)} ({lang})")
        else:
            stats["failed"] += 1
            logger.error(f"[{idx}/{total}] FAILED send to {_mask_email(email)} ({lang})")

        if idx < total:
            await asyncio.sleep(SEND_DELAY_SECONDS)

    # Persist sent_at so a future accidental broadcast aborts.
    if stats["sent"] > 0:
        sent_at_iso = datetime.now(timezone.utc).isoformat()
        write_sent_at(manifest["slug"], sent_at_iso)
        logger.info(f"Wrote sent_at={sent_at_iso} to manifest.")

    logger.info("=" * 72)
    logger.info(f"Broadcast complete: {stats}")
    logger.info(f"Audit log: {audit_path}")
    logger.info("=" * 72)

    try:
        await directus.close()
        await cache.close()
        await encryption.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Cleanup error: {exc}")

    return 0 if stats["failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send an OpenMates newsletter issue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--slug",
        type=str,
        required=True,
        help="Issue slug — must match backend/newsletters/issues/<slug>.yml",
    )
    parser.add_argument("--lang", type=str, default=None, choices=list(SUPPORTED_LANGS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--render-to", type=str, default=None)
    parser.add_argument("--test-to", type=str, default=None)
    parser.add_argument("--confirm-send", action="store_true")
    parser.add_argument("--resend-confirm", action="store_true", help="Override the sent_at double-send guard.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help=(
            "Override the webapp origin that appears in the email "
            "(e.g. https://app.dev.openmates.org). Defaults to the dev webapp "
            "for --test-to sends and to the prod webapp for --confirm-send."
        ),
    )
    args = parser.parse_args()

    # Back-compat placeholder for legacy --issue-dir callers.
    args.issue_dir = None

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Fatal: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
