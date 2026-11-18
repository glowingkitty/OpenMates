#!/usr/bin/env python3
# contract-test-file: tooling
"""Receipt check of scripts/owner_message.py against a fake broker socket (tooling test, no network)."""

import json
import socket
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import owner_message as om  # noqa: E402

CHAT = "6f9e5f06-0000-4000-8000-000000000001"
VALID = f"VALID\nchat: {CHAT}\nsent: 2026-11-13T12:00:00Z\ntext: confirm production update"


@pytest.fixture
def broker(monkeypatch):
    """A one-request-at-a-time Unix socket that answers like the connector broker."""
    folder = tempfile.mkdtemp()
    path = Path(folder) / "broker.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen()
    answers = {"r1": {"ok": True, "text": VALID},
               "gone": {"ok": True, "text": "INVALID: no such receipt."}}
    seen = []

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                request = json.loads(conn.makefile().readline())
                seen.append(request)
                conn.sendall(json.dumps(answers[request["args"]["receipt"]]).encode() + b"\n")

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(om, "SOCKET", path)
    monkeypatch.setattr(om.ask_broker, "__defaults__", (path,))
    yield seen
    server.close()


def test_valid_receipt_for_this_chat_is_verified(broker, capsys):
    assert om.main(["verify", "r1", "--chat", CHAT]) == 0
    out = capsys.readouterr().out
    assert out.startswith("VERIFIED")
    assert out.rstrip().endswith("confirm production update")
    assert broker == [{"verb": "verify_message", "args": {"receipt": "r1"}}]


def test_receipt_of_another_chat_is_refused(broker, capsys):
    assert om.main(["verify", "r1", "--chat", "aaaaaaaa-other"]) == 1
    assert "not this chat" in capsys.readouterr().err


def test_unknown_receipt_or_missing_broker_is_refused(broker, capsys, monkeypatch):
    assert om.main(["verify", "gone", "--chat", CHAT]) == 1
    assert capsys.readouterr().err.startswith("INVALID")
    monkeypatch.setattr(om.ask_broker, "__defaults__", (Path("/nonexistent/broker.sock"),))
    assert om.main(["verify", "r1", "--chat", CHAT]) == 1
    assert "could not be asked" in capsys.readouterr().err


def test_unknown_chat_id_is_refused():
    verified, text = om.check(VALID, "")
    assert not verified and "unknown" in text
