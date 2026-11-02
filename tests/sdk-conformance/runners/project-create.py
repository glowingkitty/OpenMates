#!/usr/bin/env python3
"""Actual Python direct SDK creation and real encrypted HTTP payload assertions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from project_create_server import CAPABILITY, ProjectCreatePeer  # noqa: E402


def run_vector(suite, vector):
    from openmates import OpenMates
    from openmates.sdk import OpenMatesConfigError

    peer = ProjectCreatePeer(suite, vector, "pip").start()
    try:
        client = OpenMates(
            api_url=peer.endpoint,
            api_key=suite["account"]["api_key"],
            device_id="synthetic-project-fixture",
        )
        for _ in range(vector["repetitions"]):
            try:
                context = (
                    {"team_id": suite["team"]["team_id"]}
                    if vector["team"]
                    else {"personal": True}
                )
                output = client.projects.create(vector["input"], **context)
            except OpenMatesConfigError:
                assert vector["error"]
            else:
                assert not vector["error"]
                for key, value in vector["expected"].items():
                    assert output[key] == value
                assert (
                    isinstance(output["project_id"], str)
                    and len(output["project_id"]) == 36
                )
        report = peer.status()
        assert report["failure"] is None
        assert report["posts"] == (0 if vector["error"] else vector["repetitions"])
        assert "bearer-only-transport" in report["checks"]
        if not vector["error"]:
            assert {
                "backend-required-fields",
                "fresh-project-key-and-focus",
                "canonical-encrypted-default-focus",
                "encrypted-private-fields",
                "scope-bound-key-wrapper",
                "secret-free-wire",
                "safe-write-policy",
            } <= set(report["checks"])
        return {"id": vector["id"], "status": "passed"}
    finally:
        peer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    raw = Path(args.fixture).read_bytes()
    try:
        assert args.capability == CAPABILITY
        suite = json.loads(raw)["capabilities"][CAPABILITY]
        results = [run_vector(suite, vector) for vector in suite["vectors"]]
        assert results
    except Exception:
        print("Python Project creation conformance failed", file=sys.stderr)
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
