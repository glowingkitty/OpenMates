"""Shared synthetic conformance and historical Python ciphertext compatibility."""

# contract-test-file: tooling
import base64
import ast
import importlib.util
import json
from pathlib import Path
import pytest
from openmates import sdk

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/sdk-conformance/fixtures/core.json"
SPEC = importlib.util.spec_from_file_location(
    "sdk_conformance_runner", ROOT / "tests/sdk-conformance/runners/python.py"
)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


@pytest.mark.parametrize("capability", json.loads(FIXTURE.read_text())["capabilities"])
def test_actual_python_library_shared_conformance(capability):
    vectors = json.loads(FIXTURE.read_text())["capabilities"][capability]["vectors"]
    assert RUNNER.run(capability, vectors)


def test_previous_python_fixed_header_remains_readable_but_new_writes_use_fnv():
    vector = json.loads(FIXTURE.read_text())["capabilities"][
        "crypto.aes-gcm-combined.v1"
    ]["vectors"][1]
    key = base64.b64decode(vector["key_b64"])
    old = bytearray(base64.b64decode(vector["ciphertext_b64"]))
    old[2:6] = b"\x01\x00\x00\x00"
    assert (
        sdk._decrypt_aes_gcm_text(base64.b64encode(old).decode(), key)
        == vector["plaintext"]
    )
    old[-1] ^= 1
    assert sdk._decrypt_aes_gcm_text(base64.b64encode(old).decode(), key) is None
    new = base64.b64decode(sdk._encrypt_aes_gcm_text(vector["plaintext"], key))
    assert new[:2] == b"OM" and new[2:6] == sdk._key_fingerprint(key)


def test_python_library_has_no_cli_subprocess_imports_or_calls():
    package = ROOT / "packages/openmates-python/openmates"
    inspected = 0
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text())
        inspected += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.split(".")[0] in {"subprocess", "pty", "pexpect"}
                    for alias in node.names
                )
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in {
                    "subprocess",
                    "pty",
                    "pexpect",
                }
                assert not (
                    node.module == "os"
                    and any(
                        alias.name
                        in {"system", "popen", "spawnv", "spawnve", "execv", "execve"}
                        for alias in node.names
                    )
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                assert node.func.attr not in {
                    "system",
                    "popen",
                    "spawnv",
                    "spawnve",
                    "execv",
                    "execve",
                }
    assert inspected > 5
