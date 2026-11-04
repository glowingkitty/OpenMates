"""Bounded HTTP and `gh api` fetching for the hourly security watcher.

`default_fetch(url, options)` is the production implementation of the
injectable `fetch` callable used by `sources.collect`. URLs starting with
`gh:` run `gh api <path>` (paginated, one JSON value per line); everything
else is an HTTPS request with timeouts, a fixed User-Agent and a response size
bound. Failures raise `FetchError` with a sanitized error code, never a raw
exception message. See security-monitoring.sources.hourly-deterministic.
"""

from __future__ import annotations

import json
import socket
import subprocess
from typing import Any, Mapping
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; OpenMates-security-monitor/1; +https://openmates.org)"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
GH_TIMEOUT_SECONDS = 120


class FetchError(RuntimeError):
    """A source request failed; `code` is a short sanitized reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _gh(path: str, options: Mapping[str, Any]) -> Any:
    command = ["gh", "api", path, "-H", "Accept: application/vnd.github+json"]
    paginate = options.get("paginate", True)
    if paginate:
        command += ["--paginate", "--jq", ".[]"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=float(options.get("timeout", GH_TIMEOUT_SECONDS)), check=False)
    except FileNotFoundError as error:
        raise FetchError("gh_unavailable") from error
    except subprocess.TimeoutExpired as error:
        raise FetchError("timeout") from error
    if result.returncode != 0:
        lowered = (result.stderr or "").lower()
        if "404" in lowered or "not found" in lowered:
            raise FetchError("http_404")
        if "403" in lowered or "forbidden" in lowered or "rate limit" in lowered:
            raise FetchError("http_403")
        if "auth" in lowered or "401" in lowered:
            raise FetchError("gh_auth")
        raise FetchError("gh_error")
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise FetchError("too_large")
    try:
        if paginate:
            return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as error:
        raise FetchError("invalid_json") from error


def default_fetch(url: str, options: Mapping[str, Any] | None = None) -> Any:
    """Fetch one URL. options: method, json (request body), format (json|text), timeout."""
    options = options or {}
    if url.startswith("gh:"):
        return _gh(url[3:], options)
    if not url.startswith("https://"):
        raise FetchError("insecure_url")
    body = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, */*"}
    if options.get("json") is not None:
        body = json.dumps(options["json"]).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=str(options.get("method", "POST" if body else "GET")))
    try:
        with urllib.request.urlopen(request, timeout=float(options.get("timeout", DEFAULT_TIMEOUT_SECONDS))) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise FetchError(f"http_{error.code}") from error
    except (TimeoutError, socket.timeout) as error:
        raise FetchError("timeout") from error
    except urllib.error.URLError as error:
        raise FetchError("timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "network_error") from error
    except OSError as error:
        raise FetchError("network_error") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise FetchError("too_large")
    text = raw.decode("utf-8", errors="replace")
    if options.get("format", "json") == "text":
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise FetchError("invalid_json") from error
