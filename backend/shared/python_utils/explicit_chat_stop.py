"""Recognize a narrow, explicit chat stop without treating barge-in as control."""

import re

STOP_CLARIFY = "Which run or task should I stop? Please give its name."
STOP_REQUESTED = (
    "I requested a stop for that assistant task. Any command it already started could still be running."
)
STOP_RUN_REQUESTED = "I requested a stop for that run. It may take a moment to stop."
STOP_RUN_ENDED = "That run has already ended."
STOP_UNCONFIRMED = "I couldn’t confirm a stop for that run or task. It could still be running."
STOP_REPLIES = frozenset({
    STOP_CLARIFY, STOP_REQUESTED, STOP_RUN_REQUESTED, STOP_RUN_ENDED, STOP_UNCONFIRMED,
})

_COMMAND = re.compile(
    r"(?:(?:please|(?:can|could|would) you(?: please)?) )?"
    r"(?:cancel|stop|abort)(?: (?P<label>[a-z0-9][a-z0-9 -]*))?"
)
_KINDS = {"run", "test", "task", "job", "build", "execution", "command"}
_KIND = _KINDS | {f"{kind}s" for kind in _KINDS} | {"work"}
_UNRESOLVED = {"it", "that", "this", "everything", "all", "both", "current", "running", "the", "my"}
_PLAYBACK = {
    "speaking", "talking", "reading", "playing", "responding", "playback", "audio",
    "your audio", "your voice", "reading aloud", "playing audio", "talking for a second",
    "for a second", "for one second", "for a moment", "for a bit", "a second", "a moment",
}


def explicit_stop_label(content: str) -> tuple[str, ...] | None:
    """Return no action, an unresolved stop, or the explicitly named work label."""
    if not isinstance(content, str) or len(content) > 100 or "\n" in content or "\r" in content:
        return None
    normalized = " ".join(content.casefold().strip().rstrip(".!?").split())
    match = _COMMAND.fullmatch(normalized)
    if not match:
        return None
    words = (match["label"] or "").split()
    if words and words[0] in {"the", "my"}:
        words.pop(0)
    if words and words[-1] == "please":
        words.pop()
    if " ".join(words) in _PLAYBACK:
        return None
    if not words or words[-1] not in _KIND:
        return ()
    words.pop()
    if words and words[-1] in _KIND:
        words.pop()
    if (not words or len(words) > 5 or all(word in _UNRESOLVED for word in words)
            or set(words) & {"all", "both", "every", "and", "or", "then", "except", "not", "cancel", "stop", "abort"}):
        return ()
    return tuple(words)
