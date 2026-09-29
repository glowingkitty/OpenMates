# Internal chat-failure notification dispatch and privacy boundary.
# Only terminal technical failures enter this path; content never leaves the
# caller. The email worker owns deduplication and daily failure counting.
# Delivery failure must not change the original chat response or trigger retries
# of inference. See docs/architecture/core/chat-failure-notifications.md.

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)
EMAIL_TASK = "app.tasks.email_tasks.chat_failure_email_task.send_chat_failure_email"
QUEUE_TIMEOUT_SECONDS = 1.0
QUEUE_RETRY_POLICY = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
}
STAGES = frozenset({"dispatch", "preprocessing", "inference", "streaming", "finalization"})
CATEGORIES = frozenset({"processing_error", "timeout", "unexpected_error", "delivery_error"})
EXPECTED_REJECTIONS = frozenset({"insufficient_credits", "harmful_content", "policy_rejection", "user_cancelled", "insufficient_team_credits", "harmful_or_illegal_detected", "misuse_detected"})
TYPED_FAILURE_REASONS = frozenset({"recovery_claim_failed"})
RECOVERY_TECHNICAL_FAILURE_STAGES = {
    "dispatch_failed": "dispatch",
    "soft_time_limit": "inference",
    "runtime_error": "inference",
    "unhandled_error": "inference",
    "claim_expired": "inference",
    "worker_timeout": "inference",
}


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
    failure_category = result.get("failure_category")
    if isinstance(failure_category, str):
        if failure_category in EXPECTED_REJECTIONS:
            return None
        # Categories never enter the notification payload. Unknown categories
        # stay alertable so a newly introduced technical failure cannot go quiet.
        return RECOVERY_TECHNICAL_FAILURE_STAGES.get(failure_category, "inference")
    if result.get("failure_reason") in TYPED_FAILURE_REASONS:
        return "inference"
    output = result.get("main_processing_output")
    if isinstance(output, str) and (error_marker in output or "chat.an_error_occured" in output):
        return "inference"
    if result.get("_celery_task_state") == "FAILURE":
        return "inference"
    return None


def terminal_class(result: Any, error_marker: str) -> str:
    """Classify the actual turn outcome for privacy-safe request telemetry."""
    if not isinstance(result, dict):
        return "failed_before_main"
    if result.get("interrupted_by_revocation"):
        return "revoked"
    if result.get("interrupted_by_soft_time_limit"):
        return "soft_limited"

    stage = failure_stage(result, error_marker)
    if stage == "preprocessing":
        return "failed_before_main"
    if stage is not None:
        return "failed_during_main"
    return "completed"


def _notification_payload(
    request_identity: str,
    *,
    stage: str,
    category: str,
) -> dict[str, str] | None:
    try:
        if notification_environment() not in {"development", "production"}:
            return None
        if stage not in STAGES or category not in CATEGORIES or not request_identity:
            logger.error("[CHAT_FAILURE_EMAIL] invalid_metadata")
            return None
        return {
            "failure_fingerprint": hashlib.sha256(request_identity.encode()).hexdigest(),
            "stage": stage,
            "category": category,
        }
    except Exception:
        logger.error("[CHAT_FAILURE_EMAIL] queue_unavailable")
        return None


def _start_enqueue(payload: dict[str, str]) -> tuple[threading.Event, list[bool]]:
    """Start broker publication without an executor that can block loop shutdown."""
    completed = threading.Event()
    outcome: list[bool] = []

    def enqueue() -> None:
        try:
            from backend.core.api.app.tasks.celery_config import app

            app.send_task(
                EMAIL_TASK,
                kwargs=payload,
                queue="email",
                retry=True,
                retry_policy=QUEUE_RETRY_POLICY,
            )
            outcome.append(True)
        except Exception:
            outcome.append(False)
        finally:
            completed.set()

    try:
        threading.Thread(target=enqueue, daemon=True).start()
    except Exception:
        outcome.append(False)
        completed.set()
    return completed, outcome


def _log_enqueue_outcome(
    outcome: list[bool],
    *,
    completed: bool,
    stage: str,
    category: str,
) -> bool:
    if not completed:
        # The broker might have accepted the job. Worker-side deduplication makes
        # later handling safe; never claim the timed-out operation was rejected.
        logger.error("[CHAT_FAILURE_EMAIL] queue_delivery_unknown")
        return False
    if not outcome or not outcome[0]:
        logger.error("[CHAT_FAILURE_EMAIL] queue_unavailable")
        return False
    logger.info("[CHAT_FAILURE_EMAIL] queued stage=%s category=%s", stage, category)
    return True


async def notify_chat_failure(
    request_identity: str,
    *,
    stage: str,
    category: str = "processing_error",
) -> bool:
    """Queue bounded best-effort delivery, without content or raw identifiers."""
    payload = _notification_payload(
        request_identity,
        stage=stage,
        category=category,
    )
    if payload is None:
        return False

    completed, outcome = _start_enqueue(payload)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + QUEUE_TIMEOUT_SECONDS
    while not completed.is_set() and loop.time() < deadline:
        await asyncio.sleep(min(0.01, max(0, deadline - loop.time())))
    return _log_enqueue_outcome(
        outcome,
        completed=completed.is_set(),
        stage=stage,
        category=category,
    )


def notify_chat_failure_sync(
    request_identity: str,
    *,
    stage: str,
    category: str = "processing_error",
) -> bool:
    """Synchronous bounded producer safe to call inside or outside an event loop."""
    payload = _notification_payload(
        request_identity,
        stage=stage,
        category=category,
    )
    if payload is None:
        return False

    completed, outcome = _start_enqueue(payload)
    finished = completed.wait(QUEUE_TIMEOUT_SECONDS)
    return _log_enqueue_outcome(
        outcome,
        completed=finished,
        stage=stage,
        category=category,
    )
