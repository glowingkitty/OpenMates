#!/usr/bin/env python3
"""
Send an OpenMates newsletter issue to confirmed subscribers.

Each issue lives in its own directory (typically under the
`openmates-marketing/campaigns/<slug>/` folder OUTSIDE this repo) with:

    <issue-dir>/
        meta.yml           # slug, category, cta_url, video_id, video_thumbnail
        newsletter_EN.md   # body for English, with optional YAML frontmatter
        newsletter_DE.md   # body for German, with optional YAML frontmatter
        (optional video-thumbnail.jpg referenced from meta.yml)

The workflow is three-stepped and mandatory in this order:

    1. --dry-run [--render-to preview.html]
       Render without sending. Inspect locally.

    2. --test-to <your@email>
       Send only to this address (ignores subscriber list). Inspect in your
       inbox on multiple clients. Safe to re-run.

    3. --confirm-send
       Real broadcast to the eligible subscriber list. Requires typing
       "SEND" when prompted — even the flag alone will not broadcast.

Guardrails:
    - Without --confirm-send, the script never broadcasts.
    - --test-to short-circuits to the single recipient; --confirm-send is
      irrelevant for test-to sends.
    - Every run writes an audit log to /app/logs/newsletters/<slug>-<ts>.jsonl.
    - 500ms delay between sends to avoid Brevo rate limiting.

Usage:
    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --issue-dir /path/to/openmates-marketing/campaigns/<slug>/ \\
        --dry-run --render-to /tmp/preview.html

    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --issue-dir /path/to/openmates-marketing/campaigns/<slug>/ \\
        --test-to anthropic939jdq1@openmates.org

    docker exec -it api python /app/backend/scripts/send_newsletter.py \\
        --issue-dir /path/to/openmates-marketing/campaigns/<slug>/ \\
        --confirm-send
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, '/app/backend')

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
from backend.scripts.newsletter_md_renderer import (  # noqa: E402
    IssueMeta,
    LocalizedIssue,
    SUPPORTED_LANGS,
    build_video_thumbnail_attachment,
    load_issue_meta,
    render_issue,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
# Auto-redact emails/tokens that slip into log messages (defence in depth —
# all direct recipient logging in this script already masks, but the filter
# protects against future regressions per .claude/rules/privacy.md).
logger.addFilter(SensitiveDataFilter())


def _mask_email(email: str) -> str:
    """Return a redacted form of an email address for safe logging."""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) >= 2 else local
    return f"{visible}***@{domain}"

AUDIT_LOG_DIR = Path("/app/logs/newsletters")
SEND_DELAY_SECONDS = 0.5
CONFIRM_TOKEN = "SEND"


def resolve_base_url() -> str:
    """Return the deployed webapp origin for building landing/unsubscribe URLs."""
    from backend.core.api.app.services.email.config_loader import load_shared_urls

    shared_urls = load_shared_urls()
    env_name = (
        "development"
        if os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test")
        or "localhost" in os.getenv("WEBAPP_URL", "").lower()
        else "production"
    )
    base = shared_urls.get("urls", {}).get("base", {}).get("webapp", {}).get(env_name)
    if not base:
        base = os.getenv("WEBAPP_URL") or (
            "http://localhost:5173" if env_name == "development" else "https://openmates.org"
        )
    if not base.startswith("http"):
        base = f"https://{base}"
    return base


async def fetch_subscribers(directus: DirectusService) -> List[Dict[str, Any]]:
    """Fetch all confirmed newsletter subscribers (sorted by subscribe date).

    The ``confirmed_at`` filter is defence in depth: although the
    ``newsletter_subscribers`` collection is only written after double
    opt-in, an explicit filter guarantees we never broadcast to a row
    that (due to a future bug or manual DB edit) slipped in without
    valid Art. 6(1)(a) consent. ``limit=-1`` disables Directus' default
    page size so large subscriber lists aren't silently truncated.
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


def render_localized(issue_dir: Path, meta: IssueMeta, base_url: str) -> Dict[str, LocalizedIssue]:
    """Render each supported language, erroring out if a body file is missing.

    Raising for missing files is intentional — silently skipping a language
    would let a half-translated newsletter ship.
    """
    rendered: Dict[str, LocalizedIssue] = {}
    for lang in SUPPORTED_LANGS:
        rendered[lang] = render_issue(issue_dir, lang, meta, base_url)
    return rendered


def build_full_html_preview(
    email_template_service: EmailTemplateService,
    localized: LocalizedIssue,
    meta: IssueMeta,
    unsubscribe_url: str,
    base_url: str,
    darkmode: bool,
) -> str:
    """Render the MJML template to final HTML for preview or sending."""
    context = {
        "newsletter_content": localized.html_body,
        "newsletter_subtitle": localized.subtitle,
        "cta_url": meta.cta_url,
        "cta_text": localized.cta_text,
        "show_social_media": meta.show_social_media,
        "unsubscribe_url": unsubscribe_url,
        "block_list_url": f"{base_url}/#settings/newsletter/block",
        "darkmode": darkmode,
    }
    return email_template_service.render_template("newsletter", context, localized.lang)


