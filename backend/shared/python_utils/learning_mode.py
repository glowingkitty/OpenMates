"""Shared Learning Mode policy and artifact helpers.

Learning Mode is an account-wide backend policy used by the API, AI worker,
CLI, web app, and Apple app. This module intentionally has no FastAPI,
Directus, or Redis dependency so policy validation, passcode handling, prompt
construction, and generated-artifact caps can be tested deterministically.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


AGE_GROUP_UNDER_10 = "under_10"
AGE_GROUP_10_12 = "10_12"
AGE_GROUP_13_15 = "13_15"
AGE_GROUP_16_18 = "16_18"
AGE_GROUP_ADULT = "adult"

VALID_AGE_GROUPS = {
    AGE_GROUP_UNDER_10,
    AGE_GROUP_10_12,
    AGE_GROUP_13_15,
    AGE_GROUP_16_18,
    AGE_GROUP_ADULT,
}

MAX_FAILED_DEACTIVATION_ATTEMPTS = 5
DEACTIVATION_BLOCK_SECONDS = 24 * 60 * 60
PASSCODE_HASH_ITERATIONS = 210_000
PASSCODE_HASH_PREFIX = "pbkdf2_sha256"

LEARNING_MODE_GLOBAL_PROMPT_MARKER = "LEARNING_MODE_ACTIVE_TEACHING_POLICY"

LEARNING_MODE_CODE_MAX_LINES = 40
LEARNING_MODE_DOCUMENT_MAX_LINES = 80
LEARNING_MODE_MAIL_MAX_LINES = 30
LEARNING_MODE_MERMAID_MAX_LINES = 40
LEARNING_MODE_PLOT_MAX_LINES = 20
LEARNING_MODE_SHEET_MAX_ROWS = 12
LEARNING_MODE_SHEET_MAX_COLS = 8
LEARNING_MODE_BLOCKED_SUGGESTION_PHRASES = (
    "answer key",
    "final answer",
    "complete answer",
    "full solution",
    "solve this",
    "calculate the solution",
    "find the solution",
    "calculate the roots",
    "step-by-step solution image",
)
LEARNING_MODE_ARTIFACT_ACTIONS = (
    "generate",
    "create",
    "write",
    "build",
    "make",
    "show",
)
LEARNING_MODE_ARTIFACT_TARGETS = (
    "image",
    "video",
    "document",
    "sheet",
    "spreadsheet",
    "code",
    "app",
    "artifact",
)


AGE_GROUP_PROMPT_GUIDANCE = {
    AGE_GROUP_UNDER_10: "Use very simple language, concrete examples, and tiny steps.",
    AGE_GROUP_10_12: "Use simple explanations, gentle hints, and small practice tasks.",
    AGE_GROUP_13_15: "Use scaffolded problem solving, concise explanations, and learner check-ins.",
    AGE_GROUP_16_18: "Use deeper concepts and independence while still avoiding complete deliverables.",
    AGE_GROUP_ADULT: "Use normal technical depth while staying teaching-first and avoiding complete deliverables.",
}

AGE_GROUP_DISPLAY_LABELS = {
    AGE_GROUP_UNDER_10: "under 10",
    AGE_GROUP_10_12: "10-12",
    AGE_GROUP_13_15: "13-15",
    AGE_GROUP_16_18: "16-18",
    AGE_GROUP_ADULT: "adult",
}


class LearningModeError(ValueError):
    """Policy error that carries the updated policy state for persistence."""

    def __init__(self, reason: str, updated_policy: Dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.updated_policy = updated_policy


@dataclass(frozen=True)
class LearningModeLimits:
    code_max_lines: int = LEARNING_MODE_CODE_MAX_LINES
    document_max_lines: int = LEARNING_MODE_DOCUMENT_MAX_LINES
    mail_max_lines: int = LEARNING_MODE_MAIL_MAX_LINES
    mermaid_max_lines: int = LEARNING_MODE_MERMAID_MAX_LINES
    plot_max_lines: int = LEARNING_MODE_PLOT_MAX_LINES
    sheet_max_rows: int = LEARNING_MODE_SHEET_MAX_ROWS
    sheet_max_cols: int = LEARNING_MODE_SHEET_MAX_COLS


def _validate_passcode(passcode: str) -> str:
    value = (passcode or "").strip()
    if len(value) < 4:
        raise ValueError("Learning Mode passcode must be at least 4 characters long")
    if len(value) > 128:
        raise ValueError("Learning Mode passcode is too long")
    return value


def _validate_age_group(age_group: str) -> str:
    if age_group not in VALID_AGE_GROUPS:
        raise ValueError("Invalid Learning Mode age group")
    return age_group


def hash_learning_mode_passcode(passcode: str, *, salt: Optional[bytes] = None) -> str:
    """Hash a passcode using PBKDF2-SHA256 with a per-policy random salt."""

    value = _validate_passcode(passcode)
    salt_bytes = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt_bytes,
        PASSCODE_HASH_ITERATIONS,
    )
    return "$".join(
        [
            PASSCODE_HASH_PREFIX,
            str(PASSCODE_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt_bytes).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_learning_mode_passcode(passcode: str, stored_hash: str) -> bool:
    """Return True when a plaintext passcode matches the stored hash."""

    try:
        prefix, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if prefix != PASSCODE_HASH_PREFIX:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            _validate_passcode(passcode).encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def activate_learning_mode_policy(passcode: str, age_group: str, *, now: int) -> Dict[str, Any]:
    """Build fields to persist for an enabled account-wide Learning Mode policy."""

    return {
        "learning_mode_enabled": True,
        "learning_mode_age_group": _validate_age_group(age_group),
        "learning_mode_passcode_hash": hash_learning_mode_passcode(passcode),
        "learning_mode_failed_attempts": 0,
        "learning_mode_deactivation_blocked_until": None,
        "learning_mode_activated_at": int(now),
    }


def deactivate_learning_mode_policy(
    policy: Mapping[str, Any],
    *,
    passcode: str,
    now: int,
) -> Dict[str, Any]:
    """Return disabled policy fields or raise LearningModeError with updated state."""

    current = dict(policy or {})
    if not current.get("learning_mode_enabled"):
        return {
            **current,
            "learning_mode_enabled": False,
            "learning_mode_failed_attempts": 0,
            "learning_mode_deactivation_blocked_until": None,
        }

    blocked_until = current.get("learning_mode_deactivation_blocked_until")
    if isinstance(blocked_until, (int, float)) and int(blocked_until) > int(now):
        raise LearningModeError("blocked", current)

    stored_hash = str(current.get("learning_mode_passcode_hash") or "")
    if not verify_learning_mode_passcode(passcode, stored_hash):
        attempts = int(current.get("learning_mode_failed_attempts") or 0) + 1
        updated = {
            **current,
            "learning_mode_failed_attempts": attempts,
        }
        if attempts >= MAX_FAILED_DEACTIVATION_ATTEMPTS:
            updated["learning_mode_deactivation_blocked_until"] = int(now) + DEACTIVATION_BLOCK_SECONDS
        raise LearningModeError("wrong_passcode", updated)

    return {
        **current,
        "learning_mode_enabled": False,
        "learning_mode_failed_attempts": 0,
        "learning_mode_deactivation_blocked_until": None,
    }


def build_learning_mode_context(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return the safe AI/client context derived from persisted policy fields."""

    if not policy or not policy.get("learning_mode_enabled"):
        return {"enabled": False}
    age_group = policy.get("learning_mode_age_group")
    if age_group not in VALID_AGE_GROUPS:
        age_group = AGE_GROUP_13_15
    context: Dict[str, Any] = {"enabled": True, "age_group": age_group}
    blocked_until = policy.get("learning_mode_deactivation_blocked_until")
    if isinstance(blocked_until, (int, float)) and int(blocked_until) > 0:
        context["deactivation_blocked_until"] = int(blocked_until)
    return context


