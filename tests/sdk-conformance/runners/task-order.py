#!/usr/bin/env python3
"""Actual public PyO3-backed sorting against qualified shared golden vectors."""

# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import SessionClientError, sort_tasks  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    capability = "local.task-order.v1"
    assert args.capability == capability
    raw = Path(args.fixture).read_bytes()
    suite = json.loads(raw)["capabilities"][capability]
    assert suite["vectors"]
    results = []
    for vector in suite["vectors"]:
        rows = vector["tasks"]
        before = copy.deepcopy(rows)
        if vector.get("error"):
            try:
                sort_tasks(rows, locale=vector["locale"])
            except SessionClientError as error:
                assert error.code == vector["error"]
            else:
                raise AssertionError("invalid task order input was accepted")
        else:
            ordered = sort_tasks(rows, locale=vector["locale"])
            assert ordered is not rows
            assert len(ordered) == len(vector["expected_indices"])
            for row, index in zip(ordered, vector["expected_indices"], strict=True):
                assert row is rows[index], vector["id"]
            assert ordered == [before[index] for index in vector["expected_indices"]]
        assert rows == before, "input rows remain unchanged on success or error"
        results.append({"id": vector["id"], "status": "passed"})
    print(
        json.dumps(
            {
                "capability": capability,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
