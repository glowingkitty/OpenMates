# Wellbeing layer: shared contract between lanes

Owner decision 10. Specification: `specifications/features/wellbeing-support/`.

## Signals (scored 0..1 inside the existing preprocessing decision call)
`suicidal`, `method_or_means`, `plan_or_timeline`, `self_harm`, `self_injury_now`, `hopelessness_isolation`,
`eating_disorder`, `reality_loss`, `mania`, `danger_from_others`.
The score is about the USER's own current state, judged from the conversation so far; fiction,
roleplay, lyrics, research, gaming, idioms, dark humour and worry about someone else score 0.

## Per-chat history (client-encrypted)
- Server -> client: `user_cache_events` event `wellbeing_scores_updated`
  `{"chat_id": str, "scores": [{"t": int unix seconds, "s": {signal: float}}]}`, newest last, at most 8 entries,
  floats rounded to 2 decimals. An empty list clears the history.
- The server emits it only when the current turn has a signal >= 0.2 or the incoming history was non-empty.
- Client stores it as chat field `encrypted_wellbeing_scores` (same path as `encrypted_focus_phase_state`).
- Client -> server: inference payload key `wellbeing_scores` (same list), transient, never stored or logged.

## Level (server, per request, not stored)
0 none, 1 elevated (gentle check-in instruction), 2 high (helpline card, support before the task),
3 acute (helpline card at once, encourage reaching someone now). Computed by
`backend/apps/ai/processing/wellbeing_level.py` from the history plus the current scores.

## Helpline card
An embed of type `helplines`, created server-side (finished, vault-encrypted TOON, delivered like any direct embed) and referenced
by a ```json {"type": "helplines", "embed_id": ...}``` block at the very start of the assistant message.
No custom WebSocket event exists for the card. Content:
`{"country": "DE", "language": "de", "lines": [{"name": str, "phone": str|null, "sms": str|null,
"chat_url": str|null, "hours": str|null, "topics": [str]}], "emergency_number": "112",
"directory_url": "https://findahelpline.com", "source": "throughline"|"emergency_only"}`.
Lines come from the helpline-directory API when its key is configured; otherwise `lines` is empty
and the card shows the emergency number and the directory link.

## Never
No blocking, no lecturing, no strike, no server-side per-user storage, no memory writes;
only an anonymous daily counter (`wellbeing:card_shown:<YYYY-MM-DD>`, `wellbeing:checkin:<YYYY-MM-DD>`).
