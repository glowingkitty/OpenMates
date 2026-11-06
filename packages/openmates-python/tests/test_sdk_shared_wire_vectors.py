# contract-test-file: tooling
"""Python SDK against every shared API-key wire/helper vector, plus new bindings."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))

from openmates import key_management, models, sdk as sdk_module  # noqa: E402


def _runner():
    spec = importlib.util.spec_from_file_location(
        "sdk_api_key_operations_runner",
        ROOT / "tests/sdk-conformance/runners/sdk-api-key-operations.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_executes_every_shared_vector():
    _, results = _runner().run_all()
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)) and len(ids) >= 70
    assert "finance-default-leaves-prompt-injection-untouched" in ids


def test_finance_defaults_leave_prompt_injection_untouched():
    import inspect

    default = inspect.signature(sdk_module.OpenMatesFinance.check_accounts).parameters[
        "prompt_injection_protection"
    ].default
    assert default is None


def test_key_management_round_trip_and_refusals():
    key = key_management.random_key()
    assert key_management.decode_key(key_management.encode_key(key)) == key
    sealed = key_management.encrypt_combined("synthetic text", key)
    assert key_management.decrypt_combined(sealed, key) == "synthetic text"
    assert key_management.key_fingerprint(key) == sdk_module._key_fingerprint(key)
    with pytest.raises(key_management.KeyManagementError):
        key_management.decrypt_combined(sealed, bytes(32))
    with pytest.raises(key_management.KeyManagementError):
        key_management.decode_key("c2hvcnQ=")
    with pytest.raises(key_management.KeyManagementError):
        key_management.encrypt_combined("x", b"short")


def test_models_parse_rust_layout():
    chat = models.Chat.from_json({
        "id": "c", "title": "t",
        "messages": [{"id": "m", "role": "user", "content": "hi", "embeds": [{"id": "e", "title": "x"}]}],
    })
    assert chat.messages[0].embeds[0].id == "e"
    assert [w.label for w in models.WORKSPACES][:2] == ["Chats", "Apps"]
    with pytest.raises(ValueError):
        models.StreamUpdate("invented")
