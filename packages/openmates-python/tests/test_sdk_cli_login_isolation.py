"""The Python SDK is API-key only and never touches the CLI login.

A fake CLI login is planted in HOME/.openmates, OPENMATES_STATE_DIR and the XDG
dirs. A process-wide audit hook records every file open and subprocess while the
SDK is imported, constructed and used; none may touch those paths, spawn a
keychain helper, or send the planted cookie. Spec: surface.sdk sdk.library.explicit-headless.
"""
import importlib
import json
import sys
from unittest.mock import patch

import pytest

FAKE_COOKIE = "cli-login-cookie-must-never-leave-the-cli"
_RECORDING: dict[str, list] = {"active": [], "events": []}


def _audit(event, args):
    if _RECORDING["active"] and event in {"open", "os.listdir", "os.scandir", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
        _RECORDING["events"].append((event, str(args[0]) if args else ""))


sys.addaudithook(_audit)


class _Response:
    status_code = 200
    ok = True
    headers = {"content-type": "application/json"}
    text = '{"id": "account"}'
    content = text.encode()

    def json(self):
        return {"id": "account"}


# contract-test: direct surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
def test_api_key_sdk_never_reads_or_sends_cli_login(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cli_dirs = [home / ".openmates", tmp_path / "state", tmp_path / "xdg-config", tmp_path / "xdg-data"]
    for directory in cli_dirs:
        directory.mkdir(parents=True)
        (directory / "session.json").write_text(json.dumps({"cookies": {"auth_refresh_token": FAKE_COOKIE}, "ws_token": FAKE_COOKIE}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)
    sent = []

    def fake_request(*args, **kwargs):
        sent.append({"args": [str(a) for a in args], "headers": dict(kwargs.get("headers") or {}), "cookies": kwargs.get("cookies")})
        return _Response()

    _RECORDING["events"].clear()
    _RECORDING["active"].append(True)
    try:
        with patch("requests.get", fake_request), patch("requests.post", fake_request), patch("requests.request", fake_request):
            sdk = importlib.import_module("openmates")
            importlib.import_module("openmates.session_client")
            client = sdk.OpenMates(api_key="sk-api-guardtest", api_url="https://api.example.invalid", device_id_path=tmp_path / "sdk-only" / "device-id")
            client.account.info()
            # Without a key the SDK never discovers an account login.
            with pytest.raises(sdk.OpenMatesConfigError):
                sdk.OpenMates(device_id="guard-device").account.info()
    finally:
        _RECORDING["active"].pop()

    touched = [path for event, path in _RECORDING["events"] if any(path == str(d) or path.startswith(str(d) + "/") for d in cli_dirs)]
    assert touched == [], "SDK accessed CLI credential/state locations"
    assert [e for e in _RECORDING["events"] if e[0] != "open" and not e[0].startswith("os.")] == [], "SDK spawned a keychain or CLI process"
    assert len(sent) == 1
    assert sent[0]["headers"].get("Authorization") == "Bearer sk-api-guardtest"
    assert sent[0]["cookies"] is None and "Cookie" not in sent[0]["headers"]
    assert FAKE_COOKIE not in json.dumps(sent)
