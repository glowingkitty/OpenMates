"""Expose isolated container endpoints to the GitHub runner without app egress.

The gateway has no credentials or application behavior. It forwards raw TCP
between loopback-published ports and fixed API/CMS services on the internal
Docker network, retaining HTTP, streaming and WebSocket semantics unchanged.
Only the gateway joins the ingress bridge; application services remain internal.
See docs/architecture/isolated-github-tests.md.
"""

import os
import select
import socket
import socketserver
import threading

TARGETS = {8000: ("api", 8000), 8055: ("cms", 8055)}


class Forwarder(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(TARGETS[self.server.server_address[1]], timeout=10) as upstream:
            self.request.settimeout(60)
            upstream.settimeout(60)
            sockets = [self.request, upstream]
            while True:
                ready, _, _ = select.select(sockets, [], [], 60)
                if not ready:
                    return
                for stream in ready:
                    data = stream.recv(65536)
                    if not data:
                        return
                    destination = upstream if stream is self.request else self.request
                    destination.sendall(data)


class Gateway(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if os.environ.get("OPENMATES_CI_GATEWAY") != "github-isolated":
        raise RuntimeError("Gateway is only supported inside the isolated CI profile")
    servers = [Gateway(("0.0.0.0", port), Forwarder) for port in TARGETS]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()
