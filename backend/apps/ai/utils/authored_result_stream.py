"""Incremental reading of a streaming ``openmates_embeds`` block, item by item.

The assistant writes the block over many stream chunks. ``AuthoredResultsStreamParser``
scans the JSON text as it arrives (chunks may split anywhere, including inside a
string or an escape) and returns each entry of the top-level ``items`` array as
soon as that entry's JSON value is complete. ``ProgressiveEnvelope`` then
validates each entry with the same per-entry normalization the closed block uses
(``normalize_authored_result_entry``), so a card published while streaming is
the card the one-shot path produces for the same source.

Progressive output is only a preview of the final result. Whenever the partial
text already proves the closed block would be rejected as a whole (wrong
``schemaVersion``, unknown or repeated top-level field, a duplicate JSON field,
size limit), the envelope stops offering entries; the caller then relies on the
closed block alone. Labels repeated later invalidate every occurrence, so the
caller must drop an earlier published label listed in ``duplicated_labels``.
This module performs no I/O and holds no secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from backend.apps.ai.utils.authored_result_fences import (
    AuthoredResultEntry,
    normalize_authored_result_entry,
    parse_authored_results_json,
)

_ENVELOPE_FIELDS = frozenset({"schemaVersion", "title", "items", "view"})
_WHITESPACE = frozenset(" \t\r\n")


@dataclass(frozen=True)
class StreamedEntry:
    """One complete raw entry of ``items`` in source order."""

    index: int
    raw: str


class AuthoredResultsStreamParser:
    """Character scanner over the block body that yields complete ``items`` entries.

    ``feed`` accepts any split of the text. Entries are returned once the
    envelope has shown ``"schemaVersion": 1``; entries completed earlier are held
    back until then. ``abandoned`` becomes true when the text can no longer be a
    valid envelope; afterwards nothing more is returned.
    """

    def __init__(self, *, source_byte_limit: int) -> None:
        self._source_byte_limit = source_byte_limit
        self._text = ""
        self._bytes = 0
        self._pos = 0
        self._stack: list[str] = []
        self._in_string = False
        self._escape = False
        self._string_start = 0
        # Depth-1 (envelope) state: "key", "colon", "value", "in_value", "comma".
        self._expect = "key"
        self._key: str | None = None
        self._seen_keys: set[str] = set()
        self._value_start: int | None = None
        self._element_start: int | None = None
        self._element_index = 0
        self._held: list[StreamedEntry] = []
        self.items_state = "absent"
        self.schema_version_ok = False
        self.title: str | None = None
        self.abandoned = False
        self.closed = False

    @property
    def text(self) -> str:
        """All text fed so far."""
        return self._text

    @property
    def items_open(self) -> bool:
        """True while the ``items`` array is open, so more entries may follow."""
        return self.items_state == "open" and not self.abandoned

    def feed_source(self, source: str) -> list[StreamedEntry]:
        """Feed the whole text so far; only the unseen suffix is scanned.

        The stream consumer passes the accumulated block each time. A source that
        no longer extends the text already read cannot be followed safely.
        """
        if not source.startswith(self._text):
            self.abandon()
            return []
        return self.feed(source[len(self._text):])

    def feed(self, chunk: str) -> list[StreamedEntry]:
        """Scan one more chunk and return entries that became available."""
        if self.abandoned or not chunk:
            return []
        self._bytes += len(chunk.encode("utf-8"))
        if self._bytes > self._source_byte_limit:
            self.abandon()
            return []
        self._text += chunk
        ready: list[StreamedEntry] = []
        while self._pos < len(self._text) and not self.abandoned:
            self._step(self._text[self._pos], ready)
            self._pos += 1
        if self.abandoned:
            return []
        if self.schema_version_ok:
            ready, self._held = [*self._held, *ready], []
            return ready
        self._held.extend(ready)
        return []

    def abandon(self) -> None:
        """Stop offering entries; the closed block alone decides the result."""
        self.abandoned = True
        self._held = []

    def _step(self, char: str, ready: list[StreamedEntry]) -> None:
        position = self._pos
        if self._in_string:
            if self._escape:
                self._escape = False
            elif char == "\\":
                self._escape = True
            elif char == '"':
                self._in_string = False
                if len(self._stack) == 1 and self._expect == "key":
                    self._on_key(self._text[self._string_start:position + 1])
            return
        if char in _WHITESPACE:
            return
        if self.closed:
            # Trailing text makes the closed envelope invalid JSON.
            self.abandon()
            return
        depth = len(self._stack)
        if depth == 0:
            if char != "{":
                self.abandon()
                return
            self._stack.append("{")
            return
        if depth == 1:
            self._step_envelope(char, position)
            return
        if depth == 2 and self._items_container():
            if self._element_start is None:
                if char == "]":
                    self._stack.pop()
                    self.items_state = "closed"
                    self._expect = "comma"
                    return
                if char == ",":
                    return
                self._element_start = position
            elif char in ",]":
                # A scalar element ends at the next separator.
                self._emit(self._text[self._element_start:position].strip(), ready)
                if char == "]":
                    self._stack.pop()
                    self.items_state = "closed"
                    self._expect = "comma"
                return
        self._step_container(char, position, ready)

    def _items_container(self) -> bool:
        return self._key == "items" and self._stack == ["{", "["]

    def _step_envelope(self, char: str, position: int) -> None:
        if self._expect == "key":
            if char == '"':
                self._in_string = True
                self._string_start = position
            elif char == "}" and not self._seen_keys:
                self._close_envelope()
            else:
                self.abandon()
        elif self._expect == "colon":
            if char == ":":
                self._expect = "value"
            else:
                self.abandon()
        elif self._expect == "value":
            self._value_start = position
            self._expect = "in_value"
            if self._key == "items":
                if char != "[":
                    self.abandon()
                    return
                self.items_state = "open"
            if char in "{[":
                self._stack.append(char)
            elif char == '"':
                self._in_string = True
                self._string_start = position
        elif self._expect == "in_value":
            if char in ",}":
                self._on_value(self._text[self._value_start:position].strip())
                if char == "}":
                    self._close_envelope()
                else:
                    self._expect = "key"
            # Other characters continue a number or literal.
        elif self._expect == "comma":
            if char == ",":
                self._expect = "key"
            elif char == "}":
                self._close_envelope()
            else:
                self.abandon()

    def _step_container(self, char: str, position: int, ready: list[StreamedEntry]) -> None:
        if char == '"':
            self._in_string = True
            self._string_start = position
        elif char in "{[":
            self._stack.append(char)
        elif char in "}]":
            opener = self._stack.pop()
            if (opener, char) not in {("{", "}"), ("[", "]")}:
                self.abandon()
                return
            if len(self._stack) == 2 and self._items_container() and self._element_start is not None:
                self._emit(self._text[self._element_start:position + 1], ready)
            elif len(self._stack) == 1:
                # A container value of the envelope (``view``) is complete.
                self._on_value(self._text[self._value_start:position + 1])
                self._expect = "comma"

    def _emit(self, raw: str, ready: list[StreamedEntry]) -> None:
        ready.append(StreamedEntry(self._element_index, raw))
        self._element_index += 1
        self._element_start = None

    def _on_key(self, raw_key: str) -> None:
        try:
            key = parse_authored_results_json(raw_key)
        except (ValueError, RecursionError):
            self.abandon()
            return
        if key not in _ENVELOPE_FIELDS or key in self._seen_keys:
            self.abandon()
            return
        self._seen_keys.add(key)
        self._key = key
        self._expect = "colon"

    def _on_value(self, raw_value: str) -> None:
        if self._key == "items":
            return
        try:
            value = parse_authored_results_json(raw_value)
        except (ValueError, RecursionError):
            self.abandon()
            return
        if self._key == "schemaVersion":
            if type(value) is not int or value != 1:
                self.abandon()
                return
            self.schema_version_ok = True
        elif self._key == "title" and isinstance(value, str) and value.strip():
            self.title = value.strip()

    def _close_envelope(self) -> None:
        self._stack.pop()
        self.closed = True
        if self.items_state == "open":
            self.abandon()


@dataclass
class ProgressiveEnvelope:
    """Validate streamed entries in order with the closed block's per-entry rules."""

    source_byte_limit: int
    item_limit: int
    parser: AuthoredResultsStreamParser = field(init=False)
    seen_labels: set[str] = field(default_factory=set)
    duplicated_labels: set[str] = field(default_factory=set)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.parser = AuthoredResultsStreamParser(source_byte_limit=self.source_byte_limit)

    @property
    def abandoned(self) -> bool:
        """True once the closed block can no longer be a valid envelope."""
        return self.parser.abandoned

    @property
    def pending(self) -> bool:
        """True while more entries can still arrive."""
        return self.parser.items_open

    def feed_source(self, source: str) -> list[AuthoredResultEntry]:
        """Return newly complete, individually valid entries of ``source``."""
        accepted: list[AuthoredResultEntry] = []
        for streamed in self.parser.feed_source(source):
            try:
                raw = parse_authored_results_json(streamed.raw)
            except (ValueError, RecursionError):
                # Malformed or ambiguous JSON makes the closed block invalid.
                self.parser.abandon()
                return []
            label = raw.get("id") if isinstance(raw, dict) else None
            duplicate = isinstance(label, str) and label in self.seen_labels
            if isinstance(label, str):
                # Entries past the limit still invalidate a repeated label.
                if duplicate:
                    self.duplicated_labels.add(label)
                self.seen_labels.add(label)
            if streamed.index >= self.item_limit:
                continue
            entry = normalize_authored_result_entry(
                raw, streamed.index, self.warnings, duplicate_label=duplicate,
            )
            if entry is not None:
                accepted.append(entry)
        return accepted

