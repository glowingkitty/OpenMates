"""Bounded app-server RPC requests using synthetic WebSocket frames."""

# contract-test-file: tooling
import json
import pytest

from scripts import codex_rpc


def frame(value):
    payload = json.dumps(value).encode()
    assert len(payload) < 126
    return bytes([0x81, len(payload)]) + payload


class Socket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.pending = b""
        self.timeout = None
        self.send_timeouts = []

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, _data):
        self.send_timeouts.append(self.timeout)

    def recv(self, size):
        if not self.pending:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            self.pending = response
        part, self.pending = self.pending[:size], self.pending[size:]
        return part


def client(sock):
    rpc = codex_rpc.CodexRPC.__new__(codex_rpc.CodexRPC)
    rpc.socket = sock
    rpc.buffer = b""
    rpc.sequence = 0
    rpc.notifications = []
    return rpc


# contract-test: tooling
def test_per_call_timeout_resets_and_late_complete_response_is_ignored():
    sock = Socket([TimeoutError("slow read"),
                   frame({"id": 1, "result": {"late": True}})
                   + frame({"id": 2, "result": {"current": True}})])
    rpc = client(sock)
    with pytest.raises(TimeoutError):
        rpc.call("thread/list", {}, timeout=0.05)
    assert sock.send_timeouts[0] == 0.05
    assert rpc.call("thread/list", {}) == {"current": True}
    assert sock.send_timeouts[1] == codex_rpc.TIMEOUT


# contract-test: tooling
def test_nonpositive_timeout_never_sends_request():
    sock = Socket([])
    rpc = client(sock)
    with pytest.raises(TimeoutError):
        rpc.call("thread/list", {}, timeout=0)
    assert not sock.send_timeouts


# contract-test: tooling
def test_deadline_is_checked_across_fragmented_frame(monkeypatch):
    moment = [0.0]
    monkeypatch.setattr(codex_rpc.time, "monotonic", lambda: moment[0])

    class SlowSocket(Socket):
        def recv(self, _size):
            moment[0] += 0.3
            if not self.pending:
                self.pending = self.responses.pop(0)
            part, self.pending = self.pending[:1], self.pending[1:]
            return part

    rpc = client(SlowSocket([frame({"id": 1, "result": {"ok": True}})]))
    with pytest.raises(TimeoutError, match="deadline"):
        rpc.call("thread/list", {}, timeout=0.5)
    assert moment[0] <= 0.6
