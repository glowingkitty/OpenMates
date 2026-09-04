#!/usr/bin/env python3
"""Linux-safe unit coverage for the Apple notification lifecycle probe.

Tests inject opaque values and request seams only. No network calls, account
credentials, APNs tokens, or response bodies are used outside local fakes.
"""

from __future__ import annotations

# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle,apple-notifications.payload.privacy-safe

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apple_notification_contract_test.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apple_notification_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_login(*_args, **_kwargs):
    return object()


# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_lifecycle_requires_native_identity_rotates_and_unregisters_rotated_token(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setenv("OPENMATES_IOS_BUNDLE_ID", "org.openmates.app")

    def request(_opener, _api, path, body, headers, method, _timeout):
        calls.append((path, body, headers, method))
        if path == module.REGISTER_PATH and not headers:
            return 403, {}
        return 200, {"success": True}

    result = module.run("https://api.dev.openmates.org", slot=14, timeout=1, request=request, login=fake_login, token_factory=lambda length: "a" * length, device_id_factory=lambda: "device-opaque")

    assert result["status"] == "passed"
    assert [call[0] for call in calls] == [module.REGISTER_PATH, module.REGISTER_PATH, module.REGISTER_PATH, module.UNREGISTER_PATH]
    assert calls[1][1]["device_id"] == calls[2][1]["device_id"] == calls[3][1]["device_id"]
    assert calls[2][1]["token"] == calls[3][1]["token"]
    assert calls[1][2]["X-OpenMates-Bundle-ID"] == "org.openmates.app"


# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_cleanup_of_rotated_token_runs_after_mid_lifecycle_failure():
    module = load_module()
    calls = []

    def request(_opener, _api, path, body, headers, method, _timeout):
        calls.append((path, body, headers, method))
        if path == module.REGISTER_PATH and not headers:
            return 403, {}
        if path == module.REGISTER_PATH and body["token"] == "token-two":
            return 500, {"success": False}
        return 200, {"success": True}

    tokens = iter(("token-one", "token-two"))
    with pytest.raises(module.ContractFailure, match="token rotation"):
        module.run("https://api.dev.openmates.org", slot=14, timeout=1, request=request, login=fake_login, token_factory=lambda _length: next(tokens), device_id_factory=lambda: "device-opaque")

    assert calls[-1][0] == module.UNREGISTER_PATH
    assert calls[-1][1]["token"] == "token-two"


# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_cleanup_failure_is_visible_even_after_a_mid_lifecycle_failure():
    module = load_module()

    def request(_opener, _api, path, body, headers, method, _timeout):
        if path == module.REGISTER_PATH and not headers:
            return 403, {}
        if path == module.UNREGISTER_PATH:
            return 500, {"success": False}
        return 500, {"success": False}

    with pytest.raises(module.ContractFailure, match="cleanup also failed") as exc_info:
        module.run("https://api.dev.openmates.org", slot=14, timeout=1, request=request, login=fake_login, token_factory=lambda _length: "secret-token-value", device_id_factory=lambda: "device")

    assert "status=500" in str(exc_info.value)
    assert "response_keys=success" in str(exc_info.value)
    assert "secret-token-value" not in str(exc_info.value)


# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_https_is_required_before_notification_login_or_requests(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "login_native", lambda *_args, **_kwargs: pytest.fail("login must not run over HTTP"))

    with pytest.raises(module.ContractFailure, match="require an https API URL"):
        module.run("http://api.dev.openmates.org", slot=14, timeout=1)