def is_learning_mode_enabled(context: Optional[Mapping[str, Any]]) -> bool:
    return bool(context and context.get("enabled") is True)


def build_learning_mode_global_prompt(age_group: str) -> str:
    """Build the global prompt modifier appended whenever Learning Mode is active."""

    validated_age_group = _validate_age_group(age_group)
    age_guidance = AGE_GROUP_PROMPT_GUIDANCE[validated_age_group]
    age_label = AGE_GROUP_DISPLAY_LABELS[validated_age_group]
    return (
        f"{LEARNING_MODE_GLOBAL_PROMPT_MARKER}\n"
        "Learning Mode is active for this account. Your goal is to teach, not to complete "
        "assignments or generate full deliverables. Prefer guiding questions, hints, short "
        "examples, step-by-step reasoning, pseudocode, diagrams, and review of learner-provided work.\n"
        f"Learner age group: {age_label}. {age_guidance}\n"
        "Do not generate complete projects, complete application implementations, long source files, "
        "full assignment answers, or production-ready artifacts. Code examples must be short and "
        "illustrative. If the learner asks for a complete answer, transform the request into guided "
        "steps and invite them to attempt the next part.\n"
        "Do not use image, video, document, sheet, diagram, or code generation as a way to bypass "
        "Learning Mode or reveal a complete answer. Generated media may support conceptual learning, "
        "flashcards, metaphors, and short illustrative examples only."
    )


