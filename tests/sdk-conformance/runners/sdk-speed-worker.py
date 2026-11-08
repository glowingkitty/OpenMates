#!/usr/bin/env python3
"""Python arm of the cross-SDK speed check (tests/sdk-conformance/benchmark_sdk_speed.py).

Line 1 on stdin is {api_url, api_key, device_id}; each further line is
{op, args, iterations}. Runs the real `openmates` API-key client and answers one
JSON line per request with a plaintext-free digest of the last result.
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/openmates-python"))
from openmates import OpenMates  # noqa: E402 - sibling package path is set up above
from openmates.sdk import OpenMatesApiError, OpenMatesConfigError  # noqa: E402 - same reason


def sha(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def code(error):
    if isinstance(error, OpenMatesConfigError):
        return "crypto"
    if not isinstance(error, OpenMatesApiError):
        return "protocol"
    status = error.status_code
    mapped = {401: "authentication", 403: "forbidden", 409: "conflict"}.get(status)
    if mapped:
        return mapped
    if status in (400, 404, 410, 422):
        return "invalid"
    return "offline" if status == 429 or status >= 500 else "protocol"


def invoke(client, op, args):
    if op == "drafts.list":
        rows = sorted([draft["chat_id"], sha(draft["markdown"])] for draft in client.drafts.list())
        return {"count": len(rows), "rows": rows}
    if op == "drafts.get":
        draft = client.drafts.get(args["chat_id"])
        return {"found": True, "markdown": sha(draft["markdown"])} if draft else {"found": False}
    if op == "history.list":
        return {"count": len(client.history.list(limit=args.get("limit")))}
    if op == "wikipedia.search":
        value = client.wikipedia.search(args["query"], language=args.get("language"), limit=args.get("limit"))
        results = value.get("results")
        return {"count": len(results) if isinstance(results, list) else 0}
    if op == "wikipedia.summary":
        return {"title": client.wikipedia.summary(args["title"], language=args.get("language")).get("title")}
    raise ValueError(f"unknown benchmark operation {op}")


def main():
    init = json.loads(sys.stdin.readline())
    client = OpenMates(api_key=init["api_key"], api_url=init["api_url"], device_id=init["device_id"])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        iterations = request["iterations"]
        if not isinstance(iterations, int) or not 1 <= iterations <= 1000:
            raise ValueError("iterations")
        answer = {"ok": True}
        for _ in range(iterations):
            try:
                answer = {"ok": True, "digest": invoke(client, request["op"], request.get("args") or {})}
            except (OpenMatesApiError, OpenMatesConfigError) as error:
                answer = {"ok": False, "error": code(error), "status": getattr(error, "status_code", None)}
                break
        print(json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
