#!/usr/bin/env python3
"""Linux-safe unit coverage for the Apple auth contract probe.

The tests use synthetic response objects and validate that secret-bearing fields
and non-generic lookup shapes fail before any live API invocation is attempted.
"""

from __future__ import annotations

# contract-test: supporting surface=rest_api assertions=auth.keys.client-wrapped,auth.lookup.anti-enumeration,auth.surface.first-party-boundary

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apple_auth_contract_test.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apple_auth_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: supporting surface=rest_api assertions=auth.keys.client-wrapped
def test_secret_response_fields_fail_without_serializing_their_values():
    module = load_module()

    with pytest.raises(module.ContractFailure, match="forbidden secret boundary field"):
        module._assert_no_secrets({"ws_token": "opaque", "refresh_token": "secret-value"}, "synthetic")


# contract-test: supporting surface=rest_api assertions=auth.surface.first-party-boundary
def test_native_header_identity_is_complete_and_origin_free():
    module = load_module()

    assert module.NATIVE_HEADERS["User-Agent"].startswith("OpenMates-Apple/")
    assert module.NATIVE_HEADERS["X-OpenMates-Client"] == "ios"
    assert "Origin" not in module.NATIVE_HEADERS


# contract-test: supporting surface=rest_api assertions=auth.surface.first-party-boundary
def test_https_is_required_before_auth_credentials_are_loaded(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "load_test_account", lambda *_args, **_kwargs: pytest.fail("credentials must not be read before HTTPS validation"))

    with pytest.raises(module.ContractFailure, match="require an https API URL"):
        module.run("http://api.dev.openmates.org", slot=14, timeout=1)
