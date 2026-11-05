#!/usr/bin/env python3
"""Real direct Python client/facade with in-memory requests IO; no profiles/network."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument("--fixture", type=Path, required=True)
parser.add_argument("--capability", required=True, choices=["sdk.drafts"])
args = parser.parse_args()
sys.path.insert(0, str(args.root / "packages/openmates-python"))
from openmates import OpenMates  # noqa: E402 - import follows sys.path setup for sibling runner modules
from openmates.sdk import OpenMatesApiError, OpenMatesConfigError  # noqa: E402 - import follows sys.path setup for sibling runner modules

source = args.fixture.read_bytes()
fixture = json.loads(source)["capabilities"][args.capability]
results = []


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class IO:
    def __init__(self, raw=None, session=None, status=200, empty=False):
        self.raw, self.session, self.status, self.empty = (
            raw,
            session or fixture["session"],
            status,
            empty,
        )
        self.calls = []

    def request(self, method, url, **kw):
        path = urlsplit(url).path
        self.calls.append((method, path, kw))
        assert urlsplit(url).netloc == "api.example.invalid"
        assert kw["headers"]["Authorization"] == "Bearer sk-api-synthetic"
        assert ".synthetic" not in json.dumps(kw)
        if method == "POST":
            assert path == "/v1/sdk/session"
            return Response(self.session)
        assert method == "GET" and path.startswith("/v1/sdk/drafts")
        if self.status != 200:
            return Response({"detail": "synthetic-error"}, self.status)
        if path == "/v1/sdk/drafts":
            return Response({"drafts": [] if self.empty else [self.raw]})
        return Response(
            {
                "draft": self.raw
                if self.raw and path.endswith("/" + self.raw["chat_id"])
                else None
            }
        )

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


def client(**kw):
    return OpenMates(
        api_url="https://api.example.invalid", device_id="synthetic-device", **kw
    )


def refused(operation, kind):
    try:
        operation()
    except kind as error:
        return error
    raise AssertionError("operation unexpectedly accepted")


def run_io(io, operation):
    with (
        patch("openmates.sdk.requests.get", io.get),
        patch("openmates.sdk.requests.post", io.post),
    ):
        return operation()


for vector in (v for v in fixture["vectors"] if v["kind"] == "record"):
    raw = vector["draft"]
    io = IO(raw)
    c = client(api_key=fixture["credential"])

    def check():
        assert c.drafts.list_encrypted() == [raw]
        assert c.drafts.get_encrypted(raw["chat_id"]) == raw
        assert not any(m == "POST" for m, _, _ in io.calls)
        for decoded in [c.drafts.list()[0], c.drafts.get(raw["chat_id"])]:
            assert decoded == {
                **raw,
                "markdown": vector["markdown"],
                "preview": vector["preview"],
            }
        assert sum(m == "POST" for m, _, _ in io.calls) == 1
        assert c.drafts.get("missing") is None
        assert not hasattr(c.drafts, "create") and not hasattr(c.drafts, "clear")

    run_io(io, check)
    results.append({"id": vector["id"], "status": "passed"})
raw = fixture["vectors"][0]["draft"]
for id, io in [
    ("wrong-account-key", IO(raw, fixture["wrong_account_session"])),
    ("project-grant-not-account-key", IO(raw, fixture["project_grant_session"])),
]:
    c = client(api_key=fixture["credential"])
    run_io(
        io, lambda: refused(lambda: c.drafts.get(raw["chat_id"]), OpenMatesConfigError)
    )
    results.append({"id": id, "status": "passed"})
broken = deepcopy(raw)
broken["encrypted_draft_md"] = "not-authenticated"
c = client(api_key=fixture["credential"])
run_io(
    IO(broken),
    lambda: refused(lambda: c.drafts.get(raw["chat_id"]), OpenMatesConfigError),
)
results.append({"id": "corrupt-markdown", "status": "passed"})
for id, io in [
    ("get-missing-no-key-unwrap", IO()),
    ("empty-list-no-key-unwrap", IO(empty=True)),
]:
    c = client(api_key=fixture["credential"])
    observed = run_io(
        io, lambda: c.drafts.get("missing") if not io.empty else c.drafts.list()
    )
    assert observed == ([] if io.empty else None)
    assert len(io.calls) == 1 and io.calls[0][0] == "GET"
    results.append({"id": id, "status": "passed"})
io = IO(raw)
c = client(anonymous=True, anonymous_id="synthetic-anonymous")
run_io(io, lambda: refused(lambda: c.drafts.get(raw["chat_id"]), OpenMatesConfigError))
assert not io.calls
results.append({"id": "anonymous-refused-no-request", "status": "passed"})
for case in fixture["error_cases"]:
    io = IO(raw, status=case["status"])
    c = client(api_key=fixture["credential"])
    error = run_io(
        io, lambda: refused(lambda: c.drafts.get(raw["chat_id"]), OpenMatesApiError)
    )
    assert error.status_code == case["status"] and len(io.calls) == 1
    results.append({"id": case["id"], "status": "passed"})
limits = []
for limit in fixture["open_parity_limits"]:
    c = client(api_key=fixture["credential"])
    decoded = run_io(
        IO(limit["draft"]), lambda: c.drafts.get(limit["draft"]["chat_id"])
    )
    assert decoded["preview"] == limit["previews"]["python"]
    limits.append(
        {
            "id": limit["id"],
            "status": "open-existing-sdk-divergence",
            "observed": "Unicode scalar slice",
        }
    )
assert {v["id"] for v in fixture["vectors"]} == {r["id"] for r in results}
print(
    json.dumps(
        {
            "capability": args.capability,
            "language": "python",
            "status": "passed",
            "fixtureSha256": hashlib.sha256(source).hexdigest(),
            "results": results,
            "openParityLimits": limits,
        }
    )
)
