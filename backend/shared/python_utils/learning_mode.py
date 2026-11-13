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
LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER = "LEARNING_MODE_COLLABORATIVE_BUILDING_POLICY"

LEARNING_MODE_CODE_MAX_LINES = 40
# Collaborative building needs runnable files; truncating them mid-file would
# hand the learner broken code, so the ceiling is a sanity bound, not a teaching cap.
LEARNING_MODE_COLLABORATIVE_CODE_MAX_LINES = 300
LEARNING_MODE_DOCUMENT_MAX_LINES = 80
LEARNING_MODE_MAIL_MAX_LINES = 30
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

# Structured teaching rubric per age group. Each line is a prompt instruction;
# the learner's own language is handled by the shared output-language rule, so
# tone cues here describe register ("informal address where the language has
# one"), not a particular language.
AGE_GROUP_RUBRIC: Dict[str, Dict[str, str]] = {
    AGE_GROUP_UNDER_10: {
        "reading": "Write for a reader of about 7-9: sentences of at most 10 words, one idea per message.",
        "terms": "Avoid technical words: use everyday words instead of defining jargon, and do not add reference links.",
        "analogies": "Use analogies from the learner's own world (animals, toys, food, games).",
        "tone": "Warm and playful; praise effort; use informal address where the language has one; an occasional emoji is fine.",
        "questions": "Ask exactly one short question per message, then wait.",
        "check_in": "Check understanding after every new idea.",
        "build_step": "about 10 lines of code at most per step",
    },
    AGE_GROUP_10_12: {
        "reading": "Write for a reader of about 10-12: short sentences (about 15 words), one or two ideas per message.",
        "terms": "Define every new technical term in a short plain clause the first time it appears.",
        "analogies": "Use analogies from games, school, sports and daily life.",
        "tone": "Friendly and encouraging; use informal address where the language has one; at most one emoji per message and only when it fits.",
        "questions": "Ask at most one question per message.",
        "check_in": "Check understanding after each idea.",
        "build_step": "about 20 lines of code at most per step",
    },
    AGE_GROUP_13_15: {
        "reading": "Write for a reader of about 13-15: clear sentences, concise explanations, scaffolded steps.",
        "terms": "Define new concepts (not obvious words) in a short clause the first time they appear.",
        "analogies": "Use an analogy when a concept is abstract; prefer concrete examples.",
        "tone": "Encouraging but not childish; informal address where natural; emojis are rare.",
        "questions": "Ask at most two questions per message.",
        "check_in": "Check in after every two or three ideas.",
        "build_step": "about 40 lines of code at most per step",
    },
    AGE_GROUP_16_18: {
        "reading": "Write precisely at a fluent reading level; deeper concepts are fine.",
        "terms": "Define only terms that are new to the field, in a short clause the first time they appear.",
        "analogies": "Prefer concrete examples; use an analogy only when it clarifies.",
        "tone": "Respectful and collegial; no emojis.",
        "questions": "Ask at most two questions per message and encourage independent reasoning.",
        "check_in": "Check in after each completed step.",
        "build_step": "about 80 lines of code at most per step",
    },
    AGE_GROUP_ADULT: {
        "reading": "Use normal technical depth and concise language.",
        "terms": "Define only specialist terms the learner has not used themselves, in a short clause the first time they appear.",
        "analogies": "Use examples over analogies.",
        "tone": "Neutral and supportive; no emojis.",
        "questions": "Ask at most two questions per message.",
        "check_in": "Check in after each completed step.",
        "build_step": "about 80 lines of code at most per step",
    },
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


def default_collaborative_build(age_group: str) -> bool:
    """Collaborative building is on by default except for the youngest learners."""

    return _validate_age_group(age_group) != AGE_GROUP_UNDER_10


def resolve_collaborative_build(age_group: str, requested: Optional[bool]) -> bool:
    """Resolve the stored toggle: omitted means the age default; under 10 is always off."""

    validated = _validate_age_group(age_group)
    if validated == AGE_GROUP_UNDER_10:
        return False
    return default_collaborative_build(validated) if requested is None else bool(requested)


def activate_learning_mode_policy(
    passcode: str,
    age_group: str,
    *,
    now: int,
    collaborative_build: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build fields to persist for an enabled account-wide Learning Mode policy."""

    validated_age_group = _validate_age_group(age_group)
    return {
        "learning_mode_enabled": True,
        "learning_mode_age_group": validated_age_group,
        "learning_mode_collaborative_build": resolve_collaborative_build(
            validated_age_group, collaborative_build
        ),
        "learning_mode_passcode_hash": hash_learning_mode_passcode(passcode),
        "learning_mode_failed_attempts": 0,
        "learning_mode_deactivation_blocked_until": None,
        "learning_mode_activated_at": int(now),
    }


def _require_valid_passcode(current: Mapping[str, Any], passcode: str, *, now: int) -> None:
    """Raise LearningModeError for a blocked or wrong passcode, counting the attempt."""

    blocked_until = current.get("learning_mode_deactivation_blocked_until")
    if isinstance(blocked_until, (int, float)) and int(blocked_until) > int(now):
        raise LearningModeError("blocked", dict(current))

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

    _require_valid_passcode(current, passcode, now=now)
    return {
        **current,
        "learning_mode_enabled": False,
        "learning_mode_failed_attempts": 0,
        "learning_mode_deactivation_blocked_until": None,
    }


def set_collaborative_build_policy(
    policy: Mapping[str, Any],
    *,
    enabled: bool,
    passcode: Optional[str],
    now: int,
) -> Dict[str, Any]:
    """Change the collaborative-building toggle of an active Learning Mode policy.

    Turning it off is stricter than the current state and needs no passcode.
    Turning it on loosens the guardrails, so it needs the passcode and shares the
    deactivation lockout counter. Reasons raised without a passcode check are
    ``learning_mode_inactive`` and ``age_not_supported``.
    """

    current = dict(policy or {})
    if not current.get("learning_mode_enabled"):
        raise LearningModeError("learning_mode_inactive", current)
    if not enabled:
        return {**current, "learning_mode_collaborative_build": False}
    if current.get("learning_mode_age_group") == AGE_GROUP_UNDER_10:
        raise LearningModeError("age_not_supported", current)
    _require_valid_passcode(current, passcode or "", now=now)
    return {
        **current,
        "learning_mode_collaborative_build": True,
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
    # Accounts that predate the toggle have no stored value and stay strict.
    collaborative_build = (
        policy.get("learning_mode_collaborative_build") is True and age_group != AGE_GROUP_UNDER_10
    )
    context: Dict[str, Any] = {
        "enabled": True,
        "age_group": age_group,
        "collaborative_build": collaborative_build,
    }
    blocked_until = policy.get("learning_mode_deactivation_blocked_until")
    if isinstance(blocked_until, (int, float)) and int(blocked_until) > 0:
        context["deactivation_blocked_until"] = int(blocked_until)
    return context


def build_anonymous_request_learning_mode_context(
    value: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return safe request-scoped Learning Mode context for anonymous chat.

    Anonymous users have no server-side policy or passcode; the browser keeps
    the setting and its local lock. The server only accepts the three teaching
    fields and never persists or logs them. Each is stricter than no Learning
    Mode, except collaborative building, which is limited to ages 10 and up.
    """

    if not value or value.get("enabled") is not True:
        return {"enabled": False}
    age_group = _validate_age_group(str(value.get("age_group") or ""))
    return {
        "enabled": True,
        "age_group": age_group,
        "collaborative_build": resolve_collaborative_build(
            age_group, value.get("collaborative_build") is True
        ),
        "source": "anonymous_session",
    }


def is_learning_mode_enabled(context: Optional[Mapping[str, Any]]) -> bool:
    return bool(context and context.get("enabled") is True)


def is_collaborative_build_enabled(context: Optional[Mapping[str, Any]]) -> bool:
    """True only when Learning Mode is active and the collaborative toggle is on."""

    return is_learning_mode_enabled(context) and bool(
        context and context.get("collaborative_build") is True
    )


def _build_age_rubric_section(age_group: str) -> str:
    rubric = AGE_GROUP_RUBRIC[age_group]
    return (
        "Teaching style for this learner:\n"
        f"- Reading level: {rubric['reading']}\n"
        f"- Terms: {rubric['terms']}\n"
        f"- Analogies: {rubric['analogies']}\n"
        f"- Tone: {rubric['tone']}\n"
        f"- Questions: {rubric['questions']}\n"
        f"- Check-ins: {rubric['check_in']}\n"
    )


def _build_term_definition_section(age_group: str) -> str:
    if age_group == AGE_GROUP_UNDER_10:
        return (
            "Terms: this learner is young, so avoid jargon and name things in everyday words; "
            "do not add Wikipedia links in your answers.\n"
        )
    return (
        "Term definitions: the first time a concept or technical term appears in this conversation "
        "(check the earlier messages), explain it right where it appears in one short plain sentence "
        "as the teaching style above asks, then link it once as `[term](wiki:Article_Title)` so the "
        "learner can read more. In Learning Mode this includes concept terms, not only proper nouns, "
        "and overrides the general advice against linking common words for terms that have a clear "
        "Wikipedia article. The visible text must match the article title; if unsure, leave it plain. "
        "Never define or link the same term again later in the conversation. Speak the definition "
        "in prose and never read link syntax aloud.\n"
    )


_TEACH_FIRST_DELIVERABLES = (
    "Do not generate complete projects, complete application implementations, long source files, "
    "full assignment answers, or production-ready artifacts. Code examples must be short and "
    "illustrative. If the learner asks for a complete answer, transform the request into guided "
    "steps and invite them to attempt the next part.\n"
)


def _build_collaborative_section(age_group: str) -> str:
    step = AGE_GROUP_RUBRIC[age_group]["build_step"]
    return (
        f"{LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER}\n"
        "Collaborative building is allowed for this learner: you may write code and build small "
        "projects together with them, as a mentor who builds WITH the learner, not FOR them.\n"
        "- Understand first: before building, ask at most 2-3 questions per message about what it "
        "should do, who uses it, how it looks and what happens on errors. Question anything unclear "
        "or contradictory, then summarize in your own words and wait for confirmation.\n"
        "- Explain the plan before the first code: which parts exist and what runs where (the page "
        "in the browser, a server, stored data, files, outside services), with one everyday analogy "
        "that fits the age. When a picture helps, create a diagram with the Diagrams app if it is "
        "available in this chat (do not use Mermaid unless the learner asks for it); if it is not "
        "available, describe the picture in plain words instead of claiming a diagram exists. Ask "
        "whether the plan fits.\n"
        f"- Build in small steps ({step}). For each step say in one or two sentences what you do and "
        "why, then let the learner try it: HTML code embeds can be previewed right in the chat and "
        "multi-file apps open as an application embed. Never tell them to open a file in a browser "
        "unless the project truly needs a local setup.\n"
        "- The learner decides what to build next and writes defined parts themselves; ask a short "
        "understanding question between steps.\n"
        "- When an error appears, read the error message together with the learner first, explain it, "
        "then fix it.\n"
        "- Ask whether it is the learner's own project or a graded or school assignment. For graded "
        "work, homework and exercises, go back to teaching-first for that task: hints and short "
        "illustrative snippets only, never a finished solution.\n"
        "- Before anything is published or shared publicly, warn that everyone can see it, including "
        "the code, and ask the learner to check it for personal information.\n"
        "Everything else in Learning Mode still applies: no answer keys or finished essays and "
        "documents, calculation results stay hidden so the learner works through the steps, and "
        "answers to unanswered practice exercises are never given.\n"
    )


def build_learning_mode_global_prompt(age_group: str, *, collaborative_build: bool = False) -> str:
    """Build the global prompt modifier appended whenever Learning Mode is active."""

    validated_age_group = _validate_age_group(age_group)
    age_guidance = AGE_GROUP_PROMPT_GUIDANCE[validated_age_group]
    age_label = AGE_GROUP_DISPLAY_LABELS[validated_age_group]
    collaborative = collaborative_build and validated_age_group != AGE_GROUP_UNDER_10
    deliverables = _build_collaborative_section(validated_age_group) if collaborative else _TEACH_FIRST_DELIVERABLES
    media_bypass = (
        "Do not use image, video, document, sheet, diagram, or code generation as a way to bypass "
        "Learning Mode or reveal a complete answer. Generated media may support conceptual learning, "
        "flashcards, metaphors, and short illustrative examples only."
        if not collaborative
        else "Do not use image, video, document or sheet generation to bypass Learning Mode or reveal "
        "a complete answer; generated media may support conceptual learning, flashcards and metaphors only."
    )
    return (
        f"{LEARNING_MODE_GLOBAL_PROMPT_MARKER}\n"
        "Learning Mode is active for this account. Your goal is to teach, not to complete "
        "assignments or generate full deliverables. Prefer guiding questions, hints, short "
        "examples, step-by-step reasoning, pseudocode, diagrams, and review of learner-provided work.\n"
        f"Learner age group: {age_label}. {age_guidance}\n"
        f"{_build_age_rubric_section(validated_age_group)}"
        f"{_build_term_definition_section(validated_age_group)}"
        f"{deliverables}"
        "For an unanswered practice task, give at most one small hint before asking for the learner's "
        "next step. Do not provide all conversions or working and leave only a trivial final sum. "
        "Solving a previous problem does not count as attempting the newly posed problem.\n"
        "Interactive question titles, field labels, option identifiers and placeholders must not "
        "reveal the answer to that question or its current substep. Use neutral placeholders.\n"
        f"{media_bypass}"
    )


def build_learning_mode_system_prompt(
    *,
    mate_prompt: str,
    learning_mode_mate_prompt: str,
    age_group: str,
    collaborative_build: bool = False,
) -> str:
    """Compose the active mate prompt and global Learning Mode modifier."""

    del mate_prompt  # Explicitly not used while Learning Mode is active.
    return "\n\n".join(
        part.strip()
        for part in [
            learning_mode_mate_prompt,
            build_learning_mode_global_prompt(age_group, collaborative_build=collaborative_build),
        ]
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
        max_lines = (
            LEARNING_MODE_COLLABORATIVE_CODE_MAX_LINES
            if is_collaborative_build_enabled(learning_mode_context)
            else LEARNING_MODE_CODE_MAX_LINES
        )
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


# Targets a collaborative learner may legitimately ask to build together.
LEARNING_MODE_COLLABORATIVE_ALLOWED_TARGETS = ("code", "app")


def filter_learning_mode_suggestions(
    suggestions: list[str],
    *,
    collaborative_build: bool = False,
) -> list[str]:
    """Remove suggestion chips that would bypass Learning Mode via artifacts.

    Answer-key phrases are always removed. Chips asking to build code or an app
    are allowed during collaborative building; other artifact requests are not.
    """

    filtered: list[str] = []
    for suggestion in suggestions:
        normalized = suggestion.strip().lower()
        if any(phrase in normalized for phrase in LEARNING_MODE_BLOCKED_SUGGESTION_PHRASES):
            continue
        if any(normalized.startswith(action) for action in LEARNING_MODE_ARTIFACT_ACTIONS):
            targets = [target for target in LEARNING_MODE_ARTIFACT_TARGETS if target in normalized]
            if collaborative_build:
                targets = [t for t in targets if t not in LEARNING_MODE_COLLABORATIVE_ALLOWED_TARGETS]
            if targets:
                continue
        filtered.append(suggestion)
    return filtered


def should_disable_learning_mode_application_artifact(context: Optional[Mapping[str, Any]]) -> bool:
    """Return True when runnable generated app artifacts must not be created."""

    return is_learning_mode_enabled(context) and not is_collaborative_build_enabled(context)


def learning_mode_context_from_preferences(user_preferences: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    context = (user_preferences or {}).get("learning_mode")
    if not isinstance(context, dict):
        return {"enabled": False}
    if not context.get("enabled"):
        return {"enabled": False}
    age_group = context.get("age_group")
    if age_group not in VALID_AGE_GROUPS:
        age_group = AGE_GROUP_13_15
    return {
        "enabled": True,
        "age_group": age_group,
        "collaborative_build": context.get("collaborative_build") is True
        and age_group != AGE_GROUP_UNDER_10,
    }
