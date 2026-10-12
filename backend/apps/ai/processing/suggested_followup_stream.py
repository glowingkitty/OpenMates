"""Extract optional trailing composer metadata from authored model text.

Only a standalone marker outside a fenced block can start metadata. The parser
withholds delimiter prefixes across arbitrary provider chunk boundaries, so no
part of a recognized metadata block reaches the answer stream or tool history.
"""

OPEN = "<<suggested_followup_message>>"
CLOSE = "<</suggested_followup_message>>"
MAX_SUGGESTION_CHARS = 400


class SuggestedFollowupStream:
    def __init__(self) -> None:
        self._state = "answer"
        self._candidate = ""
        self._metadata = ""
        self._close_candidate = ""
        self._line = ""
        self._fenced = False
        self._valid = True
        self._suggestion: str | None = None

    @property
    def suggestion(self) -> str | None:
        return self._suggestion if self._state == "closed" and self._valid else None

    def _emit(self, value: str) -> str:
        for char in value:
            if char == "\n":
                if self._line.lstrip().startswith(("```", "~~~")):
                    self._fenced = not self._fenced
                self._line = ""
            else:
                self._line += char
                if len(self._line) > 128:
                    self._line = self._line[-128:]
        return value

    def feed(self, chunk: str) -> str:
        answer: list[str] = []
        for char in chunk:
            if self._state == "closed":
                if not char.isspace():
                    self._valid = False
                continue
            if self._state == "metadata":
                candidate = self._close_candidate + char
                if CLOSE.startswith(candidate):
                    self._close_candidate = candidate
                    if candidate == CLOSE:
                        self._state = "closed"
                        self._close_candidate = ""
                        value = self._metadata.strip()
                        if not value or len(value) > MAX_SUGGESTION_CHARS or OPEN in value:
                            self._valid = False
                        else:
                            self._suggestion = value
                    continue
                if len(self._metadata) <= MAX_SUGGESTION_CHARS + len(CLOSE):
                    self._metadata += self._close_candidate + char
                self._close_candidate = ""
                if len(self._metadata) > MAX_SUGGESTION_CHARS + len(CLOSE):
                    self._valid = False
                continue
            if self._candidate:
                candidate = self._candidate + char
                if OPEN.startswith(candidate):
                    self._candidate = candidate
                    if candidate == OPEN:
                        self._candidate = ""
                        self._state = "metadata"
                    continue
                answer.append(self._emit(self._candidate))
                self._candidate = ""
            if not self._fenced and not self._line and char == OPEN[0]:
                self._candidate = char
            else:
                answer.append(self._emit(char))
        return "".join(answer)

    def finish(self) -> str:
        if self._state == "answer" and self._candidate:
            pending = self._emit(self._candidate)
            self._candidate = ""
            return pending
        # An unfinished metadata block is dropped, including a partial closer.
        return ""

def may_publish_suggested_followup(
    request_data,
    *,
    suggestion: str | None,
    response: str,
    is_error: bool,
    is_server_error: bool,
    stream_exception: Exception | None,
    terminal_failure_reason: str | None,
    was_revoked: bool,
    was_soft_limited: bool,
) -> bool:
    """Only successful, final, private-chat turns may expose composer metadata."""
    return bool(
        suggestion
        and 0 < len(suggestion) <= 400
        and response.strip()
        and not is_error
        and not is_server_error
        and stream_exception is None
        and terminal_failure_reason is None
        and not was_revoked
        and not was_soft_limited
        and not request_data.is_sub_chat
        and not request_data.is_sub_chat_continuation
        and not request_data.is_incognito
        and not request_data.is_async_skill_continuation
        and not request_data.awaiting_async_skill_continuation
        and not request_data.is_external
        and (request_data.user_preferences or {}).get("follow_up_suggestions_enabled", True) is not False
    )
