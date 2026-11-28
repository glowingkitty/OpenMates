# contract-test-file: infrastructure
"""Self-host readiness probe reports API state and fails closed."""

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "check_selfhost_chat_readiness.py"
_spec = importlib.util.spec_from_file_location("check_selfhost_chat_readiness", _PATH)
readiness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readiness)


def _fake(responses):
    return lambda url, timeout=10.0: responses.get(url.split("localhost:8000")[-1], (0, ""))


def test_ready_api_passes_and_writes_result(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness, "fetch", _fake({
        "/health": (200, "ok"),
        "/v1/settings/server-status": (200, json.dumps({"is_self_hosted": True})),
    }))
    out = tmp_path / "r.json"
    assert readiness.main(["--mode", "image", "--milestone", "fresh", "--output", str(out)]) == 0
    result = json.loads(out.read_text())
    assert result["ok"] and result["server_status"] == {"is_self_hosted": True}


def test_unreachable_api_fails_after_install(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness, "fetch", _fake({}))
    out = tmp_path / "r.json"
    assert readiness.main(["--mode", "source", "--milestone", "restart", "--output", str(out)]) == 1
    assert not json.loads(out.read_text())["ok"]


def test_volume_absent_requires_no_api(monkeypatch, tmp_path):
    out = tmp_path / "r.json"
    monkeypatch.setattr(readiness, "fetch", _fake({}))
    assert readiness.main(["--mode", "source", "--milestone", "volume-absent", "--output", str(out)]) == 0
    monkeypatch.setattr(readiness, "fetch", _fake({"/health": (200, "ok")}))
    assert readiness.main(["--mode", "source", "--milestone", "volume-absent", "--output", str(out)]) == 1
