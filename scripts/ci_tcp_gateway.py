"""Expose isolated container endpoints to the GitHub runner without app egress.

The gateway has no credentials or application behavior. It forwards raw TCP
between loopback-published ports and fixed API/CMS services on the internal
Docker network, retaining HTTP, streaming and WebSocket semantics unchanged.
Only the gateway joins the ingress bridge; application services remain internal.
See docs/architecture/isolated-github-tests.md.
"""

import os
import ipaddress
import select
import socket
import socketserver
import threading

TARGETS = {8000: ("api", 8000), 8055: ("cms", 8055)}


PUBLIC_PROVIDER_HOSTS = frozenset({"webench.ti.com"})
PROVIDER_PROXY_PORT = 3128
MAX_PROXY_HEADER = 16384


def relay(client, upstream):
    client.settimeout(60)
    upstream.settimeout(60)
    sockets = [client, upstream]
    while True:
        ready, _, _ = select.select(sockets, [], [], 60)
        if not ready:
            return
        for stream in ready:
            data = stream.recv(65536)
            if not data:
                return
            (upstream if stream is client else client).sendall(data)


def public_provider_target(line: bytes) -> str:
    """Only fixed credential-free HTTPS authorities; no general forward proxy."""
    parts = line.decode("ascii").strip().split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] != "HTTP/1.1":
        raise ValueError("Only HTTPS CONNECT is supported")
    host, separator, port = parts[1].rpartition(":")
    if separator != ":" or port != "443" or host not in PUBLIC_PROVIDER_HOSTS:
        raise ValueError("Provider destination is not approved")
    return host


class ProviderProxy(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            line = self.rfile.readline(MAX_PROXY_HEADER + 1)
            host = public_provider_target(line)
            size = len(line)
            while True:
                header = self.rfile.readline(MAX_PROXY_HEADER + 1)
                size += len(header)
                if size > MAX_PROXY_HEADER or not header:
                    raise ValueError("Invalid CONNECT headers")
                if header == b"\r\n":
                    break
            # Resolve once, reject private/rebound answers, and connect to that
            # exact IP. End-to-end TLS/certificate validation stays with httpx.
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError("Provider did not resolve to public addresses")
            address = (addresses[0][4][0], 443)
        except (ValueError, UnicodeError, OSError):
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        try:
            upstream = socket.create_connection(address, timeout=10)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        with upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            relay(self.request, upstream)


class Forwarder(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(TARGETS[self.server.server_address[1]], timeout=10) as upstream:
            relay(self.request, upstream)


class Gateway(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if os.environ.get("OPENMATES_CI_GATEWAY") != "github-isolated":
        raise RuntimeError("Gateway is only supported inside the isolated CI profile")
    servers = [Gateway(("0.0.0.0", port), Forwarder) for port in TARGETS]
    if os.environ.get("OPENMATES_CI_PUBLIC_PROVIDER_PROXY") == "1":
        servers.append(Gateway(("0.0.0.0", PROVIDER_PROXY_PORT), ProviderProxy))
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()