def prompt_confirmation(eligible_count: int, categories_note: str) -> bool:
    """Interactive confirmation prompt for real broadcasts.

    Refuses to broadcast when stdin is not a TTY — this blocks naive
    automation like ``echo SEND | docker exec api ...`` from bypassing
    the typed confirmation the operator is meant to read.
    """
    if not sys.stdin.isatty():
        logger.error(
            "Refusing to broadcast: stdin is not a TTY. "
            "Run `docker exec -it api python ...` so the confirmation prompt "
            "is interactive; piped/automated input is not allowed."
        )
        return False
    print("\n" + "=" * 72)
    print(f"About to broadcast newsletter to {eligible_count} subscribers.")
    print(categories_note)
    print("This will send REAL EMAILS via Brevo and cannot be undone.")
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


async def send_one(
    email_template_service: EmailTemplateService,
    recipient_email: str,
    recipient_lang: str,
    darkmode: bool,
    rendered: Dict[str, LocalizedIssue],
    meta: IssueMeta,
    unsubscribe_url: Optional[str],
    base_url: str,
    attachments: Optional[List[Dict[str, Any]]],
) -> bool:
    """Send a single newsletter email using the MJML template + our MD body."""
    localized = rendered.get(recipient_lang) or rendered["en"]
    context = {
        "newsletter_content": localized.html_body,
        "newsletter_subtitle": localized.subtitle,
        "cta_url": meta.cta_url,
        "cta_text": localized.cta_text,
        "show_social_media": meta.show_social_media,
        "unsubscribe_url": unsubscribe_url,
        "block_list_url": f"{base_url}/#settings/newsletter/block" if unsubscribe_url else None,
        "darkmode": darkmode,
    }
    return await email_template_service.send_email(
        template="newsletter",
        recipient_email=recipient_email,
        context=context,
        subject=localized.subject,
        lang=localized.lang,
        attachments=attachments,
    )


