"""Python key-management primitives and presentation models against shared vectors.

Gate capabilities sdk.key-management.primitives.v1 (openmates.key_management) and
sdk.models.layout.v1 (openmates.models). Pure library calls: no network, account,
CLI state or environment. Every vector is executed; unknown ops fail closed.
"""
# contract-test-file: tooling
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import key_management, models  # noqa: E402  (path set above)

KEYS = "sdk.key-management.primitives.v1"
MODELS = "sdk.models.layout.v1"


def _refused(call) -> None:
    try:
        call()
    except key_management.KeyManagementError:
        return
    raise AssertionError("invalid key-management input was accepted")


def key_case(vector: dict) -> None:
    op = vector["op"]
    key = bytes.fromhex(vector["key_hex"]) if "key_hex" in vector else None
    if op == "encode_key":
        assert key_management.encode_key(key) == vector["expect"]
    elif op == "decode_key":
        if vector.get("expect_error"):
            _refused(lambda: key_management.decode_key(vector["value"]))
        else:
            assert key_management.decode_key(vector["value"]).hex() == vector["expect_hex"]
    elif op == "key_fingerprint":
        assert key_management.key_fingerprint(key).hex() == vector["expect_hex"]
    elif op == "hash_email":
        assert key_management.hash_email(vector["email"]) == vector["expect"]
    elif op == "hash_key":
        salt = base64.b64decode(vector["salt_b64"])
        assert key_management.hash_key(vector["password"], salt) == vector["expect"]
    elif op == "decrypt_combined":
        if vector.get("expect_error"):
            _refused(lambda: key_management.decrypt_combined(vector["ciphertext"], key))
        else:
            assert key_management.decrypt_combined(vector["ciphertext"], key) == vector["expect"]
    elif op == "encrypt_combined":
        sealed = key_management.encrypt_combined(vector["plaintext"], key)
        raw = base64.b64decode(sealed)
        assert raw[:2] == b"OM" and raw[2:6] == key_management.key_fingerprint(key)
        assert key_management.decrypt_combined(sealed, key) == vector["plaintext"]
    elif op == "random_key":
        first, second = key_management.random_key(), key_management.random_key()
        assert len(first) == 32 and len(second) == 32 and first != second
    else:
        raise AssertionError("Unsupported key-management vector op: " + op)


def _layout(value) -> object:
    """Language-neutral JSON projection of a frozen dataclass (tuples become lists)."""
    return json.loads(json.dumps(dataclasses.asdict(value)))


def model_case(vector: dict) -> None:
    kind = vector["kind"]
    if kind == "workspaces":
        actual = [{"id": workspace.value, "label": workspace.label} for workspace in models.WORKSPACES]
        assert actual == vector["expect"]
        return
    parser = {"chat": models.Chat, "message": models.Message, "item": models.Item}[kind].from_json
    if vector.get("expect_error"):
        try:
            parser(vector["input"])
        except (KeyError, TypeError, ValueError):
            return
        raise AssertionError("invalid model input was accepted")
    assert _layout(parser(vector["input"])) == vector["expect"], vector["id"]


def run_capability(capability: str, raw: bytes) -> list[dict]:
    vectors = json.loads(raw)["capabilities"][capability]["vectors"]
    assert vectors, capability
    case = {KEYS: key_case, MODELS: model_case}.get(capability)
    if case is None:
        raise AssertionError("Unsupported conformance capability: " + capability)
    results = []
    for vector in vectors:
        case(vector)
        results.append({"id": vector["id"], "status": "passed"})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    arguments = parser.parse_args()
    raw = Path(arguments.fixture).read_bytes()
    results = run_capability(arguments.capability, raw)
    print(json.dumps({
        "capability": arguments.capability,
        "language": "python",
        "status": "passed",
        "fixtureSha256": hashlib.sha256(raw).hexdigest(),
        "results": results,
    }))


if __name__ == "__main__":
    main()
