# backend/apps/ai/processing/answer_safety.py
#
# Answer safety: every finished assistant answer is checked together with its
# request by the decision model. An answer is withdrawn only for illegal content
# or a wellbeing risk, and a withdrawn answer never gives the user a strike.
# Live checks during streaming run only in risky chats. Architecture:
# docs/plans/safety-decisions-build/.

"""
Answer-safety questions, thresholds and the withdrawal decision.

The two withdrawal questions are scored by the same decision call that already
scores `harmful_response` in postprocessing. Where postprocessing is skipped
(incognito, anonymous metadata failures) `check_answer_safety` makes a minimal
call that carries only the safety questions.

Withdrawing an answer publishes `assistant_answer_withdrawn` and replaces any
server-side cached copy with the localized notice. No strike path is reachable
from here: strikes belong to rejected requests, never to withdrawn answers.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional

from backend.apps.ai.processing.jev_decisions import evaluate_jev_decisions, score_value

logger = logging.getLogger(__name__)

WithdrawalReason = Literal["illegal", "wellbeing"]

WITHDRAWN_EVENT = "assistant_answer_withdrawn"
WITHDRAWN_MARKER_TTL_SECONDS = 24 * 3600


def withdrawn_marker_key(chat_id: str, message_id: str) -> str:
    """Redis key set while a client may still replace a withdrawn persisted answer."""
    return f"answer_withdrawn:{chat_id}:{message_id}"

# Raw decision scores run 0-9 (index into the level list below).
ANSWER_SAFETY_LEVELS: List[str] = [
    "Safe",
    "Very low concern",
    "Low concern",
    "Some concern",
    "Ambiguous",
    "Moderate concern",
    "Elevated concern",
    "Clearly harmful",
    "Highly harmful",
    "Extreme harm",
]

ILLEGAL_WITHDRAW_SCORE = 7.0
WELLBEING_WITHDRAW_SCORE = 7.0

# Live checks (risky chats only).
LIVE_CHECK_INTERVAL_CHARS = 1500
MAX_LIVE_CHECKS_PER_ANSWER = 3
RISKY_WELLBEING_LEVEL = 2

ANSWER_SAFETY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "answer_illegal": {
        "type": "score",
        "instructions": (
            "Rate whether the assistant answer itself gives real help toward illegal content: "
            "sexual content involving minors, non-consensual intimate imagery, sexual deepfakes "
            "of real people, weapons capable of mass harm, or clear criminal facilitation. "
            "Refusals, warnings, news and neutral education are safe."
        ),
        "criteria": ANSWER_SAFETY_LEVELS,
    },
    "answer_wellbeing_harm": {
        "type": "score",
        "instructions": (
            "Rate whether the assistant answer gives method or means details for self-harm or "
            "suicide, encourages it, or affirms a dangerous delusion. Supportive, caring answers "
            "and pointers to help are safe."
        ),
        "criteria": ANSWER_SAFETY_LEVELS,
    },
}


@dataclass(frozen=True)
class Withdrawal:
    """Decision to withdraw an answer; `score` is the raw 0-9 score that triggered it."""

    reason: WithdrawalReason
    score: float


def decide_withdrawal(scores: Mapping[str, float]) -> Optional[Withdrawal]:
    """Withdraw only for illegal content or a wellbeing risk; illegal takes precedence."""
    illegal = scores.get("answer_illegal", 0.0)
    wellbeing = scores.get("answer_wellbeing_harm", 0.0)
    if illegal >= ILLEGAL_WITHDRAW_SCORE:
        return Withdrawal("illegal", illegal)
    if wellbeing >= WELLBEING_WITHDRAW_SCORE:
        return Withdrawal("wellbeing", wellbeing)
    return None


def extract_answer_safety_scores(response: Any) -> Dict[str, float]:
    """Read both withdrawal scores from a decision response."""
    return {question_id: score_value(response, question_id) for question_id in ANSWER_SAFETY_QUESTIONS}


async def check_answer_safety(
    *,
    model_id: str,
    user_message: str,
    assistant_response: str,
    secrets_manager: Any,
    telemetry_task_id: Optional[str] = None,
    telemetry_purpose: str = "answer_safety_decision",
) -> Optional[Withdrawal]:
    """Minimal decision call with only the safety questions (one extra call)."""
    response = await evaluate_jev_decisions(
        state={"user_message": user_message, "assistant_response": assistant_response},
        questions=ANSWER_SAFETY_QUESTIONS,
        secrets_manager=secrets_manager,
        model_id=model_id,
        telemetry_task_id=telemetry_task_id,
        telemetry_purpose=telemetry_purpose,
    )
    return decide_withdrawal(extract_answer_safety_scores(response))


def is_risky_chat(
    preprocessing_result: Any,
    harm_threshold: float,
    misuse_threshold: float,
) -> bool:
    """A chat is risky when preprocessing marks harm/misuse above its threshold or wellbeing level >= 2."""
    if (getattr(preprocessing_result, "harmful_or_illegal_score", None) or 0) >= harm_threshold:
        return True
    if (getattr(preprocessing_result, "misuse_risk_score", None) or 0) >= misuse_threshold:
        return True
    # Transitional compatibility read: `wellbeing_level` is added to PreprocessingResult by
    # the preprocessing lane; until it exists every chat reads as level 0.
    return int(getattr(preprocessing_result, "wellbeing_level", 0) or 0) >= RISKY_WELLBEING_LEVEL


class LiveCheckGate:
    """Decides when the accumulated answer of a risky chat is checked during streaming.

    Non-risky chats never check. A check is due every `LIVE_CHECK_INTERVAL_CHARS`
    new characters, at most `MAX_LIVE_CHECKS_PER_ANSWER` times per answer.
    """

    def __init__(
        self,
        *,
        risky: bool,
        model_id: Optional[str],
        user_message: str,
        secrets_manager: Any,
        task_id: str,
    ) -> None:
        self.enabled = bool(risky and model_id)
        self.model_id = model_id
        self.user_message = user_message
        self.secrets_manager = secrets_manager
        self.task_id = task_id
        self.calls = 0
        self._checked_length = 0

    async def maybe_check(self, accumulated_answer: str) -> Optional[Withdrawal]:
        """Run a live check when due; returns the withdrawal decision, if any."""
        if not self.enabled or self.calls >= MAX_LIVE_CHECKS_PER_ANSWER:
            return None
        if len(accumulated_answer) - self._checked_length < LIVE_CHECK_INTERVAL_CHARS:
            return None
        self._checked_length = len(accumulated_answer)
        self.calls += 1
        try:
            return await check_answer_safety(
                model_id=self.model_id or "",
                user_message=self.user_message,
                assistant_response=accumulated_answer,
                secrets_manager=self.secrets_manager,
                telemetry_task_id=self.task_id,
                telemetry_purpose="answer_safety_live_decision",
            )
        except (RuntimeError, ValueError) as exc:
            # A failed live check never ends the stream; the final check still covers the answer.
            logger.warning("[Task ID: %s] Live answer-safety check unavailable (%s)", self.task_id, type(exc).__name__)
            return None


def withdrawal_notice(reason: str, language: str) -> str:
    """Localized notice for a withdrawn answer (English when the language has no entry)."""
    from backend.core.api.app.services.translations import TranslationService

    service = TranslationService()
    key = f"answer_safety.{reason}"
    for lang in (language, "en"):
        text = service.get_nested_translation(key, lang)
        if text != key:
            return text
    raise LookupError(f"Missing translation source for {key}")


def build_withdrawn_event(
    *,
    user_id: str,
    user_id_hash: str,
    chat_id: str,
    task_id: str,
    message_id: str,
    reason: str,
    notice_text: str,
) -> Dict[str, Any]:
    """Payload for the `assistant_answer_withdrawn` event on the typing-indicator channel."""
    return {
        "type": WITHDRAWN_EVENT,
        "event_for_client": WITHDRAWN_EVENT,
        "user_id_uuid": user_id,
        "user_id_hash": user_id_hash,
        "chat_id": chat_id,
        "task_id": task_id,
        "message_id": message_id,
        "reason": reason,
        "notice_text": notice_text,
    }


async def scrub_cached_answer(
    *,
    cache_service: Any,
    encryption_service: Any,
    user_vault_key_id: Optional[str],
    user_id: str,
    chat_id: str,
    message_id: str,
    notice_text: str,
) -> bool:
    """Replace the server-side AI-cache copy of a withdrawn answer with the notice.

    Also drops the provider replay context, which holds the answer text. Returns
    True when a cached copy was replaced; an absent copy (incognito) is fine.
    """
    import json

    entries = await cache_service.get_ai_messages_history(user_id, chat_id)
    if not entries:
        return False
    replaced = False
    updated: List[str] = []
    for raw in entries:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            updated.append(raw)
            continue
        if isinstance(message, dict) and message.get("id") == message_id:
            encrypted, _ = await encryption_service.encrypt_with_user_key(notice_text, user_vault_key_id)
            message["encrypted_content"] = encrypted
            message["encrypted_native_cache_context"] = None
            raw = json.dumps(message)
            replaced = True
        updated.append(raw)
    if replaced and not await cache_service.set_ai_messages_history(user_id, chat_id, updated):
        raise RuntimeError("Could not replace the cached copy of a withdrawn answer")
    return replaced


async def withdraw_answer(
    *,
    withdrawal: Withdrawal,
    cache_service: Any,
    encryption_service: Any,
    user_vault_key_id: Optional[str],
    user_id: str,
    user_id_hash: str,
    chat_id: str,
    task_id: str,
    message_id: str,
    language: str,
    extra_decision_calls: int,
) -> str:
    """Publish the withdrawal event and scrub the cached copy; returns the notice text.

    No strike is recorded here or anywhere on this path.
    """
    notice = withdrawal_notice(withdrawal.reason, language)
    # Marks this message as withdrawn by the server; the client may then replace
    # the already persisted copy (replace_withdrawn_message_handler).
    if not await cache_service.set(withdrawn_marker_key(chat_id, message_id), "1", ttl=WITHDRAWN_MARKER_TTL_SECONDS):
        raise RuntimeError("Could not mark the withdrawn answer")
    await scrub_cached_answer(
        cache_service=cache_service, encryption_service=encryption_service,
        user_vault_key_id=user_vault_key_id, user_id=user_id, chat_id=chat_id,
        message_id=message_id, notice_text=notice,
    )
    await cache_service.publish_event(
        f"ai_typing_indicator_events::{user_id_hash}",
        build_withdrawn_event(
            user_id=user_id, user_id_hash=user_id_hash, chat_id=chat_id, task_id=task_id,
            message_id=message_id, reason=withdrawal.reason, notice_text=notice,
        ),
    )
    log_extra_decision_calls(task_id, extra_decision_calls, withdrawn=True)
    return notice


def log_extra_decision_calls(task_id: str, count: int, *, withdrawn: bool) -> None:
    """Count-only cost log: extra answer-safety decision calls for one answer (no content)."""
    logger.info(
        "[Task ID: %s] [AnswerSafety] extra_decision_calls=%d withdrawn=%s",
        task_id, count, withdrawn,
    )


def load_decision_model_id() -> Optional[str]:
    """The configured decision model (apps/ai/app.yml default_llms.decision_model)."""
    from backend.apps.ai.processing.content_sanitization import _load_llm_key_from_app_yml

    return _load_llm_key_from_app_yml("decision_model")


async def decide_finished_answer(
    *,
    postprocessing_scores: Optional[Mapping[str, float]],
    decision_model_id: Optional[str],
    user_message: str,
    assistant_response: str,
    secrets_manager: Any,
    task_id: str,
) -> tuple[Optional[Withdrawal], int]:
    """Decide on a finished answer; returns (withdrawal, extra decision calls made).

    Scores from the postprocessing decision call are reused (0 extra calls). When
    postprocessing was skipped or its decision call was unavailable (incognito,
    anonymous, external), one minimal call carries only the safety questions.
    """
    if postprocessing_scores is not None:
        return decide_withdrawal(postprocessing_scores), 0
    if not decision_model_id:
        raise RuntimeError("Answer-safety check needs a configured decision model")
    withdrawal = await check_answer_safety(
        model_id=decision_model_id, user_message=user_message,
        assistant_response=assistant_response, secrets_manager=secrets_manager,
        telemetry_task_id=task_id,
    )
    return withdrawal, 1
