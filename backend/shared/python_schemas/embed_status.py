# backend/shared/python_schemas/embed_status.py
# Embed Status State Machine — canonical definition of valid embed statuses and transitions.
# Architecture: docs/architecture/embeds.md — "Embed State Machine" section
# Tests: frontend/packages/ui/src/data/__tests__/embedRegistry.test.ts (state machine parity checks)
# Tests: backend/tests/test_embed_status.py (planned)
#
# This module is the single source of truth for embed status values and valid transitions.
# Both backend services and the frontend TypeScript mirror (embedStateMachine.ts) must stay
# in sync with the definitions here.

from enum import Enum
from typing import Dict, FrozenSet, Optional

import logging

logger = logging.getLogger(__name__)


class EmbedStatus(str, Enum):
    """
    All valid embed statuses.

    State diagram:
        (initial) ──► PROCESSING ──► FINISHED
                            │
                            ├──► ERROR
                            │
                            └──► CANCELLED

        FINISHED ──► ERROR  (frontend-only: decryption failure)

    Terminal states: FINISHED, ERROR, CANCELLED
    """

    PROCESSING = "processing"
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


# ── Valid transitions ────────────────────────────────────────────────────────
# Key = current status, Value = frozenset of statuses it may transition to.
# Any transition not listed here is invalid and will be rejected.
ALLOWED_TRANSITIONS: Dict[EmbedStatus, FrozenSet[EmbedStatus]] = {
    EmbedStatus.PROCESSING: frozenset({
        EmbedStatus.PROCESSING,   # streaming updates (content changes, status stays)
        EmbedStatus.FINISHED,     # normal completion
        EmbedStatus.ERROR,        # skill failure
        EmbedStatus.CANCELLED,    # user pressed stop
    }),
    EmbedStatus.FINISHED: frozenset({
        EmbedStatus.ERROR,        # frontend-only: decryption failure on stored embed
    }),
    EmbedStatus.ERROR: frozenset(),       # terminal — no transitions out
    EmbedStatus.CANCELLED: frozenset(),   # terminal — no transitions out
}

# ── Terminal states (no further transitions allowed except explicit exceptions above) ───
TERMINAL_STATUSES: FrozenSet[EmbedStatus] = frozenset({
    EmbedStatus.FINISHED,
    EmbedStatus.ERROR,
    EmbedStatus.CANCELLED,
})


def validate_embed_transition(
    current: str,
    target: str,
    embed_id: str = "",
    log_prefix: str = "",
    strict: bool = False,
) -> bool:
    """
    Check whether transitioning from `current` to `target` is valid.

    Args:
        current: Current status string (e.g. "processing")
        target: Desired new status string (e.g. "finished")
        embed_id: Embed ID for logging context
        log_prefix: Logging prefix
        strict: If True, raise ValueError on invalid transition instead of returning False

    Returns:
        True if the transition is valid, False otherwise.

    Raises:
        ValueError: Only if strict=True and the transition is invalid.
    """
    try:
        current_status = EmbedStatus(current)
    except ValueError:
        msg = f"{log_prefix} Unknown embed status '{current}' for embed {embed_id}"
        logger.warning(msg)
        if strict:
            raise ValueError(msg)
        return False

    try:
        target_status = EmbedStatus(target)
    except ValueError:
        msg = f"{log_prefix} Unknown target embed status '{target}' for embed {embed_id}"
        logger.warning(msg)
        if strict:
            raise ValueError(msg)
        return False

    allowed = ALLOWED_TRANSITIONS.get(current_status, frozenset())
    if target_status in allowed:
        return True

    msg = (
        f"{log_prefix} Invalid embed transition: '{current}' → '{target}' "
        f"for embed {embed_id}. Allowed from '{current}': {sorted(s.value for s in allowed)}"
    )
    logger.warning(msg)
    if strict:
        raise ValueError(msg)
    return False


def is_terminal(status: str) -> bool:
    """Check if an embed status is terminal (no further transitions expected)."""
    try:
        return EmbedStatus(status) in TERMINAL_STATUSES
    except ValueError:
        return False


def normalize_status(value: Optional[str]) -> EmbedStatus:
    """
    Normalize a status string to an EmbedStatus enum value.
    Unknown or None values default to FINISHED (matches existing frontend behavior).
    """
    if value is None:
        return EmbedStatus.FINISHED
    try:
        return EmbedStatus(value)
    except ValueError:
        logger.warning(f"Unknown embed status '{value}', defaulting to 'finished'")
        return EmbedStatus.FINISHED