async def run(args: argparse.Namespace) -> int:
    issue_dir = Path(args.issue_dir).expanduser().resolve()
    if not issue_dir.is_dir():
        logger.error(f"Issue directory does not exist: {issue_dir}")
        return 2

    meta = load_issue_meta(issue_dir)
    logger.info(f"Loaded issue {meta.slug!r} (category={meta.category})")

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    await encryption.initialize()
    email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

    base_url = resolve_base_url()
    logger.info(f"Webapp base URL: {base_url}")

    rendered = render_localized(issue_dir, meta, base_url)
    for lang, issue in rendered.items():
        logger.info(
            f"Rendered {lang}: subject={issue.subject!r} subtitle={issue.subtitle!r} "
            f"has_video={issue.has_video} body_chars={len(issue.html_body)}"
        )

    attachments: Optional[List[Dict[str, Any]]] = None
    thumb_attachment = build_video_thumbnail_attachment(meta)
    if thumb_attachment:
        attachments = [thumb_attachment]
        logger.info(f"Attached video thumbnail: {meta.video_thumbnail_path.name}")

    # ---- Dry-run / render-only path ----------------------------------------
    if args.dry_run or args.render_to:
        preview_lang = args.lang or "en"
        preview = rendered.get(preview_lang)
        if preview is None:
            logger.error(f"--lang {preview_lang} not in rendered languages {list(rendered)}")
            return 2

        fake_unsub = f"{base_url}/#settings/newsletter/unsubscribe/DRY-RUN-TOKEN"
        html = build_full_html_preview(
            email_template_service, preview, meta, fake_unsub, base_url, darkmode=False
        )

        if args.render_to:
            out = Path(args.render_to).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            logger.info(f"Wrote preview HTML ({len(html)} chars) to {out}")

        if args.dry_run:
            logger.info("[DRY RUN] No emails sent. Re-run with --test-to <email> to test-send.")
        return 0

    # ---- Test-to-self path --------------------------------------------------
    if args.test_to:
        logger.info(f"Test-send to {_mask_email(args.test_to)} (will NOT touch subscriber list)")
        audit_path = open_audit_log(meta.slug)
        append_audit(
            audit_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "test",
                "slug": meta.slug,
                # Audit log keeps the full recipient so we can correlate a failed
                # test-send with a later delivery issue. The audit directory is
                # container-local and not shipped to OpenObserve.
                "recipient": args.test_to,
            },
        )
        # Pick the user's preferred language via --lang flag (default en).
        lang = args.lang or "en"
        success = await send_one(
            email_template_service=email_template_service,
            recipient_email=args.test_to,
            recipient_lang=lang,
            darkmode=False,
            rendered=rendered,
            meta=meta,
            unsubscribe_url=f"{base_url}/#settings/newsletter/unsubscribe/TEST-TOKEN",
            base_url=base_url,
            attachments=attachments,
        )
        logger.info("Test send: %s", "OK" if success else "FAILED")
        return 0 if success else 1

    # ---- Real broadcast path ------------------------------------------------
    if not args.confirm_send:
        logger.error(
            "Refusing to broadcast without --confirm-send. "
            "Run with --dry-run, --test-to <email>, or --confirm-send."
        )
        return 2

    subscribers = await fetch_subscribers(directus)
    if args.limit:
        subscribers = subscribers[: args.limit]
    if not subscribers:
        logger.warning("No subscribers found; nothing to send.")
        return 0

    lang_breakdown: Dict[str, int] = {}
    for sub in subscribers:
        lang_breakdown[sub.get("language", "en")] = lang_breakdown.get(sub.get("language", "en"), 0) + 1

    categories_note = (
        f"Category: {meta.category}. "
        f"(Per-category preference filtering lands with Part B — for now every confirmed "
        f"subscriber receives every category.)"
    )
    print("\nSubscriber language breakdown:")
    for lang_code, count in sorted(lang_breakdown.items(), key=lambda kv: -kv[1]):
        print(f"  {lang_code}: {count}")
    if not prompt_confirmation(len(subscribers), categories_note):
        logger.info("Broadcast cancelled by user.")
        return 0

    audit_path = open_audit_log(meta.slug)
    logger.info(f"Audit log: {audit_path}")

    stats = {
        "sent": 0,
        "failed": 0,
        "skipped_ignored": 0,
        "skipped_decrypt_failed": 0,
        "skipped_category_off": 0,
    }
    total = len(subscribers)

    for idx, sub in enumerate(subscribers, 1):
        sub_id = sub.get("id", "unknown")
        hashed_email = sub.get("hashed_email", "")
        encrypted_email = sub.get("encrypted_email_address", "")

        if hashed_email and await check_ignored_email(hashed_email, directus):
            stats["skipped_ignored"] += 1
            append_audit(audit_path, {"ts": datetime.now(timezone.utc).isoformat(), "subscriber_id": sub_id, "status": "skipped_ignored"})
            continue

        # Per-category opt-out: skip recipients who turned off this issue's
        # category in Settings → Newsletter. NULL categories (pre-migration
        # rows) fall back to DEFAULT_NEWSLETTER_CATEGORIES.
        if not is_subscriber_allowed_for_category(sub.get("categories"), meta.category):
            stats["skipped_category_off"] += 1
            append_audit(
                audit_path,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "subscriber_id": sub_id,
                    "status": "skipped_category_off",
                    "category": meta.category,
                },
            )
            continue

        try:
            email = await encryption.decrypt_newsletter_email(encrypted_email)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{idx}/{total}] decrypt failed for {sub_id}: {exc}")
            stats["skipped_decrypt_failed"] += 1
            append_audit(audit_path, {"ts": datetime.now(timezone.utc).isoformat(), "subscriber_id": sub_id, "status": "skipped_decrypt_failed"})
            continue

        lang = sub.get("language", "en")
        if lang not in rendered:
            lang = "en"
        unsub = build_unsubscribe_url(sub.get("unsubscribe_token"), base_url)
        darkmode = bool(sub.get("darkmode", False))

        success = await send_one(
            email_template_service=email_template_service,
            recipient_email=email,
            recipient_lang=lang,
            darkmode=darkmode,
            rendered=rendered,
            meta=meta,
            unsubscribe_url=unsub,
            base_url=base_url,
            attachments=attachments,
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
        description="Send an OpenMates newsletter issue (MD-driven)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--issue-dir",
        type=str,
        required=True,
        help="Absolute path to the newsletter issue directory (containing meta.yml + newsletter_{EN,DE}.md)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        choices=list(SUPPORTED_LANGS),
        help="Language for --dry-run preview or --test-to send (default: en)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render only; do not send. Pair with --render-to to dump preview HTML.",
    )
    parser.add_argument(
        "--render-to",
        type=str,
        default=None,
        help="Write rendered preview HTML to this path (implies --dry-run semantics).",
    )
    parser.add_argument(
        "--test-to",
        type=str,
        default=None,
        help="Send only to this one email address (ignores subscriber list).",
    )
    parser.add_argument(
        "--confirm-send",
        action="store_true",
        help="Required to broadcast to real subscribers. Still prompts for typed confirmation.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of real-broadcast recipients (only meaningful with --confirm-send).",
    )

    args = parser.parse_args()

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
