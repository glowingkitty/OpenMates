# Internal admin email for technical chat failures on managed servers.
# Redis atomically deduplicates request identities and counts daily failures
# across all email workers. Each distinct terminal failure remains eligible.
# Self-hosted servers never send this category of notification.
# Architecture: docs/architecture/core/chat-failure-notifications.md.

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.chat_failure_notifications import CATEGORIES, EMAIL_TASK, STAGES, notification_environment

logger = logging.getLogger(__name__)
DEDUP_SECONDS = 7 * 24 * 60 * 60
COUNTER_SECONDS = 2 * 24 * 60 * 60
# No content/identifiers in values or logs; only a one-way deduplication key.
DEDUPE_AND_COUNT_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then return {0, 0} end
redis.call('SET', KEYS[1], 'seen', 'EX', ARGV[1])
local failures = redis.call('HINCRBY', KEYS[2], 'failures', 1)
redis.call('EXPIRE', KEYS[2], ARGV[2])
return {1, failures}
"""


async def deliver_chat_failure(failure_fingerprint: str, stage: str, category: str) -> str:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    edition = notification_environment()
    if edition not in {"development", "production"}:
        return "edition_policy_unavailable" if edition == "unavailable" else "self_hosted_disabled"
    if not re.fullmatch(r"[0-9a-f]{64}", failure_fingerprint) or stage not in STAGES or category not in CATEGORIES:
        logger.error("[CHAT_FAILURE_EMAIL] invalid_metadata")
        return "invalid_metadata"
    cache = CacheService()
    secrets = None
    try:
        day = datetime.now(timezone.utc).date().isoformat()
        prefix = f"chat_failure_email:{edition}"
        try:
            redis = await cache.client
            is_new, failures = await redis.eval(
                DEDUPE_AND_COUNT_LUA, 2, f"{prefix}:seen:{failure_fingerprint}", f"{prefix}:day:{day}",
                DEDUP_SECONDS, COUNTER_SECONDS,
            )
        except Exception:
            logger.error("[CHAT_FAILURE_EMAIL] dedupe_unavailable environment=%s", edition)
            return "dedupe_unavailable"
        if is_new == 0:
            return "duplicate"
        recipient = os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
        if not recipient:
            logger.error("[CHAT_FAILURE_EMAIL] missing_admin_email environment=%s", edition)
            return "missing_admin_email"
        revision = os.getenv("BUILD_COMMIT_SHA", "")
        revision = revision if re.fullmatch(r"[0-9a-f]{7,40}", revision) else "unavailable"
        secrets = SecretsManager()
        await secrets.initialize()
        service = EmailTemplateService(secrets_manager=secrets)
        accepted = await service.send_email(
            template="chat-failure-alert", recipient_email=recipient,
            subject=f"OpenMates {edition}: chat processing failed",
            context={"darkmode": True, "environment": edition, "stage": stage, "category": category,
                     "revision": revision, "failures": failures},
            lang="en",
        )
        outcome = "accepted" if accepted else "rejected"
        logger.log(logging.INFO if accepted else logging.ERROR,
                   "[CHAT_FAILURE_EMAIL] %s environment=%s failure_number=%s", outcome, edition, failures)
        return outcome
    except Exception:
        logger.error("[CHAT_FAILURE_EMAIL] delivery_unknown environment=%s", edition)
        return "delivery_unknown"
    finally:
        # Cleanup errors are not delivery outcomes and must not cause re-sends.
        for resource in (secrets, cache):
            if resource is not None:
                try:
                    await (resource.aclose() if resource is secrets else resource.close())
                except Exception:
                    logger.error("[CHAT_FAILURE_EMAIL] cleanup_failed")


@app.task(name=EMAIL_TASK, ignore_result=True)
def send_chat_failure_email(failure_fingerprint: str, stage: str, category: str) -> str:
    """Send once per fingerprint; ambiguous delivery remains deduplicated."""
    return asyncio.run(deliver_chat_failure(failure_fingerprint, stage, category))
