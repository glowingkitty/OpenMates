"""Python API-key SDK against the shared operation wire vectors.

The Rust SDK runs the same vectors in packages/openmates-rust/tests/sdk_operations_a.rs.
Transport is replaced with a recorder; no network, account or purchase is involved.
"""
# contract-test-file: tooling
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))

from openmates import sdk as sdk_module  # noqa: E402

VECTORS = json.loads((ROOT / "tests/sdk-conformance/fixtures/sdk-api-key-operations.json").read_text())["capabilities"]["sdk.api-key-operations.v1"]["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_python_sdk_emits_the_shared_wire_vector(vector, monkeypatch, tmp_path):
    client = sdk_module.OpenMates(api_key="sk-api-ops", device_id="ops-device", device_id_path=tmp_path / "device")
    seen = []

    def record(method, path, payload, **_kwargs):
        seen.append((method, path, payload))
        return {"ok": True}

    monkeypatch.setattr(client, "_request", record)
    monkeypatch.setattr(client, "_get", lambda path: record("GET", path, None))
    namespace, method = vector["operation"].split(".")
    kwargs = dict(vector["kwargs"])
    if "confirmed" in vector:
        kwargs["confirmed"] = vector["confirmed"]
    getattr(getattr(client, namespace), method)(*vector["args"], **kwargs)
    expected = vector["expect"]
    assert seen == [(expected["method"], expected["path"], expected["body"])]
