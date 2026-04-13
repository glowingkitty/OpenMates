# backend/core/api/app/tasks/email_tasks/webhook_rate_limit_digest_email_task.py
"""
Daily digest email for webhooks that hit their rate limit in the last 24 hours.

Why:
    Incoming webhooks can fire from upstream services that the user doesn't
    fully control (GitHub Actions runaway, Stripe retry storm, a misconfigured
    cron). Each successful fire dispatches an AI ask-skill and therefore costs
    credits. Per-key rate limits are the first line of defense; this daily
    digest is the second — so the user finds out their webhook is hammering
    the limit even if they never open Settings.

Runs:
    Once per day at 07:00 UTC via the Celery beat schedule in celery_config.py.

Data source:
    `webhook_auth._record_rate_limit_hit` increments per-day counters in Redis:
        webhook_rl_hits:{user_id}:{webhook_id}:{YYYY-MM-DD}
    TTL is 48h so this task can always read "today" and "yesterday" when it
    fires at 07:00 UTC.

Grouping:
    One email per affected user, listing every webhook of theirs that hit its
    limit at least once in the last 24 hours, with the hit count. After the
    email is sent the counters are deleted so we don't double-send.

Related:
    webhook_chat_notification_email_task.py (same structural pattern)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    name="app.tasks.email_tasks.webhook_rate_limit_digest_email_task.process_webhook_rate_limit_digest",
    bind=True,
)
def process_webhook_rate_limit_digest(self) -> bool:
    """Entry point for the Celery beat schedule."""
    logger.info("[WEBHOOK_RL_DIGEST] Starting daily rate-limit digest")
    try:
        return asyncio.run(_async_process_webhook_rate_limit_digest())
    except Exception as e:
        logger.error(f"[WEBHOOK_RL_DIGEST] Task error: {e}", exc_info=True)
        return False


async def _async_process_webhook_rate_limit_digest() -> bool:
    """
    Scan Redis for rate-limit hit counters from the last 24h, group by user,
    send one digest email per affected user, then clear the counters.
    """
    secrets_manager = SecretsManager()
    cache_service = None
    encryption_service = None
    directus_service = None

    try:
        await secrets_manager.initialize()

        # Import here to avoid circular imports at module load.
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.directus import DirectusService

        encryption_service = EncryptionService()
        await encryption_service.initialize()

        cache_service = CacheService()
        await cache_service.initialize()

        directus_service = DirectusService()
        await directus_service.initialize()

        client = await cache_service.client
        if not client:
            logger.warning("[WEBHOOK_RL_DIGEST] Cache unavailable — skipping run")
            return False

        # Collect counters for today + yesterday (UTC) so an overnight run
        # picks up both days of hits that are still within the 48h TTL.
        now = datetime.now(timezone.utc)
        days = [
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
        ]

        # Scan pattern: webhook_rl_hits:{user_id}:{webhook_id}:{YYYY-MM-DD}
        # user_id → { webhook_id → hit_count }
        by_user: Dict[str, Dict[str, int]] = {}
        keys_to_clear: List[str] = []

        for day in days:
            pattern = f"webhook_rl_hits:*:*:{day}"
            async for raw_key in client.scan_iter(match=pattern, count=500):
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                parts = key.split(":")
                if len(parts) != 4:
                    continue
                _, user_id, webhook_id, _day = parts
                try:
                    raw_count = await client.get(key)
                    hit_count = int(raw_count) if raw_count else 0
                except Exception as get_err:
                    logger.warning(f"[WEBHOOK_RL_DIGEST] Failed to read {key}: {get_err}")
                    continue
                if hit_count <= 0:
                    continue
                by_user.setdefault(user_id, {}).setdefault(webhook_id, 0)
                by_user[user_id][webhook_id] += hit_count
                keys_to_clear.append(key)

        if not by_user:
            logger.info("[WEBHOOK_RL_DIGEST] No rate-limit events in the last 24h")
            return True

        logger.info(
            f"[WEBHOOK_RL_DIGEST] {sum(sum(w.values()) for w in by_user.values())} "
            f"rate-limit events across {len(by_user)} user(s)"
        )

        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        sent_for_users: List[str] = []
        for user_id, webhook_hits in by_user.items():
            sent = await _send_digest_for_user(
                user_id=user_id,
                webhook_hits=webhook_hits,
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service,
                email_template_service=email_template_service,
            )
            if sent:
                sent_for_users.append(user_id)

        # Clear the processed counters so we don't double-report them
        # tomorrow. Only clear keys for users we actually emailed — a failed
        # send should retry on the next run.
        for key in keys_to_clear:
            parts = key.split(":")
            if len(parts) != 4:
                continue
            user_id = parts[1]
            if user_id in sent_for_users:
                try:
                    await client.delete(key)
                except Exception as del_err:
                    logger.warning(f"[WEBHOOK_RL_DIGEST] Failed to delete {key}: {del_err}")

        logger.info(
            f"[WEBHOOK_RL_DIGEST] Sent digest to {len(sent_for_users)} / {len(by_user)} user(s)"
        )
        return True

    except Exception as e:
        logger.error(f"[WEBHOOK_RL_DIGEST] Error: {e}", exc_info=True)
        return False
    finally:
        if cache_service:
            await cache_service.close()
        if encryption_service and hasattr(encryption_service, "close"):
            await encryption_service.close()
        if directus_service:
            await directus_service.close()
        await secrets_manager.aclose()


async def _send_digest_for_user(
    user_id: str,
    webhook_hits: Dict[str, int],
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    email_template_service: EmailTemplateService,
) -> bool:
    """Fetch user profile, decrypt notification email, send the digest."""
    try:
        # Fetch user data (cache first, Directus fallback).
        encrypted_email: Optional[str] = None
        vault_key_id: Optional[str] = None
        language = "en"
        darkmode = False
        email_enabled = False

        cached = await cache_service.get_user_by_id(user_id)
        if cached:
            encrypted_email = cached.get("encrypted_notification_email")
            vault_key_id = cached.get("vault_key_id")
            language = cached.get("language") or "en"
            darkmode = bool(cached.get("darkmode", False))
            email_enabled = bool(cached.get("email_notifications_enabled", False))
        else:
            try:
                success, profile, _ = await directus_service.get_user_profile(user_id)
                if success and profile:
                    encrypted_email = profile.get("encrypted_notification_email")
                    vault_key_id = profile.get("vault_key_id")
                    language = profile.get("language") or "en"
                    darkmode = bool(profile.get("darkmode", False))
                    email_enabled = bool(profile.get("email_notifications_enabled", False))
            except Exception as fetch_err:
                logger.warning(f"[WEBHOOK_RL_DIGEST] Profile fetch failed for {user_id[:8]}...: {fetch_err}")
                return False

        if not email_enabled:
            logger.debug(f"[WEBHOOK_RL_DIGEST] Email disabled for {user_id[:8]}..., skipping")
            return True  # Not an error — we just don't email this user.
        if not encrypted_email or not vault_key_id:
            logger.debug(f"[WEBHOOK_RL_DIGEST] No notification email for {user_id[:8]}...")
            return True

        # Decrypt recipient email
        recipient_email = await encryption_service.decrypt_with_user_key(
            encrypted_email, vault_key_id
        )
        if not recipient_email:
            logger.warning(f"[WEBHOOK_RL_DIGEST] Email decryption failed for {user_id[:8]}...")
            return False

        # Fetch the user's webhook records so we can show rate-limit settings
        # alongside the hit count.
        user_webhooks = await directus_service.get_user_webhooks_by_user_id(user_id)
        webhook_lookup: Dict[str, Dict[str, Any]] = {
            w.get("id"): w for w in (user_webhooks or []) if w.get("id")
        }

        digest_rows = _build_digest_rows(webhook_hits, webhook_lookup)

        # Build the deep-link to Settings › Developers › Webhooks.
        from backend.shared.python_utils.frontend_url import get_frontend_base_url
        base_url = get_frontend_base_url()
        settings_url = f"{base_url}/#settings/developers/webhooks"

        email_context = {
            "darkmode": darkmode,
            "settings_url": settings_url,
            "webhook_rows": digest_rows,
            "total_hits": sum(row["hit_count"] for row in digest_rows),
        }

        sent = await email_template_service.send_email(
            template="webhook-rate-limit-digest",
            recipient_email=recipient_email,
            context=email_context,
            lang=language,
        )
        if sent:
            logger.info(
                f"[WEBHOOK_RL_DIGEST] Sent digest to user {user_id[:8]}... "
                f"({len(digest_rows)} webhook(s))"
            )
        return bool(sent)

    except Exception as e:
        logger.error(f"[WEBHOOK_RL_DIGEST] Failed to send digest for {user_id[:8]}...: {e}", exc_info=True)
        return False


def _build_digest_rows(
    webhook_hits: Dict[str, int],
    webhook_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Flatten hit counts into email template rows, enriched with each
    webhook's current rate-limit config (and a best-effort decrypted name —
    deferred to the template since the name is master-key-encrypted)."""
    rows: List[Dict[str, Any]] = []
    for webhook_id, hit_count in webhook_hits.items():
        record = webhook_lookup.get(webhook_id) or {}
        rows.append({
            "webhook_id": webhook_id,
            "hit_count": hit_count,
            "rate_limit_count": record.get("rate_limit_count"),
            "rate_limit_period": record.get("rate_limit_period") or "hour",
            "encrypted_name": record.get("encrypted_name"),
            "created_at": record.get("created_at"),
        })
    rows.sort(key=lambda r: r["hit_count"], reverse=True)
    return rows
