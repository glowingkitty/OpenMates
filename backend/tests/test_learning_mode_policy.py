"""Regression tests for account-wide Learning Mode policy handling.

Learning Mode is a backend-enforced account policy: clients can display and
optimistically send context, but request processing must resolve the account
state server-side. These tests cover the deterministic policy logic without
requiring Directus or Redis.
"""

from __future__ import annotations

import time

import pytest

from backend.shared.python_utils.learning_mode import (
    AGE_GROUP_13_15,
    DEACTIVATION_BLOCK_SECONDS,
    MAX_FAILED_DEACTIVATION_ATTEMPTS,
    LearningModeError,
    activate_learning_mode_policy,
    build_learning_mode_context,
    deactivate_learning_mode_policy,
    verify_learning_mode_passcode,
)


def test_activation_hashes_passcode_and_returns_safe_context() -> None:
    now = int(time.time())

    policy = activate_learning_mode_policy(
        passcode="teacher-pin-123",
        age_group=AGE_GROUP_13_15,
        now=now,
    )

    assert policy["learning_mode_enabled"] is True
    assert policy["learning_mode_age_group"] == AGE_GROUP_13_15
    assert policy["learning_mode_failed_attempts"] == 0
    assert policy["learning_mode_activated_at"] == now
    assert "teacher-pin-123" not in policy["learning_mode_passcode_hash"]
    assert verify_learning_mode_passcode("teacher-pin-123", policy["learning_mode_passcode_hash"])

    context = build_learning_mode_context(policy)
    assert context == {"enabled": True, "age_group": AGE_GROUP_13_15}


def test_deactivation_blocks_after_five_failed_attempts() -> None:
    now = int(time.time())
    policy = activate_learning_mode_policy(
        passcode="teacher-pin-123",
        age_group=AGE_GROUP_13_15,
        now=now,
    )

    for attempt in range(1, MAX_FAILED_DEACTIVATION_ATTEMPTS + 1):
        with pytest.raises(LearningModeError) as exc_info:
            deactivate_learning_mode_policy(policy, passcode="wrong", now=now + attempt)
        policy = exc_info.value.updated_policy

    assert policy["learning_mode_enabled"] is True
    assert policy["learning_mode_failed_attempts"] == MAX_FAILED_DEACTIVATION_ATTEMPTS
    assert policy["learning_mode_deactivation_blocked_until"] == (
        now + MAX_FAILED_DEACTIVATION_ATTEMPTS + DEACTIVATION_BLOCK_SECONDS
    )

    with pytest.raises(LearningModeError) as exc_info:
        deactivate_learning_mode_policy(policy, passcode="teacher-pin-123", now=now + 10)
    assert exc_info.value.reason == "blocked"
    assert exc_info.value.updated_policy["learning_mode_enabled"] is True


def test_deactivation_with_correct_passcode_resets_policy() -> None:
    now = int(time.time())
    policy = activate_learning_mode_policy(
        passcode="teacher-pin-123",
        age_group=AGE_GROUP_13_15,
        now=now,
    )

    updated = deactivate_learning_mode_policy(policy, passcode="teacher-pin-123", now=now + 1)

    assert updated["learning_mode_enabled"] is False
    assert updated["learning_mode_failed_attempts"] == 0
    assert updated["learning_mode_deactivation_blocked_until"] is None
    assert build_learning_mode_context(updated) == {"enabled": False}


def test_invalid_age_group_is_rejected() -> None:
    with pytest.raises(ValueError):
        activate_learning_mode_policy(passcode="teacher-pin-123", age_group="exact_age_9", now=1)
