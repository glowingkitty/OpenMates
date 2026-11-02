#!/usr/bin/env python3
"""Exercise the real Python SDK library; no CLI process or product requests."""

from __future__ import annotations
import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))


def rejected(operation) -> None:
    try:
        operation()
    except Exception:
        return
    raise AssertionError("adversarial input was accepted")


async def native_session_case(vector: dict) -> None:
    from openmates import SessionClient, SessionClientError

    async def refused(operation, code):
        try:
            await operation
        except SessionClientError as error:
            assert error.code == code
            return
        raise AssertionError("native policy refusal was not enforced")

    client = SessionClient(**vector["options"])
    try:
        await client.import_session(vector["session"])
        assert (await client.export_session(include_secrets=True))["session"] == vector[
            "session"
        ]
        await refused(client.export_session(include_secrets=False), "forbidden")
        await refused(
            client.import_session(
                {**vector["session"], "api_url": "https://other.example.invalid"}
            ),
            "forbidden",
        )
        await refused(
            client.login_password("invalid", "synthetic-private-password"),
            "authentication",
        )
        assert (await client.export_session(include_secrets=True))["session"] == vector[
            "session"
        ]
        try:
            SessionClient(**{**vector["options"], "enhanced_privacy": True})
        except SessionClientError as error:
            assert error.code == "invalid_argument"
        else:
            raise AssertionError("enhanced privacy was silently disabled")
        try:
            client.respond_to_consent("invented", [])
        except SessionClientError as error:
            assert error.code == "forbidden"
        else:
            raise AssertionError("unknown consent was accepted")
        await refused(client.send("Synthetic private send"), "forbidden")
        client.cancel()
        await client.logout()
        await refused(client.export_session(include_secrets=True), "authentication")
    finally:
        await client.close()
    await refused(client.list("chats"), "cancelled")


def run(capability: str, vectors: list[dict]) -> list[dict]:
    from openmates import sdk
    from openmates import chat_completion_recovery as recovery

    results = []
    for vector in vectors:
        if capability == "crypto.aes-gcm-combined.v1":
            key = base64.b64decode(vector["key_b64"])
            assert (
                sdk._decrypt_aes_gcm_text(vector["ciphertext_b64"], key)
                == vector["plaintext"]
            )
            encrypted = sdk._encrypt_aes_gcm_text(vector["plaintext"], key)
            assert sdk._decrypt_aes_gcm_text(encrypted, key) == vector["plaintext"]
            raw = base64.b64decode(encrypted)
            assert raw[:2] == b"OM" and raw[2:6] == sdk._key_fingerprint(key)
            assert (
                sdk._decrypt_aes_gcm_text(vector["ciphertext_b64"], bytes([42]) * 32)
                is None
            )
            raw = bytearray(base64.b64decode(vector["ciphertext_b64"]))
            raw[-1] ^= 1
            assert (
                sdk._decrypt_aes_gcm_text(base64.b64encode(raw).decode(), key) is None
            )
            if raw.startswith(b"OM"):
                header = bytearray(base64.b64decode(vector["ciphertext_b64"]))
                header[2] ^= 1
                assert (
                    sdk._decrypt_aes_gcm_text(base64.b64encode(header).decode(), key)
                    is None
                )
        elif capability == "crypto.recovery-envelope.v1":
            private, public = recovery.derive_recovery_keypair(
                vector["chat_key"], vector["chat_id"], vector["key_version"]
            )
            assert (
                private == vector["recovery_private_key"]
                and public == vector["recovery_public_key"]
            )
            assert (
                recovery.build_recovery_associated_data(vector)
                == vector["associated_data"]
            )
            options = {
                name: vector[name]
                for name in (
                    "owner_id",
                    "chat_id",
                    "turn_id",
                    "job_id",
                    "assistant_message_id",
                    "key_version",
                )
            }
            options["recovery_private_key"] = private
            assert (
                recovery.open_recovery_envelope(vector["envelope"], **options)
                == vector["plaintext"].encode()
            )
            rejected(
                lambda: recovery.open_recovery_envelope(
                    vector["envelope"],
                    **{**options, "key_version": options["key_version"] + 1},
                )
            )
            for field in ("epk", "nonce", "ciphertext"):
                envelope = deepcopy(vector["envelope"])
                raw = bytearray(
                    base64.urlsafe_b64decode(
                        envelope[field] + "=" * (-len(envelope[field]) % 4)
                    )
                )
                raw[0] ^= 1
                envelope[field] = base64.urlsafe_b64encode(raw).decode().rstrip("=")
                rejected(lambda: recovery.open_recovery_envelope(envelope, **options))
            rejected(
                lambda: recovery.open_recovery_envelope(
                    {
                        **vector["envelope"],
                        "epk": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),
                    },
                    **options,
                )
            )
        elif capability == "crypto.slug-lookup.v1":
            key = base64.b64decode(vector["key_b64"])
            assert sdk._normalize_object_slug(vector["input"]) == vector["normalized"]
            assert (
                sdk._object_slug_lookup_hash(vector["normalized"], key)
                == vector["lookup_hash"]
            )
            rejected(lambda: sdk._normalize_object_slug("❄"))
        elif capability == "protocol.generated-skills.v1":
            calls = []
            previous = sdk.requests.post

            def post(url, **kwargs):
                calls.append((url, kwargs))
                return SimpleNamespace(status_code=200, json=lambda: vector["response"])

            sdk.requests.post = post
            try:
                client = sdk.OpenMates(
                    api_key="sk-api-synthetic-conformance.synthetic-local-setup-secret",
                    api_url="https://api.example.invalid",
                    device_id="synthetic-conformance",
                )
                output = getattr(getattr(client.apps, vector["app"]), vector["skill"])(
                    vector["input"]
                )
                assert output == vector["response"] and len(calls) == 1
                url, options = calls[0]
                assert (
                    vector["method"] == "POST"
                    and url == "https://api.example.invalid" + vector["path"]
                )
                assert options["json"] == vector["input"]
                assert (
                    options["headers"]["Authorization"]
                    == "Bearer sk-api-synthetic-conformance"
                )
            finally:
                sdk.requests.post = previous
        elif capability == "session.native-boundary.v1":
            asyncio.run(native_session_case(vector))
        else:
            raise ValueError("Unsupported conformance capability")
        results.append({"id": vector.get("id", vector.get("name")), "status": "passed"})
    assert results
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    arguments = parser.parse_args()
    raw = Path(arguments.fixture).read_bytes()
    try:
        vectors = json.loads(raw)["capabilities"][arguments.capability]["vectors"]
        results = run(arguments.capability, vectors)
    except Exception:
        print(f"Python SDK conformance failed: {arguments.capability}", file=sys.stderr)
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "capability": arguments.capability,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
