"""Typed raw file download result for the Python SDK (Rust ``sdk_ops::RawDownload``).

Billing invoice PDFs, credit notes and usage exports are returned as
``RawDownload`` instead of a plain dict, matching the Rust SDK type and the npm
``RawDownload`` shape. The download filename follows one cross-SDK contract
(``filename_from_disposition``), proved by the shared ``sdk.billing`` vectors in
``tests/sdk-conformance/fixtures/sdk-api-key-wire.json``.

Compatibility: up to 0.30.0 these methods returned
``{"content_type", "filename", "data"}`` dicts. ``RawDownload`` keeps read-only
mapping access for exactly those keys (``raw["data"]``, ``raw.get(...)``,
``dict(raw)``), so existing callers keep working; prefer the attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from string import hexdigits
from typing import Any

_ENCODED = re.compile(r"filename\*=UTF-8''([^;]+)")
_PLAIN = re.compile(r'filename="?([^";]+)"?')
_KEYS = ("content_type", "filename", "data")


@dataclass(frozen=True)
class RawDownload:
    """Raw file response; the body bytes are never interpreted."""

    content_type: str
    filename: str | None
    data: bytes

    def __getitem__(self, key: str) -> Any:
        # Legacy dict access (0.30.0 returned a dict with exactly these keys).
        if key not in _KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: object) -> bool:
        return key in _KEYS

    def get(self, key: str, default: Any = None) -> Any:
        """Legacy ``dict.get`` access for the three result keys."""
        return getattr(self, key) if key in _KEYS else default

    def keys(self) -> tuple[str, ...]:
        """Legacy mapping keys, so ``dict(raw)`` yields the 0.30.0 dict."""
        return _KEYS


def _percent_decode(value: str) -> str | None:
    """Strict UTF-8 percent decoding; malformed input yields None (npm decodeURIComponent throws)."""
    out = bytearray()
    index = 0
    while index < len(value):
        if value[index] == "%":
            pair = value[index + 1 : index + 3]
            if len(pair) != 2 or not all(char in hexdigits for char in pair):
                return None
            out.append(int(pair, 16))
            index += 3
        else:
            out.extend(value[index].encode("utf-8"))
            index += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return None


def filename_from_disposition(header: str | None) -> str | None:
    """Shared download filename contract (Rust ``sdk_ops::filename``, npm ``extractFilename``).

    ``filename*=UTF-8''`` (percent-decoded) wins over ``filename=``; a malformed
    encoded name yields None. Only the last path component is kept, so a server
    cannot steer a caller that saves by filename outside its directory, and an
    empty, ``.`` or ``..`` name yields None.
    """
    if not header:
        return None
    encoded = _ENCODED.search(header)
    if encoded:
        name = _percent_decode(encoded.group(1))
    else:
        plain = _PLAIN.search(header)
        name = plain.group(1) if plain else None
    if name is None:
        return None
    base = re.split(r"[/\\]", name)[-1]
    return None if base in ("", ".", "..") else base
