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


def test_public_provider_authority_rejects_shared_paid_and_alternate_ports():
    import pytest
    assert gateway.public_provider_target(b"CONNECT webench.ti.com:443 HTTP/1.1\r\n") == "webench.ti.com"
    for line in (b"CONNECT api.openai.com:443 HTTP/1.1", b"CONNECT api.dev.openmates.org:443 HTTP/1.1",
                 b"CONNECT webench.ti.com:80 HTTP/1.1", b"CONNECT webench.ti.com.evil.test:443 HTTP/1.1",
                 b"GET https://webench.ti.com/ HTTP/1.1", b"CONNECT 127.0.0.1:443 HTTP/1.1"):
        with pytest.raises(ValueError):
            gateway.public_provider_target(line)


def test_public_proxy_rejects_private_dns_before_connect(monkeypatch):
    proxy = gateway.Gateway(('127.0.0.1', 0), gateway.ProviderProxy)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    original = socket.getaddrinfo
    def resolve(host, *args, **kwargs):
        if host == 'webench.ti.com':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        return original(host, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    try:
        with socket.create_connection(proxy.server_address, timeout=5) as client:
            client.sendall(b'CONNECT webench.ti.com:443 HTTP/1.1\r\n\r\n')
            assert b'403 Forbidden' in client.recv(256)
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join()


def test_allowed_connect_preserves_opaque_tls_payload(monkeypatch):
    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(65536):
                self.request.sendall(data)
    upstream = gateway.Gateway(('127.0.0.1', 0), Echo)
    proxy = gateway.Gateway(('127.0.0.1', 0), gateway.ProviderProxy)
    resolve = socket.getaddrinfo
    connect = socket.create_connection
    def lookup(host, *args, **kwargs):
        if host == 'webench.ti.com':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        return resolve(host, *args, **kwargs)
    def open_socket(address, *args, **kwargs):
        return connect(upstream.server_address if address == ('8.8.8.8', 443) else address, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', lookup)
    monkeypatch.setattr(socket, 'create_connection', open_socket)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (proxy, upstream)]
    for thread in threads:
        thread.start()
    try:
        with connect(proxy.server_address, timeout=5) as client:
            client.sendall(b'CONNECT webench.ti.com:443 HTTP/1.1\r\nHost: webench.ti.com:443\r\n\r\n')
            assert b'200 Connection Established' in client.recv(256)
            payload = bytes(range(256)) * 400
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
