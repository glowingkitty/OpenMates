"""Run every shared API-key wire vector through the real Python SDK.

Gate capabilities: sdk.api-key-operations.v1 (billing, settings, reminders,
notifications), sdk.api-key-domains-b.v1 (feedback, inspirations, suggestions,
learning mode, benchmark, finance) and sdk.public-utilities-helpers.v1 (pure
public-utility helpers). Transport is the `requests`
module replaced by a recorder: no network, account or purchase is involved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
FIXTURES = ROOT / "tests/sdk-conformance/fixtures"
API_URL = "https://api.example.invalid"
API_KEY = "sk-api-synthetic-operations"


def wire_case(sdk, vector: dict) -> None:
    calls = []

    def recorder(method):
        def call(url, *args, **kwargs):
            verb = method if method != "request" else url
            target = args[0] if method == "request" else url
            calls.append((verb.upper(), target, kwargs))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"ok": True},
                headers={"content-type": "application/json"},
                content=b"{}",
                text="{}",
            )

        return call

    names = ("get", "post", "put", "patch", "delete", "request")
    previous = {name: getattr(sdk.requests, name) for name in names}
    for name in names:
        setattr(sdk.requests, name, recorder(name))
    try:
        with tempfile.TemporaryDirectory() as directory:
            client = sdk.OpenMates(
                api_key=API_KEY,
                api_url=API_URL,
                device_id="synthetic-operations",
                device_id_path=Path(directory) / "device",
            )
            namespace, method = vector["operation"].split(".")
            kwargs = dict(vector["kwargs"])
            if "confirmed" in vector:
                kwargs["confirmed"] = vector["confirmed"]
            getattr(getattr(client, namespace), method)(*vector["args"], **kwargs)
    finally:
        for name, value in previous.items():
            setattr(sdk.requests, name, value)
    assert len(calls) == 1, "exactly one request"
    verb, url, options = calls[0]
    expected = vector["expect"]
    assert verb == expected["method"] and url.startswith(API_URL)
    assert url[len(API_URL):] == expected["path"], (url, expected["path"])
    assert options.get("json") == expected["body"]
    assert options["headers"]["Authorization"] == "Bearer " + API_KEY.split(".")[0]


def pure_case(utilities, vector: dict) -> None:
    function = getattr(utilities, vector["function"])
    expected = vector["expect"]
    if isinstance(expected, dict) and expected.get("error") == "invalid":
        try:
            function(*vector["args"])
        except ValueError:
            return
        raise AssertionError("invalid input was accepted")
    assert function(*vector["args"]) == expected, vector["id"]


WIRE_CAPABILITIES = {
    "sdk.api-key-operations.v1": "sdk-api-key-operations.json",
    "sdk.api-key-domains-b.v1": "sdk-api-key-domains-b.json",
}
PURE_CAPABILITIES = {"sdk.public-utilities-helpers.v1": "sdk-api-key-domains-b.json"}


def run_capability(capability: str, raw: bytes) -> list[dict]:
    """Execute one gate capability's vectors; unknown capabilities fail closed."""
    from openmates import sdk, public_utilities

    vectors = json.loads(raw)["capabilities"][capability]["vectors"]
    assert vectors, capability
    results = []
    for vector in vectors:
        if capability in WIRE_CAPABILITIES:
            wire_case(sdk, vector)
        elif capability in PURE_CAPABILITIES:
            pure_case(public_utilities, vector)
        else:
            raise AssertionError("Unsupported conformance capability: " + capability)
        results.append({"id": vector["id"], "status": "passed"})
    return results


def run_all() -> tuple[str, list[dict]]:
    """Every shared wire/helper vector across both fixtures (Python unit test entry)."""
    digest = hashlib.sha256()
    results = []
    for capability, name in {**WIRE_CAPABILITIES, **PURE_CAPABILITIES}.items():
        raw = (FIXTURES / name).read_bytes()
        digest.update(raw)
        results.extend(run_capability(capability, raw))
    assert results
    return digest.hexdigest(), results


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
