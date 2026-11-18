"""Interpreting turns for spawned-chat updates inside an active voice call.

Spec: feature.video-call ``video-call.chat.orchestration-continuity`` and
feature.chat-orchestration ``chat-orchestration.events.automatic-interpretation``.

While a call is bound to a creator chat, the call WebSocket owns the dispatch of
the automatic interpreting turn, because only this process learns (from the
client's ``assistant_state``) whether assistant speech is still playing and
(from the transcription provider) whether the user is speaking. The call loop
calls :meth:`CallInterpretationGate.tick` at least once per second; the gate
starts a turn only when the call is quiet, so the turn never cuts off the
current answer or the user. Outside a call the debounced text-only dispatcher in
``chat_orchestration_interpretation`` handles the same buffered events.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from backend.shared.python_utils import chat_orchestration_interpretation as interpretation

logger = logging.getLogger(__name__)

# Silence after the user's last speech activity and after the assistant's last
# audible or generating state before an update may be spoken.
QUIET_SECONDS = 1.5


class CallInterpretationGate:
    """Per-call state for dispatching interpreting turns at quiet moments."""

    def __init__(self, *, cache_service: Any, directus_service: Any, encryption_service: Any,
                 user_id: str, chat_id: str, call_id: str,
                 issue: Callable[[str], Awaitable[None]],
                 send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._cache = cache_service
        self._directus = directus_service
        self._encryption = encryption_service
        self._user_id = user_id
        self._chat_id = chat_id
        self._call_id = call_id
        self._issue = issue
        self._send = send
        self._last_speech = 0.0
        self._last_assistant = 0.0
        self.bound = False

    async def bind(self, ttl_seconds: int) -> None:
        await interpretation.bind_call(cache_service=self._cache, user_id=self._user_id,
                                       chat_id=self._chat_id, call_id=self._call_id, ttl_seconds=ttl_seconds)
        self.bound = True

    def user_spoke(self) -> None:
        self._last_speech = time.monotonic()

    async def tick(self, *, assistant_active: bool, speech_pending: bool) -> None:
        """Dispatch buffered updates when assistant and user have both been quiet."""
        now = time.monotonic()
        if assistant_active:
            self._last_assistant = now
        if speech_pending:
            self._last_speech = now
        if (not self.bound or assistant_active or speech_pending
                or now - self._last_speech < QUIET_SECONDS or now - self._last_assistant < QUIET_SECONDS):
            return
        if not await interpretation.pending_due(cache_service=self._cache, user_id=self._user_id,
                                                chat_id=self._chat_id):
            return
        events = await interpretation.claim_events(cache_service=self._cache, encryption_service=self._encryption,
                                                   user_id=self._user_id, chat_id=self._chat_id)
        if not events:
            return
        anchor = events[-1]["event_message_id"]
        try:
            await self._issue(anchor)
        except ValueError:
            # The call is no longer active for this chat: the text-only
            # dispatcher answers the updates instead.
            await interpretation.requeue_events(cache_service=self._cache, encryption_service=self._encryption,
                                                user_id=self._user_id, chat_id=self._chat_id, events=events)
            return
        await self._send({"type": "orchestration_turn", "call_id": self._call_id, "message_id": anchor})
        task_id = await interpretation.dispatch_interpretation(
            cache_service=self._cache, directus_service=self._directus, encryption_service=self._encryption,
            user_id=self._user_id, chat_id=self._chat_id, events=events,
            voice_delivery={"voice_mode": True, "voice_call_id": self._call_id, "voice_turn_id": anchor,
                            "voice_heard_boundary": None, "auto_speak_response": True},
        )
        logger.info("Voice call interpreting turn call_id=%s events=%s task=%s",
                    self._call_id, len(events), task_id or "deferred")
        # A busy chat requeues the events; the next quiet tick retries.
        self._last_assistant = now

    async def close(self) -> None:
        """Unbind the call; updates still waiting continue as a text-only turn."""
        if not self.bound:
            return
        self.bound = False
        await interpretation.unbind_call(cache_service=self._cache, user_id=self._user_id,
                                         chat_id=self._chat_id, call_id=self._call_id)
        await interpretation.schedule_dispatch(cache_service=self._cache, user_id=self._user_id,
                                               chat_id=self._chat_id)
