"""Global-CLI Task reader: shared cooldown and per-process list reuse.

The ``openmates`` executable is replaced by a subprocess stub; no network,
credentials or live Tasks are involved.
"""

# contract-test-file: tooling
import json
import subprocess

import pytest

from scripts import openmates_task_reader as reader


def _stub(monkeypatch, calls, *, returncode=0, stdout='{"tasks": [], "complete": true}', stderr=""):
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(reader.subprocess, "run", run)
    monkeypatch.setattr(reader, "_INVOCATION_READS", {})


def test_list_reads_are_reused_within_one_process(tmp_path, monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    assert reader.cli(tmp_path, ["list"])["complete"] is True
    reader.cli(tmp_path, ["list"])
    assert calls == [["openmates", "tasks", "list", "--json"]]


def test_rate_limit_defers_the_next_request_without_sending_it(tmp_path, monkeypatch):
    calls = []
    _stub(monkeypatch, calls, returncode=1, stderr="HTTP 429 Too Many Requests")
    with pytest.raises(reader.TaskDeliveryDeferred, match="HTTP429"):
        reader.cli(tmp_path, ["list"])
    state = json.loads((tmp_path / "logs/openmates-task-reader/request-backoff.json").read_text())
    assert state["rate_limit_failures"] == 1
    with pytest.raises(reader.TaskDeliveryDeferred, match="no request sent"):
        reader.cli(tmp_path, ["list"])
    assert len(calls) == 1