def build_learning_mode_system_prompt(
    *,
    mate_prompt: str,
    learning_mode_mate_prompt: str,
    age_group: str,
) -> str:
    """Compose the active mate prompt and global Learning Mode modifier."""

    del mate_prompt  # Explicitly not used while Learning Mode is active.
    return "\n\n".join(
        part.strip()
        for part in [learning_mode_mate_prompt, build_learning_mode_global_prompt(age_group)]
        if part and part.strip()
    )


def cap_learning_mode_lines(content: str, *, max_lines: int) -> Tuple[str, Dict[str, Any]]:
    """Cap text by lines and return durable shortened metadata."""

    lines = (content or "").splitlines()
    original_line_count = len(lines)
    capped_lines = lines[:max_lines]
    shortened = original_line_count > max_lines
    return "\n".join(capped_lines), {
        "learning_mode_shortened": shortened,
        "original_line_count": original_line_count,
        "shown_line_count": len(capped_lines) if shortened else original_line_count,
    }


def apply_learning_mode_cap_to_embed_result(
    child_type: str,
    result: Dict[str, Any],
    learning_mode_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Cap generated app-skill child embed content when Learning Mode is active."""

    if not is_learning_mode_enabled(learning_mode_context):
        return result

    capped_result = dict(result)
    cap_field: Optional[str] = None
    max_lines = LEARNING_MODE_DOCUMENT_MAX_LINES

    if child_type == "code" and isinstance(capped_result.get("code"), str):
        cap_field = "code"
        max_lines = LEARNING_MODE_CODE_MAX_LINES
    elif child_type == "document":
        for field in ("content", "markdown", "text", "html", "document"):
            if isinstance(capped_result.get(field), str):
                cap_field = field
                max_lines = LEARNING_MODE_DOCUMENT_MAX_LINES
                break
    elif child_type == "sheet":
        for field in ("table_content", "csv", "content", "code"):
            if isinstance(capped_result.get(field), str):
                cap_field = field
                max_lines = LEARNING_MODE_SHEET_MAX_ROWS
                break

    if not cap_field:
        return capped_result

    capped_content, metadata = cap_learning_mode_lines(
        capped_result[cap_field],
        max_lines=max_lines,
    )
    capped_result[cap_field] = capped_content
    capped_result.update(metadata)
    if child_type == "code" and cap_field == "code":
        capped_result["line_count"] = metadata["shown_line_count"]
    return capped_result


def apply_learning_mode_policy_to_skill_result(
    app_id: str,
    skill_id: str,
    result: Dict[str, Any],
    learning_mode_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Hide complete tool answers that would bypass Learning Mode."""

    if not is_learning_mode_enabled(learning_mode_context):
        return result

    sanitized = dict(result)
    if app_id == "math" and skill_id == "calculate":
        for field in (
            "result",
            "result_latex",
            "result_numeric",
            "result_str",
            "steps",
            "expression_latex",
        ):
            sanitized.pop(field, None)
        sanitized.update({
            "learning_mode_shortened": True,
            "learning_mode_tool_result_hidden": True,
            "learning_mode_notice": "Tool result hidden since Learning Mode is active. Work through the next step with the assistant.",
        })
    return sanitized


def is_learning_mode_blocked_skill(app_id: str, skill_id: str) -> bool:
    """Return True for skills that bypass teaching-first Learning Mode policy."""

    return app_id == "math" and skill_id == "calculate"


def filter_learning_mode_suggestions(suggestions: list[str]) -> list[str]:
    """Remove suggestion chips that would bypass Learning Mode via artifacts."""

    filtered: list[str] = []
    for suggestion in suggestions:
        normalized = suggestion.strip().lower()
        if any(phrase in normalized for phrase in LEARNING_MODE_BLOCKED_SUGGESTION_PHRASES):
            continue
        if (
            any(normalized.startswith(action) for action in LEARNING_MODE_ARTIFACT_ACTIONS)
            and any(target in normalized for target in LEARNING_MODE_ARTIFACT_TARGETS)
        ):
            continue
        filtered.append(suggestion)
    return filtered


def should_disable_learning_mode_application_artifact(context: Optional[Mapping[str, Any]]) -> bool:
    """Return True when runnable generated app artifacts must not be created."""

    return is_learning_mode_enabled(context)


def learning_mode_context_from_preferences(user_preferences: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    context = (user_preferences or {}).get("learning_mode")
    if not isinstance(context, dict):
        return {"enabled": False}
    if not context.get("enabled"):
        return {"enabled": False}
    age_group = context.get("age_group")
    if age_group not in VALID_AGE_GROUPS:
        age_group = AGE_GROUP_13_15
    return {"enabled": True, "age_group": age_group}
