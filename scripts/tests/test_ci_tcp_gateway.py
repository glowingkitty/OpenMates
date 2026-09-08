# contract-test-file: tooling
"""Verify the runner gateway preserves arbitrary protocol bytes.

The fixture uses two synthetic local TCP servers, no OpenMates application,
Docker service, browser, provider or account. A payload larger than a forwarding
buffer checks byte order across multiple reads without HTTP-specific behavior.
See docs/architecture/isolated-github-tests.md.
"""

import socket
import socketserver
import threading
from scripts import ci_tcp_gateway as gateway


def test_gateway_preserves_multiple_binary_buffers(monkeypatch):
    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(65536):
                self.request.sendall(data)
    upstream = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Echo)
    proxy = gateway.Gateway(('127.0.0.1', 0), gateway.Forwarder)
    monkeypatch.setitem(gateway.TARGETS, proxy.server_address[1], upstream.server_address)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, proxy)]
    for thread in threads:
        thread.start()
    try:
        payload = bytes(range(256)) * 400
        with socket.create_connection(proxy.server_address, timeout=5) as client:
            client.sendall(payload)
            received = b''
            while len(received) < len(payload):
                received += client.recv(65536)
            assert received == payload
    finally:
        for server in (proxy, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()
