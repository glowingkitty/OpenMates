"""Per-call special terms (names, product words) sent as speech-recognition hints.

The list is stored client-encrypted with the chat. The call device sends it in
plaintext over the authenticated call WebSocket, the same exposure as the call
audio. The server keeps it in memory for that call only and never logs it.
"""

from typing import Any

MAX_TERMS = 50
MAX_TERM_CHARS = 64


def parse_terms(event: dict[str, Any]) -> list[str]:
    """Validate an ``stt_terms`` frame; raise ValueError on any malformed entry."""
    raw = event.get("terms")
    if not isinstance(raw, list) or len(raw) > MAX_TERMS:
        raise ValueError("Invalid terms")
    terms: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("Invalid term")
        term = " ".join(item.split())
        if not term or len(term) > MAX_TERM_CHARS or not term.isprintable():
            raise ValueError("Invalid term")
        if term.casefold() not in {t.casefold() for t in terms}:
            terms.append(term)
    return terms
