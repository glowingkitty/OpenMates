"""Brevo API calls from the dev host over IPv4 only.

The Brevo account accepts API calls only from its authorised IP list. The dev
host prefers IPv6, and its IPv6 address is not on that list, so direct host
calls (test-run alert emails, audit summaries, the signup email smoke) failed
with HTTP 401 "unrecognised IP address" although the key was valid (TASK-427).
The host's IPv4 egress is authorised, as is every container. Host scripts that
call api.brevo.com open their connection through ``urlopen`` here.
Architecture: docs/architecture/infrastructure/transactional-email-monitoring.md
"""

from __future__ import annotations

import http.client
import socket
import urllib.request
from typing import Any


def _create_ipv4_connection(address: tuple[str, int], timeout: Any = None, source_address: Any = None) -> socket.socket:
    """socket.create_connection, restricted to the host's IPv4 addresses."""
    host, port = address
    last_error: OSError | None = None
    for _family, _type, _proto, _name, sockaddr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        try:
            return socket.create_connection(sockaddr, timeout, source_address)
        except OSError as exc:
            last_error = exc
    raise last_error or OSError(f"no IPv4 address for {host}")


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _create_ipv4_connection


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(_IPv4HTTPSHandler())


def urlopen(request: urllib.request.Request | str, timeout: float = 30) -> Any:
    """Drop-in for urllib.request.urlopen that never connects over IPv6."""
    return _OPENER.open(request, timeout=timeout)
