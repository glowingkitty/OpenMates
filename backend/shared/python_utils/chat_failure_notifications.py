# Internal chat-failure notification dispatch and privacy boundary.
# Only terminal technical failures enter this path; content never leaves the
# caller. The email worker owns deduplication and the shared daily allowance.
# Delivery failure must not change the original chat response or trigger retries
# of inference. See docs/architecture/core/chat-failure-notifications.md.

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)
EMAIL_TASK = "app.tasks.email_tasks.chat_failure_email_task.send_chat_failure_email"
QUEUE_TIMEOUT_SECONDS = 1.0
STAGES = frozenset({"dispatch", "preprocessing", "inference", "streaming", "finalization"})
CATEGORIES = frozenset({"processing_error", "timeout", "unexpected_error", "delivery_error"})
EXPECTED_REJECTIONS = frozenset({"insufficient_credits", "harmful_content", "policy_rejection", "user_cancelled", "insufficient_team_credits", "harmful_or_illegal_detected", "misuse_detected"})


def notification_environment() -> str:
    """Load the existing signed domain policy in workers before edition checks."""
    from backend.core.api.app.utils.server_mode import get_allowed_domain, get_server_edition
    if not get_allowed_domain():
        from backend.core.api.app.services.domain_security import DomainSecurityService
        try:
            DomainSecurityService().load_security_config()
        except (Exception, SystemExit):
            # The domain loader is also a startup guard and can raise SystemExit.
            # An optional notification must never terminate a chat/email worker.
            logger.error("[CHAT_FAILURE_EMAIL] edition_policy_unavailable")
            return "unavailable"
    return get_server_edition()


def failure_stage(result: Any, error_marker: str) -> str | None:
    """Inspect an internal result locally; never forward its text or exceptions."""
    if not isinstance(result, dict):
        return "finalization"
    if result.get("interrupted_by_revocation"):
        return None
    preprocessing = result.get("preprocessing_summary") or {}
    rejection = preprocessing.get("rejection_reason")
    if rejection in EXPECTED_REJECTIONS:
        return None
    if result.get("interrupted_by_soft_time_limit"):
        return "inference"
    if rejection == "llm_error" or preprocessing.get("can_proceed") is False:
        return "preprocessing"
    output = result.get("main_processing_output")
    if isinstance(output, str) and (error_marker in output or "chat.an_error_occured" in output):
        return "inference"
    if result.get("_celery_task_state") == "FAILURE":
        return "inference"
    return None


async def notify_chat_failure(request_identity: str, *, stage: str, category: str = "processing_error") -> None:
    """Queue bounded best-effort delivery, without content or raw identifiers."""
    try:
        if notification_environment() not in {"development", "production"}:
            return
        if stage not in STAGES or category not in CATEGORIES or not request_identity:
            logger.error("[CHAT_FAILURE_EMAIL] invalid_metadata")
            return
        from backend.core.api.app.tasks.celery_config import app
        fingerprint = hashlib.sha256(request_identity.encode()).hexdigest()
        await asyncio.wait_for(
            asyncio.to_thread(
                app.send_task, EMAIL_TASK,
                kwargs={"failure_fingerprint": fingerprint, "stage": stage, "category": category},
                queue="email", retry=False,
            ),
            timeout=QUEUE_TIMEOUT_SECONDS,
        )
        logger.info("[CHAT_FAILURE_EMAIL] queued stage=%s category=%s", stage, category)
    except TimeoutError:
        # The broker might have accepted the job. Worker-side deduplication makes
        # later handling safe; never claim the timed-out operation was rejected.
        logger.error("[CHAT_FAILURE_EMAIL] queue_delivery_unknown")
    except Exception:
        logger.error("[CHAT_FAILURE_EMAIL] queue_unavailable")
