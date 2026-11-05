"""Required isolated-CI coverage of the existing explicit Python boundary."""
# contract-test-file: tooling
import builtins
import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# contract-test: supporting surface=sdks.pip assertions=sdk.auth.credential-separation,sdk.library.explicit-headless
def test_root_api_key_credentials_ignore_cli_state(tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).resolve().parents[3] / "tests/sdk-conformance/fixtures/sdk-root-credential-boundary.json").read_bytes())
    assert fixture["policy"] == "explicit-sdk-credentials-v1" and len(fixture["cases"]) == 8
    state = tmp_path / "cli-state"
    state.mkdir()
    sentinel = state / "session.json"
    sentinel.write_text('{"masterKeyExportedB64":"SYNTHETIC-CLI-SECRET"}')
    before = sentinel.read_bytes()
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(state))
    # OPENMATES_API_KEY remains the documented 0.x convenience fallback for the
    # root API-key client; it is not CLI login discovery, so it is unset here.
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)
    monkeypatch.setenv("OPENMATES_API_URL", "https://ambient.example.invalid")
    real_open = builtins.open
    accesses = []

    def guarded_open(file, *args, **kwargs):
        if str(file).startswith(str(state)):
            accesses.append(str(file))
            raise AssertionError("CLI credential access forbidden")
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", guarded_open), patch("io.open", guarded_open):
        sdk = importlib.import_module("openmates")
        absent = sdk.OpenMates(device_id="synthetic-explicit-device")
        with pytest.raises(sdk.OpenMatesConfigError):
            absent._get_raw("/v1/sdk/session")
        explicit = sdk.OpenMates(api_key="synthetic-explicit-key", api_url="https://caller.example.invalid", device_id="synthetic-explicit-device")
        assert explicit._api_key == "synthetic-explicit-key"
        assert explicit._api_url == "https://caller.example.invalid"
        # Deferred package helpers must not turn a caller key into CLI discovery.
        importlib.import_module("openmates.direct_chats")
        importlib.import_module("openmates.session_client")
        assert accesses == []
    assert sentinel.read_bytes() == before
