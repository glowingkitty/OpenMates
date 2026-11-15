"""Minimal client for the local Gatus API (read statuses, push external results)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Iterable, Mapping

from .alerts import CheckResult

TIMEOUT_S = 10


class GatusError(RuntimeError):
    """Gatus could not be read or did not accept a pushed result."""


def parse_timestamp(value: str) -> float:
    """Parse Gatus' RFC 3339 timestamps (nanosecond precision allowed)."""
    text = value.strip().replace("Z", "+00:00")
    main, _, rest = text.partition(".")
    if rest:
        digits = "".join(ch for ch in rest if ch.isdigit())
        zone = rest[len(digits):]
        text = f"{main}.{digits[:6]}{zone}"
    return datetime.fromisoformat(text).timestamp()


def parse_statuses(payload: Any) -> dict[str, tuple[CheckResult, ...]]:
    """Map each Gatus endpoint key to its results, oldest first."""
    if not isinstance(payload, list):
        raise GatusError("unexpected statuses payload")
    parsed: dict[str, tuple[CheckResult, ...]] = {}
    for endpoint in payload:
        key = endpoint.get("key")
        if not isinstance(key, str):
            continue
        results = [CheckResult(parse_timestamp(r["timestamp"]), bool(r.get("success")))
                   for r in endpoint.get("results") or [] if isinstance(r.get("timestamp"), str)]
        parsed[key] = tuple(sorted(results, key=lambda r: r.timestamp))
    return parsed


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
        return json.load(response)


def fetch_statuses(base_url: str, external_keys: Iterable[str] = (), page_size: int = 100
                   ) -> dict[str, tuple[CheckResult, ...]]:
    """Read every endpoint's recent results from Gatus.

    Gatus' list route leaves out external endpoints (verified against v5.38.0),
    so each of ``external_keys`` is read from its own statuses route.
    """
    base = base_url.rstrip("/")
    try:
        parsed = parse_statuses(_get_json(f"{base}/api/v1/endpoints/statuses?page=1&pageSize={page_size}"))
        for key in external_keys:
            if key in parsed:
                continue
            try:
                one = _get_json(f"{base}/api/v1/endpoints/{urllib.parse.quote(key)}/statuses?page=1&pageSize={page_size}")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:  # no result pushed yet
                    continue
                raise
            parsed.update(parse_statuses([one]))
        return parsed
    except (OSError, ValueError) as exc:
        raise GatusError(f"cannot read Gatus statuses: {type(exc).__name__}") from exc


def push_external(base_url: str, key: str, token: str, success: bool, error: str = "",
                  duration_s: float | None = None) -> None:
    """Report one result for a Gatus external endpoint."""
    query: Mapping[str, str] = {"success": "true" if success else "false"}
    if error:
        query = {**query, "error": error[:200]}
    if duration_s is not None:
        query = {**query, "duration": f"{max(duration_s, 0):.3f}s"}
    url = f"{base_url.rstrip('/')}/api/v1/endpoints/{urllib.parse.quote(key)}/external?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, method="POST", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            if response.status >= 300:
                raise GatusError(f"Gatus rejected result for {key}: HTTP {response.status}")
    except OSError as exc:
        raise GatusError(f"cannot push result for {key}: {type(exc).__name__}") from exc
