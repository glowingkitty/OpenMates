"""Bounded JSON-RPC client for the installed Codex app-server daemon.

Uses daemon discovery and the supported Unix WebSocket transport, never storage
edits or server startup. Requests use unique IDs and explicit timeouts; an
uncertain mutation must be reconciled by its caller, never retried blindly.
See docs/architecture/codex-orchestration.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

MAX_FRAME = 16 * 1024 * 1024
TIMEOUT = 15


class CodexRPC:
    def __init__(self):
        result = subprocess.run(
            ["codex", "app-server", "daemon", "version"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=True,
        )
        meta = json.loads(result.stdout)
        path = meta.get("socketPath", "")
        if meta.get("status") != "running" or not Path(path).is_absolute():
            raise RuntimeError("Codex daemon unavailable; start the app explicitly")
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(TIMEOUT)
        self.buffer = b""
        self.sequence = 0
        try:
            self.socket.connect(path)
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall(
                (
                    f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            while b"\r\n\r\n" not in self.buffer:
                data = self.socket.recv(4096)
                if not data or len(self.buffer) > 65536:
                    raise RuntimeError("Invalid Codex handshake")
                self.buffer += data
            head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            expected = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()
            )
            if b" 101 " not in head or expected not in head:
                raise RuntimeError("Codex WebSocket handshake rejected")
            self.call(
                "initialize",
                {
                    "clientInfo": {"name": "openmates_orchestration", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.send({"method": "initialized"})
        except BaseException:
            self.close()
            raise

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def send_frame(self, payload, opcode=1):
        mask = os.urandom(4)
        n = len(payload)
        header = bytes(
            [128 | opcode, 128 | (n if n < 126 else 126 if n < 65536 else 127)]
        )
        if n >= 126:
            header += struct.pack("!H" if n < 65536 else "!Q", n)
        self.socket.sendall(
            header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
        )

    def send(self, value):
        self.send_frame(json.dumps(value).encode())

    def exact(self, n):
        while len(self.buffer) < n:
            data = self.socket.recv(min(MAX_FRAME, max(4096, n - len(self.buffer))))
            if not data:
                raise RuntimeError("Codex connection closed")
            self.buffer += data
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def receive(self):
        payload = b""
        while True:
            a, b = self.exact(2)
            n = b & 127
            if n == 126:
                n = struct.unpack("!H", self.exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self.exact(8))[0]
            if n + len(payload) > MAX_FRAME:
                raise RuntimeError("Codex response exceeds bounded frame size")
            mask = self.exact(4) if b & 128 else None
            data = self.exact(n)
            if mask:
                data = bytes(v ^ mask[i % 4] for i, v in enumerate(data))
            op = a & 15
            if op == 8:
                raise RuntimeError("Codex closed WebSocket")
            if op == 9:
                self.send_frame(data, 10)
                continue
            if op == 10:
                continue
            payload += data
            if a & 128:
                return json.loads(payload)

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.1, deadline - time.monotonic()))
            response = self.receive()
            if response.get("id") != request_id:
                continue
            if "error" in response:
                # Error bodies may contain private prompts. Return the code only.
                raise RuntimeError(
                    f"Codex {method} rejected: {response['error'].get('code')}"
                )
            return response.get("result", {})
        raise TimeoutError(
            f"Codex {method} acceptance uncertain; reconcile before retry"
        )
