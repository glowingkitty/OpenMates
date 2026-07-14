"""Provider thought-signature serialization helpers.

Purpose: keep Gemini/Anthropic thinking signatures JSON-safe before they are
stored in cross-provider message history. Provider clients can import this pure
helper without pulling in each other's SDK dependencies.
Security: signatures are opaque provider verification bytes, not user content.
"""

from __future__ import annotations

import base64
from typing import Any


def serialize_thought_signature(signature: Any) -> str | None:
    if signature is None:
        return None
    if isinstance(signature, bytes):
        return base64.b64encode(signature).decode("utf-8")
    if isinstance(signature, str):
        return signature
    return None
